import logging
from datetime import datetime, date
from typing import Optional

import pytz

from backend.models.trade import DailyStats
from backend.models.account import Account

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Futures contract point values (dollars per 1 point move per contract)
POINT_VALUES = {
    "MES": 5.0,
    "MNQ": 2.0,
    "NQ": 20.0,
    "ES": 50.0,
    "MGC": 10.0,
    "MYM": 0.5,
    "M2K": 5.0,
}


class RiskManager:
    def __init__(self, config):
        self.config = config
        self._active_trade_count = 0
        self._daily_realized_pnl = 0.0
        self._session_high_pnl = 0.0

    # ── Market Hours ──────────────────────────────────────────────────────────

    def is_market_open(self, instrument_type: str = "futures") -> bool:
        now = datetime.now(ET)
        weekday = now.weekday()

        if instrument_type == "futures":
            # Futures trade nearly 24/5 (closed Fri 5pm – Sun 6pm ET)
            if weekday == 6:
                return False
            if weekday == 5 and now.hour >= 17:
                return False
            return True

        # Regular equity hours: Mon–Fri 9:30–16:00 ET
        if weekday >= 5:
            return False
        open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_time <= now <= close_time

    def minutes_until_close(self) -> int:
        now = datetime.now(ET)
        close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return max(0, int((close - now).total_seconds() / 60))

    def should_avoid_trading(self) -> tuple[bool, str]:
        """Avoid trading in the final 5 minutes before close and first 5 after open."""
        now = datetime.now(ET)
        mins_to_close = self.minutes_until_close()
        if mins_to_close < 5:
            return True, "Too close to market close"

        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        mins_since_open = (now - market_open).total_seconds() / 60
        if 0 < mins_since_open < 5:
            return True, "First 5 minutes after open — high volatility"

        return False, ""

    # ── Position Sizing ───────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        account_balance: float = 50000.0,
    ) -> int:
        stop_distance = abs(entry_price - stop_price)
        if stop_distance == 0:
            return 1

        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        risk_per_contract = stop_distance * point_value

        # Risk-based sizing (% of account)
        risk_dollars = account_balance * (self.config.RISK_PER_TRADE_PERCENT / 100)
        risk_dollars = min(risk_dollars, self.config.MAX_STOP_LOSS_DOLLARS)

        contracts = int(risk_dollars / risk_per_contract)
        return max(1, min(contracts, 20))

    def calculate_stop_loss_dollars(
        self,
        symbol: str,
        entry: float,
        stop: float,
        contracts: int,
    ) -> float:
        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        return abs(entry - stop) * point_value * contracts

    # ── Trade Validation ──────────────────────────────────────────────────────

    def validate_signal(self, signal: dict) -> tuple[bool, str]:
        stop_distance = abs(signal["entry_price"] - signal["stop_loss"])
        contracts = signal.get("contracts", 1)
        symbol = signal["symbol"]
        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        risk_dollars = stop_distance * point_value * contracts

        if risk_dollars > self.config.MAX_STOP_LOSS_DOLLARS:
            return False, f"Risk ${risk_dollars:.0f} exceeds max ${self.config.MAX_STOP_LOSS_DOLLARS}"

        rr = signal.get("risk_reward_ratio", 0)
        if rr < self.config.MIN_RISK_REWARD_RATIO:
            return False, f"R:R {rr:.2f} below minimum {self.config.MIN_RISK_REWARD_RATIO}"

        # Rule-based strategies (ORB, momentum) were validated in the backtest
        # without a confidence gate — the strategy's own signal logic IS the
        # quality filter. AI_CONFIDENCE_THRESHOLD applies to the ML model only.
        strategy = signal.get("strategy", "")
        if strategy not in ("orb", "momentum"):
            if signal["confidence"] < self.config.AI_CONFIDENCE_THRESHOLD:
                return False, f"Confidence {signal['confidence']:.2f} below threshold"

        return True, "ok"

    def check_can_trade(
        self,
        daily_stats: Optional[DailyStats],
        account: Optional[Account],
    ) -> tuple[bool, str]:
        if not self.config.TRADING_ENABLED:
            return False, "Trading disabled"

        if not self.is_market_open():
            return False, "Market closed"

        should_avoid, reason = self.should_avoid_trading()
        if should_avoid:
            return False, reason

        if self._active_trade_count >= self.config.MAX_CONCURRENT_TRADES:
            return False, f"Max concurrent trades ({self.config.MAX_CONCURRENT_TRADES}) reached"

        if daily_stats:
            daily_pnl = daily_stats.pnl or 0.0
            prop_rules = self.config.get_prop_firm_rules()

            # Stop if daily profit target hit
            if daily_pnl >= self.config.DAILY_PROFIT_TARGET_DOLLARS:
                return False, f"Daily profit target ${self.config.DAILY_PROFIT_TARGET_DOLLARS:,.0f} reached"

            # Stop if daily loss limit breached
            if daily_pnl <= -prop_rules["daily_loss_limit"]:
                return False, f"Daily loss limit ${prop_rules['daily_loss_limit']:,.0f} breached"

            # Warn buffer at 80% of daily loss limit
            if daily_pnl <= -(prop_rules["daily_loss_limit"] * 0.8):
                logger.warning("Approaching daily loss limit: $%.0f used", abs(daily_pnl))

        if account:
            prop_rules = self.config.get_prop_firm_rules()
            if account.max_drawdown_reached >= prop_rules["max_drawdown"]:
                return False, f"Max drawdown ${prop_rules['max_drawdown']:,.0f} reached"

        return True, "ok"

    # ── Prop Firm Dashboard ───────────────────────────────────────────────────

    def get_prop_firm_status(
        self,
        account: Optional[Account],
        daily_stats: Optional[DailyStats],
    ) -> dict:
        rules = self.config.get_prop_firm_rules()
        daily_pnl = daily_stats.pnl if daily_stats else 0.0
        cumulative = account.cumulative_profit if account else 0.0
        drawdown = account.max_drawdown_reached if account else 0.0

        return {
            "firm": rules.get("name", "None"),
            "allows_automation": rules.get("allows_automation", True),
            "account_size": rules["account_size"],
            "daily_loss_limit": rules["daily_loss_limit"],
            "daily_loss_used": abs(min(daily_pnl, 0.0)),
            "daily_loss_remaining": max(0, rules["daily_loss_limit"] + daily_pnl),
            "max_drawdown_limit": rules["max_drawdown"],
            "max_drawdown_used": drawdown,
            "max_drawdown_remaining": max(0, rules["max_drawdown"] - drawdown),
            "profit_target": rules["profit_target"],
            "cumulative_profit": cumulative,
            "profit_progress_pct": min(100, (cumulative / rules["profit_target"]) * 100) if rules["profit_target"] > 0 else 0,
            "evaluation_passed": (account.evaluation_passed if account else False),
            "evaluation_failed": (account.evaluation_failed if account else False),
            "trailing_drawdown": rules.get("trailing_drawdown", False),
            "notes": rules.get("notes", ""),
        }

    # ── Trailing Stop ─────────────────────────────────────────────────────────

    def calculate_trailing_stop(
        self,
        symbol: str,
        side: str,
        entry: float,
        current_price: float,
        original_stop: float,
        trail_after_pct: float = 0.5,
    ) -> float:
        """Move stop to breakeven once trade is 50% of the way to target."""
        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        if side == "long":
            gain = current_price - entry
            if gain > 0 and gain >= abs(entry - original_stop) * trail_after_pct:
                return max(original_stop, entry)
        else:
            gain = entry - current_price
            if gain > 0 and gain >= abs(entry - original_stop) * trail_after_pct:
                return min(original_stop, entry)

        return original_stop

    # ── State Tracking ────────────────────────────────────────────────────────

    def increment_active_trades(self):
        self._active_trade_count += 1

    def decrement_active_trades(self):
        self._active_trade_count = max(0, self._active_trade_count - 1)

    def update_daily_pnl(self, pnl_delta: float):
        self._daily_realized_pnl += pnl_delta
        self._session_high_pnl = max(self._session_high_pnl, self._daily_realized_pnl)

    def reset_daily(self):
        self._daily_realized_pnl = 0.0
        self._session_high_pnl = 0.0
        self._active_trade_count = 0
