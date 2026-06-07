"""
Base strategy interface that all trading strategies must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Subclasses implement generate_signal() and return a dict or None.
    """

    name: str = "base"
    description: str = ""

    def __init__(self, config=None):
        self.config = config
        self.enabled = True

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        """
        Analyse the DataFrame and return a signal dict, or None if no setup.

        Expected return format:
        {
            "symbol": str,
            "direction": "long" | "short",
            "confidence": float (0-1),
            "entry_price": float,
            "stop_loss": float,
            "target_1": float,
            "target_2": float,
            "risk_reward_ratio": float,
            "strategy": str,
            "reason": str,
        }
        """

    def is_valid_signal(self, signal: dict, max_stop_dollars: float = 250.0, min_rr: float = 2.0) -> bool:
        """Basic validation shared across all strategies."""
        if not signal:
            return False
        if signal.get("direction") == "neutral":
            return False
        if signal.get("confidence", 0) < 0.50:
            return False
        if signal.get("risk_reward_ratio", 0) < min_rr:
            return False
        return True

    def __repr__(self) -> str:
        return f"<Strategy: {self.name}>"
