from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON
from datetime import datetime
from backend.models.trade import Base
from backend.clock import utc_now


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "long" | "short" | "neutral"

    # Confidence and scoring
    confidence = Column(Float, nullable=False)  # 0.0 to 1.0
    long_probability = Column(Float, nullable=True)
    short_probability = Column(Float, nullable=True)

    # Price levels
    entry_zone_low = Column(Float, nullable=True)
    entry_zone_high = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)

    # Risk metrics
    risk_reward_ratio = Column(Float, nullable=True)
    risk_amount = Column(Float, nullable=True)
    reward_amount = Column(Float, nullable=True)

    # Signal metadata
    timeframe = Column(String(10), nullable=True)  # "1m", "5m", "15m", "1h"
    strategy = Column(String(50), nullable=True)
    indicators_json = Column(JSON, nullable=True)

    # Status
    status = Column(String(20), default="pending")
    # "pending" | "triggered" | "expired" | "cancelled" | "taken"
    outcome = Column(String(20), nullable=True)
    # "win" | "loss" | "breakeven" | "pending"

    # Timestamps
    created_at = Column(DateTime, default=utc_now, index=True)
    expires_at = Column(DateTime, nullable=True)
    triggered_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": self.confidence,
            "long_probability": self.long_probability,
            "short_probability": self.short_probability,
            "entry_price": self.entry_price,
            "entry_zone_low": self.entry_zone_low,
            "entry_zone_high": self.entry_zone_high,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "risk_reward_ratio": self.risk_reward_ratio,
            "risk_amount": self.risk_amount,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "status": self.status,
            "outcome": self.outcome,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "indicators": self.indicators_json or {},
        }

    @property
    def is_valid(self) -> bool:
        """Check if signal is still valid (not expired or cancelled)."""
        if self.status in ("expired", "cancelled", "taken"):
            return False
        if self.expires_at and utc_now() > self.expires_at:
            return False
        return True
