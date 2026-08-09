"""
Market Data Service
Provides historical and simulated real-time market data with technical indicators.
"""
import logging
import random
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from backend.clock import utc_now

logger = logging.getLogger(__name__)

# Map internal symbols to yfinance tickers.
# NQ (E-mini) and MNQ (Micro) share the same underlying Nasdaq-100 future for
# DATA purposes — the $20 vs $2 per-point difference is applied later via each
# instrument's point_value, not the price feed. Same for ES/MES.
SYMBOL_MAP = {
    "ES": "ES=F",    # E-mini S&P 500 futures
    "MES": "ES=F",   # Micro E-mini S&P 500 (same feed as ES)
    "NQ": "NQ=F",    # E-mini Nasdaq-100 futures
    "MNQ": "NQ=F",   # Micro E-mini Nasdaq-100 (same feed as NQ)
    "GC": "GC=F",    # Gold futures
    "MGC": "GC=F",   # Micro Gold (same feed as GC)
    "SPY": "SPY",
    "QQQ": "QQQ",
}


# ── Data-feed health (shared across all MarketDataService instances) ─────────
# The engine creates several MarketDataService objects (scheduler, broker,
# API). Feed health must be GLOBAL so the watchdog and /api/status see the
# truth no matter which instance failed. This is what makes a data outage
# loud instead of silent — the failure mode that cost 25 days of the campaign.
_feed_lock = threading.Lock()
_feed_state = {
    "consecutive_failures": 0,
    "last_success": None,      # datetime of last non-empty download
    "last_failure": None,
    "last_error": "",
    "resets": 0,               # how many times we rebuilt the yfinance session
}

# Rebuild the yfinance HTTP session after this many consecutive empty/failed
# downloads. A long-running process's session cookies/crumbs go stale after
# days-weeks and Yahoo starts answering "possibly delisted; no price data
# found" forever. A fresh session recovers instantly (a new process proved
# this while the 3-week-old engine process was blind).
_RESET_AFTER_FAILURES = 3


def get_feed_health() -> dict:
    """Snapshot of data-feed health for /api/status and the watchdog."""
    with _feed_lock:
        st = dict(_feed_state)
    st["last_success"] = st["last_success"].isoformat() if st["last_success"] else None
    st["last_failure"] = st["last_failure"].isoformat() if st["last_failure"] else None
    st["healthy"] = st["consecutive_failures"] < _RESET_AFTER_FAILURES
    return st


def _record_feed_success():
    with _feed_lock:
        _feed_state["consecutive_failures"] = 0
        _feed_state["last_success"] = utc_now()


def _record_feed_failure(error: str) -> int:
    with _feed_lock:
        _feed_state["consecutive_failures"] += 1
        _feed_state["last_failure"] = utc_now()
        _feed_state["last_error"] = error[:300]
        return _feed_state["consecutive_failures"]


def _reset_yfinance_session():
    """
    Tear down cached HTTP auth state inside yfinance so the next download
    re-authenticates from scratch (fresh cookie + crumb). Yahoo's crumb/cookie
    pair goes stale after days/weeks in a long-running process and every
    request then fails with "possibly delisted; no price data found".

    ORDER MATTERS. The persisted cookie must be purged FIRST: yfinance reloads
    it from disk on the next request (_load_cookie_curlCffi) and only checks
    its LOCAL expiry timestamp, so a cookie Yahoo has invalidated server-side
    looks perfectly valid and is reinstalled immediately — which would make
    wiping the in-memory state pointless.

    yfinance internals differ by version, so each step is guarded and the
    outcome is logged. If a future version renames these, the log says so
    loudly instead of the heal silently becoming a no-op (verified against the
    installed version: 0.2.x kept a YfData singleton; 1.5.x does not, and
    persists the cookie via cache.get_cookie_cache().store('curlCffi', ...)).
    """
    with _feed_lock:
        _feed_state["resets"] += 1
    logger.warning("Data feed: rebuilding yfinance session (reset #%d)", _feed_state["resets"])

    try:
        from yfinance.data import YfData
    except Exception as exc:
        logger.error("Data feed: cannot import yfinance internals to heal: %s", exc)
        return

    done = []

    # 1. Purge the DISK cookie first (1.x). Both _get_cookie_basic and
    #    _get_cookie_csrf reload from here, so leaving it in place undoes
    #    everything below.
    purged = False
    try:
        import yfinance.cache as _yc
        # Preferred: DELETE the cached row. Storing an empty dict is NOT
        # equivalent — yfinance's loader only treats a MISSING row as a miss,
        # and an empty one makes it raise IndexError on every request.
        cache_obj = _yc.get_cookie_cache() if hasattr(_yc, "get_cookie_cache") else None
        schema = getattr(_yc, "_CookieSchema", None)
        if cache_obj is not None and schema is not None:
            if getattr(cache_obj, "initialised", 0) == -1:
                cache_obj.initialise()
            schema.delete().where(schema.strategy == "curlCffi").execute()
            purged = True
            done.append("disk-cookie")
        elif hasattr(_yc, "get_cookie_cache_manager"):   # older layout
            _yc.get_cookie_cache_manager().get_cookie_db().delete_cookies()
            purged = True
            done.append("disk-cookie(legacy)")
    except Exception as exc:
        logger.error("Data feed: disk cookie purge failed: %s", exc)

    if not purged:
        logger.error(
            "Data feed: could NOT purge the persisted cookie (yfinance %s). The "
            "stale cookie will be reloaded from disk and healing will FAIL — "
            "this is the failure that once cost 25 days.",
            getattr(__import__("yfinance"), "__version__", "?"),
        )

    # 2. 0.2.x singleton slot, if this version has one.
    try:
        if hasattr(YfData, "_YfData__instance"):
            YfData._YfData__instance = None
            done.append("singleton")
    except Exception:
        pass

    # 3. Wipe auth state on every live YfData: the crumb, the cookie, AND the
    #    session itself (whose jar holds the rotten cookie independently of
    #    _cookie). Dropping _session forces a brand-new handshake.
    wiped = 0
    try:
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, YfData):
                for attr in ("_crumb", "_cookie"):
                    try:
                        setattr(obj, attr, None)
                    except Exception:
                        pass
                try:
                    sess = getattr(obj, "_session", None)
                    jar = getattr(sess, "cookies", None)
                    if jar is not None and hasattr(jar, "clear"):
                        jar.clear()
                except Exception:
                    pass
                wiped += 1
        if wiped:
            done.append(f"instances({wiped})")
    except Exception as exc:
        logger.error("Data feed: YfData sweep failed: %s", exc)

    if done:
        logger.warning("Data feed: session rebuild cleared %s", ", ".join(done))
    else:
        logger.error("Data feed: session rebuild cleared NOTHING — the outage "
                     "will persist. yfinance internals have changed.")


class MarketDataService:
    """
    Fetches and caches market data from yfinance.
    Simulates real-time bars from the most recent historical candle.

    Self-healing: consecutive failed downloads trigger a full yfinance
    session rebuild, and feed health is exported globally so a data outage
    can never again be silent.
    """

    # CLASS-level cache, shared by every instance. The scheduler and the paper
    # broker each construct their own MarketDataService; with per-instance
    # caches they could see two different prices for the same symbol at the
    # same instant — the scan deciding entries on one snapshot while exit
    # monitoring judged stops on another.
    _cache: dict[str, pd.DataFrame] = {}
    _cache_time: dict[str, datetime] = {}

    def __init__(self):
        # 90s: fresh enough that a newly completed 5m bar is seen within
        # ~1-2 scan cycles, without refetching 10d of bars every single scan.
        self._cache_ttl_seconds = 90
        # On failure, serve stale cache for up to this long so one bad fetch
        # doesn't blind position monitoring.
        self._stale_ok_seconds = 3600

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
        Results are cached for _cache_ttl_seconds; on download failure the
        stale cache is served (up to _stale_ok_seconds) while the feed heals.
        """
        cache_key = f"{symbol}_{period}_{interval}"
        now = utc_now()

        # Return cached data if still fresh
        if cache_key in self._cache:
            age = (now - self._cache_time[cache_key]).total_seconds()
            if age < self._cache_ttl_seconds:
                return self._cache[cache_key].copy()

        ticker = self._get_ticker(symbol)
        logger.info("Fetching historical data for %s (%s) period=%s interval=%s", symbol, ticker, period, interval)

        df = pd.DataFrame()
        error = ""
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
            error = repr(exc)
            logger.error("yfinance download failed for %s: %s", symbol, exc)

        if df is None or df.empty:
            failures = _record_feed_failure(error or f"empty response for {ticker}")
            logger.warning("No data returned for %s (consecutive feed failures: %d)", symbol, failures)

            # Self-heal: stale session tokens make Yahoo answer "possibly
            # delisted" forever. Rebuild the session and retry once, with a
            # small backoff so we don't hammer while rate-limited.
            if failures >= _RESET_AFTER_FAILURES and failures % _RESET_AFTER_FAILURES == 0:
                _reset_yfinance_session()
                _time.sleep(2 + random.uniform(0, 3))
                try:
                    df = yf.download(
                        ticker, period=period, interval=interval,
                        auto_adjust=True, progress=False, threads=False,
                    )
                    if df is not None and not df.empty:
                        logger.warning("Data feed RECOVERED for %s after session rebuild", symbol)
                except Exception as exc:
                    logger.error("Retry after session rebuild failed for %s: %s", symbol, exc)
                    df = pd.DataFrame()

            if df is None or df.empty:
                # Serve stale cache rather than blinding position monitoring.
                if cache_key in self._cache:
                    age = (now - self._cache_time[cache_key]).total_seconds()
                    if age < self._stale_ok_seconds:
                        logger.warning("Serving %ds-stale cache for %s while feed is down", int(age), symbol)
                        return self._cache[cache_key].copy()
                return pd.DataFrame()

        _record_feed_success()

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
                "timestamp": utc_now().isoformat(),
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
            "timestamp": utc_now().isoformat(),
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

    @staticmethod
    def drop_forming_bar(df: pd.DataFrame, interval_seconds: int = 300) -> pd.DataFrame:
        """
        Remove the still-forming last bar so callers only ever see COMPLETED
        bars — exactly what the backtest iterates over.

        yfinance includes the in-progress bar during market hours. Evaluating
        it live meant the strategy saw a candle whose low/close were still
        moving: stops measured from a running low (inflating size), entries on
        engulfings that un-engulfed by the close, and trade populations the
        backtest structurally cannot produce.
        """
        if df is None or df.empty:
            return df
        try:
            last_ts = df.index[-1]
            ts = last_ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None) \
                if last_ts.tzinfo is not None else last_ts.to_pydatetime()
            if (utc_now() - ts).total_seconds() < interval_seconds:
                return df.iloc[:-1]
        except Exception:
            pass
        return df

    def get_last_bar(self, symbol: str) -> Optional[dict]:
        """
        The last COMPLETED bar's OHLC + timestamp. Exit detection must use
        this (intrabar high/low, stop-first) — a single spot sample cannot see
        a wick that hit the stop and came back, which suppressed stop-outs the
        backtest books at -1R.
        """
        df = self.get_historical(symbol, period="5d", interval="5m")
        df = self.drop_forming_bar(df)
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        return {
            "ts": str(df.index[-1]),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
        }

    def get_last_close(self, symbol: str) -> Optional[float]:
        """
        The most recent REAL traded close — no simulated noise.

        Anything that writes P&L must use this. get_realtime_bar() adds a
        random ±0.05% jitter so the dashboard ticker looks alive; on MNQ at
        20,000 that is ±10 index points, which is wider than a typical V2
        structural stop. Feeding that into exit detection decides wins and
        losses with a random number generator instead of the market.
        """
        df = self.get_historical(symbol, period="5d", interval="5m")
        if df is None or df.empty:
            return None
        return float(df.iloc[-1]["close"])

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Display-only price (includes simulated tick noise).

        DO NOT use for fills, exits, or any P&L calculation — use
        get_last_close() for those.
        """
        bar = self.get_realtime_bar(symbol)
        return bar.get("close")

    def is_market_open(self, symbol: str = "MES") -> bool:
        """Return True if the regular US equity session is open (9:30–16:00 ET Mon–Fri)."""
        import pytz
        from datetime import time as dtime
        ET = pytz.timezone("America/New_York")
        now_et = datetime.now(ET)
        if now_et.weekday() >= 5:
            return False
        current_time = now_et.time()
        return dtime(9, 30) <= current_time <= dtime(16, 0)

    def is_futures_open(self) -> bool:
        """
        CME equity-index futures (ES/NQ/MES/MNQ) trade nearly 24/5:
        Sunday 18:00 ET → Friday 17:00 ET, with a daily maintenance halt
        17:00–18:00 ET. This is what the headline "MARKET" pill should reflect
        for a futures platform — not the 9:30–16:00 stock session.
        """
        import pytz
        from datetime import time as dtime
        ET = pytz.timezone("America/New_York")
        now = datetime.now(ET)
        wd = now.weekday()          # Mon=0 … Sat=5, Sun=6
        t = now.time()
        if wd == 5:                                  # Saturday — closed all day
            return False
        if wd == 6:                                  # Sunday — opens 18:00 ET
            return t >= dtime(18, 0)
        if wd == 4 and t >= dtime(17, 0):            # Friday — closes 17:00 ET
            return False
        if dtime(17, 0) <= t < dtime(18, 0):         # daily maintenance halt
            return False
        return True

    def get_sessions_status(self) -> dict:
        """
        Live open/closed state for the three global trading sessions, so the UI
        can show *which* market is active (Asia/London/New York) instead of a
        single binary 'closed'. Reuses the V2 session windows.
        """
        import pytz
        from backend.strategies.v2 import sessions as V2S
        ET = pytz.timezone("America/New_York")
        now = datetime.now(ET)
        minute = V2S._minute_of_day(now)

        meta = {
            "ASIA":     ("Asia · Tokyo", "8:00 PM – 4:00 AM ET"),
            "LONDON":   ("London",       "4:00 AM – 12:00 PM ET"),
            "NEW_YORK": ("New York",     "9:00 AM – 6:00 PM ET"),
        }
        futures_open = self.is_futures_open()
        sessions = []
        for sess in (V2S.ASIA, V2S.LONDON, V2S.NEW_YORK):
            is_open = futures_open and V2S._in_window(minute, sess.start, sess.end)
            label, hours = meta[sess.name]
            sessions.append({
                "name": sess.name,
                "label": label,
                "hours": hours,
                "open": is_open,
                "kill_zone": bool(is_open and V2S.in_kill_zone(now, sess)),
            })
        return {
            "futures_open": futures_open,
            "now_et": now.strftime("%H:%M"),
            "sessions": sessions,
        }

    def get_multi_timeframe(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Return indicator-enriched DataFrames for 1m, 5m, and 15m timeframes."""
        frames = {}
        for interval, period in [("1m", "7d"), ("5m", "60d"), ("15m", "60d")]:
            df = self.get_historical(symbol, period=period, interval=interval)
            if not df.empty:
                frames[interval] = self.add_indicators(df)
        return frames
