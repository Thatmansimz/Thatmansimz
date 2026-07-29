import logging
from datetime import datetime, date
from typing import Optional

import pytz
from sqlalchemy.orm import Session

from backend.models.trade import Trade, DailyStats
from backend.models.signal import Signal
from backend.models.account import Account
from backend.services.risk_manager import RiskManager, POINT_VALUES

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Why signals are being turned away, surfaced on /api/status so a silently
# non-trading engine can never again look identical to a quiet market.
_rejections: dict[str, int] = {}
_last_rejection: dict = {"reason": None, "at": None}


def _note_rejection(reason: str):
    key = reason.split("|")[0].strip()[:60]
    _rejections[key] = _rejections.get(key, 0) + 1
    _last_rejection["reason"] = key
    _last_rejection["at"] = datetime.now(ET).isoformat()


def rejection_summary() -> dict:
    return {
        "total": sum(_rejections.values()),
        "by_reason": dict(sorted(_rejections.items(), key=lambda kv: -kv[1])[:5]),
        "last_reason": _last_rejection["reason"],
        "last_at": _last_rejection["at"],
    }


def trading_day() -> date:
    """
    The trading date in EXCHANGE time, not the machine's local time.

    Every gate in this system (sessions, kill zones, market hours) runs on ET.
    If the record is keyed on the host's local date instead, then on any
    non-ET machine the recorded day flips mid-session — which silently resets
    the daily loss limit partway through the Asia window and shifts the equity
    curve one row off the trade log.
    """
    return datetime.now(ET).date()


def _point_value(symbol: str) -> float:
    """Dollars per 1-point move per contract for this symbol."""
    return POINT_VALUES.get(symbol.upper(), 5.0)


class ExecutionService:
    def __init__(self, broker, risk_manager: RiskManager, db: Session):
        self.broker = broker
        self.risk_manager = risk_manager
        self.db = db

    def _get_or_create_daily_stats(self, trade_date: date = None) -> DailyStats:
        trade_date = trade_date or trading_day()
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

    def _reject(self, daily_stats, reason: str, detail: str = ""):
        """
        Record a turned-away signal in BOTH the in-memory reason breakdown and
        the persisted daily counter. Every rejection path must come through
        here — an uncounted rejection is exactly how a blocked engine passes
        for a quiet market.
        """
        logger.warning("Signal REJECTED: %s%s", reason, f" | {detail}" if detail else "")
        _note_rejection(reason)
        if daily_stats:
            daily_stats.signals_rejected = (daily_stats.signals_rejected or 0) + 1
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

    async def process_signal(self, signal_data: dict) -> Optional[Trade]:
        account = self._get_account()
        daily_stats = self._get_or_create_daily_stats()

        can_trade, reason = self.risk_manager.check_can_trade(daily_stats, account)
        if not can_trade:
            logger.info("Signal blocked: %s", reason)
            self._reject(daily_stats, reason)
            return None

        valid, validation_msg = self.risk_manager.validate_signal(signal_data)
        if not valid:
            self._reject(daily_stats, validation_msg,
                         f"{signal_data.get('direction')} {signal_data.get('symbol')}")
            return None

        # One position per symbol — the broker book is keyed by symbol, so a
        # second concurrent trade on the same symbol would silently overwrite
        # the first and later be booked at its own entry price (a fabricated
        # break-even loser). The strategy is stateless and re-evaluates the same
        # forming 5m bar every 60s, so without this guard one setup becomes
        # several trades.
        existing = (
            self.db.query(Trade)
            .filter(Trade.symbol == signal_data["symbol"], Trade.status == "open")
            .first()
        )
        if existing:
            self._reject(daily_stats, "already in a position",
                         f"{signal_data['symbol']} trade id={existing.id}")
            return None

        # Pre-trade exposure gate: the daily-loss check above only counts
        # REALIZED P&L, so at -$1,999 of a $2,000 limit it would still admit a
        # trade risking $500-1,100 — a limit that can only detect a breach
        # after it happens is not a limit. Refuse when this trade's risk plus
        # everything already at risk could carry the day past the line.
        cand_risk = float(signal_data.get("est_risk_dollars") or 0.0)
        if not cand_risk:
            cand_risk = abs(signal_data["entry_price"] - signal_data["stop_loss"]) \
                * _point_value(signal_data["symbol"]) * signal_data.get("contracts", 1)
        open_risk = 0.0
        for t in self.db.query(Trade).filter(Trade.status == "open").all():
            stop_ref = t.initial_stop_loss or t.stop_loss or t.entry_price
            open_risk += abs((t.entry_price or 0) - (stop_ref or 0)) * _point_value(t.symbol) * t.qty
        realized = min(daily_stats.pnl or 0.0, self.risk_manager._daily_realized_pnl)
        loss_limit = self.risk_manager.config.get_prop_firm_rules()["daily_loss_limit"]
        projected = realized - cand_risk - open_risk
        if projected <= -loss_limit:
            msg = (f"projected exposure ${-projected:,.0f} would breach daily loss "
                   f"limit ${loss_limit:,.0f} (realized ${realized:,.0f}, "
                   f"this trade ${cand_risk:,.0f}, open ${open_risk:,.0f})")
            self._reject(daily_stats, "projected daily-loss breach", msg)
            return None

        # Save signal to DB. Optional fields are .get() — the V2 engine does not
        # emit entry zones or risk_amount, and hard-subscripting them raised a
        # KeyError that silently killed every single V2 signal.
        entry_px = signal_data["entry_price"]
        db_signal = Signal(
            symbol=signal_data["symbol"],
            direction=signal_data["direction"],
            confidence=signal_data["confidence"],
            long_probability=signal_data.get("prob_long", 0),
            short_probability=signal_data.get("prob_short", 0),
            entry_price=entry_px,
            entry_zone_low=signal_data.get("entry_zone_low", entry_px),
            entry_zone_high=signal_data.get("entry_zone_high", entry_px),
            stop_loss=signal_data["stop_loss"],
            target_1=signal_data["target_1"],
            target_2=signal_data.get("target_2"),
            risk_reward_ratio=signal_data["risk_reward_ratio"],
            risk_amount=signal_data.get(
                "risk_amount", signal_data.get("est_risk_dollars", 0.0)
            ),
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

        # Exit target MUST match what the backtest validated, or the live record
        # measures a system nobody tested. V2 sizes contracts so that TARGET_2
        # (the session R:R cap, 2R) lands in the $500-1500 window, and
        # scripts/v2_backtest.py exits at target_2 — that is where the 68-trade
        # / PF 1.34 / +$5,127 result comes from. Exiting at target_1 (1R) halves
        # every winner while losers stay full size, dropping the payoff ratio
        # from ~1.72 to ~0.81 — a losing configuration at V2's 41% win rate.
        # V1 ORB/momentum are untouched: their target_1 IS their real target.
        tp = signal_data["target_1"]
        if signal_data.get("strategy") == "multi_session":
            tp = signal_data.get("target_2") or tp

        try:
            order_result = await self.broker.submit_bracket_order(
                symbol=signal_data["symbol"],
                qty=qty,
                side=side,
                entry_price=signal_data["entry_price"],
                stop_price=signal_data["stop_loss"],
                target_price=tp,
            )
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            db_signal.status = "cancelled"
            self.db.commit()
            return None

        if not order_result or order_result.get("status") != "filled" or not order_result.get("order_id"):
            status = (order_result or {}).get("status")
            logger.error("Order not filled for %s (%s) — no trade recorded.",
                         signal_data["symbol"], status)
            # Count it like every other refusal, or a broker that rejects every
            # order looks exactly like a market with no setups.
            self._reject(daily_stats, f"broker rejected order ({status})")
            db_signal.status = "cancelled"
            self.db.commit()
            return None

        # Record trade at the actual FILL price (includes slippage), not the
        # signal price — otherwise slippage silently vanishes from the P&L.
        fill_price = order_result.get("fill_price", signal_data["entry_price"])
        trade = Trade(
            symbol=signal_data["symbol"],
            side=side,
            qty=qty,
            entry_price=fill_price,
            stop_loss=signal_data["stop_loss"],
            # Immutable copy — trailing rewrites stop_loss, and without this
            # the record can never reconstruct the risk that was actually taken.
            initial_stop_loss=signal_data["stop_loss"],
            session=signal_data.get("session"),
            take_profit=tp,
            take_profit_2=signal_data.get("target_2"),
            status="open",
            strategy=signal_data.get("strategy", "ai_ensemble"),
            ai_confidence=signal_data["confidence"],
            signal_id=db_signal.id,
            broker_order_id=order_result.get("order_id"),
            entry_time=datetime.utcnow(),
            trade_date=trading_day(),
        )
        self.db.add(trade)
        db_signal.status = "taken"

        # Update daily stats
        daily_stats.trades_count += 1
        daily_stats.signals_taken += 1

        self.risk_manager.increment_active_trades()
        self.db.commit()

        # Log the FILL price, not the signal price — the log is part of the
        # audit trail and must agree with the trades table. (They differ by the
        # slippage tick, which is exactly the sort of gap that makes a record
        # look doctored when someone reconciles it later.)
        logger.info(
            "Trade opened: %s %s x%d @ %.2f (signal %.2f) | SL: %.2f | TP: %.2f | Conf: %.0f%%",
            side.upper(), signal_data["symbol"], qty,
            fill_price, signal_data["entry_price"], signal_data["stop_loss"],
            tp, signal_data["confidence"] * 100,
        )
        return trade

    async def monitor_positions(self):
        open_trades = (
            self.db.query(Trade).filter(Trade.status == "open").all()
        )
        # Self-heal the concurrent-trades counter from the DB — it starts at 0
        # after a restart even when positions are open, and V2 trades can be
        # held across the midnight counter reset.
        self.risk_manager.sync_active_trades(len(open_trades))
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

        # Update the trailing stop using the SAME rule the backtest ran.
        # The old path used calculate_trailing_stop (breakeven at 0.5R, no
        # trail, and it measured R against its own mutated output so it froze
        # after one move) — a different exit system from the validated one,
        # which manufactured breakeven scratches the backtest never took.
        new_stop = self._trailing_stop_v2(trade, current_price) \
            if trade.strategy == "multi_session" else \
            self.risk_manager.calculate_trailing_stop(
                trade.symbol, trade.side, trade.entry_price, current_price,
                trade.initial_stop_loss or trade.stop_loss,
            )
        # Trailing may only tighten, never widen.
        improved = (new_stop > trade.stop_loss) if trade.side == "long" else (new_stop < trade.stop_loss)
        if improved:
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

    def _trailing_stop_v2(self, trade: Trade, current_price: float) -> float:
        """
        Reproduce scripts/v2_backtest.py's exit management exactly (lines
        78-90 of simulate()): move to breakeven once price has run +1R from
        entry — R measured against the IMMUTABLE initial stop — then ratchet
        behind min(EMA-12, price - 0.25R) on every cycle. This is the rule the
        +$5,127 baseline was produced under; the strategy itself advertises it
        ('method': 'ema12_pivot', 'breakeven_at_r': 1.0).
        """
        init_stop = trade.initial_stop_loss or trade.stop_loss
        r = abs(trade.entry_price - init_stop)
        stop = trade.stop_loss
        if r <= 0:
            return stop

        # EMA-12 of completed 5m closes, same series the backtest uses.
        ema = None
        try:
            from backend.services.market_data import MarketDataService
            md = MarketDataService()
            df = md.get_historical(trade.symbol, period="5d", interval="5m")
            df = md.drop_forming_bar(df)
            if df is not None and not df.empty:
                ema = float(df["close"].ewm(span=12, adjust=False).mean().iloc[-1])
        except Exception:
            ema = None

        if trade.side == "long":
            if current_price >= trade.entry_price + r and stop < trade.entry_price:
                stop = trade.entry_price
            if ema is not None:
                stop = max(stop, min(ema, current_price - r * 0.25))
        else:
            if current_price <= trade.entry_price - r and stop > trade.entry_price:
                stop = trade.entry_price
            if ema is not None:
                stop = min(stop, max(ema, current_price + r * 0.25))
        return round(stop, 2)

    async def _reconcile_closed_trade(self, trade: Trade):
        try:
            fill = await self.broker.get_last_fill(trade.broker_order_id)
        except Exception:
            fill = None

        # Only an actual EXIT fill may close a trade. The old code defaulted to
        # trade.take_profit when the fill was missing — i.e. it assumed the most
        # profitable possible outcome — and otherwise fell back to the ENTRY
        # fill, booking exit == entry. Both fabricate results. If we cannot
        # prove how the trade ended, leave it open and say so loudly.
        if not fill or not fill.get("exit") or not fill.get("price"):
            logger.error(
                "Trade %d (%s, order %s): broker has no exit fill — leaving OPEN "
                "for reconciliation rather than inventing an exit price.",
                trade.id, trade.symbol, trade.broker_order_id,
            )
            return
        # Carry the actual exit CAUSE into the record. The broker knows whether
        # the stop or the target was crossed; collapsing everything to
        # "broker_closed" made a target-hit and a stop-out — the two most
        # different events in the record — indistinguishable in the DB.
        cause = {"target": "target", "stop": "stop_loss", "manual": "manual"}.get(
            fill.get("cause"), "broker_closed"
        )
        await self._finalize_trade(trade, float(fill["price"]), cause)

    async def close_position(self, trade_id: int, reason: str = "manual") -> bool:
        trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade or trade.status != "open":
            return False

        try:
            fill = await self.broker.close_position(trade.symbol)
        except Exception as exc:
            logger.error("Failed to close trade %d: %s", trade_id, exc)
            return False

        # The paper broker returns {"price": 0.0, "status": "no_position"} when
        # it has nothing to close. That 0.0 used to be accepted as a real exit
        # price, booking a five-figure phantom loss that also tripped the
        # max-drawdown lockout permanently. Never finalize on a refusal.
        if not fill or fill.get("status") == "no_position" or not fill.get("price"):
            logger.error(
                "Trade %d: broker reports no position for %s — NOT finalizing "
                "(would have booked a fake exit). Leaving open.",
                trade_id, trade.symbol,
            )
            return False

        await self._finalize_trade(trade, float(fill["price"]), reason)
        return True

    async def _finalize_trade(self, trade: Trade, exit_price: float, reason: str):
        from backend.config import settings
        from backend.services.costs import round_trip_commission

        # Last line of defence for the track record: no legitimate futures exit
        # is zero or wildly detached from the entry. Refuse rather than write a
        # number that would poison the balance, the drawdown gate and the
        # permanent equity curve.
        entry = trade.entry_price or 0.0
        if not exit_price or exit_price <= 0 or (
            entry > 0 and abs(exit_price - entry) / entry > 0.25
        ):
            logger.error(
                "Trade %d (%s): REFUSING to finalize at implausible exit %.2f "
                "(entry %.2f, reason=%s). Trade left open.",
                trade.id, trade.symbol, exit_price or 0.0, entry, reason,
            )
            return

        pv = _point_value(trade.symbol)
        if trade.side == "long":
            gross_pnl = (exit_price - trade.entry_price) * pv * trade.qty
        else:
            gross_pnl = (trade.entry_price - exit_price) * pv * trade.qty

        commission = round_trip_commission(trade.qty, settings.COMMISSION_PER_SIDE)
        net_pnl = gross_pnl - commission

        trade.exit_price = exit_price
        trade.exit_time = datetime.utcnow()
        trade.pnl = round(gross_pnl, 2)
        trade.net_pnl = round(net_pnl, 2)
        trade.commission = commission
        trade.exit_reason = reason

        # R multiple against the IMMUTABLE initial stop — the working stop is
        # trailed, so measuring against it makes every trade's risk read $0.
        init_stop = trade.initial_stop_loss or trade.stop_loss
        init_risk = abs((trade.entry_price or 0) - (init_stop or 0)) * pv * trade.qty
        trade.r_multiple = round(gross_pnl / init_risk, 2) if init_risk > 0 else None

        # Status comes from the exit CAUSE, not from the sign of the P&L.
        # Sign-derived status wrote "target_hit" on manual closes that were
        # 90 points from the target, and "stopped_out" on trailed-breakeven
        # scratches that never touched the structural stop.
        if reason == "target":
            trade.status = "target_hit"
        elif reason == "stop_loss":
            trailed_to_be = (
                trade.initial_stop_loss is not None
                and abs((trade.stop_loss or 0) - (trade.entry_price or 0))
                    < abs((trade.initial_stop_loss or 0) - (trade.entry_price or 0)) * 0.5
            )
            trade.status = "breakeven_stop" if trailed_to_be else "stopped_out"
        else:
            trade.status = "closed"   # manual / end_of_day / emergency / legacy

        # Book the outcome on the SAME day row the trade was counted on. Using
        # "today" here split every overnight Asia trade across two rows — the
        # trade counted on Monday, its win/loss on Tuesday — which made every
        # daily win-rate arithmetically impossible and mis-charged the daily
        # loss limit to a day that never took the risk.
        daily_stats = self._get_or_create_daily_stats(trade.trade_date)
        daily_stats.pnl = (daily_stats.pnl or 0) + net_pnl
        daily_stats.gross_pnl = (daily_stats.gross_pnl or 0) + gross_pnl
        daily_stats.commissions = (daily_stats.commissions or 0) + commission
        if net_pnl > 0:
            daily_stats.wins += 1
        elif net_pnl < 0:
            daily_stats.losses += 1
        else:
            # A true scratch is neither — booking it as a loss made the trades
            # table and the daily table disagree about the same event.
            daily_stats.breakeven = (daily_stats.breakeven or 0) + 1

        # Move the account — without this, balance/equity flatline forever and
        # the forward-test equity curve records nothing.
        account = self._get_account()
        if account:
            account.balance = (account.balance or 0.0) + net_pnl
            account.equity = account.balance
            account.realized_pnl_today = (account.realized_pnl_today or 0.0) + net_pnl
            account.cumulative_profit = (account.cumulative_profit or 0.0) + net_pnl
            account.last_trade_date = trading_day()
            account.update_peak()
            drawdown = account.calculate_drawdown_from_peak()
            account.max_drawdown_reached = max(account.max_drawdown_reached or 0.0, drawdown)
        if account:
            daily_stats.current_balance = account.balance
            daily_stats.ending_balance = account.balance
            hwm = max(daily_stats.high_water_mark or daily_stats.starting_balance or 0.0,
                      account.balance)
            daily_stats.high_water_mark = hwm
            daily_stats.max_drawdown = max(daily_stats.max_drawdown or 0.0,
                                           hwm - account.balance)

        # Commit the DB FIRST, then move the broker's persisted balance. If the
        # broker went first and the commit failed, the trade would still be
        # "open" while the balance already moved — and the recovery path would
        # book the same P&L a second time. DB-then-broker means the worst case
        # is a retry that finds the trade already closed.
        self.risk_manager.decrement_active_trades()
        self.risk_manager.update_daily_pnl(net_pnl)
        self.db.commit()

        realize = getattr(self.broker, "realize_pnl", None)
        if callable(realize):
            realize(net_pnl)

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
