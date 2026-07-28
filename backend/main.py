import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import init_db, get_db, SessionLocal
from backend.models.trade import Trade, DailyStats
from backend.models.signal import Signal
from backend.models.account import Account
from backend.services.ai_engine import AIEngine
from backend.services.market_data import MarketDataService
from backend.services.risk_manager import RiskManager
from backend.services.execution import ExecutionService
from backend.services.scheduler import TradingScheduler, get_scheduler_state
from backend.brokers import get_broker

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
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

    os.makedirs("data", exist_ok=True)
    init_db()

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
    if settings.TRADING_ENABLED:
        await scheduler.start()

        # Auto-begin the forward-test campaign on first armed boot so the
        # 60-day clock starts the moment the engine goes live — no manual step
        # to forget, and the start date never moves after that.
        from backend.services.forward_test import get_campaign, begin_campaign
        if get_campaign() is None:
            try:
                acct = await broker.get_account()
                start_equity = float(acct.get("equity", settings.PROP_FIRM_ACCOUNT_SIZE))
            except Exception:
                start_equity = settings.PROP_FIRM_ACCOUNT_SIZE
            begin_campaign(
                settings.FORWARD_TEST_TARGET_DAYS,
                settings.STRATEGY,
                settings.SYMBOLS,
                start_equity,
            )

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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "symbols": settings.SYMBOLS,
        "ai_threshold": settings.AI_CONFIDENCE_THRESHOLD,
        "max_stop_dollars": settings.MAX_STOP_LOSS_DOLLARS,
        "daily_target": settings.DAILY_PROFIT_TARGET_DOLLARS,
    }


@app.post("/api/settings/max-stop")
async def set_max_stop(value: float):
    """Live-adjust the max stop-loss budget per trade from the dashboard."""
    value = max(50.0, min(5000.0, round(float(value))))
    settings.MAX_STOP_LOSS_DOLLARS = value
    # Push into the running strategy so it takes effect on the next signal.
    if scheduler is not None and getattr(scheduler, "strategy", None) is not None:
        try:
            scheduler.strategy.max_stop_dollars = value
        except Exception:
            pass
    return {"max_stop_dollars": settings.MAX_STOP_LOSS_DOLLARS}


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
        .filter(Trade.trade_date == date.today())
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
    stats = db.query(DailyStats).filter(DailyStats.date == date.today()).first()
    if not stats:
        return {"date": date.today().isoformat(), "pnl": 0.0, "trades_count": 0}
    return stats.to_dict()


@app.get("/api/stats/performance")
async def performance_stats(db: Session = Depends(get_db)):
    all_trades = db.query(Trade).filter(Trade.status.in_(["closed", "stopped_out", "target_hit"])).all()
    if not all_trades:
        return {"total_trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0}

    wins = [t for t in all_trades if (t.net_pnl or 0) > 0]
    losses = [t for t in all_trades if (t.net_pnl or 0) <= 0]

    avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t.net_pnl or 0 for t in all_trades)
    gross_wins = sum(t.net_pnl for t in wins) if wins else 0
    gross_losses = abs(sum(t.net_pnl for t in losses)) if losses else 0

    return {
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

    trades = db.query(Trade).filter(
        Trade.status.in_(["closed", "stopped_out", "target_hit"])
    ).all()

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
            "total_trades": 0, "overall": stats_for([]), "win_loss_ratio": 0.0,
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

    # ── auto strengths / weaknesses ──
    strengths, weaknesses = [], []

    if overall["payoff"] >= 1.0:
        strengths.append(f"Winners pay {overall['payoff']}x your losers (${overall['avg_win']:.0f} vs ${abs(overall['avg_loss']):.0f}) — the risk/reward math works.")
    elif overall["payoff"] > 0:
        weaknesses.append(f"Losers (${abs(overall['avg_loss']):.0f}) outweigh winners (${overall['avg_win']:.0f}) — payoff only {overall['payoff']}x. Let winners run or cut losers faster.")

    L, Sh = by_direction.get("long"), by_direction.get("short")
    if L and Sh and L["trades"] >= 3 and Sh["trades"] >= 3:
        if L["win_rate"] - Sh["win_rate"] >= 15:
            strengths.append(f"Longs win {L['win_rate']}% vs shorts {Sh['win_rate']}% — your edge is on the buy side. Filter shorts harder.")
        elif Sh["win_rate"] - L["win_rate"] >= 15:
            strengths.append(f"Shorts win {Sh['win_rate']}% vs longs {L['win_rate']}% — your edge is on the sell side.")

    rich_syms = {k: v for k, v in by_symbol.items() if v["trades"] >= 3}
    if len(rich_syms) >= 2:
        best = max(rich_syms, key=lambda k: rich_syms[k]["expectancy"])
        worst = min(rich_syms, key=lambda k: rich_syms[k]["expectancy"])
        if rich_syms[best]["expectancy"] > 0:
            strengths.append(f"{best} is your best instrument: +${rich_syms[best]['expectancy']:.0f}/trade over {rich_syms[best]['trades']} trades.")
        if rich_syms[worst]["expectancy"] < 0:
            weaknesses.append(f"{worst} is bleeding ${abs(rich_syms[worst]['expectancy']):.0f}/trade over {rich_syms[worst]['trades']} trades — consider dropping it.")

    for name, st in by_session.items():
        if st["trades"] >= 4 and st["pnl"] < 0:
            weaknesses.append(f"{name} session is net negative (${st['pnl']:.0f} over {st['trades']} trades) — strong candidate to turn off.")
        elif st["trades"] >= 4 and st["win_rate"] >= 58 and st["pnl"] > 0:
            strengths.append(f"{name} is your power window: {st['win_rate']}% win rate, +${st['pnl']:.0f}.")

    hi, lo = by_confidence.get(">75%"), by_confidence.get("<65%")
    if hi and lo and hi["trades"] >= 3 and lo["trades"] >= 3:
        if hi["win_rate"] > lo["win_rate"] + 10:
            strengths.append(f"High-confidence signals (>75%) win {hi['win_rate']}% vs {lo['win_rate']}% for low — the AI score is predictive. Raising your threshold would help.")
        elif lo["win_rate"] >= hi["win_rate"]:
            weaknesses.append("Low-confidence trades win as often as high-confidence ones — the confidence score needs recalibration.")

    so = by_exit.get("stopped_out")
    if so and overall["trades"] and so["trades"] / overall["trades"] >= 0.5:
        weaknesses.append(f"{so['trades']} of {overall['trades']} trades hit the stop — stops may be too tight or entries too early.")

    if overall["expectancy"] > 0:
        strengths.append(f"Positive expectancy: +${overall['expectancy']:.0f} per trade. This is the number that scales when you add size.")
    else:
        weaknesses.append(f"Negative expectancy: -${abs(overall['expectancy']):.0f} per trade. Do NOT add size until this flips positive.")

    if not strengths:
        strengths.append("No clear edge has emerged yet — let the sample grow before drawing conclusions.")
    if not weaknesses:
        weaknesses.append("No glaring leaks in this sample — keep monitoring as trades accumulate.")

    return {
        "total_trades": overall["trades"],
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
    The 60-day live paper campaign: day counter, equity curve, uptime
    heartbeat, and trade record since the immovable start date.
    """
    from backend.services.forward_test import campaign_status
    return campaign_status(db)


@app.post("/api/forward-test/begin")
async def forward_test_begin(target_days: int = 0, db: Session = Depends(get_db)):
    """
    Manually (re)start the campaign clock. Normally unnecessary — the campaign
    auto-begins the first time the engine boots armed. Restarting moves the
    start date, which invalidates the track record, so use deliberately.
    """
    from backend.services.forward_test import begin_campaign, campaign_status
    days = target_days or settings.FORWARD_TEST_TARGET_DAYS
    try:
        acct = await broker.get_account() if broker else {}
        start_equity = float(acct.get("equity", settings.PROP_FIRM_ACCOUNT_SIZE))
    except Exception:
        start_equity = settings.PROP_FIRM_ACCOUNT_SIZE
    begin_campaign(days, settings.STRATEGY, settings.SYMBOLS, start_equity)
    return campaign_status(db)


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
    """
    Replay the validated ORB edge over recent data and record the results as
    paper trades, so the Insights panel / charts fill immediately. Stage 1 of
    the plan — zero money at risk. Requires market-data access on the host.
    """
    _guard_campaign(force)
    try:
        from scripts.forward_test import run_forward_test
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Forward-test module unavailable: {exc}")

    symbols = [s for s in settings.SYMBOLS if s.upper() in ("MNQ", "NQ", "MES", "ES")] or ["MNQ", "NQ"]
    try:
        summary = run_forward_test(
            db, symbols, period=period,
            max_stop=settings.MAX_STOP_LOSS_DOLLARS, reset=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Forward-test failed: {exc}")
    return {"ok": True, **summary}


@app.post("/api/forward-test/reset")
async def forward_test_reset(force: bool = False, db: Session = Depends(get_db)):
    """Clear paper forward-test trades (leaves any real trades untouched)."""
    _guard_campaign(force)
    from scripts.forward_test import reset_forward_trades, rebuild_daily_stats
    cleared = reset_forward_trades(db)
    rebuild_daily_stats(db, settings.PROP_FIRM_ACCOUNT_SIZE)
    return {"ok": True, "cleared": cleared}


# ── Trading Control ───────────────────────────────────────────────────────────

@app.post("/api/trading/start")
async def start_trading():
    global scheduler
    settings.TRADING_ENABLED = True
    if scheduler and not get_scheduler_state()["running"]:
        await scheduler.start()
    return {"trading_enabled": True, "message": "Trading started"}


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
    today = db.query(DailyStats).filter(DailyStats.date == date.today()).first()
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
                today = db.query(DailyStats).filter(DailyStats.date == date.today()).first()
                open_trades = db.query(Trade).filter(Trade.status == "open").all()
                await ws.send_json({
                    "type": "heartbeat",
                    "market_open": market_data.is_futures_open(),
                    "daily_pnl": today.pnl if today else 0.0,
                    "open_positions": len(open_trades),
                    "scheduler": get_scheduler_state(),
                    "timestamp": datetime.utcnow().isoformat(),
                })
            finally:
                db.close()
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        _ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)
