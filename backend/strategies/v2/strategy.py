"""
V2 — Multi-Session Engine: the "Two Indications" entry filter
=============================================================

A fully self-contained strategy implementing the business-partner spec:

  Section 1  Global sessions + kill zones + overlap rule        (sessions.py)
  Section 2  Macro support/resistance from preceding session    (macro_zones.py)
  Section 3  Heikin Ashi / session VWAP / EMA 12 / ATR          (indicators.py)
  Section 4  Two-Indications entry engine  (this file)
  Section 5  Risk: structural stop, 1:1 / 2:1 TP, trailing, ATR sizing
  Section 6  Programmatic JSON signal schema

It subclasses BaseStrategy so it is drop-in compatible with the existing
scheduler/backtester — but it lives in its own `v2/` package and is NEVER the
default, so it cannot disturb the validated V1 ORB code.

Instruments: NQ (E-mini, $20/pt) and MNQ (Micro, $2/pt).
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import pytz

from backend.strategies.base import BaseStrategy
from backend.strategies.v2 import indicators as ind
from backend.strategies.v2 import sessions as S
from backend.strategies.v2 import macro_zones as mz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# point value ($ per 1.00 move) and tick size per instrument
SPECS = {
    "NQ":  {"point_value": 20.0, "tick": 0.25},
    "MNQ": {"point_value": 2.0,  "tick": 0.25},
}

# Section 5 monetary guard — target net profit window per setup
TARGET_PROFIT_MIN = 500.0
TARGET_PROFIT_MAX = 1500.0


class MultiSessionStrategy(BaseStrategy):
    """24/5 multi-session Heikin-Ashi engulfing engine (V2)."""

    name = "multi_session"
    description = "V2 — 3-session HA two-indications engulfing engine (NQ/MNQ)"

    def __init__(self, config=None):
        super().__init__(config)
        self.ema_period = 12
        self.atr_period = 14
        # Strong-candle shadow tolerance, as a fraction of the bar's ATR.
        self.flat_tol_frac = 0.08
        # Max contracts cap (safety) and NY high-vol scale-down threshold.
        self.max_contracts = 20
        self.ny_highvol_atr_pts = 60.0  # MNQ-point ATR above which NY scales down
        # V2 sizes to a profit window, not a hard stop cap. Keep min R:R modest.
        self.min_rr = 1.0

        # ── Asia session tweaks ──
        # Asia kill zone (8–10 PM ET) has enough volatility to reach 2R.
        # Tested grid: kz-only + 2.0R + no macro → PF 1.01, +$27 (first positive).
        # kz-only + 1.5R → -$1,430 (too tight). Original all-night → -$878.
        self.asia_kill_zone_only = True    # only enter during 8–10 PM ET kill zone
        self.asia_max_rr = 2.0            # match London/NY — kill zone moves are big enough
        self.asia_require_macro_zone = False  # macro filter selected bad entries, removed

    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _et(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
        return index if index.tz is None else index.tz_convert(ET)

    def _spec(self, symbol: str) -> dict:
        return SPECS.get(symbol.upper(), SPECS["MNQ"])

    # ──────────────────────────────────────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        state = self.evaluate(df, symbol)
        return state if state and state.get("state") == "signal" else None

    def evaluate(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        """
        Full Section-6 state object for the latest bar. Returns one of:
          flat | paused | watching | indication_1 | signal
        generate_signal() only forwards "signal".
        """
        if df is None or df.empty or len(df) < 20:
            return None
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None

        et = self._et(df.index)
        ts = et[-1]
        spec = self._spec(symbol)
        point_value, tick = spec["point_value"], spec["tick"]

        # ── Section 1: which session, kill zone, overlap, volatility pause ──
        session = S.active_session(ts)
        if session is None:
            return self._state(ts, symbol, "flat", reason="No active session")

        overlap = S.in_overlap(ts)
        kill = S.in_kill_zone(ts, session)
        if S.in_volatility_pause(ts, session):
            return self._state(ts, symbol, "paused", session=session, overlap=overlap,
                               reason="Volatility pause (first 5 min of kill zone)")

        # ── Asia kill-zone gate: only trade 8–10 PM ET, not all night ──
        if session.name == "ASIA" and self.asia_kill_zone_only and not kill:
            return self._state(ts, symbol, "flat", session=session, overlap=overlap,
                               reason="Asia: outside kill zone (8–10 PM ET) — standing down")

        # ── Current session instance bars (for VWAP/EMA reset) ──
        labels = mz.label_session_instances(et)
        cur_name, cur_inst = labels[-1]
        sess_idxs = [i for i, (n, inst) in enumerate(labels) if inst == cur_inst]
        sess_df = df.iloc[sess_idxs]
        if len(sess_df) < 3:
            return self._state(ts, symbol, "watching", session=session, overlap=overlap,
                               reason="Session just opened — building data")

        # ── Section 3: indicators ──
        ha = ind.heikin_ashi(df)
        ema12 = ind.ema(df["close"], self.ema_period)
        vwap = ind.session_vwap(sess_df)
        atr_pts = ind.atr(df, self.atr_period)
        tol = max(atr_pts * self.flat_tol_frac, tick)

        # ── Section 2: macro zones from preceding session ──
        zones = mz.build_macro_zones(df, et, labels, session, cur_inst)

        # ── Asia macro-zone gate: require prior-NY S/R confluence ──
        if session.name == "ASIA" and self.asia_require_macro_zone:
            has_zone = zones and (zones.resistance is not None or zones.support is not None)
            if not has_zone:
                return self._state(ts, symbol, "watching", session=session, overlap=overlap,
                                   kill=kill, reason="Asia: no macro S/R zone — skipping mid-range entry")

        # ── Section 4, Indication 1 on candle n-1 (Heikin Ashi) ──
        ha_prev = ha.iloc[-2]
        close_prev = float(ema12.iloc[-2])  # ema value at n-1
        vwap_ref = vwap
        ema_prev = float(ema12.iloc[-2])
        ha_o, ha_h = float(ha_prev["ha_open"]), float(ha_prev["ha_high"])
        ha_l, ha_c = float(ha_prev["ha_low"]), float(ha_prev["ha_close"])

        long_ind1 = (
            ha_c > vwap_ref and ha_c > ema_prev
            and ind.is_flat_bottom(ha_o, ha_h, ha_l, ha_c, tol)
        )
        short_ind1 = (
            ha_c < vwap_ref and ha_c < ema_prev
            and ind.is_flat_top(ha_o, ha_h, ha_l, ha_c, tol)
        )

        if not (long_ind1 or short_ind1):
            return self._state(ts, symbol, "watching", session=session, overlap=overlap,
                               kill=kill, zones=zones, vwap=vwap, ema12=float(ema12.iloc[-1]),
                               atr=atr_pts, reason="No Indication 1 (velocity break)")

        bias = "long" if long_ind1 else "short"

        # ── Section 4, Indication 2 on candle n (total engulfing) ──
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        p_hi, p_lo = float(prev["high"]), float(prev["low"])
        c_hi, c_lo = float(curr["high"]), float(curr["low"])
        c_open, c_close = float(curr["open"]), float(curr["close"])

        total_engulf = (c_hi > p_hi) and (c_lo < p_lo)
        directional = (c_close > c_open) if bias == "long" else (c_close < c_open)

        if not (total_engulf and directional):
            return self._state(ts, symbol, "indication_1", session=session, overlap=overlap,
                               kill=kill, zones=zones, bias=bias, vwap=vwap,
                               ema12=float(ema12.iloc[-1]), atr=atr_pts,
                               reason=f"Indication 1 ({bias}) set — awaiting engulfing close")

        # ── Section 5: stop, targets, sizing, trailing ──
        entry = c_close
        if bias == "long":
            swing = min(c_lo, p_lo)
            stop = swing - tick
            stop_dist = entry - stop
        else:
            swing = max(c_hi, p_hi)
            stop = swing + tick
            stop_dist = stop - entry

        if stop_dist <= 0:
            return self._state(ts, symbol, "watching", session=session, overlap=overlap,
                               reason="Invalid structural stop")

        # Asia gets a tunable R:R (default 1.5) — better than the original 1.0
        # cap while still respecting Asia's tighter range vs London/NY's 2.0.
        rr = self.asia_max_rr if session.name == "ASIA" else session.max_rr
        if bias == "long":
            t1 = entry + stop_dist          # 1:1
            t2 = entry + stop_dist * rr     # session R:R cap
        else:
            t1 = entry - stop_dist
            t2 = entry - stop_dist * rr

        contracts = self._size_contracts(stop_dist, point_value, session, atr_pts, symbol)
        est_risk = stop_dist * point_value * contracts
        est_target = abs(t2 - entry) * point_value * contracts

        # ── ORB momentum metrics if within first 15 min of session open ──
        orb = self._orb_metrics(sess_df, session, ts, entry, bias)

        sig = self._state(
            ts, symbol, "signal", session=session, overlap=overlap, kill=kill,
            zones=zones, bias=bias, vwap=vwap, ema12=float(ema12.iloc[-1]), atr=atr_pts,
            reason=f"TWO-INDICATIONS {bias.upper()} | engulfing close in {session.name}",
        )
        sig.update({
            "direction": bias,
            "confidence": self._confidence(bias, zones, entry, kill, orb),
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "target_1": round(t1, 2),
            "target_2": round(t2, 2),
            "targets": [round(t1, 2), round(t2, 2)],
            "risk_reward_ratio": round(rr, 2),
            "contracts": contracts,
            "est_risk_dollars": round(est_risk, 2),
            "est_target_profit": round(est_target, 2),
            "in_monetary_window": TARGET_PROFIT_MIN <= est_target <= TARGET_PROFIT_MAX,
            "orb": orb,
            "trailing": {
                "enabled": True,
                "method": "ema12_pivot",
                "breakeven_at_r": 1.0,
                "note": "Slide stop to BE at +1R, then trail behind EMA-12 / local pivots",
            },
            "strategy": self.name,
            "timeframe": "5m",
        })
        logger.info("V2[%s] %s %s @ %.2f SL %.2f T2 %.2f x%d (~$%.0f risk)",
                    session.name, bias.upper(), symbol, entry, stop, t2, contracts, est_risk)
        return sig

    # ──────────────────────────────────────────────────────────────────────
    # Section 5 helpers
    # ──────────────────────────────────────────────────────────────────────
    def _size_contracts(self, stop_dist, point_value, session, atr_pts, symbol) -> int:
        """
        Size to land the 2R target inside the $500–$1500 window, then apply ATR
        scaling: scale DOWN in volatile NY, lean on MNQ micros in Asia.
        """
        per_contract_target = stop_dist * session.max_rr * point_value
        if per_contract_target <= 0:
            return 1
        midpoint = (TARGET_PROFIT_MIN + TARGET_PROFIT_MAX) / 2.0
        contracts = max(1, round(midpoint / per_contract_target))

        # ATR scaling
        if session.name == "NEW_YORK" and atr_pts >= self.ny_highvol_atr_pts:
            contracts = max(1, int(contracts * 0.5))   # scale down in volatile NY
        if session.name == "ASIA" and symbol.upper() == "NQ":
            contracts = max(1, int(contracts * 0.5))   # prefer micros overnight

        return min(contracts, self.max_contracts)

    def _orb_metrics(self, sess_df, session, ts, entry, bias) -> dict:
        """Opening-range context if the setup fires in the first 15 min."""
        mins = S.minutes_since_session_open(ts, session)
        if mins > 15 or len(sess_df) < 1:
            return {"active": False}
        et = self._et(sess_df.index)
        first15 = [i for i, t in enumerate(et)
                   if S.minutes_since_session_open(t, session) <= 15]
        if not first15:
            return {"active": False}
        seg = sess_df.iloc[first15]
        or_high = float(seg["high"].max())
        or_low = float(seg["low"].min())
        broke = entry > or_high if bias == "long" else entry < or_low
        return {
            "active": True,
            "or_high": round(or_high, 2),
            "or_low": round(or_low, 2),
            "breakout": bool(broke),
            "minutes_into_session": mins,
        }

    def _confidence(self, bias, zones, entry, kill, orb) -> float:
        conf = 0.55
        if kill:
            conf += 0.10                       # peak-volatility window
        if orb.get("active") and orb.get("breakout"):
            conf += 0.07                       # opening-range momentum
        # confluence with macro zone (mean reversion off the edge / retest)
        if zones:
            if bias == "long" and zones.support and zones.support.contains(entry):
                conf += 0.08
            if bias == "short" and zones.resistance and zones.resistance.contains(entry):
                conf += 0.08
        return round(min(0.93, conf), 4)

    # ──────────────────────────────────────────────────────────────────────
    # Section 6 — programmatic JSON state object
    # ──────────────────────────────────────────────────────────────────────
    def _state(self, ts, symbol, state, session=None, overlap=False, kill=False,
               zones=None, bias=None, vwap=None, ema12=None, atr=None, reason="") -> dict:
        out = {
            "schema": "tajari.v2.signal/1",
            "timestamp": ts.isoformat(),
            "symbol": symbol,
            "state": state,                    # flat|paused|watching|indication_1|signal
            "session": session.name if session else None,
            "kill_zone": kill,
            "overlap": overlap,
            "bias": bias,
            "reason": reason,
        }
        if vwap is not None:
            out["indicators"] = {
                "vwap": round(vwap, 2) if vwap == vwap else None,
                "ema12": round(ema12, 2) if ema12 is not None else None,
                "atr": round(atr, 2) if atr is not None else None,
            }
        if zones is not None:
            out["macro_zones"] = {
                "source_session": zones.source_session,
                "resistance": ({"low": round(zones.resistance.low, 2),
                                "high": round(zones.resistance.high, 2)}
                               if zones.resistance else None),
                "support": ({"low": round(zones.support.low, 2),
                             "high": round(zones.support.high, 2)}
                            if zones.support else None),
            }
        return out
