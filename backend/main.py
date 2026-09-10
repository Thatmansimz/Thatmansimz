import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import init_db, get_db, SessionLocal
from backend.models.trade import Trade, DailyStats
from backend.models.signal import Signal
from backend.models.account import Account
from backend.services.ai_engine import AIEngine
from backend.services.market_data import MarketDataService
from backend.services.risk_manager import RiskManager
from backend.services.execution import ExecutionService, rejection_summary as _rejection_summary, trading_day
from backend.services.scheduler import TradingScheduler, get_scheduler_state
from backend.brokers import get_broker
from backend.clock import ET, et_iso, utc_now

class _ETFormatter(logging.Formatter):
    """
    Stamp log lines on the EXCHANGE clock.

    Logging defaults to the host's local time. On this Phoenix machine that put
    log lines 3 hours behind the ET dates the record is keyed to and 7 hours
    behind the UTC timestamps stored on each trade — so a trade and the log line
    describing it appeared to be different events. The %Z suffix is mandatory:
    an unlabelled timestamp is how three clocks hid in one system.
    """
    def formatTime(self, record, datefmt=None):
        stamped = datetime.fromtimestamp(record.created, tz=ET)
        return stamped.strftime(datefmt or "%Y-%m-%d %H:%M:%S %Z")


_handler = logging.StreamHandler()
_handler.setFormatter(_ETFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    handlers=[_handler],
    force=True,
)
logger = logging.getLogger(__name__)

def _orb_window_status() -> dict:
    """
    Is the validated ORB trade window live right now?

    The ORB edge is anchored to the 9:30 ET NY open and only takes trades
    between 9:35 and 14:00 ET on weekdays. The futures MARKET is open ~24/5
    (Asia/London included), but the strategy is deliberately idle outside this
    window — so the dashboard distinguishes ARMED (watching) from LIVE (trading).
    """
    import pytz
    from datetime import time as dtime, timedelta

    ET = pytz.timezone("America/New_York")
    now = datetime.now(ET)
    open_t = dtime(9, 35)
    close_t = dtime(14, 0)
    is_weekday = now.weekday() < 5
    active = is_weekday and open_t <= now.time() <= close_t

    # After the 14:00 cutoff (but NY session still open): done for today.
    after_cutoff = is_weekday and now.time() > close_t

    # Minutes until the next ORB open — always the next weekday at 9:35 AM ET.
    opens_in = None
    if not active:
        nxt = now.replace(hour=9, minute=35, second=0, microsecond=0)
        if now.time() >= close_t or now.weekday() >= 5:
            nxt = nxt + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt <= now:
            nxt = nxt + timedelta(days=1)
        opens_in = int((nxt - now).total_seconds() // 60)

    return {"active": active, "after_cutoff": after_cutoff, "opens_in_min": opens_in}


def _v2_window_status() -> dict:
    """
    Trade-window status for the V2 multi-session engine (STRATEGY=multi_session).

    V2 trades the full London (4:00–12:00 ET) and NY (9:00–18:00 ET) sessions,
    but Asia ONLY inside its 8–10 PM ET kill zone. Futures are closed
    Fri 5 PM → Sun 6 PM ET. The dashboard pill uses this to show
    LIVE (a tradeable window is open) vs ARMED (waiting for the next one).
    """
    import pytz
    from datetime import time as dtime, timedelta
    from backend.strategies.v2 import sessions as S

    ET = pytz.timezone("America/New_York")

    def tradeable(dt) -> bool:
        wd = dt.weekday()
        if wd == 5:  # Saturday
            return False
        if wd == 4 and dt.time() >= dtime(17, 0):  # Friday after 5 PM
            return False
        if wd == 6 and dt.time() < dtime(18, 0):   # Sunday before 6 PM
            return False
        sess = S.active_session(dt)
        if sess is None:
            return False
        if sess.name == "ASIA" and not S.in_kill_zone(dt, sess):
            return False
        return True

    now = datetime.now(ET)
    active = tradeable(now)
    opens_in = None
    if not active:
        probe = now.replace(second=0, microsecond=0)
        for i in range(1, 7 * 24 * 60):  # scan up to a week ahead
            probe_t = probe + timedelta(minutes=i)
            if tradeable(probe_t):
                opens_in = i
                break

    return {"active": active, "after_cutoff": False, "opens_in_min": opens_in}


def _trade_window_status() -> dict:
    """Dispatch on the active strategy so the ARMED/LIVE pill tells the truth."""
    if settings.STRATEGY.lower() == "multi_session":
        return _v2_window_status()
    return _orb_window_status()


# Global service instances
broker = None
ai_engine = None
risk_manager = None
execution_service = None
scheduler = None
market_data = MarketDataService()

_ws_clients: list[WebSocket] = []


async def broadcast(data: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, ai_engine, risk_manager, execution_service, scheduler

    # A restart never re-arms this research release, even with a legacy .env.
    # There is no registered frozen forward run yet.
    settings.TRADING_ENABLED = False

    os.makedirs("data", exist_ok=True)
    init_db()

    # One-time backfill: trades recorded before initial_stop_loss existed had
    # their stop trailed in place, leaving no record of the risk actually
    # taken. The original stop survives on the linked signal row — restore it.
    db = SessionLocal()
    try:
        for t in db.query(Trade).filter(Trade.initial_stop_loss.is_(None)).all():
            sig = db.query(Signal).filter(Signal.id == t.signal_id).first() if t.signal_id else None
            if sig and sig.stop_loss:
                t.initial_stop_loss = sig.stop_loss
        db.commit()
    except Exception as exc:
        logger.warning("initial_stop_loss backfill skipped: %s", exc)
    finally:
        db.close()

    # Seed account record
    db = SessionLocal()
    try:
        if not db.query(Account).first():
            db.add(Account(
                broker=settings.BROKER,
                balance=settings.PROP_FIRM_ACCOUNT_SIZE,
                equity=settings.PROP_FIRM_ACCOUNT_SIZE,
                buying_power=settings.PROP_FIRM_ACCOUNT_SIZE,
                prop_firm=settings.PROP_FIRM,
                evaluation_start_balance=settings.PROP_FIRM_ACCOUNT_SIZE,
                peak_balance=settings.PROP_FIRM_ACCOUNT_SIZE,
                all_time_high=settings.PROP_FIRM_ACCOUNT_SIZE,
            ))
            db.commit()
    finally:
        db.close()

    broker = get_broker(settings.BROKER, settings)
    ai_engine = AIEngine(settings)
    risk_manager = RiskManager(settings)

    db = SessionLocal()
    execution_service = ExecutionService(broker, risk_manager, db)

    scheduler = TradingScheduler(execution_service, ai_engine, risk_manager)
    logger.info("AI Trading Platform started | Broker: %s | Prop Firm: %s", settings.BROKER, settings.PROP_FIRM)

    yield

    if scheduler:
        await scheduler.stop()
    logger.info("Platform shut down")


app = FastAPI(
    title="AI Day Trading Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.API_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def authenticate_mutations(request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not settings.API_TOKEN:
            return JSONResponse(status_code=503, content={"detail": "Mutation access is disabled until API_TOKEN is configured."})
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {settings.API_TOKEN}"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    return await call_next(request)


@app.get("/api/workspace")
async def workspace_status(db: Session = Depends(get_db)):
    """Current state only; historical assessment numbers are a separate artifact."""
    from backend.services.readiness import readiness_status
    closed = db.query(Trade).filter(Trade.status.in_(CLOSED_STATUSES)).all()
    return {
        "observed_at": utc_now().isoformat() + "Z",
        "broker": settings.BROKER,
        "trading_enabled": settings.TRADING_ENABLED,
        "scheduler_running": get_scheduler_state()["running"],
        "strategy": settings.STRATEGY,
        "symbols": settings.SYMBOLS,
        "closed_trades": len(closed),
        "open_positions": db.query(Trade).filter(Trade.status == "open").count(),
        "recorded_net_pnl": round(sum(t.net_pnl or 0 for t in closed), 2),
        "reconciliation_issues": broker.reconciliation_issues() if hasattr(broker, "reconciliation_issues") else [],
        "scope": "All records in this checkout's database; not broker-verified performance.",
        "readiness": readiness_status(),
    }


CLOSED_STATUSES = ["closed", "stopped_out", "target_hit", "breakeven_stop"]


def _campaign_trades(db: Session):
    """
    Closed trades belonging to the ACTIVE forward-test campaign only.

    Without this scope the analytics blend the old Stage-1 ORB replay trades
    (a different strategy, a different instrument set, months earlier) into the
    live V2 record — which produces confident, completely false conclusions
    like "MES is bleeding, consider dropping it" for an instrument the engine
    is not trading at all. The audited record must contain only the campaign.

    Returns (trades, scope_label). Falls back to all trades when no campaign
    is running, so pre-campaign analysis still works.
    """
    from backend.services.forward_test import get_campaign
    q = db.query(Trade).filter(Trade.status.in_(CLOSED_STATUSES))
    meta = get_campaign()
    if not meta:
        return q.all(), "all-time"
    start = date.fromisoformat(meta["start_date"])
    return q.filter(Trade.trade_date >= start).all(), f"campaign since {meta['start_date']}"


# ── Status & Health ───────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    from backend.services.market_data import get_feed_health
    sched = get_scheduler_state()
    sessions = market_data.get_sessions_status()
    orb = _trade_window_status()
    return {
        "status": "ok",
        "broker": settings.BROKER,
        "prop_firm": settings.PROP_FIRM,
        "strategy": settings.STRATEGY,
        "trading_enabled": settings.TRADING_ENABLED,
        # Data-feed health — a blind engine must never look healthy. The
        # watchdog and dashboard both read this.
        "data_feed": get_feed_health(),
        # ORB trade window: the strategy only fires 9:35–14:00 ET on weekdays.
        # Used by the UI to show ARMED (enabled, waiting) vs LIVE (in-window).
        "orb_window_active": orb["active"],
        "orb_after_cutoff": orb["after_cutoff"],
        "orb_opens_in_min": orb["opens_in_min"],
        # Futures platform → headline pill follows 24/5 futures hours, not the
        # 9:30–16:00 stock session.
        "market_open": sessions["futures_open"],
        "stock_market_open": market_data.is_market_open(),
        "sessions": sessions["sessions"],
        "now_et": sessions["now_et"],
        "scheduler_running": sched["running"],
        "last_cycle": sched.get("last_cycle"),
        "cycles_today": sched.get("cycles_today", 0),
        "signals_today": sched.get("signals_today", 0),
        "scan_status": sched.get("scan_status", "idle"),
        # Why signals are being turned away. An engine that generates setups and
        # rejects every one of them looks identical to a quiet market — this is
        # the difference, made visible.
        "rejections": _rejection_summary(),
        "symbols": settings.SYMBOLS,
        "ai_threshold": settings.AI_CONFIDENCE_THRESHOLD,
        # Report the cap that ACTUALLY governs the active strategy. V2 is bound
        # by V2_MAX_RISK_DOLLARS, so showing V1's $250 here told the operator
        # the risk was 4x smaller than it really is.
        "max_stop_dollars": (
            risk_manager._risk_cap(settings.STRATEGY.lower())
            if risk_manager else settings.MAX_STOP_LOSS_DOLLARS
        ),
        "daily_target": settings.DAILY_PROFIT_TARGET_DOLLARS,
    }


@app.post("/api/settings/max-stop")
async def set_max_stop(value: float):
    """
    Live-adjust the risk cap per trade from the dashboard.

    Writes whichever cap actually governs the active strategy — under
    multi_session that is V2_MAX_RISK_DOLLARS. Previously this always wrote
    V1's MAX_STOP_LOSS_DOLLARS, so under V2 the slider was a silent no-op.
    """
    value = max(50.0, min(5000.0, round(float(value))))
    if settings.STRATEGY.lower() == "multi_session":
        settings.V2_MAX_RISK_DOLLARS = value
    else:
        settings.MAX_STOP_LOSS_DOLLARS = value
        # Push into the running strategy so it takes effect on the next signal.
        if scheduler is not None and getattr(scheduler, "strategy", None) is not None:
            try:
                scheduler.strategy.max_stop_dollars = value
            except Exception:
                pass
    return {"max_stop_dollars": value}


# ── Account ───────────────────────────────────────────────────────────────────

@app.get("/api/account")
async def get_account(db: Session = Depends(get_db)):
    account = db.query(Account).first()
    if not account:
        raise HTTPException(status_code=404, detail="No account found")
    return account.to_dict()


@app.post("/api/account/sync")
async def sync_account(db: Session = Depends(get_db)):
    if not broker:
        raise HTTPException(status_code=503, detail="Broker not initialized")
    try:
        data = await broker.get_account()
        account = db.query(Account).first()
        if account:
            account.balance = data.get("balance", account.balance)
            account.equity = data.get("equity", account.equity)
            account.buying_power = data.get("buying_power", account.buying_power)
            account.unrealized_pnl = data.get("unrealized_pnl", 0)
            db.commit()
        return {"synced": True, **data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Trades ────────────────────────────────────────────────────────────────────

@app.get("/api/trades")
async def list_trades(
    status: Optional[str] = None,
    limit: int = 100,
    trade_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Trade)
    if status:
        q = q.filter(Trade.status == status)
    if trade_date:
        try:
            d = date.fromisoformat(trade_date)
            q = q.filter(Trade.trade_date == d)
        except ValueError:
            pass
    trades = q.order_by(Trade.created_at.desc()).limit(limit).all()
    return [t.to_dict() for t in trades]


@app.get("/api/trades/today")
async def trades_today(db: Session = Depends(get_db)):
    trades = (
        db.query(Trade)
        .filter(Trade.trade_date == trading_day())
        .order_by(Trade.created_at.desc())
        .all()
    )
    return [t.to_dict() for t in trades]


@app.post("/api/trades/{trade_id}/close")
async def close_trade(trade_id: int, db: Session = Depends(get_db)):
    if not execution_service:
        raise HTTPException(status_code=503, detail="Execution service not ready")
    closed = await execution_service.close_position(trade_id, "manual")
    if not closed:
        raise HTTPException(status_code=404, detail="Trade not found or already closed")
    return {"closed": True, "trade_id": trade_id}


# ── Signals ───────────────────────────────────────────────────────────────────

@app.get("/api/signals")
async def list_signals(limit: int = 20, db: Session = Depends(get_db)):
    signals = (
        db.query(Signal)
        .order_by(Signal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [s.to_dict() for s in signals]


@app.post("/api/signals/generate")
async def generate_signal_now(symbol: str = "MES"):
    if not ai_engine:
        raise HTTPException(status_code=503, detail="AI engine not ready")
    signal = ai_engine.generate_signal(
        symbol=symbol,
        confidence_threshold=0.0,
        max_stop_dollars=settings.MAX_STOP_LOSS_DOLLARS,
    )
    if not signal:
        return {"signal": None, "message": "No signal generated"}
    return signal


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats/daily")
async def daily_stats(db: Session = Depends(get_db)):
    stats = db.query(DailyStats).order_by(DailyStats.date.desc()).limit(30).all()
    return [s.to_dict() for s in stats]


@app.get("/api/stats/today")
async def today_stats(db: Session = Depends(get_db)):
    stats = db.query(DailyStats).filter(DailyStats.date == trading_day()).first()
    if not stats:
        return {"date": trading_day().isoformat(), "pnl": 0.0, "trades_count": 0}
    return stats.to_dict()


@app.get("/api/stats/performance")
async def performance_stats(db: Session = Depends(get_db)):
    all_trades, scope = _campaign_trades(db)
    if not all_trades:
        return {"total_trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                "profit_factor": 0, "scope": scope}

    wins = [t for t in all_trades if (t.net_pnl or 0) > 0]
    losses = [t for t in all_trades if (t.net_pnl or 0) <= 0]

    avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t.net_pnl or 0 for t in all_trades)
    gross_wins = sum(t.net_pnl for t in wins) if wins else 0
    gross_losses = abs(sum(t.net_pnl for t in losses)) if losses else 0

    return {
        "scope": scope,
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0,
        "expectancy": round((avg_win * len(wins) + avg_loss * len(losses)) / len(all_trades), 2),
    }


@app.get("/api/funnel")
async def funnel(db: Session = Depends(get_db)):
    """
    THE FUNNEL: bars evaluated → signals found → rejected → trades taken.

    This exists because "no trades" has two completely different causes that
    used to look identical from the outside: a genuinely quiet market, and an
    engine silently throwing away every setup it found. One of those cost this
    project 25 days. The middle number is the whole point.
    """
    from backend.services.forward_test import get_campaign

    meta = get_campaign()
    q = db.query(DailyStats)
    if meta:
        q = q.filter(DailyStats.date >= date.fromisoformat(meta["start_date"]))
    rows = q.order_by(DailyStats.date.asc()).all()

    today_row = next((r for r in rows if r.date == trading_day()), None)

    def totals(subset):
        return {
            "bars": sum(r.bars_evaluated or 0 for r in subset),
            "signals": sum(r.signals_generated or 0 for r in subset),
            "rejected": sum(r.signals_rejected or 0 for r in subset),
            "taken": sum(r.signals_taken or 0 for r in subset),
        }

    camp = totals(rows)
    today = totals([today_row] if today_row else [])
    rej = _rejection_summary()

    # Plain-English read of the funnel, so the operator never has to interpret.
    # bars_evaluated / signals_rejected are newer counters than signals / taken,
    # so immediately after a deploy the top of the funnel is shorter than the
    # middle. Say so rather than drawing a confident conclusion from half a
    # funnel — a wrong "healthy" is exactly the kind of reassurance that hid
    # the 25-day outage.
    # STALENESS FIRST. Every branch below reads whole-campaign aggregates, so a
    # campaign that traded once a week ago and has been silent since still
    # satisfied `camp["taken"] > 0` and reported "Healthy" — which is precisely
    # the reassuring-but-wrong verdict this panel exists to prevent. Six silent
    # days in the live campaign read as healthy for all six of them.
    last_active = None
    for r in rows:
        if (r.bars_evaluated or 0) or (r.signals_generated or 0) or (r.signals_taken or 0):
            last_active = r.date
    days_since_activity = (trading_day() - last_active).days if last_active else None

    if last_active is None and not rows:
        verdict = "Warming up — no completed bars evaluated yet."
    elif days_since_activity is not None and days_since_activity >= 3:
        verdict = (f"⚠ STALE — no bars, signals or trades for {days_since_activity} days "
                   f"(last activity {last_active.isoformat()}). The numbers below are "
                   "history, not current health. Check the data feed and the session gate.")
    elif camp["bars"] < camp["signals"]:
        verdict = ("⏳ Warming up — bar/rejection counters started at the last deploy. "
                   "The funnel reads correctly from the next full trading day.")
    elif camp["signals"] == 0 and camp["bars"] > 0:
        verdict = "No setups found yet — the strategy is looking and finding nothing."
    elif camp["signals"] > 0 and camp["taken"] == 0:
        verdict = ("⚠ Setups ARE firing but NONE became trades — something downstream "
                   "is blocking every one. Check the rejection reasons.")
    elif camp["rejected"] > camp["taken"] * 3 and camp["rejected"] > 5:
        verdict = "⚠ Most setups are being rejected — worth understanding why."
    elif camp["taken"] > 0:
        verdict = "Healthy: setups are being found and converted into trades."
    else:
        verdict = "Warming up — no completed bars evaluated yet."

    return {
        "scope": f"campaign since {meta['start_date']}" if meta else "all-time",
        "campaign": camp,
        "today": today,
        "conversion_pct": round(100.0 * camp["taken"] / camp["signals"], 1) if camp["signals"] else 0.0,
        "rejection_reasons": rej.get("by_reason") or {},
        "last_rejection": rej.get("last_reason"),
        "last_rejection_at": rej.get("last_at"),
        "last_activity_date": last_active.isoformat() if last_active else None,
        "days_since_activity": days_since_activity,
        "verdict": verdict,
        "daily": [
            {"date": r.date.isoformat(), "bars": r.bars_evaluated or 0,
             "signals": r.signals_generated or 0, "rejected": r.signals_rejected or 0,
             "taken": r.signals_taken or 0}
            for r in rows
        ],
    }


@app.get("/api/record")
async def record(db: Session = Depends(get_db)):
    """
    THE RECORD: the credible view. No gauges, no live telemetry — just the
    numbers someone with money would ask for. Equity curve with drawdown,
    R-multiple distribution, session and direction breakdown, and the backtest
    baseline to compare against.
    """
    import json as _json
    from backend.services.forward_test import get_campaign
    from backend.models.trade import EquitySnapshot

    meta = get_campaign()
    trades, scope = _campaign_trades(db)
    trades = [t for t in trades if t.exit_time]
    trades.sort(key=lambda t: t.exit_time)

    start_equity = (meta or {}).get("start_equity", settings.PROP_FIRM_ACCOUNT_SIZE)

    # Equity curve built from the trade log itself (the defensible source —
    # it reconciles to the trades a reviewer can inspect), plus the underwater
    # curve, which is the chart that actually decides whether a strategy is
    # survivable.
    equity, peak, max_dd, curve = start_equity, start_equity, 0.0, []
    for i, t in enumerate(trades, 1):
        equity += (t.net_pnl or 0.0)
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        curve.append({
            "n": i,
            "date": t.exit_time.date().isoformat(),
            "equity": round(equity, 2),
            "drawdown": round(-dd, 2),
            "pnl": round(t.net_pnl or 0.0, 2),
            "r": t.r_multiple,
        })

    wins = [t for t in trades if (t.net_pnl or 0) > 0]
    losses = [t for t in trades if (t.net_pnl or 0) < 0]
    gw = sum(t.net_pnl for t in wins) if wins else 0.0
    gl = abs(sum(t.net_pnl for t in losses)) if losses else 0.0
    n = len(trades)

    # R-multiple histogram — the shape of the edge, not just its average.
    buckets = [("≤-1R", -99, -1.0), ("-1 to -0.5", -1.0, -0.5), ("-0.5 to 0", -0.5, 0.0),
               ("0 to +1R", 0.0, 1.0), ("+1 to +2R", 1.0, 2.0), ("≥+2R", 2.0, 99)]
    r_dist = []
    for label, lo, hi in buckets:
        c = sum(1 for t in trades if t.r_multiple is not None and lo <= t.r_multiple < hi)
        r_dist.append({"bucket": label, "count": c})
    r_known = [t.r_multiple for t in trades if t.r_multiple is not None]

    def group(key_fn):
        out = {}
        for t in trades:
            k = key_fn(t) or "Unknown"
            g = out.setdefault(k, {"trades": 0, "wins": 0, "pnl": 0.0})
            g["trades"] += 1
            g["wins"] += 1 if (t.net_pnl or 0) > 0 else 0
            g["pnl"] = round(g["pnl"] + (t.net_pnl or 0.0), 2)
        for g in out.values():
            g["win_rate"] = round(100.0 * g["wins"] / g["trades"], 1) if g["trades"] else 0.0
            g["expectancy"] = round(g["pnl"] / g["trades"], 2) if g["trades"] else 0.0
        return out

    # Backtest baseline, if one has been generated (scripts/v2_backtest.py
    # --save-baseline). This is what the campaign is measured against.
    baseline = None
    try:
        with open(os.path.join("data", "baseline.json")) as f:
            baseline = _json.load(f)
    except Exception:
        baseline = None

    # day_index is 1-based (day 1 on the start date). days_elapsed is how many
    # days have actually PASSED. They differ by exactly one, and the field used
    # to be named days_elapsed while holding day_index — so on the start date it
    # claimed one day had elapsed before any had, and every downstream
    # multiplication inherited the inflation.
    day_index = 0
    days_elapsed = 0
    if meta:
        _delta = (trading_day() - date.fromisoformat(meta["start_date"])).days
        day_index = max(1, _delta + 1)
        days_elapsed = max(0, _delta)

    expected = None
    if baseline and day_index:
        b_days = max(1, baseline.get("days", 30))
        per_day = baseline.get("total_pnl", 0) / b_days
        b_pf = baseline.get("profit_factor")
        b_sessions = baseline.get("sessions")
        b_target_rr = baseline.get("target_rr")

        # A benchmark is only a benchmark if it describes the system that is
        # actually running, and if beating it means something. Neither was
        # checked, so the dashboard silently compared live results against a
        # LOSING backtest (PF 0.96, -$932) generated under a DIFFERENT session
        # set — which made any positive number read as "beating expectations".
        warnings = []
        comparable = True

        if b_pf is not None and b_pf < 1.0:
            warnings.append(
                f"Baseline is UNPROFITABLE (profit factor {b_pf}, "
                f"{baseline.get('total_pnl')} over {b_days}d). Beating it is not "
                "evidence of an edge — the bar itself is below break-even."
            )
            comparable = False

        live_sessions = sorted(getattr(settings, "V2_SESSIONS", None) or [])
        if b_sessions is None:
            warnings.append(
                "Baseline records no session set, so it cannot be verified "
                "against the live configuration. Regenerate it with "
                "scripts/v2_backtest.py --save-baseline to make this checkable."
            )
            comparable = False
        elif sorted(b_sessions) != live_sessions:
            warnings.append(
                f"Baseline tested sessions {sorted(b_sessions)} but the engine "
                f"is running {live_sessions}. Per-day P&L and trade frequency "
                "are not comparable across different session sets."
            )
            comparable = False

        live_rr = getattr(settings, "V2_TARGET_RR", 0) or None
        if b_target_rr is not None and live_rr and float(b_target_rr) != float(live_rr):
            warnings.append(
                f"Baseline used target {b_target_rr}R, the engine is running "
                f"{live_rr}R."
            )
            comparable = False

        expected = {
            "per_day": round(per_day, 2),
            # Scaled by day_index, not the old inflated value.
            "to_date": round(per_day * day_index, 2),
            "trades_per_day": round(baseline.get("total_trades", 0) / b_days, 2),
            "win_rate": baseline.get("win_rate"),
            "profit_factor": b_pf,
            "expectancy": round(baseline.get("total_pnl", 0) / max(1, baseline.get("total_trades", 1)), 2),
            # Consumers MUST check this before rendering any "vs expected"
            # verdict. False means the comparison is not meaningful.
            "comparable": comparable,
            "warnings": warnings,
            "baseline_sessions": b_sessions,
            "live_sessions": live_sessions,
        }

    return {
        "scope": scope,
        "start_date": (meta or {}).get("start_date"),
        "days_elapsed": days_elapsed,
        "day_index": day_index,
        "target_days": (meta or {}).get("target_days", 60),
        "start_equity": start_equity,
        "summary": {
            "trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(100.0 * len(wins) / n, 1) if n else 0.0,
            "net_pnl": round(sum(t.net_pnl or 0 for t in trades), 2),
            "profit_factor": round(gw / gl, 2) if gl > 0 else (float("inf") if gw > 0 else 0.0),
            "expectancy": round(sum(t.net_pnl or 0 for t in trades) / n, 2) if n else 0.0,
            "avg_win": round(gw / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-gl / len(losses), 2) if losses else 0.0,
            "payoff": round((gw / len(wins)) / (gl / len(losses)), 2) if wins and losses else 0.0,
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(100.0 * max_dd / start_equity, 2) if start_equity else 0.0,
            "avg_r": round(sum(r_known) / len(r_known), 2) if r_known else None,
            "return_pct": round(100.0 * sum(t.net_pnl or 0 for t in trades) / start_equity, 2) if start_equity else 0.0,
        },
        "curve": curve,
        "r_distribution": r_dist,
        "by_session": group(lambda t: t.session),
        "by_direction": group(lambda t: (t.side or "").upper()),
        "by_symbol": group(lambda t: t.symbol),
        "baseline": baseline,
        "expected": expected,
    }


@app.get("/api/stats/insights")
async def trade_insights(db: Session = Depends(get_db)):
    """
    Break the closed-trade history down by direction, symbol, session,
    exit reason and AI-confidence, then auto-generate plain-English
    strengths and weaknesses so the operator can SEE the edge (and the leaks).
    """
    import pytz
    from backend.strategies.v2 import sessions as V2S

    ET = pytz.timezone("America/New_York")
    UTC = pytz.utc
    SESSION_LABEL = {"ASIA": "Asia", "LONDON": "London", "NEW_YORK": "New York"}

    trades, scope = _campaign_trades(db)

    def stats_for(subset) -> dict:
        n = len(subset)
        if n == 0:
            return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                    "pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                    "payoff": 0.0, "expectancy": 0.0}
        wins = [t for t in subset if (t.net_pnl or 0) > 0]
        losses = [t for t in subset if (t.net_pnl or 0) <= 0]
        gw = sum(t.net_pnl or 0 for t in wins)
        gl = abs(sum(t.net_pnl or 0 for t in losses))
        aw = gw / len(wins) if wins else 0.0
        al = gl / len(losses) if losses else 0.0
        pnl = sum(t.net_pnl or 0 for t in subset)
        return {
            "trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / n * 100, 1),
            "pnl": round(pnl, 2),
            "avg_win": round(aw, 2), "avg_loss": round(-al, 2),
            "payoff": round(aw / al, 2) if al > 0 else 0.0,
            "expectancy": round(pnl / n, 2),
        }

    if not trades:
        return {
            "total_trades": 0, "scope": scope, "overall": stats_for([]), "win_loss_ratio": 0.0,
            "by_direction": {}, "by_symbol": {}, "by_session": {},
            "by_exit": {}, "by_confidence": {},
            "strengths": [], "weaknesses": [],
            "note": "Insights unlock as trades close. Run in paper mode to build history — they'll auto-surface your best direction, session, and instrument.",
        }

    def session_of(t) -> str:
        if not t.entry_time:
            return "Unknown"
        ts = t.entry_time
        if ts.tzinfo is None:
            ts = UTC.localize(ts)
        sess = V2S.active_session(ts.astimezone(ET))
        return SESSION_LABEL.get(sess.name, "Off-session") if sess else "Off-session"

    def conf_bucket(t) -> str:
        c = t.ai_confidence or 0
        if c >= 0.75:
            return ">75%"
        if c >= 0.65:
            return "65-75%"
        return "<65%"

    def group(key_fn) -> dict:
        buckets: dict = {}
        for t in trades:
            buckets.setdefault(key_fn(t), []).append(t)
        return {k: stats_for(v) for k, v in buckets.items()}

    overall = stats_for(trades)
    by_direction = group(lambda t: (t.side or "?").lower())
    by_symbol = group(lambda t: t.symbol or "?")
    by_session = group(session_of)
    by_exit = group(lambda t: t.status)
    by_confidence = group(conf_bucket)

    wl_ratio = round(overall["wins"] / overall["losses"], 2) if overall["losses"] else float(overall["wins"])

    # ── observations, NOT advice ──
    #
    # This block used to be a selection machine pointed at the operator. It
    # fired on n>=3 trades and emitted prescriptions — "consider dropping it",
    # "raising your threshold would help", "strong candidate to turn off" —
    # from samples where nothing whatsoever is detectable. On 171 trades the
    # minimum detectable effect is PF 1.26; on 3 trades it is meaningless. An
    # unledgered comparison presented as a recommendation is exactly how a
    # trader talks himself into curve-fitting.
    #
    # Rules now: (a) every claim carries its sample size, (b) nothing below
    # MIN_N is reported at all, (c) no imperative verbs — describe, never
    # prescribe, (d) a standing caveat until the sample can support inference.
    MIN_N = 30          # per-bucket floor for any comparative observation
    MIN_N_TOTAL = 200   # below this, no aggregate claim is inferentially valid

    strengths, weaknesses = [], []
    n_all = overall["trades"]

    if n_all < MIN_N_TOTAL:
        weaknesses.append(
            f"SAMPLE TOO SMALL for inference: {n_all} closed trades. "
            f"~{MIN_N_TOTAL} are needed before any figure here distinguishes edge "
            f"from variance. Everything below is descriptive only."
        )

    if overall["payoff"] >= 1.0:
        strengths.append(f"Winners pay {overall['payoff']}x losers (${overall['avg_win']:.0f} vs ${abs(overall['avg_loss']):.0f}) over {n_all} trades.")
    elif overall["payoff"] > 0:
        weaknesses.append(f"Losers (${abs(overall['avg_loss']):.0f}) outweigh winners (${overall['avg_win']:.0f}); payoff {overall['payoff']}x over {n_all} trades.")

    L, Sh = by_direction.get("long"), by_direction.get("short")
    if L and Sh and L["trades"] >= MIN_N and Sh["trades"] >= MIN_N:
        gap = L["win_rate"] - Sh["win_rate"]
        if abs(gap) >= 15:
            side = "Longs" if gap > 0 else "Shorts"
            a, b = (L, Sh) if gap > 0 else (Sh, L)
            strengths.append(
                f"{side} won {a['win_rate']}% (n={a['trades']}) vs {b['win_rate']}% (n={b['trades']}). "
                f"Directional split — not yet a validated difference."
            )

    rich_syms = {k: v for k, v in by_symbol.items() if v["trades"] >= MIN_N}
    if len(rich_syms) >= 2:
        best = max(rich_syms, key=lambda k: rich_syms[k]["expectancy"])
        worst = min(rich_syms, key=lambda k: rich_syms[k]["expectancy"])
        strengths.append(f"{best}: {rich_syms[best]['expectancy']:+.0f}/trade over {rich_syms[best]['trades']} trades (highest of {len(rich_syms)} instruments).")
        if rich_syms[worst]["expectancy"] < 0:
            weaknesses.append(f"{worst}: ${rich_syms[worst]['expectancy']:.0f}/trade over {rich_syms[worst]['trades']} trades (lowest of {len(rich_syms)}).")

    sess_n = {k: v for k, v in by_session.items() if v["trades"] >= MIN_N}
    for name, st in sess_n.items():
        sign = "net negative" if st["pnl"] < 0 else "net positive"
        weaknesses.append(f"{name}: {sign} ${st['pnl']:.0f} over {st['trades']} trades.") if st["pnl"] < 0 \
            else strengths.append(f"{name}: +${st['pnl']:.0f} over {st['trades']} trades, {st['win_rate']}% win rate.")
    if len(sess_n) >= 2:
        weaknesses.append(
            f"Comparing {len(sess_n)} sessions on one sample favours the winner by "
            f"selection alone — the best of 3 zero-edge sessions still shows a median "
            f"profit factor near 1.25. Session ranking here is not evidence."
        )

    so = by_exit.get("stopped_out")
    if so and n_all >= MIN_N and so["trades"] / n_all >= 0.5:
        weaknesses.append(f"{so['trades']} of {n_all} trades exited at a stop ({100*so['trades']/n_all:.0f}%).")

    if overall["expectancy"] > 0:
        strengths.append(f"Expectancy +${overall['expectancy']:.0f}/trade over {n_all} trades.")
    else:
        weaknesses.append(f"Expectancy -${abs(overall['expectancy']):.0f}/trade over {n_all} trades.")

    if not strengths:
        strengths.append(f"Nothing meets the {MIN_N}-trade reporting floor yet.")
    if not weaknesses:
        weaknesses.append(f"Nothing meets the {MIN_N}-trade reporting floor yet.")

    return {
        "total_trades": overall["trades"],
        "scope": scope,
        "overall": overall,
        "win_loss_ratio": wl_ratio,
        "by_direction": by_direction,
        "by_symbol": by_symbol,
        "by_session": by_session,
        "by_exit": by_exit,
        "by_confidence": by_confidence,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


# ── Paper Forward-Test ──────────────────────────────────────────────────────

@app.get("/api/forward-test/status")
async def forward_test_status(db: Session = Depends(get_db)):
    """
    Legacy campaign metadata. Calendar progress is not evidence of validity.
    """
    from backend.services.forward_test import campaign_status
    return campaign_status(db)


@app.post("/api/forward-test/begin")
async def forward_test_begin(target_days: int = 0, db: Session = Depends(get_db)):
    raise HTTPException(status_code=409, detail="Forward-run creation, replay into the trading ledger and reset are disabled. Register a frozen protocol and preserve research/forward records separately.")


def _guard_campaign(force: bool):
    """
    Replay/reset endpoints rewrite the trades table. While the 60-day live
    campaign is running that would corrupt the audited track record, so they
    refuse unless explicitly forced.
    """
    from backend.services.forward_test import get_campaign
    if get_campaign() is not None and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                "60-day forward-test campaign is ACTIVE — this would corrupt the "
                "audited track record. If you truly intend to abandon the campaign, "
                "call again with ?force=true."
            ),
        )


@app.post("/api/forward-test/run")
async def forward_test_run(period: str = "30d", force: bool = False, db: Session = Depends(get_db)):
    raise HTTPException(status_code=409, detail="Forward-run creation, replay into the trading ledger and reset are disabled. Register a frozen protocol and preserve research/forward records separately.")


@app.post("/api/forward-test/reset")
async def forward_test_reset(force: bool = False, db: Session = Depends(get_db)):
    raise HTTPException(status_code=409, detail="Forward-run creation, replay into the trading ledger and reset are disabled. Register a frozen protocol and preserve research/forward records separately.")


# ── Trading Control ───────────────────────────────────────────────────────────

@app.post("/api/trading/start")
async def start_trading():
    from backend.services.readiness import readiness_status
    raise HTTPException(status_code=409, detail=readiness_status())


@app.post("/api/trading/stop")
async def stop_trading():
    settings.TRADING_ENABLED = False
    if scheduler:
        await scheduler.stop()
    return {"trading_enabled": False, "message": "Trading stopped"}


@app.post("/api/trading/close-all")
async def close_all_positions():
    if not execution_service:
        raise HTTPException(status_code=503, detail="Execution service not ready")
    count = await execution_service.emergency_close_all()
    return {"closed": count, "message": f"Emergency closed {count} positions"}


# ── Prop Firm Status ──────────────────────────────────────────────────────────

@app.get("/api/prop-firm/status")
async def prop_firm_status(db: Session = Depends(get_db)):
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not ready")
    account = db.query(Account).first()
    today = db.query(DailyStats).filter(DailyStats.date == trading_day()).first()
    return risk_manager.get_prop_firm_status(account, today)


# ── Market Data ───────────────────────────────────────────────────────────────

@app.get("/api/market/quote/{symbol}")
async def get_quote(symbol: str):
    bar = market_data.get_realtime_bar(symbol.upper())
    if not bar:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    return bar


# ── AI Training ───────────────────────────────────────────────────────────────

@app.post("/api/ai/train")
async def train_model(symbol: str = "MES"):
    if not ai_engine:
        raise HTTPException(status_code=503, detail="AI engine not ready")
    result = ai_engine.train(symbol)
    return result


@app.get("/api/ai/models")
async def list_models():
    if not ai_engine:
        return {"models": []}
    return {"models": list(ai_engine.models.keys())}


# ── Backtest ──────────────────────────────────────────────────────────────────

@app.post("/api/backtest")
async def run_backtest(symbol: str = "MES", period: str = "30d"):
    if not ai_engine:
        raise HTTPException(status_code=503, detail="AI engine not ready")

    df = market_data.get_historical(symbol, period=period, interval="5m")
    df = market_data.add_indicators(df)
    if df.empty:
        raise HTTPException(status_code=500, detail="No data")

    results = []
    capital = settings.PROP_FIRM_ACCOUNT_SIZE
    pv = 5.0

    for i in range(50, len(df) - 10):
        sub_df = df.iloc[:i]
        pred = ai_engine.predict(symbol, sub_df)
        if pred["direction"] == "neutral" or pred["confidence"] < settings.AI_CONFIDENCE_THRESHOLD:
            continue

        row = df.iloc[i]
        entry = float(row["close"])
        atr = float(row.get("atr", entry * 0.002))

        if pred["direction"] == "long":
            stop = entry - atr * 1.5
            target = entry + atr * 3.0
        else:
            stop = entry + atr * 1.5
            target = entry - atr * 3.0

        # Simulate outcome using next 6 bars
        outcome = "timeout"
        for j in range(1, 7):
            if i + j >= len(df):
                break
            future = float(df.iloc[i + j]["close"])
            if pred["direction"] == "long":
                if future >= target:
                    outcome = "win"
                    exit_price = target
                    break
                if future <= stop:
                    outcome = "loss"
                    exit_price = stop
                    break
            else:
                if future <= target:
                    outcome = "win"
                    exit_price = target
                    break
                if future >= stop:
                    outcome = "loss"
                    exit_price = stop
                    break
        else:
            exit_price = float(df.iloc[min(i + 6, len(df) - 1)]["close"])

        if pred["direction"] == "long":
            pnl = (exit_price - entry) * pv
        else:
            pnl = (entry - exit_price) * pv

        capital += pnl
        results.append({"outcome": outcome, "pnl": round(pnl, 2)})

    if not results:
        return {"trades": 0, "message": "No signals generated in backtest period"}

    wins = [r for r in results if r["outcome"] == "win"]
    losses = [r for r in results if r["outcome"] == "loss"]
    total_pnl = sum(r["pnl"] for r in results)

    return {
        "symbol": symbol,
        "period": period,
        "total_trades": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(results) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(results), 2),
        "final_capital": round(capital, 2),
    }


# ── WebSocket Live Feed ───────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            # Send live update every 5 seconds
            db = SessionLocal()
            try:
                today = db.query(DailyStats).filter(DailyStats.date == trading_day()).first()
                open_trades = db.query(Trade).filter(Trade.status == "open").all()
                await ws.send_json({
                    "type": "heartbeat",
                    "market_open": market_data.is_futures_open(),
                    "daily_pnl": today.pnl if today else 0.0,
                    "open_positions": len(open_trades),
                    "scheduler": get_scheduler_state(),
                    "timestamp": utc_now().isoformat(),
                })
            finally:
                db.close()
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        _ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)
