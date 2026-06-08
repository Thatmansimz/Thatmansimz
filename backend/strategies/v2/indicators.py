"""
V2 — Technical Indicators (Section 3)
=====================================

Self-contained so V2 never depends on the V1 indicator pipeline.

  • Heikin Ashi candles — used to judge candle strength / structural symmetry.
  • Session VWAP        — reset at the start of each session window.
  • EMA 12              — trend overlay.
  • ATR                 — drives contract scaling (Section 5).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame with ha_open/ha_high/ha_low/ha_close aligned to df.index.
    HA is path-dependent (each open depends on the prior HA candle), so this
    must be computed over a continuous series.
    """
    ha = pd.DataFrame(index=df.index)
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

    o = df["open"].to_numpy()
    c = ha_close.to_numpy()
    ha_open_vals = np.empty(len(df), dtype=float)
    ha_open_vals[0] = (o[0] + df["close"].iloc[0]) / 2.0
    for i in range(1, len(df)):
        ha_open_vals[i] = (ha_open_vals[i - 1] + c[i - 1]) / 2.0

    ha["ha_open"] = ha_open_vals
    ha["ha_close"] = ha_close
    ha["ha_high"] = pd.concat([df["high"], ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    ha["ha_low"] = pd.concat([df["low"], ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    return ha


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def session_vwap(day_df: pd.DataFrame) -> float:
    """VWAP over the supplied (single-session) slice."""
    if day_df.empty:
        return float("nan")
    typical = (day_df["high"] + day_df["low"] + day_df["close"]) / 3.0
    cum_vol = day_df["volume"].cumsum()
    vwap = (typical * day_df["volume"]).cumsum() / cum_vol.replace(0, float("nan"))
    v = float(vwap.iloc[-1])
    return v if v == v else float(day_df["close"].iloc[-1])


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range over the last `period` bars (point units)."""
    if len(df) < 2:
        return 0.0
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return float(tr.tail(period).mean())


def is_flat_bottom(ha_open: float, ha_high: float, ha_low: float, ha_close: float,
                   tol: float) -> bool:
    """Strong bullish HA candle: bullish body with (near) no lower shadow."""
    bullish = ha_close > ha_open
    lower_shadow = min(ha_open, ha_close) - ha_low
    return bullish and lower_shadow <= tol


def is_flat_top(ha_open: float, ha_high: float, ha_low: float, ha_close: float,
                tol: float) -> bool:
    """Strong bearish HA candle: bearish body with (near) no upper shadow."""
    bearish = ha_close < ha_open
    upper_shadow = ha_high - max(ha_open, ha_close)
    return bearish and upper_shadow <= tol
