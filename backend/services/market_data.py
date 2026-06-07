"""
Market Data Service
Provides historical and simulated real-time market data with technical indicators.
"""
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Map internal symbols to yfinance tickers
SYMBOL_MAP = {
    "MES": "ES=F",   # E-mini S&P 500 futures (proxy)
    "MNQ": "NQ=F",   # E-mini Nasdaq-100 futures (proxy)
    "MGC": "GC=F",   # Gold futures proxy
    "SPY": "SPY",
    "QQQ": "QQQ",
}


class MarketDataService:
    """
    Fetches and caches market data from yfinance.
    Simulates real-time bars from the most recent historical candle.
    """

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_time: dict[str, datetime] = {}
        self._cache_ttl_seconds = 60  # Refresh cache every 60 seconds

    def _get_ticker(self, symbol: str) -> str:
        return SYMBOL_MAP.get(symbol.upper(), symbol)

    def get_historical(
        self,
        symbol: str,
        period: str = "60d",
        interval: str = "5m",
    ) -> pd.DataFrame:
        """
        Download OHLCV data for a symbol and return a cleaned DataFrame.
        Results are cached for _cache_ttl_seconds.
        """
        cache_key = f"{symbol}_{period}_{interval}"
        now = datetime.utcnow()

        # Return cached data if still fresh
        if cache_key in self._cache:
            age = (now - self._cache_time[cache_key]).total_seconds()
            if age < self._cache_ttl_seconds:
                return self._cache[cache_key].copy()

        ticker = self._get_ticker(symbol)
        logger.info("Fetching historical data for %s (%s) period=%s interval=%s", symbol, ticker, period, interval)

        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.error("yfinance download failed for %s: %s", symbol, exc)
            return pd.DataFrame()

        if df.empty:
            logger.warning("No data returned for %s", symbol)
            return df

        # Flatten multi-level columns if present (yfinance sometimes returns them)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Ensure standard column names
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"adj close": "close"})
        required = {"open", "high", "low", "close", "volume"}
        df = df[[c for c in df.columns if c in required]].copy()
        df.dropna(inplace=True)

        self._cache[cache_key] = df
        self._cache_time[cache_key] = now
        logger.info("Loaded %d bars for %s", len(df), symbol)
        return df.copy()

    def get_realtime_bar(self, symbol: str) -> dict:
        """
        Return a simulated current OHLCV bar based on latest historical data.
        Adds small random noise so the 'live' price drifts realistically.
        """
        df = self.get_historical(symbol, period="5d", interval="5m")
        if df.empty:
            return {
                "symbol": symbol,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0,
                "timestamp": datetime.utcnow().isoformat(),
            }

        last = df.iloc[-1]
        close = float(last["close"])

        # Simulate tick movement ±0.05%
        noise = close * random.uniform(-0.0005, 0.0005)
        current_price = round(close + noise, 2)

        return {
            "symbol": symbol,
            "open": float(last["open"]),
            "high": max(float(last["high"]), current_price),
            "low": min(float(last["low"]), current_price),
            "close": current_price,
            "volume": int(last["volume"]) + random.randint(0, 500),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add a comprehensive set of technical indicators to the DataFrame.
        All computations use pure pandas/numpy for speed and transparency.
        """
        if df.empty or len(df) < 50:
            return df

        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # ── Simple & Exponential Moving Averages ───────────────────────────────
        for period in [9, 21, 50, 200]:
            df[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
            df[f"sma_{period}"] = close.rolling(period).mean()

        # ── RSI (14) ───────────────────────────────────────────────────────────
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        # ── MACD ───────────────────────────────────────────────────────────────
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # ── Bollinger Bands (20, 2σ) ───────────────────────────────────────────
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        df["bb_upper"] = bb_mid + 2 * bb_std
        df["bb_lower"] = bb_mid - 2 * bb_std
        df["bb_mid"] = bb_mid
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / bb_mid.replace(0, np.nan)
        df["bb_pct"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

        # ── ATR (14) ───────────────────────────────────────────────────────────
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        df["atr"] = tr.ewm(com=13, adjust=False).mean()
        df["atr_pct"] = df["atr"] / close.replace(0, np.nan)

        # ── VWAP (rolling within session) ─────────────────────────────────────
        typical = (high + low + close) / 3
        df["vwap"] = (typical * volume).cumsum() / volume.cumsum().replace(0, np.nan)

        # ── Volume indicators ──────────────────────────────────────────────────
        df["volume_ma_20"] = volume.rolling(20).mean()
        df["rel_volume"] = volume / df["volume_ma_20"].replace(0, np.nan)
        df["volume_trend"] = volume.rolling(5).mean() / volume.rolling(20).mean().replace(0, np.nan)

        # ── OBV (On-Balance Volume) ───────────────────────────────────────────
        obv = [0]
        for i in range(1, len(df)):
            if close.iloc[i] > close.iloc[i - 1]:
                obv.append(obv[-1] + volume.iloc[i])
            elif close.iloc[i] < close.iloc[i - 1]:
                obv.append(obv[-1] - volume.iloc[i])
            else:
                obv.append(obv[-1])
        df["obv"] = obv
        df["obv_ema"] = pd.Series(obv, index=df.index).ewm(span=20, adjust=False).mean()

        # ── Stochastic Oscillator (14, 3) ─────────────────────────────────────
        low_14 = low.rolling(14).min()
        high_14 = high.rolling(14).max()
        df["stoch_k"] = 100 * (close - low_14) / (high_14 - low_14).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        # ── Williams %R (14) ──────────────────────────────────────────────────
        df["williams_r"] = -100 * (high_14 - close) / (high_14 - low_14).replace(0, np.nan)

        # ── CCI (20) ──────────────────────────────────────────────────────────
        cci_period = 20
        tp = (high + low + close) / 3
        tp_sma = tp.rolling(cci_period).mean()
        tp_mad = tp.rolling(cci_period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        df["cci"] = (tp - tp_sma) / (0.015 * tp_mad.replace(0, np.nan))

        # ── ADX / DMI ─────────────────────────────────────────────────────────
        adx_period = 14
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr14 = tr.ewm(com=adx_period - 1, adjust=False).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(com=adx_period - 1, adjust=False).mean() / atr14.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(com=adx_period - 1, adjust=False).mean() / atr14.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        df["adx"] = dx.ewm(com=adx_period - 1, adjust=False).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di

        # ── Rate of Change (10) ───────────────────────────────────────────────
        df["roc_10"] = close.pct_change(10) * 100

        # ── Candlestick body / wick features ──────────────────────────────────
        df["body_size"] = (close - df["open"]).abs() / close.replace(0, np.nan)
        df["upper_wick"] = (high - close.clip(lower=df["open"])) / close.replace(0, np.nan)
        df["lower_wick"] = (close.clip(upper=df["open"]) - low) / close.replace(0, np.nan)
        df["is_bullish"] = (close > df["open"]).astype(int)

        # ── Price position relative to EMAs ───────────────────────────────────
        df["above_ema_9"] = (close > df["ema_9"]).astype(int)
        df["above_ema_21"] = (close > df["ema_21"]).astype(int)
        df["above_ema_50"] = (close > df["ema_50"]).astype(int)
        df["above_ema_200"] = (close > df["ema_200"]).astype(int)
        df["price_vs_vwap"] = (close - df["vwap"]) / close.replace(0, np.nan)

        # ── Trend: higher-highs / lower-lows (lookback 5) ─────────────────────
        df["hh_5"] = (high > high.shift(1)) & (high.shift(1) > high.shift(2))
        df["ll_5"] = (low < low.shift(1)) & (low.shift(1) < low.shift(2))
        df["hh_5"] = df["hh_5"].astype(int)
        df["ll_5"] = df["ll_5"].astype(int)

        # ── Time-of-day features ──────────────────────────────────────────────
        if hasattr(df.index, "hour"):
            df["hour"] = df.index.hour
            df["minute"] = df.index.minute
            df["day_of_week"] = df.index.dayofweek
            # Market session flags (ET = UTC-5)
            df["is_open_auction"] = ((df["hour"] == 9) & (df["minute"] >= 30)).astype(int)
            df["is_power_hour"] = (df["hour"] == 15).astype(int)
            df["is_lunch"] = ((df["hour"] >= 12) & (df["hour"] < 13)).astype(int)

        df.dropna(inplace=True)
        return df

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Return the most recent close price for a symbol."""
        bar = self.get_realtime_bar(symbol)
        return bar.get("close")

    def is_market_open(self, symbol: str = "MES") -> bool:
        """Return True if the regular session is currently open (9:30–16:00 ET Mon–Fri)."""
        import pytz
        from datetime import time as dtime
        ET = pytz.timezone("America/New_York")
        now_et = datetime.now(ET)
        if now_et.weekday() >= 5:
            return False
        current_time = now_et.time()
        return dtime(9, 30) <= current_time <= dtime(16, 0)

    def get_multi_timeframe(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Return indicator-enriched DataFrames for 1m, 5m, and 15m timeframes."""
        frames = {}
        for interval, period in [("1m", "7d"), ("5m", "60d"), ("15m", "60d")]:
            df = self.get_historical(symbol, period=period, interval=interval)
            if not df.empty:
                frames[interval] = self.add_indicators(df)
        return frames
