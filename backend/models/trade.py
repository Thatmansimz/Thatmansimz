from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, date
from backend.clock import (configured_cycle_seconds, et_iso, expected_cycles,
                           trading_day, utc_now, uptime_pct)

Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # "long" | "short"
    qty = Column(Integer, nullable=False, default=1)

    # Prices
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    # stop_loss is the CURRENT working stop (trailing mutates it).
    # initial_stop_loss is the structural stop at entry and is NEVER rewritten —
    # without it, a trailed-to-breakeven trade records risk = $0 and the R
    # multiple of every trade is unreconstructable from the trades table.
    stop_loss = Column(Float, nullable=True)
    initial_stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    r_multiple = Column(Float, nullable=True)     # gross P&L / initial risk
    session = Column(String(20), nullable=True)   # ASIA / LONDON / NEW_YORK at entry

    # Status
    status = Column(String(20), nullable=False, default="pending")
    # "pending" | "open" | "closed" | "cancelled" | "stopped_out" | "target_hit"

    # P&L
    pnl = Column(Float, nullable=True, default=0.0)
    pnl_percent = Column(Float, nullable=True, default=0.0)
    commission = Column(Float, nullable=True, default=0.0)
    net_pnl = Column(Float, nullable=True, default=0.0)

    # Timestamps
    entry_time = Column(DateTime, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Metadata
    strategy = Column(String(50), nullable=True)
    ai_confidence = Column(Float, nullable=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    broker_order_id = Column(String(100), nullable=True)
    exit_reason = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Trade date for daily grouping. Defaults to the EXCHANGE date, never
    # date.today() — that is the host's local date, which on this Phoenix
    # machine is a different calendar day from ET for 3 hours of every night.
    trade_date = Column(Date, default=trading_day, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "initial_stop_loss": self.initial_stop_loss,
            "r_multiple": self.r_multiple,
            "session": self.session,
            "take_profit": self.take_profit,
            "status": self.status,
            "pnl": self.pnl,
            "net_pnl": self.net_pnl,
            "ai_confidence": self.ai_confidence,
            "strategy": self.strategy,
            # Stored naive UTC, kept as-is for anything that already parses it.
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            # …and the same instants on the exchange clock, which is the clock
            # trade_date, the sessions and the campaign day are all keyed to.
            # Without these a reader compares a UTC timestamp against an ET
            # date and concludes the record disagrees with itself.
            "entry_time_et": et_iso(self.entry_time),
            "exit_time_et": et_iso(self.exit_time),
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "exit_reason": self.exit_reason,
        }


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)

    # Balance tracking
    starting_balance = Column(Float, nullable=False, default=0.0)
    ending_balance = Column(Float, nullable=True)
    current_balance = Column(Float, nullable=False, default=0.0)
    high_water_mark = Column(Float, nullable=True)

    # P&L
    pnl = Column(Float, default=0.0)
    gross_pnl = Column(Float, default=0.0)
    commissions = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    max_runup = Column(Float, default=0.0)

    # Trade counts
    trades_count = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    breakeven = Column(Integer, default=0)

    # Session metadata
    market_hours_traded = Column(Float, default=0.0)
    # The funnel, persisted: how many setups the strategy found, how many the
    # risk layer turned away, how many became trades. Without the middle number
    # a silently-blocked engine is indistinguishable from a quiet market — the
    # exact ambiguity that cost this project 25 days.
    signals_generated = Column(Integer, default=0)
    signals_rejected = Column(Integer, default=0)
    signals_taken = Column(Integer, default=0)
    bars_evaluated = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    @property
    def win_rate(self) -> float:
        if self.trades_count == 0:
            return 0.0
        return (self.wins / self.trades_count) * 100.0

    @property
    def profit_factor(self) -> float:
        if self.losses == 0:
            return float("inf") if self.wins > 0 else 0.0
        return self.wins / self.losses

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "pnl": self.pnl,
            "max_drawdown": self.max_drawdown,
            "trades_count": self.trades_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "signals_generated": self.signals_generated,
            "signals_rejected": self.signals_rejected,
            "signals_taken": self.signals_taken,
            "bars_evaluated": self.bars_evaluated,
        }


class EquitySnapshot(Base):
    """
    One row per calendar day — the audited equity record for the forward-test
    campaign. Written by the scheduler every cycle (cheap upsert), so the
    curve survives restarts and gaps are visible as missing days.
    """
    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)

    balance = Column(Float, default=0.0)          # realized account balance
    equity = Column(Float, default=0.0)           # balance + unrealized
    unrealized_pnl = Column(Float, default=0.0)

    # Engine heartbeat: scheduler cycles recorded on this date.
    cycles = Column(Integer, default=0)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "balance": self.balance,
            "equity": self.equity,
            "unrealized_pnl": self.unrealized_pnl,
            "cycles": self.cycles,
            # Measured against cycles that were POSSIBLE on this date, not
            # against a hardcoded full day. For a past date that is the whole
            # day; for today it is only the elapsed part. Dividing today by a
            # full day is why this field and forward_test's uptime_today_pct
            # reported 3% and 100% for the same day in the same response.
            "uptime_pct": uptime_pct(self.cycles, self.date) if self.date else 0.0,
            "expected_cycles": expected_cycles(self.date) if self.date else 0,
            # Which cadence produced the figure above. Without this an
            # uptime% is uninterpretable — the live engine cycles every
            # ~120s, so a 60s assumption halves every reading.
            "cycle_seconds_assumed": configured_cycle_seconds(),
        }
