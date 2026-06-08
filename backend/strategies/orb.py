"""
Opening Range Breakout (ORB) Strategy
=====================================

The most-validated intraday edge in the public literature (cf. Zarattini &
Aziz, 2023). The logic is intentionally mechanical and objective:

  1. Define the OPENING RANGE — the high and low of the first N minutes after
     the 09:30 ET cash open (default 15 minutes).
  2. Wait for price to CLOSE beyond that range inside the entry window.
       • close > OR high  → LONG breakout
       • close < OR low   → SHORT breakout
  3. Confirm with VOLUME (relative volume) and optional VWAP alignment.
  4. Stop goes on the opposite side of the range, but is HARD-CAPPED so the
     dollar risk never exceeds MAX_STOP_LOSS_DOLLARS ($250 default).
  5. Target is a fixed R-multiple of the risk (default 2R) so every trade is
     at least 2:1 reward:risk by construction.

This module is used both live (scheduler calls generate_signal on a rolling
DataFrame) and in the backtester (same code path, bar by bar).
"""
from __future__ import annotations

import logging
from datetime import time as dtime
from typing import Optional

import pandas as pd
import pytz

from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Futures point values ($ per 1.00 point move, per contract)
POINT_VALUES = {
    "MES": 5.0,
    "MNQ": 2.0,
    "MGC": 10.0,
}


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout with volume + VWAP confluence and a hard risk cap."""

    name = "orb"
    description = "Opening Range Breakout — 15-min range, volume + VWAP confirmed, 2R target"

    def __init__(self, config=None):
        super().__init__(config)
        # ── Opening range definition ──
        self.or_minutes = 15          # length of the opening range window
        self.session_open = dtime(9, 30)
        self.entry_cutoff = dtime(11, 30)   # no new breakouts after this (ET)
        # ── Confluence filters ──
        self.min_rel_volume = 1.2     # breakout bar must have above-average volume
        self.use_vwap_filter = True   # longs above VWAP, shorts below
        # ── Risk / reward ──
        self.target_r_multiple = 2.0  # target = 2x risk
        self.stop_buffer_frac = 0.10  # stop sits this fraction of OR-range beyond the edge
        self.max_stop_dollars = getattr(config, "MAX_STOP_LOSS_DOLLARS", 250.0) if config else 250.0
        self.min_rr = getattr(config, "MIN_RISK_REWARD_RATIO", 2.0) if config else 2.0

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _et_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """Return the index expressed in US/Eastern, regardless of source tz."""
        if index.tz is None:
            # yfinance sometimes hands back naive timestamps already in ET
            return index
        return index.tz_convert(ET)

    def _opening_range(self, day_df: pd.DataFrame) -> Optional[tuple[float, float]]:
        """Compute (OR high, OR low) from the first `or_minutes` of a single day."""
        et = self._et_times(day_df.index)
        # Bars whose timestamp falls within [09:30, 09:30 + or_minutes)
        end_minute = self.session_open.hour * 60 + self.session_open.minute + self.or_minutes
        in_range = []
        for i, ts in enumerate(et):
            minute_of_day = ts.hour * 60 + ts.minute
            open_minute = self.session_open.hour * 60 + self.session_open.minute
            if open_minute <= minute_of_day < end_minute:
                in_range.append(i)
        if not in_range:
            return None
        window = day_df.iloc[in_range]
        return float(window["high"].max()), float(window["low"].min())

    # ──────────────────────────────────────────────────────────────────────
    # Core signal generation
    # ──────────────────────────────────────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        if df is None or df.empty or len(df) < 5:
            return None
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None

        et = self._et_times(df.index)

        # Isolate the most recent trading day present in the data
        latest_date = et[-1].date()
        day_mask = [ts.date() == latest_date for ts in et]
        day_df = df[day_mask]
        if len(day_df) < 2:
            return None

        # The current (just-closed) bar and the one before it
        curr = day_df.iloc[-1]
        prev = day_df.iloc[-2]
        curr_et = self._et_times(day_df.index)[-1]

        # Must be inside the entry window: after the OR forms, before the cutoff
        or_end_minute = (self.session_open.hour * 60 + self.session_open.minute) + self.or_minutes
        cutoff_minute = self.entry_cutoff.hour * 60 + self.entry_cutoff.minute
        curr_minute = curr_et.hour * 60 + curr_et.minute
        if curr_minute < or_end_minute or curr_minute > cutoff_minute:
            return None

        rng = self._opening_range(day_df)
        if rng is None:
            return None
        or_high, or_low = rng
        or_range = or_high - or_low
        if or_range <= 0:
            return None

        close = float(curr["close"])
        prev_close = float(prev["close"])
        rel_vol = float(curr.get("rel_volume", 1.0)) if "rel_volume" in day_df.columns else 1.0

        # Session VWAP — computed from THIS day's bars only (the global vwap in
        # market_data is cumulative across all days, which is wrong for ORB).
        day_typical = (day_df["high"] + day_df["low"] + day_df["close"]) / 3.0
        cum_vol = day_df["volume"].cumsum()
        vwap_series = (day_typical * day_df["volume"]).cumsum() / cum_vol.replace(0, float("nan"))
        vwap = float(vwap_series.iloc[-1]) if not vwap_series.empty else close
        if vwap != vwap:  # NaN guard
            vwap = close

        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        max_stop_points = self.max_stop_dollars / point_value

        direction = None
        # Fresh breakout: prior bar inside range, current bar closes beyond it
        if close > or_high and prev_close <= or_high:
            direction = "long"
        elif close < or_low and prev_close >= or_low:
            direction = "short"
        if direction is None:
            return None

        # ── Volume confirmation ──
        if rel_vol < self.min_rel_volume:
            return None

        # ── VWAP alignment ──
        vwap_aligned = True
        if self.use_vwap_filter:
            if direction == "long" and close < vwap:
                return None
            if direction == "short" and close > vwap:
                return None

        # ── Build entry / stop / target ──
        entry = close
        buffer = or_range * self.stop_buffer_frac
        if direction == "long":
            raw_stop = or_low - buffer
            stop_dist = entry - raw_stop
            if stop_dist > max_stop_points:        # hard $250 risk cap
                stop_dist = max_stop_points
            stop = entry - stop_dist
            target = entry + stop_dist * self.target_r_multiple
        else:
            raw_stop = or_high + buffer
            stop_dist = raw_stop - entry
            if stop_dist > max_stop_points:
                stop_dist = max_stop_points
            stop = entry + stop_dist
            target = entry - stop_dist * self.target_r_multiple

        if stop_dist <= 0:
            return None

        rr = abs(target - entry) / stop_dist
        risk_dollars = stop_dist * point_value

        # ── Confidence score (0.55 – 0.90) ──
        confidence = 0.55
        if rel_vol >= self.min_rel_volume:
            confidence += 0.10
        if rel_vol >= 2.0:
            confidence += 0.10
        if self.use_vwap_filter and vwap_aligned:
            confidence += 0.08
        # Strong-body breakout bar (closed near its extreme in trade direction)
        bar_range = float(curr["high"]) - float(curr["low"])
        if bar_range > 0:
            if direction == "long":
                body_pos = (close - float(curr["low"])) / bar_range
            else:
                body_pos = (float(curr["high"]) - close) / bar_range
            if body_pos > 0.7:
                confidence += 0.07
        confidence = round(min(0.90, confidence), 4)

        signal = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "entry_price": round(entry, 2),
            "entry_zone_low": round(entry - or_range * 0.05, 2),
            "entry_zone_high": round(entry + or_range * 0.05, 2),
            "stop_loss": round(stop, 2),
            "target_1": round(target, 2),
            "target_2": round(entry + (target - entry) * 1.5, 2),
            "risk_reward_ratio": round(rr, 2),
            "risk_amount": round(risk_dollars, 2),
            "strategy": self.name,
            "timeframe": "5m",
            "reason": (
                f"ORB {direction} | OR[{or_low:.2f}-{or_high:.2f}] "
                f"vol={rel_vol:.2f}x risk=${risk_dollars:.0f} R:R={rr:.1f}"
            ),
            "indicators": {
                "or_high": round(or_high, 2),
                "or_low": round(or_low, 2),
                "or_range": round(or_range, 2),
                "rel_volume": round(rel_vol, 2),
                "vwap": round(vwap, 2),
            },
        }

        if self.is_valid_signal(signal, self.max_stop_dollars, self.min_rr):
            logger.info(
                "ORB signal: %s %s | conf=%.2f | entry=%.2f | SL=%.2f | TP=%.2f | R:R=%.1f",
                direction.upper(), symbol, confidence,
                entry, stop, target, rr,
            )
            return signal
        return None
