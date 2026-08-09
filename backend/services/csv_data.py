"""
Load purchased historical bars from CSV, in the exact shape get_historical returns.

WHY THIS EXISTS
---------------
Every research tool in this repo — scripts/continuation.py, scripts/research.py,
scripts/v2_backtest.py — reaches for MarketDataService.get_historical(), which is
yfinance and nothing else. yfinance serves roughly 60 days of 5-minute bars.

That single dependency is the binding constraint on the whole project.
continuation.py states its own defeat in its docstring: at n≈700 events the
minimum detectable effect is ~0.076 ATR while the economically required effect is
~0.018 ATR. The test cannot resolve the question it was written to answer, and no
amount of waiting fixes that — a 60-day forward test adds ~24 trades.

Purchased history collapses that. 15 years of NQ at the same event rate is
~44,000 events instead of ~700; standard error scales as 1/sqrt(n), so the
detectable effect falls to ~0.010 ATR — comfortably below what matters. The
premise becomes decidable in an afternoon.

STRICTNESS IS THE POINT
-----------------------
This project's defining failure is looking healthy while being completely broken.
A CSV loader that silently accepts misparsed timestamps, a shifted timezone, or
unsorted rows would produce a confident, wrong verdict on the single question
that decides whether the project continues. So every assumption is checked and
every check is loud.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")

# Vendors disagree on column naming; map everything onto the internal contract.
_ALIASES = {
    "date": "timestamp", "datetime": "timestamp", "time": "timestamp",
    "date_time": "timestamp", "ts": "timestamp",
    "o": "open", "h": "high", "l": "low", "c": "close",
    "v": "volume", "vol": "volume",
    "adj close": "close", "adj_close": "close", "last": "close",
}
_REQUIRED = ("open", "high", "low", "close")


class CsvDataError(ValueError):
    """Raised loudly rather than returning a subtly wrong frame."""


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_ALIASES.get(str(c).strip().lower(), str(c).strip().lower())
                  for c in df.columns]
    return df


def load_bars(path: str, *, tz: str = "America/New_York",
              interval: Optional[str] = None,
              symbol: str = "") -> pd.DataFrame:
    """
    Read a CSV of OHLC bars and return it exactly as get_historical would.

    tz         timezone the FILE's timestamps are written in. FirstRate and most
               US futures vendors ship US/Eastern; some ship UTC. Getting this
               wrong shifts every bar into the wrong session and silently
               invalidates every session-bucketed result, so it is explicit and
               has no clever auto-detection.
    interval   optional pandas resample rule ("5min", "15min"). Purchased data is
               usually 1-minute; the strategy and the existing 60-day yfinance
               baseline are 5-minute. Resampling here keeps the comparison honest.
    """
    if not os.path.exists(path):
        raise CsvDataError(f"no such file: {path}")

    # Vendors ship both headered and headerless files. Detect rather than assume:
    # a headerless file parsed with header=0 silently eats its first bar and
    # names every column after a price.
    probe = pd.read_csv(path, nrows=1, header=None)
    first = [str(v).strip().lower() for v in probe.iloc[0].tolist()]
    looks_headed = any(v in _ALIASES or v in ("timestamp",) + _REQUIRED for v in first)

    if looks_headed:
        df = pd.read_csv(path)
        df = _normalise_columns(df)
    else:
        # FirstRate's canonical layout.
        ncols = probe.shape[1]
        names = ["timestamp", "open", "high", "low", "close", "volume"][:ncols]
        if ncols < 5:
            raise CsvDataError(
                f"{path}: headerless file with {ncols} columns; expected at least "
                "timestamp,open,high,low,close")
        df = pd.read_csv(path, header=None, names=names)

    if "timestamp" not in df.columns:
        raise CsvDataError(
            f"{path}: no timestamp column found (looked for {sorted(set(_ALIASES) | {'timestamp'})})")
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise CsvDataError(f"{path}: missing required column(s): {missing}")

    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if ts.isna().any():
        bad = int(ts.isna().sum())
        raise CsvDataError(f"{path}: {bad} row(s) have unparseable timestamps")

    df = df.drop(columns=["timestamp"])
    df.index = ts

    # Localise, then convert. A naive index left alone would be read as ET by
    # downstream code regardless of what the file actually meant.
    if df.index.tz is None:
        df.index = df.index.tz_localize(pytz.timezone(tz),
                                        ambiguous="NaT", nonexistent="NaT")
        if df.index.isna().any():
            n = int(df.index.isna().sum())
            raise CsvDataError(
                f"{path}: {n} timestamp(s) are ambiguous or nonexistent in {tz} "
                "(DST transitions). The file's timezone is probably not {tz}.")
    df.index = df.index.tz_convert(ET)

    for col in _REQUIRED:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[list(_REQUIRED)].isna().any().any():
        raise CsvDataError(f"{path}: non-numeric values in OHLC columns")

    df = df.sort_index()
    dupes = int(df.index.duplicated().sum())
    if dupes:
        df = df[~df.index.duplicated(keep="first")]

    # OHLC sanity. A vendor file with high < low is corrupt, and every ATR and
    # true-range figure downstream would be quietly wrong.
    broken = (df["high"] < df["low"]) | \
             (df["high"] < df[["open", "close"]].max(axis=1)) | \
             (df["low"] > df[["open", "close"]].min(axis=1))
    if broken.any():
        raise CsvDataError(
            f"{path}: {int(broken.sum())} bar(s) violate OHLC invariants "
            f"(first at {df.index[broken.argmax()]})")

    if interval:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in df.columns:
            agg["volume"] = "sum"
        df = df.resample(interval, label="right", closed="right").agg(agg).dropna(subset=["close"])

    if df.empty:
        raise CsvDataError(f"{path}: no usable bars after parsing")

    label = f"{symbol} " if symbol else ""
    print(f"  loaded {len(df):,} {label}bars from {os.path.basename(path)}  "
          f"[{df.index[0]} → {df.index[-1]}]"
          + (f"  resampled→{interval}" if interval else "")
          + (f"  ({dupes} duplicate timestamps dropped)" if dupes else ""))
    return df
