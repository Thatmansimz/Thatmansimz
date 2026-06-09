#!/usr/bin/env python3
"""
V2 Backtester — Multi-Session Engine (NQ / MNQ)
===============================================

Simulates the business-partner V2 strategy bar-by-bar across all three global
sessions, with EMA-12 trailing and ATR-scaled contract sizing. Completely
separate from scripts/backtest.py (the validated V1 ORB runner) so the two
never interfere.

Usage:
    python3 scripts/v2_backtest.py --symbol MNQ --period 30d
    python3 scripts/v2_backtest.py --symbol NQ  --period 30d --session NEW_YORK

Note: needs Yahoo Finance access for intraday data (yfinance). Run it on your
local machine — the cloud sandbox blocks outbound market-data calls.
"""
from __future__ import annotations

import argparse
import os
import sys

# allow "import backend.*" when run from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backend.strategies.v2 import MultiSessionStrategy
from backend.strategies.v2 import sessions as S
from backend.strategies.v2.strategy import SPECS


def simulate(df: pd.DataFrame, symbol: str, only_session: str | None,
             asia_kill_zone_only: bool = True,
             asia_max_rr: float = 1.5,
             asia_require_macro_zone: bool = True) -> dict:
    strat = MultiSessionStrategy()
    strat.asia_kill_zone_only = asia_kill_zone_only
    strat.asia_max_rr = asia_max_rr
    strat.asia_require_macro_zone = asia_require_macro_zone
    spec = SPECS.get(symbol.upper(), SPECS["MNQ"])
    pv = spec["point_value"]

    trades = []
    open_pos = None  # dict with entry/stop/t2/dir/contracts/...

    et = df.index if df.index.tz is None else df.index.tz_convert(strat._et(df.index).tz)

    for i in range(25, len(df)):
        window = df.iloc[: i + 1]
        bar = df.iloc[i]
        hi, lo, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        # ── manage an open position first ──
        if open_pos:
            d = open_pos
            exited = False
            # stop / target checks (intrabar, stop-first conservative)
            if d["dir"] == "long":
                if lo <= d["stop"]:
                    pnl = (d["stop"] - d["entry"]) * pv * d["contracts"]; exited = True
                elif hi >= d["t2"]:
                    pnl = (d["t2"] - d["entry"]) * pv * d["contracts"]; exited = True
            else:
                if hi >= d["stop"]:
                    pnl = (d["entry"] - d["stop"]) * pv * d["contracts"]; exited = True
                elif lo <= d["t2"]:
                    pnl = (d["entry"] - d["t2"]) * pv * d["contracts"]; exited = True

            if exited:
                trades.append({"pnl": pnl, "session": d["session"], "dir": d["dir"]})
                open_pos = None
            else:
                # trailing: at +1R move to breakeven, then trail behind EMA-12
                r = d["risk_pts"]
                if d["dir"] == "long":
                    if close >= d["entry"] + r and d["stop"] < d["entry"]:
                        d["stop"] = d["entry"]
                    ema = float(window["close"].ewm(span=12, adjust=False).mean().iloc[-1])
                    d["stop"] = max(d["stop"], min(ema, close - r * 0.25))
                else:
                    if close <= d["entry"] - r and d["stop"] > d["entry"]:
                        d["stop"] = d["entry"]
                    ema = float(window["close"].ewm(span=12, adjust=False).mean().iloc[-1])
                    d["stop"] = min(d["stop"], max(ema, close + r * 0.25))
                continue  # one position at a time

        # ── look for a new entry ──
        sig = strat.generate_signal(window, symbol)
        if not sig:
            continue
        if only_session and sig["session"] != only_session:
            continue
        risk_pts = abs(sig["entry_price"] - sig["stop_loss"])
        if risk_pts <= 0:
            continue
        open_pos = {
            "entry": sig["entry_price"], "stop": sig["stop_loss"], "t2": sig["target_2"],
            "dir": sig["direction"], "contracts": sig["contracts"], "risk_pts": risk_pts,
            "session": sig["session"],
        }

    return _stats(trades, symbol)


def _stats(trades, symbol) -> dict:
    if not trades:
        return {"error": "no trades", "symbol": symbol}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    by_session = {}
    for t in trades:
        by_session.setdefault(t["session"], 0.0)
        by_session[t["session"]] += t["pnl"]
    return {
        "symbol": symbol,
        "total_trades": len(trades),
        "win_rate": 100.0 * len(wins) / len(trades),
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "total_pnl": sum(pnls),
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "by_session": by_session,
    }


def main():
    ap = argparse.ArgumentParser(description="Tajari V2 multi-session backtester")
    ap.add_argument("--symbol", default="MNQ", choices=["NQ", "MNQ"])
    ap.add_argument("--period", default="30d")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--session", default=None,
                    choices=["ASIA", "LONDON", "NEW_YORK"],
                    help="restrict trades to one session")
    ap.add_argument("--no-asia-kz-only", action="store_true",
                    help="allow Asia trades outside kill zone (reverts to original)")
    ap.add_argument("--asia-rr", type=float, default=1.5,
                    help="Asia R:R target (default 1.5, original was 1.0)")
    ap.add_argument("--no-asia-macro", action="store_true",
                    help="allow Asia trades without macro zone confluence")
    args = ap.parse_args()

    print("=" * 66)
    print(f"  Tajari V2 Backtest — {args.symbol} [multi-session]")
    print("=" * 66)
    print(f"  Period   : {args.period} @ {args.interval}")
    print(f"  Session  : {args.session or 'ALL (Asia + London + New York)'}")
    print()

    from backend.services.market_data import MarketDataService
    md = MarketDataService()
    print(f"  Downloading {args.symbol} data ...")
    df = md.get_historical(args.symbol, period=args.period, interval=args.interval)
    if df is None or df.empty:
        print("  ERROR: No data available (run locally — sandbox blocks market data).")
        sys.exit(0)

    print(f"  Asia tweaks: kill-zone-only={not args.no_asia_kz_only}  "
          f"rr={args.asia_rr}  macro-zone={not args.no_asia_macro}")
    print()
    stats = simulate(df, args.symbol, args.session,
                     asia_kill_zone_only=not args.no_asia_kz_only,
                     asia_max_rr=args.asia_rr,
                     asia_require_macro_zone=not args.no_asia_macro)
    if "error" in stats:
        print(f"  No trades: {stats['error']}")
        sys.exit(0)

    pf = stats["profit_factor"]
    print(f"  Total trades   : {stats['total_trades']}")
    print(f"  Win rate       : {stats['win_rate']:.1f}%")
    print(f"  Profit factor  : {pf:.2f}")
    print(f"  Total P&L      : ${stats['total_pnl']:,.2f}")
    print(f"  Avg win        : ${stats['avg_win']:,.2f}")
    print(f"  Avg loss       : ${stats['avg_loss']:,.2f}")
    print("  ── P&L by session ──")
    for sess, pnl in stats["by_session"].items():
        print(f"     {sess:<10} ${pnl:,.2f}")
    print("=" * 66)


if __name__ == "__main__":
    main()
