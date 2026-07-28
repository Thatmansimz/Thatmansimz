import asyncio
import logging
from datetime import datetime, date

import pytz

from backend.config import settings
from backend.database import SessionLocal
from backend.models.trade import DailyStats
from backend.models.signal import Signal
from backend.services.ai_engine import AIEngine
from backend.services.market_data import MarketDataService
from backend.services.risk_manager import RiskManager
from backend.services.execution import trading_day

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Global state accessible by the API
_scheduler_state = {
    "running": False,
    "last_cycle": None,
    "cycles_today": 0,
    "signals_today": 0,
    "current_symbols": [],
    "started_at": None,
    "cycle_date": None,  # ET date the daily counters belong to
}


def get_scheduler_state() -> dict:
    return _scheduler_state.copy()


class TradingScheduler:
    def __init__(self, execution_service, ai_engine: AIEngine, risk_manager: RiskManager):
        self.execution = execution_service
        self.ai = ai_engine
        self.risk_manager = risk_manager
        self.market_data = MarketDataService()
        self._running = False
        self._task: asyncio.Task = None
        self._cycle_interval_seconds = 60

        # Select the active strategy. "ml" uses the AI engine directly;
        # rule-based strategies operate on a freshly fetched DataFrame.
        self.strategy_name = getattr(settings, "STRATEGY", "ml").lower()
        self.strategy = None
        if self.strategy_name == "orb":
            from backend.strategies.orb import ORBStrategy
            self.strategy = ORBStrategy(settings)
        elif self.strategy_name == "momentum":
            from backend.strategies.momentum import MomentumStrategy
            self.strategy = MomentumStrategy(settings)
        elif self.strategy_name == "multi_session":
            # V2 business-partner engine (NQ/MNQ, 3 sessions). Opt-in only.
            from backend.strategies.v2 import MultiSessionStrategy
            self.strategy = MultiSessionStrategy(settings)
        _scheduler_state["strategy"] = self.strategy_name
        logger.info("Active strategy: %s", self.strategy_name)

    async def start(self):
        if self._running:
            return
        self._running = True
        _scheduler_state["running"] = True
        _scheduler_state["started_at"] = datetime.now(ET).isoformat()
        self._task = asyncio.create_task(self._loop())
        logger.info("Trading scheduler started")

    async def stop(self):
        self._running = False
        _scheduler_state["running"] = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Trading scheduler stopped")

    def _recover_db(self):
        """
        Roll back the long-lived execution session after any failed write.

        ExecutionService holds ONE SQLAlchemy session for the entire 60-day run.
        A single failed commit — a transient "database is locked" from an
        overlapping restart or a manual script touching data/trading.db — leaves
        that session poisoned, so every later query raises PendingRollbackError.
        The handlers below swallow it, so the process never dies, launchd never
        restarts it, and /api/status keeps reporting "scanning" with a healthy
        feed while the engine has silently stopped both opening trades AND
        monitoring open ones. Same shape as the outage that cost 25 days.
        """
        try:
            self.execution.db.rollback()
        except Exception:
            pass

    async def _loop(self):
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.error("Scheduler cycle error: %s", exc, exc_info=True)
                self._recover_db()
            await asyncio.sleep(self._cycle_interval_seconds)

    async def _cycle(self):
        now_et = datetime.now(ET)

        # Daily rollover: reset per-day counters at the ET date change.
        # Without this, cycles_today/signals_today accumulate for the entire
        # 60-day run and the risk manager's daily P&L never resets.
        today_key = now_et.date().isoformat()
        if _scheduler_state.get("cycle_date") != today_key:
            _scheduler_state["cycle_date"] = today_key
            _scheduler_state["cycles_today"] = 0
            _scheduler_state["signals_today"] = 0
            self.risk_manager.reset_daily()

        _scheduler_state["last_cycle"] = now_et.isoformat()
        _scheduler_state["cycles_today"] = _scheduler_state.get("cycles_today", 0) + 1

        # Monitor open positions every cycle
        try:
            await self.execution.monitor_positions()
        except Exception as exc:
            logger.error("Position monitor error: %s", exc)
            self._recover_db()

        # Forward-test heartbeat: upsert today's equity snapshot every cycle so
        # the 60-day track record survives restarts and gaps stay visible.
        try:
            await self._record_equity_snapshot()
        except Exception as exc:
            logger.error("Equity snapshot error: %s", exc)

        # Check if we can open new trades
        db = SessionLocal()
        try:
            from backend.models.trade import DailyStats
            today_stats = db.query(DailyStats).filter(
                DailyStats.date == trading_day()
            ).first()
            account = db.query(__import__("backend.models.account", fromlist=["Account"]).Account).first()

            can_trade, reason = self.risk_manager.check_can_trade(today_stats, account)
            if not can_trade:
                _scheduler_state["scan_status"] = reason
                if reason not in ("Trading disabled", "Market closed"):
                    logger.info("Skipping signal scan: %s", reason)
                return

            _scheduler_state["scan_status"] = "scanning"
            for symbol in settings.SYMBOLS:
                await self._scan_symbol(symbol, db, today_stats)

            # Data-feed truth check: if downloads are failing, the engine is
            # BLIND, not idle — and the dashboard/watchdog must say so. This
            # exact silence (yfinance stale-session "possibly delisted") once
            # cost 25 days of a forward-test campaign.
            from backend.services.market_data import get_feed_health
            feed = get_feed_health()
            if not feed["healthy"]:
                _scheduler_state["scan_status"] = (
                    f"DATA OUTAGE — {feed['consecutive_failures']} failed fetches"
                )
                logger.error(
                    "DATA OUTAGE: %d consecutive failed downloads (last error: %s). "
                    "Engine is blind, not idle.",
                    feed["consecutive_failures"], feed["last_error"],
                )
        finally:
            db.close()

    async def _record_equity_snapshot(self):
        from backend.services.forward_test import record_snapshot
        try:
            acct = await self.execution.broker.get_account()
            balance = float(acct.get("balance", 0.0))
            equity = float(acct.get("equity", balance))
            unrealized = float(acct.get("unrealized_pnl", 0.0))
        except Exception:
            # Broker unreachable — fall back to the DB account row so the
            # heartbeat still ticks.
            db = SessionLocal()
            try:
                from backend.models.account import Account
                row = db.query(Account).first()
                balance = row.balance if row else 0.0
                equity = row.equity if row else balance
                unrealized = 0.0
            finally:
                db.close()

        db = SessionLocal()
        try:
            record_snapshot(db, balance, equity, unrealized)
        finally:
            db.close()

    async def _scan_symbol(self, symbol: str, db, daily_stats):
        try:
            if self.strategy is not None:
                # Rule-based strategy (ORB, momentum): fetch data and evaluate
                df = self.market_data.get_historical(symbol, period="10d", interval="5m")
                if df is None or df.empty:
                    # No data is NOT "no setup" — record the difference loudly.
                    _scheduler_state["last_no_signal"] = f"{symbol} — NO DATA (feed down)"
                    logger.warning("Scan skipped for %s: no market data", symbol)
                    return
                df = self.market_data.add_indicators(df)
                signal_data = self.strategy.generate_signal(df, symbol)
            else:
                # ML path: AI engine fetches its own data internally
                signal_data = self.ai.generate_signal(
                    symbol=symbol,
                    confidence_threshold=settings.AI_CONFIDENCE_THRESHOLD,
                    max_stop_dollars=settings.MAX_STOP_LOSS_DOLLARS,
                    min_rr=settings.MIN_RISK_REWARD_RATIO,
                )
        except Exception as exc:
            logger.error("Signal generation failed for %s: %s", symbol, exc)
            return

        if signal_data is None:
            _scheduler_state["last_no_signal"] = f"{symbol} — no setup"
            return

        logger.info(
            "Signal: %s %s | Conf: %.0f%% | Entry: %.2f | SL: %.2f | TP: %.2f",
            signal_data["direction"].upper(), symbol,
            signal_data["confidence"] * 100,
            signal_data["entry_price"],
            signal_data["stop_loss"],
            signal_data["target_1"],
        )

        if daily_stats:
            daily_stats.signals_generated = (daily_stats.signals_generated or 0) + 1
            db.commit()

        _scheduler_state["signals_today"] = _scheduler_state.get("signals_today", 0) + 1
        _scheduler_state["last_signal_symbol"] = symbol
        _scheduler_state["last_signal_dir"] = signal_data["direction"]
        _scheduler_state["last_signal_conf"] = round(signal_data["confidence"] * 100)
        _scheduler_state["scan_status"] = f"signal found: {signal_data['direction'].upper()} {symbol}"

        try:
            trade = await self.execution.process_signal(signal_data)
            if trade:
                logger.info("Trade executed: ID=%d", trade.id)
                _scheduler_state["scan_status"] = f"trade taken: {signal_data['direction'].upper()} {symbol}"
        except Exception as exc:
            logger.exception("Execution error for %s signal: %s", symbol, exc)
            self._recover_db()
