from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, date

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Metadata
    strategy = Column(String(50), nullable=True)
    ai_confidence = Column(Float, nullable=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    broker_order_id = Column(String(100), nullable=True)
    exit_reason = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Trade date for daily grouping
    trade_date = Column(Date, default=date.today, index=True)

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
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
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
    signals_generated = Column(Integer, default=0)
    signals_taken = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
            "signals_taken": self.signals_taken,
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

    # Engine heartbeat: scheduler cycles recorded today. At a 60s cycle this
    # maxes at ~1440/day — uptime% = cycles / 1440.
    cycles = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "balance": self.balance,
            "equity": self.equity,
            "unrealized_pnl": self.unrealized_pnl,
            "cycles": self.cycles,
            "uptime_pct": round(min(100.0, (self.cycles or 0) / 1440.0 * 100.0), 1),
        }
