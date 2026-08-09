from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean
from datetime import datetime, date
from backend.models.trade import Base
from backend.clock import utc_now


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    broker = Column(String(50), nullable=False)
    account_id = Column(String(100), nullable=True)

    # Balance information
    balance = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    buying_power = Column(Float, default=0.0)
    margin_used = Column(Float, default=0.0)
    margin_available = Column(Float, default=0.0)

    # Daily P&L
    daily_pnl = Column(Float, default=0.0)
    daily_pnl_percent = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl_today = Column(Float, default=0.0)

    # Session high water mark (for trailing drawdown calculation)
    session_high = Column(Float, default=0.0)
    all_time_high = Column(Float, default=0.0)

    # Prop firm tracking
    prop_firm = Column(String(50), default="none")
    evaluation_day = Column(Integer, default=1)
    evaluation_start_balance = Column(Float, nullable=True)
    peak_balance = Column(Float, nullable=True)
    max_drawdown_reached = Column(Float, default=0.0)
    cumulative_profit = Column(Float, default=0.0)
    evaluation_passed = Column(Boolean, default=False)
    evaluation_failed = Column(Boolean, default=False)
    failure_reason = Column(String(200), nullable=True)

    # Timestamps
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)
    created_at = Column(DateTime, default=utc_now)
    last_trade_date = Column(Date, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "broker": self.broker,
            "account_id": self.account_id,
            "balance": self.balance,
            "equity": self.equity,
            "buying_power": self.buying_power,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_percent": self.daily_pnl_percent,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl_today": self.realized_pnl_today,
            "prop_firm": self.prop_firm,
            "evaluation_day": self.evaluation_day,
            "cumulative_profit": self.cumulative_profit,
            "max_drawdown_reached": self.max_drawdown_reached,
            "evaluation_passed": self.evaluation_passed,
            "evaluation_failed": self.evaluation_failed,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    def calculate_drawdown_from_peak(self) -> float:
        """Calculate current drawdown from the peak balance."""
        if self.peak_balance and self.peak_balance > 0:
            return self.peak_balance - self.equity
        return 0.0

    def update_peak(self):
        """Update peak balance if current equity is higher."""
        if self.equity > (self.peak_balance or 0):
            self.peak_balance = self.equity
        if self.equity > self.all_time_high:
            self.all_time_high = self.equity
