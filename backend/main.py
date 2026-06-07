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
    sched = get_scheduler_state()
    return {
        "status": "ok",
        "broker": settings.BROKER,
        "prop_firm": settings.PROP_FIRM,
        "trading_enabled": settings.TRADING_ENABLED,
        "market_open": market_data.is_market_open(),
        "scheduler_running": sched["running"],
        "last_cycle": sched.get("last_cycle"),
        "signals_today": sched.get("signals_today", 0),
        "symbols": settings.SYMBOLS,
        "ai_threshold": settings.AI_CONFIDENCE_THRESHOLD,
        "max_stop_dollars": settings.MAX_STOP_LOSS_DOLLARS,
        "daily_target": settings.DAILY_PROFIT_TARGET_DOLLARS,
    }


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
                    "market_open": market_data.is_market_open(),
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
