"""
Opening Range Breakout (ORB) + ICC Continuation Strategy
========================================================

Two entry models, selectable via `entry_mode`:

  • "breakout"  — classic: enter when a bar CLOSES beyond the opening range.
                  Simple, but prone to fakeouts (low win rate on its own).

  • "icc"       — Indication / Correction / Continuation (default):
                  1. INDICATION  : price breaks the opening range (shows intent)
                  2. CORRECTION  : price pulls back but HOLDS the broken level
                  3. CONTINUATION: we enter only when price resumes in the
                     breakout direction, taking out the pullback's high/low.
                  The pullback filters fakeouts and gives a tighter stop
                  (below the correction low) → higher win rate, better R:R.

Both modes share:
  • A REGIME FILTER (ADX trending + EMA/VWAP alignment) so we only trade when
    the market is actually moving, not chopping.
  • A hard $250 risk cap and a fixed R-multiple target (≥ 2:1 by construction).

Used identically live (scheduler) and in the backtester.
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

POINT_VALUES = {"MES": 5.0, "MNQ": 2.0, "MGC": 10.0}


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout with ICC continuation entries and a regime filter."""

    name = "orb"
    description = "Opening Range Breakout + ICC continuation, regime-filtered, 2R target"

    def __init__(self, config=None):
        super().__init__(config)
        # ── Opening range ──
        self.or_minutes = 15
        self.session_open = dtime(9, 30)
        self.entry_cutoff = dtime(12, 0)      # no new entries after noon ET

        # ── Entry model ──
        self.entry_mode = "icc"               # "icc" | "breakout"

        # ── Regime / trend filter ──
        self.require_trend = True
        self.min_adx = 18.0                   # below this = chop, stand aside
        self.use_ema_filter = True            # longs above EMA-50, shorts below
        self.use_vwap_filter = True           # longs above session VWAP, shorts below

        # ── Confluence ──
        self.min_rel_volume = 1.1

        # ── Risk / reward ──
        self.target_r_multiple = 2.0
        self.stop_buffer_frac = 0.10
        self.max_stop_dollars = getattr(config, "MAX_STOP_LOSS_DOLLARS", 250.0) if config else 250.0
        self.min_rr = getattr(config, "MIN_RISK_REWARD_RATIO", 2.0) if config else 2.0

        # ── Red-folder news filter ──
        from backend.services.news_filter import NewsFilter
        self.news_filter = NewsFilter(
            enabled=getattr(config, "NEWS_FILTER_ENABLED", True) if config else True,
            pre_minutes=getattr(config, "NEWS_BLACKOUT_PRE_MIN", 15) if config else 15,
            post_minutes=getattr(config, "NEWS_BLACKOUT_POST_MIN", 15) if config else 15,
            calendar_path=getattr(config, "NEWS_CALENDAR_PATH", "data/news_calendar.json") if config else "data/news_calendar.json",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _et_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
        if index.tz is None:
            return index
        return index.tz_convert(ET)

    @staticmethod
    def _minute_of_day(ts) -> int:
        return ts.hour * 60 + ts.minute

    def _opening_range(self, day_df: pd.DataFrame, et: pd.DatetimeIndex) -> Optional[tuple[float, float]]:
        open_min = self._minute_of_day(self.session_open)
        end_min = open_min + self.or_minutes
        idxs = [i for i, ts in enumerate(et) if open_min <= self._minute_of_day(ts) < end_min]
        if not idxs:
            return None
        window = day_df.iloc[idxs]
        return float(window["high"].max()), float(window["low"].min())

    def _session_vwap(self, day_df: pd.DataFrame) -> float:
        typical = (day_df["high"] + day_df["low"] + day_df["close"]) / 3.0
        cum_vol = day_df["volume"].cumsum()
        vwap_series = (typical * day_df["volume"]).cumsum() / cum_vol.replace(0, float("nan"))
        v = float(vwap_series.iloc[-1]) if not vwap_series.empty else float(day_df["close"].iloc[-1])
        return v if v == v else float(day_df["close"].iloc[-1])

    # ──────────────────────────────────────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        if df is None or df.empty or len(df) < 5:
            return None
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None

        et_full = self._et_times(df.index)
        latest_date = et_full[-1].date()
        day_mask = [ts.date() == latest_date for ts in et_full]
        day_df = df[day_mask]
        if len(day_df) < 4:
            return None
        et = self._et_times(day_df.index)

        # Entry window: after OR forms, before cutoff
        or_end_min = self._minute_of_day(self.session_open) + self.or_minutes
        cutoff_min = self._minute_of_day(self.entry_cutoff)
        curr_min = self._minute_of_day(et[-1])
        if curr_min < or_end_min or curr_min > cutoff_min:
            return None

        # ── Red-folder news blackout ──
        blackout, why = self.news_filter.in_blackout(et[-1])
        if blackout:
            logger.debug("Skipping %s — news blackout (%s)", symbol, why)
            return None

        rng = self._opening_range(day_df, et)
        if rng is None:
            return None
        or_high, or_low = rng
        or_range = or_high - or_low
        if or_range <= 0:
            return None

        # Post-opening-range bars (the tradable portion of the session)
        post_idxs = [i for i, ts in enumerate(et) if self._minute_of_day(ts) >= or_end_min]
        if len(post_idxs) < 2:
            return None
        post = day_df.iloc[post_idxs]

        curr = post.iloc[-1]
        close = float(curr["close"])
        rel_vol = float(curr.get("rel_volume", 1.0)) if "rel_volume" in day_df.columns else 1.0
        vwap = self._session_vwap(day_df)
        ema_50 = float(curr.get("ema_50", close)) if "ema_50" in day_df.columns else close
        adx = float(curr.get("adx", 0.0)) if "adx" in day_df.columns else 0.0

        point_value = POINT_VALUES.get(symbol.upper(), 5.0)
        max_stop_points = self.max_stop_dollars / point_value

        # ── Pick direction + stop reference based on entry mode ──
        if self.entry_mode == "icc":
            setup = self._icc_setup(post, or_high, or_low)
        else:
            setup = self._breakout_setup(post, or_high, or_low)
        if setup is None:
            return None
        direction, stop_ref = setup  # stop_ref = price level the stop sits beyond

        # ── Filters ──
        if rel_vol < self.min_rel_volume:
            return None
        if self.require_trend and adx < self.min_adx:
            return None
        if self.use_ema_filter:
            if direction == "long" and close < ema_50:
                return None
            if direction == "short" and close > ema_50:
                return None
        if self.use_vwap_filter:
            if direction == "long" and close < vwap:
                return None
            if direction == "short" and close > vwap:
                return None

        # ── Build entry / stop / target ──
        entry = close
        buffer = or_range * self.stop_buffer_frac
        if direction == "long":
            raw_stop = stop_ref - buffer
            stop_dist = entry - raw_stop
        else:
            raw_stop = stop_ref + buffer
            stop_dist = raw_stop - entry

        if stop_dist <= 0:
            return None
        if stop_dist > max_stop_points:        # hard $250 cap
            stop_dist = max_stop_points

        if direction == "long":
            stop = entry - stop_dist
            target = entry + stop_dist * self.target_r_multiple
        else:
            stop = entry + stop_dist
            target = entry - stop_dist * self.target_r_multiple

        rr = abs(target - entry) / stop_dist
        risk_dollars = stop_dist * point_value

        # ── Confidence ──
        confidence = 0.55
        if rel_vol >= 1.5:
            confidence += 0.10
        if rel_vol >= 2.0:
            confidence += 0.05
        if adx >= 25:
            confidence += 0.10
        if self.entry_mode == "icc":
            confidence += 0.08   # continuation entries are higher quality
        bar_range = float(curr["high"]) - float(curr["low"])
        if bar_range > 0:
            body_pos = ((close - float(curr["low"])) / bar_range) if direction == "long" \
                else ((float(curr["high"]) - close) / bar_range)
            if body_pos > 0.7:
                confidence += 0.07
        confidence = round(min(0.92, confidence), 4)

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
                f"{self.entry_mode.upper()} {direction} | OR[{or_low:.2f}-{or_high:.2f}] "
                f"adx={adx:.0f} vol={rel_vol:.2f}x risk=${risk_dollars:.0f} R:R={rr:.1f}"
            ),
            "indicators": {
                "or_high": round(or_high, 2),
                "or_low": round(or_low, 2),
                "or_range": round(or_range, 2),
                "rel_volume": round(rel_vol, 2),
                "adx": round(adx, 1),
                "vwap": round(vwap, 2),
                "ema_50": round(ema_50, 2),
                "entry_mode": self.entry_mode,
            },
        }

        if self.is_valid_signal(signal, self.max_stop_dollars, self.min_rr):
            logger.info(
                "ORB[%s] signal: %s %s | conf=%.2f | entry=%.2f SL=%.2f TP=%.2f R:R=%.1f",
                self.entry_mode, direction.upper(), symbol, confidence,
                entry, stop, target, rr,
            )
            return signal
        return None

    # ──────────────────────────────────────────────────────────────────────
    # Entry models — return (direction, stop_reference) or None
    # ──────────────────────────────────────────────────────────────────────
    def _breakout_setup(self, post: pd.DataFrame, or_high: float, or_low: float):
        """Classic: current bar closes beyond the range, prior bar inside it."""
        if len(post) < 2:
            return None
        close = float(post.iloc[-1]["close"])
        prev_close = float(post.iloc[-2]["close"])
        if close > or_high and prev_close <= or_high:
            return "long", or_low
        if close < or_low and prev_close >= or_low:
            return "short", or_high
        return None

    def _icc_setup(self, post: pd.DataFrame, or_high: float, or_low: float):
        """
        Indication → Correction → Continuation.

        LONG:
          • Indication : some earlier post-OR bar's HIGH exceeded or_high.
          • Correction : the prior bar pulled back (lower high than the one
                         before it) but its LOW stayed above or_high (held the
                         breakout level).
          • Continuation: the current bar closes above the prior (correction)
                         bar's HIGH and above or_high — momentum resumes.
          • Stop sits below the correction bar's low (tight).
        SHORT is the mirror image.
        """
        if len(post) < 3:
            return None

        highs = post["high"].astype(float).tolist()
        lows = post["low"].astype(float).tolist()
        closes = post["close"].astype(float).tolist()

        curr_close = closes[-1]
        corr_high = highs[-2]   # the pullback (correction) bar
        corr_low = lows[-2]
        before_corr_high = highs[-3]
        before_corr_low = lows[-3]

        # ── LONG ──
        broke_up = any(h > or_high for h in highs[:-1])
        corrected_up = (corr_high < before_corr_high) and (corr_low > or_high)
        continued_up = (curr_close > corr_high) and (curr_close > or_high)
        if broke_up and corrected_up and continued_up:
            return "long", corr_low

        # ── SHORT ──
        broke_down = any(l < or_low for l in lows[:-1])
        corrected_down = (corr_low > before_corr_low) and (corr_high < or_low)
        continued_down = (curr_close < corr_low) and (curr_close < or_low)
        if broke_down and corrected_down and continued_down:
            return "short", corr_high

        return None
