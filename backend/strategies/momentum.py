"""
Momentum Strategy — rule-based signal generation using technical indicators.

Entry logic (long):
  • RSI crosses above 30 from oversold
  • Price above EMA 9 and EMA 21
  • MACD histogram turning positive
  • Volume above 1.2x 20-period average
  • ADX > 20 (trending market)

Entry logic (short):
  • RSI crosses below 70 from overbought
  • Price below EMA 9 and EMA 21
  • MACD histogram turning negative
  • Volume above 1.2x 20-period average
  • ADX > 20
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Futures point values
POINT_VALUES = {
    "MES": 5.0,
    "MNQ": 2.0,
    "MGC": 10.0,
}


class MomentumStrategy(BaseStrategy):
    """
    Rule-based momentum strategy using RSI, MACD, EMA, and volume confluence.
    No ML — purely deterministic indicator logic.
    """

    name = "momentum"
    description = "Multi-indicator momentum with RSI/MACD/EMA confluence"

    def __init__(self, config=None):
        super().__init__(config)
        self.rsi_oversold = 35.0
        self.rsi_overbought = 65.0
        self.min_adx = 20.0
        self.min_rel_volume = 1.1
        self.atr_stop_multiplier = 1.5
        self.atr_target_multiplier = 3.0

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        """Evaluate indicator confluence and return a signal dict or None."""
        required = {"rsi", "macd_hist", "ema_9", "ema_21", "adx", "atr", "rel_volume", "close"}
        if df.empty or not required.issubset(df.columns):
            return None

        if len(df) < 3:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        rsi_now = float(curr.get("rsi", 50))
        rsi_prev = float(prev.get("rsi", 50))
        macd_now = float(curr.get("macd_hist", 0))
        macd_prev = float(prev.get("macd_hist", 0))
        adx = float(curr.get("adx", 0))
        rel_vol = float(curr.get("rel_volume", 1))
        close = float(curr["close"])
        ema9 = float(curr.get("ema_9", close))
        ema21 = float(curr.get("ema_21", close))
        atr = float(curr.get("atr", close * 0.002))

        # Trend filter
        if adx < self.min_adx:
            return None
        if rel_vol < self.min_rel_volume:
            return None

        signal = None

        # Long setup
        long_score = 0
        if rsi_now > self.rsi_oversold and rsi_prev <= self.rsi_oversold:
            long_score += 2  # RSI cross above oversold
        elif rsi_now < 55:
            long_score += 1
        if macd_now > 0 and macd_prev <= 0:
            long_score += 2  # MACD histogram turned positive
        elif macd_now > macd_prev:
            long_score += 1
        if close > ema9:
            long_score += 1
        if close > ema21:
            long_score += 1
        if rel_vol > 1.5:
            long_score += 1

        # Short setup
        short_score = 0
        if rsi_now < self.rsi_overbought and rsi_prev >= self.rsi_overbought:
            short_score += 2  # RSI cross below overbought
        elif rsi_now > 45:
            short_score += 1
        if macd_now < 0 and macd_prev >= 0:
            short_score += 2  # MACD histogram turned negative
        elif macd_now < macd_prev:
            short_score += 1
        if close < ema9:
            short_score += 1
        if close < ema21:
            short_score += 1
        if rel_vol > 1.5:
            short_score += 1

        max_score = 7
        min_score_to_signal = 4

        if long_score >= min_score_to_signal and long_score > short_score:
            confidence = min(0.90, 0.50 + (long_score / max_score) * 0.40)
            entry = close
            stop = entry - atr * self.atr_stop_multiplier
            target1 = entry + atr * self.atr_target_multiplier
            target2 = entry + atr * self.atr_target_multiplier * 1.67

            stop_dist = abs(entry - stop)
            rr = abs(target1 - entry) / stop_dist if stop_dist > 0 else 0

            point_value = POINT_VALUES.get(symbol.upper(), 5.0)
            risk_dollars = stop_dist * point_value

            signal = {
                "symbol": symbol,
                "direction": "long",
                "confidence": round(confidence, 4),
                "entry_price": round(entry, 2),
                "entry_zone_low": round(entry - atr * 0.3, 2),
                "entry_zone_high": round(entry + atr * 0.3, 2),
                "stop_loss": round(stop, 2),
                "target_1": round(target1, 2),
                "target_2": round(target2, 2),
                "risk_reward_ratio": round(rr, 2),
                "risk_amount": round(risk_dollars, 2),
                "strategy": self.name,
                "reason": f"RSI={rsi_now:.1f} MACD_hist={macd_now:.4f} ADX={adx:.1f} Vol={rel_vol:.2f}x",
                "score": long_score,
            }

        elif short_score >= min_score_to_signal and short_score > long_score:
            confidence = min(0.90, 0.50 + (short_score / max_score) * 0.40)
            entry = close
            stop = entry + atr * self.atr_stop_multiplier
            target1 = entry - atr * self.atr_target_multiplier
            target2 = entry - atr * self.atr_target_multiplier * 1.67

            stop_dist = abs(entry - stop)
            rr = abs(target1 - entry) / stop_dist if stop_dist > 0 else 0

            point_value = POINT_VALUES.get(symbol.upper(), 5.0)
            risk_dollars = stop_dist * point_value

            signal = {
                "symbol": symbol,
                "direction": "short",
                "confidence": round(confidence, 4),
                "entry_price": round(entry, 2),
                "entry_zone_low": round(entry - atr * 0.3, 2),
                "entry_zone_high": round(entry + atr * 0.3, 2),
                "stop_loss": round(stop, 2),
                "target_1": round(target1, 2),
                "target_2": round(target2, 2),
                "risk_reward_ratio": round(rr, 2),
                "risk_amount": round(risk_dollars, 2),
                "strategy": self.name,
                "reason": f"RSI={rsi_now:.1f} MACD_hist={macd_now:.4f} ADX={adx:.1f} Vol={rel_vol:.2f}x",
                "score": short_score,
            }

        if signal and self.is_valid_signal(signal):
            logger.info(
                "Momentum signal: %s %s | conf=%.2f | entry=%.2f | R:R=%.2f",
                signal["direction"].upper(), symbol,
                signal["confidence"], signal["entry_price"],
                signal["risk_reward_ratio"],
            )
            return signal

        return None
