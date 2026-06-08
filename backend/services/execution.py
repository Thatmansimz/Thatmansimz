import logging
from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.trade import Trade, DailyStats
from backend.models.signal import Signal
from backend.models.account import Account
from backend.services.risk_manager import RiskManager, POINT_VALUES

logger = logging.getLogger(__name__)


def _point_value(symbol: str) -> float:
    """Dollars per 1-point move per contract for this symbol."""
    return POINT_VALUES.get(symbol.upper(), 5.0)


class ExecutionService:
    def __init__(self, broker, risk_manager: RiskManager, db: Session):
        self.broker = broker
        self.risk_manager = risk_manager
        self.db = db

    def _get_or_create_daily_stats(self, trade_date: date = None) -> DailyStats:
        trade_date = trade_date or date.today()
        stats = self.db.query(DailyStats).filter(DailyStats.date == trade_date).first()
        if not stats:
            account = self.db.query(Account).first()
            balance = account.balance if account else 0.0
            stats = DailyStats(
                date=trade_date,
                starting_balance=balance,
                current_balance=balance,
            )
            self.db.add(stats)
            self.db.commit()
        return stats

    def _get_account(self) -> Optional[Account]:
        return self.db.query(Account).first()

    async def process_signal(self, signal_data: dict) -> Optional[Trade]:
        account = self._get_account()
        daily_stats = self._get_or_create_daily_stats()

        can_trade, reason = self.risk_manager.check_can_trade(daily_stats, account)
        if not can_trade:
            logger.info("Signal blocked: %s", reason)
            return None

        valid, validation_msg = self.risk_manager.validate_signal(signal_data)
        if not valid:
            logger.info("Signal invalid: %s", validation_msg)
            return None

        # Save signal to DB
        db_signal = Signal(
            symbol=signal_data["symbol"],
            direction=signal_data["direction"],
            confidence=signal_data["confidence"],
            long_probability=signal_data.get("prob_long", 0),
            short_probability=signal_data.get("prob_short", 0),
            entry_price=signal_data["entry_price"],
            entry_zone_low=signal_data["entry_zone_low"],
            entry_zone_high=signal_data["entry_zone_high"],
            stop_loss=signal_data["stop_loss"],
            target_1=signal_data["target_1"],
            target_2=signal_data.get("target_2"),
            risk_reward_ratio=signal_data["risk_reward_ratio"],
            risk_amount=signal_data["risk_amount"],
            timeframe=signal_data.get("timeframe", "5m"),
            strategy=signal_data.get("strategy", "ai_ensemble"),
            indicators_json=signal_data.get("indicators", {}),
            status="triggered",
            triggered_at=datetime.utcnow(),
        )
        self.db.add(db_signal)
        self.db.flush()

        # Submit order via broker
        qty = signal_data.get("contracts", 1)
        side = signal_data["direction"]

        try:
            order_result = await self.broker.submit_bracket_order(
                symbol=signal_data["symbol"],
                qty=qty,
                side=side,
                entry_price=signal_data["entry_price"],
                stop_price=signal_data["stop_loss"],
                target_price=signal_data["target_1"],
            )
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            db_signal.status = "cancelled"
            self.db.commit()
            return None

        # Record trade
        trade = Trade(
            symbol=signal_data["symbol"],
            side=side,
            qty=qty,
            entry_price=signal_data["entry_price"],
            stop_loss=signal_data["stop_loss"],
            take_profit=signal_data["target_1"],
            take_profit_2=signal_data.get("target_2"),
            status="open",
            strategy=signal_data.get("strategy", "ai_ensemble"),
            ai_confidence=signal_data["confidence"],
            signal_id=db_signal.id,
            broker_order_id=order_result.get("order_id"),
            entry_time=datetime.utcnow(),
            trade_date=date.today(),
        )
        self.db.add(trade)
        db_signal.status = "taken"

        # Update daily stats
        daily_stats.trades_count += 1
        daily_stats.signals_taken += 1

        self.risk_manager.increment_active_trades()
        self.db.commit()

        logger.info(
            "Trade opened: %s %s x%d @ %.2f | SL: %.2f | TP: %.2f | Conf: %.0f%%",
            side.upper(), signal_data["symbol"], qty,
            signal_data["entry_price"], signal_data["stop_loss"],
            signal_data["target_1"], signal_data["confidence"] * 100,
        )
        return trade

    async def monitor_positions(self):
        open_trades = (
            self.db.query(Trade).filter(Trade.status == "open").all()
        )
        for trade in open_trades:
            await self._check_trade(trade)

    async def _check_trade(self, trade: Trade):
        try:
            position = await self.broker.get_position(trade.symbol)
        except Exception as exc:
            logger.warning("Could not check position for trade %d: %s", trade.id, exc)
            return

        if not position:
            # Broker says position is gone — trade was closed externally
            await self._reconcile_closed_trade(trade)
            return

        current_price = position.get("current_price", trade.entry_price)

        # Update trailing stop
        new_stop = self.risk_manager.calculate_trailing_stop(
            trade.symbol, trade.side, trade.entry_price, current_price, trade.stop_loss
        )
        if new_stop != trade.stop_loss:
            trade.stop_loss = new_stop
            try:
                await self.broker.update_stop(trade.broker_order_id, new_stop)
            except Exception:
                pass

        # Calculate unrealized P&L
        pv = _point_value(trade.symbol)
        if trade.side == "long":
            pnl = (current_price - trade.entry_price) * pv * trade.qty
        else:
            pnl = (trade.entry_price - current_price) * pv * trade.qty
        trade.pnl = round(pnl, 2)

        # Force close 5 minutes before market close
        from backend.services.risk_manager import RiskManager
        if self.risk_manager.minutes_until_close() <= 5:
            await self.close_position(trade.id, "end_of_day")
            return

        self.db.commit()

    async def _reconcile_closed_trade(self, trade: Trade):
        try:
            fill = await self.broker.get_last_fill(trade.broker_order_id)
        except Exception:
            fill = None

        exit_price = trade.take_profit if fill is None else fill.get("price", trade.entry_price)
        await self._finalize_trade(trade, exit_price, "broker_closed")

    async def close_position(self, trade_id: int, reason: str = "manual") -> bool:
        trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade or trade.status != "open":
            return False

        try:
            fill = await self.broker.close_position(trade.symbol)
            exit_price = fill.get("price", trade.entry_price)
        except Exception as exc:
            logger.error("Failed to close trade %d: %s", trade_id, exc)
            return False

        await self._finalize_trade(trade, exit_price, reason)
        return True

    async def _finalize_trade(self, trade: Trade, exit_price: float, reason: str):
        pv = _point_value(trade.symbol)
        if trade.side == "long":
            gross_pnl = (exit_price - trade.entry_price) * pv * trade.qty
        else:
            gross_pnl = (trade.entry_price - exit_price) * pv * trade.qty

        commission = trade.qty * 2.0  # ~$2/contract round-trip estimate
        net_pnl = gross_pnl - commission

        trade.exit_price = exit_price
        trade.exit_time = datetime.utcnow()
        trade.pnl = round(gross_pnl, 2)
        trade.net_pnl = round(net_pnl, 2)
        trade.commission = commission
        trade.exit_reason = reason

        if net_pnl > 0:
            trade.status = "target_hit" if reason != "stop_loss" else "stopped_out"
        elif net_pnl < 0:
            trade.status = "stopped_out"
        else:
            trade.status = "closed"

        # Update daily stats
        daily_stats = self._get_or_create_daily_stats()
        daily_stats.pnl = (daily_stats.pnl or 0) + net_pnl
        daily_stats.gross_pnl = (daily_stats.gross_pnl or 0) + gross_pnl
        daily_stats.commissions = (daily_stats.commissions or 0) + commission
        if net_pnl > 0:
            daily_stats.wins += 1
        else:
            daily_stats.losses += 1

        self.risk_manager.decrement_active_trades()
        self.risk_manager.update_daily_pnl(net_pnl)
        self.db.commit()

        logger.info(
            "Trade closed: %s %s @ %.2f | P&L: $%.2f | Reason: %s",
            trade.side.upper(), trade.symbol, exit_price, net_pnl, reason,
        )

    async def emergency_close_all(self) -> int:
        open_trades = self.db.query(Trade).filter(Trade.status == "open").all()
        closed = 0
        for trade in open_trades:
            if await self.close_position(trade.id, "emergency"):
                closed += 1
        logger.warning("Emergency close: closed %d positions", closed)
        return closed
