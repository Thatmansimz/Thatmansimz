import logging
from datetime import datetime, date, timedelta, time as dtime
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
            # CME equity-index futures: Sunday 18:00 ET → Friday 17:00 ET, with
            # a daily 17:00–18:00 ET maintenance halt.
            #
            # The previous version was shifted one day (it blocked ALL of Sunday
            # and allowed Fri-night through Sat-afternoon), which killed every
            # Sunday-night Asia kill zone while the dashboard showed LIVE, and
            # let the engine "trade" a frozen Friday bar all weekend.
            # Python weekday: Mon=0 … Fri=4, Sat=5, Sun=6.
            t = now.time()
            if weekday == 5:                                  # Saturday: closed
                return False
            if weekday == 6:                                  # Sunday: reopen 18:00 ET
                return t >= dtime(18, 0)
            if weekday == 4 and t >= dtime(17, 0):            # Friday: closed 17:00 ET
                return False
            if dtime(17, 0) <= t < dtime(18, 0):              # daily maintenance halt
                return False
            return True

        # Regular equity hours: Mon–Fri 9:30–16:00 ET
        if weekday >= 5:
            return False
        open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_time <= now <= close_time

    def _futures_clock(self) -> bool:
        """
        24/5 strategies (V2 multi_session) run on the futures clock, where the
        daily "close" is the 17:00 ET CME maintenance halt — NOT the 16:00
        equity close. Using the equity clock here silently blocked ALL trading
        after 3:55 PM ET (minutes_until_close hit 0), which killed the entire
        Asia kill zone (8–10 PM ET) and instantly force-closed any overnight
        position as "end_of_day".
        """
        return getattr(self.config, "STRATEGY", "").lower() == "multi_session"

    def minutes_until_close(self) -> int:
        now = datetime.now(ET)
        if self._futures_clock():
            close = now.replace(hour=17, minute=0, second=0, microsecond=0)
            if now >= close:
                close += timedelta(days=1)
            return max(0, int((close - now).total_seconds() / 60))
        close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return max(0, int((close - now).total_seconds() / 60))

    def should_avoid_trading(self) -> tuple[bool, str]:
        """Avoid trading in the final 5 minutes before close and first 5 after open."""
        now = datetime.now(ET)
        mins_to_close = self.minutes_until_close()
        if mins_to_close < 5:
            return True, "Too close to market close"

        # First-5-minutes guard applies to the 9:30 NY open. V2 sessions have
        # their own volatility pauses, so this only guards the NY cash open.
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

    def _risk_cap(self, strategy: str) -> float:
        """
        Risk ceiling per trade, per strategy.

        V1 ORB sizes itself TO a risk budget, so MAX_STOP_LOSS_DOLLARS is both
        its sizing input and its ceiling. V2 multi_session sizes to a $500–1500
        PROFIT window instead (that is what the 30-day backtest validated), so
        its risk lands in the $400–1000 range. Judging V2 against V1's $250
        ceiling rejected 100% of V2 signals — the engine generated setups
        forever and never placed a single trade.
        """
        if strategy == "multi_session":
            return float(getattr(self.config, "V2_MAX_RISK_DOLLARS", 1100.0))
        return float(self.config.MAX_STOP_LOSS_DOLLARS)

    def validate_signal(self, signal: dict) -> tuple[bool, str]:
        stop_distance = abs(signal["entry_price"] - signal["stop_loss"])
        contracts = signal.get("contracts", 1)
        symbol = signal["symbol"]
        strategy = signal.get("strategy", "")
        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        risk_dollars = stop_distance * point_value * contracts

        cap = self._risk_cap(strategy)
        if risk_dollars > cap:
            return False, f"Risk ${risk_dollars:.0f} exceeds max ${cap:.0f}"

        rr = signal.get("risk_reward_ratio", 0)
        if rr < self.config.MIN_RISK_REWARD_RATIO:
            return False, f"R:R {rr:.2f} below minimum {self.config.MIN_RISK_REWARD_RATIO}"

        # Rule-based strategies were validated in the backtest WITHOUT a
        # confidence gate — the strategy's own entry logic IS the quality
        # filter. AI_CONFIDENCE_THRESHOLD applies to the ML model only.
        # multi_session belongs here too: its confidence is a descriptive score
        # starting at 0.55, so the 0.65 threshold silently rejected every V2
        # setup outside a kill zone — trades the backtest counted.
        if strategy not in ("orb", "momentum", "multi_session"):
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

            # Stop if daily loss limit breached.
            # DailyStats.pnl books to the trade's ENTRY day, so an Asia trade
            # opened Monday night and stopped out Tuesday morning charges its
            # loss to Monday — leaving Tuesday's limit reading $0 while real
            # money was lost today. _daily_realized_pnl is keyed to the EXIT day
            # (reset on the ET rollover), so take whichever is worse.
            if min(daily_pnl, self._daily_realized_pnl) <= -prop_rules["daily_loss_limit"]:
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
        # Daily P&L tracking resets at the ET date change. The active trade
        # count deliberately does NOT reset — V2 positions can be held across
        # midnight, and the count self-heals from the DB every monitor cycle.
        self._daily_realized_pnl = 0.0
        self._session_high_pnl = 0.0

    def sync_active_trades(self, count: int):
        self._active_trade_count = max(0, count)
