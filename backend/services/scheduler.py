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

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Global state accessible by the API
_scheduler_state = {
    "running": False,
    "last_cycle": None,
    "cycles_today": 0,
    "signals_today": 0,
    "current_symbols": [],
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
        _scheduler_state["strategy"] = self.strategy_name
        logger.info("Active strategy: %s", self.strategy_name)

    async def start(self):
        if self._running:
            return
        self._running = True
        _scheduler_state["running"] = True
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

    async def _loop(self):
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.error("Scheduler cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self._cycle_interval_seconds)

    async def _cycle(self):
        _scheduler_state["last_cycle"] = datetime.now(ET).isoformat()
        _scheduler_state["cycles_today"] = _scheduler_state.get("cycles_today", 0) + 1

        # Monitor open positions every cycle
        try:
            await self.execution.monitor_positions()
        except Exception as exc:
            logger.error("Position monitor error: %s", exc)

        # Check if we can open new trades
        db = SessionLocal()
        try:
            from backend.models.trade import DailyStats
            today_stats = db.query(DailyStats).filter(
                DailyStats.date == date.today()
            ).first()
            account = db.query(__import__("backend.models.account", fromlist=["Account"]).Account).first()

            can_trade, reason = self.risk_manager.check_can_trade(today_stats, account)
            if not can_trade:
                if reason not in ("Trading disabled", "Market closed"):
                    logger.info("Skipping signal scan: %s", reason)
                return

            for symbol in settings.SYMBOLS:
                await self._scan_symbol(symbol, db, today_stats)
        finally:
            db.close()

    async def _scan_symbol(self, symbol: str, db, daily_stats):
        try:
            if self.strategy is not None:
                # Rule-based strategy (ORB, momentum): fetch data and evaluate
                df = self.market_data.get_historical(symbol, period="10d", interval="5m")
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

        try:
            trade = await self.execution.process_signal(signal_data)
            if trade:
                logger.info("Trade executed: ID=%d", trade.id)
        except Exception as exc:
            logger.error("Execution error for %s signal: %s", symbol, exc)
