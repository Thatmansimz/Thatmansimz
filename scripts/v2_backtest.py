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
from backend.clock import utc_now as _utc_now
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
from backend.services.costs import slip_entry, slip_stop_exit, round_trip_commission


def simulate(df: pd.DataFrame, symbol: str, only_session: str | None,
             asia_kill_zone_only: bool = True,
             asia_max_rr: float = 2.0,
             asia_require_macro_zone: bool = False,
             commission_per_side: float = 1.50,
             slippage_ticks: int = 1,
             sessions: list | None = None,
             target_rr: float = 0.0,
             fixed_risk: float = 0.0) -> dict:
    strat = MultiSessionStrategy()
    # Mirror the live engine's config knobs exactly — same class, same fields.
    if sessions:
        strat.enabled_sessions = set(sessions)
    if target_rr:
        strat.target_rr_override = float(target_rr)
    if fixed_risk:
        strat.fixed_risk_dollars = float(fixed_risk)
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
            # stop / target checks (intrabar, stop-first conservative).
            # Stops fill through the level with slippage (market order);
            # targets fill at price (resting limit).
            if d["dir"] == "long":
                if lo <= d["stop"]:
                    fill = slip_stop_exit(symbol, "long", min(d["stop"], float(bar["open"])), slippage_ticks)
                    pnl = (fill - d["entry"]) * pv * d["contracts"]; exited = True
                elif hi >= d["t2"]:
                    pnl = (d["t2"] - d["entry"]) * pv * d["contracts"]; exited = True
            else:
                if hi >= d["stop"]:
                    fill = slip_stop_exit(symbol, "short", max(d["stop"], float(bar["open"])), slippage_ticks)
                    pnl = (d["entry"] - fill) * pv * d["contracts"]; exited = True
                elif lo <= d["t2"]:
                    pnl = (d["entry"] - d["t2"]) * pv * d["contracts"]; exited = True

            if exited:
                pnl -= round_trip_commission(d["contracts"], commission_per_side)
                trades.append({"pnl": pnl, "session": d["session"], "dir": d["dir"]})
                open_pos = None
            else:
                # trailing: at +1R move to breakeven, then trail behind EMA-12
                from backend.services.exit_rules import trail_v2
                ema = float(window["close"].ewm(span=12, adjust=False).mean().iloc[-1])
                initial_stop = d["entry"] - d["risk_pts"] if d["dir"] == "long" else d["entry"] + d["risk_pts"]
                d["stop"] = trail_v2(symbol, d["dir"], d["entry"], initial_stop, d["stop"], close, ema)
                continue  # one position at a time

        # ── look for a new entry ──
        sig = strat.generate_signal(window, symbol)
        if not sig:
            continue
        if only_session and sig["session"] != only_session:
            continue
        # Entry is a market order — fill with adverse slippage.
        entry_fill = slip_entry(symbol, sig["direction"], sig["entry_price"], slippage_ticks)
        risk_pts = abs(entry_fill - sig["stop_loss"])
        if risk_pts <= 0:
            continue
        open_pos = {
            "entry": entry_fill, "stop": sig["stop_loss"], "t2": sig["target_2"],
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
    ap.add_argument("--asia-rr", type=float, default=2.0,
                    help="Asia R:R target (default 2.0, validated by grid search)")
    ap.add_argument("--asia-macro", action="store_true",
                    help="require macro zone confluence for Asia entries (non-default)")
    ap.add_argument("--commission", type=float, default=1.50,
                    help="commission $/contract/side (default 1.50 → $3.00 round trip)")
    ap.add_argument("--slippage-ticks", type=int, default=1,
                    help="ticks of adverse slippage on entries and stop exits (default 1)")
    ap.add_argument("--sessions", default=None,
                    help="comma-separated sessions to trade, e.g. NEW_YORK "
                         "(default: all three)")
    ap.add_argument("--target-rr", type=float, default=0.0,
                    help="target as a multiple of risk; 0 = session default (2.0)")
    ap.add_argument("--fixed-risk", type=float, default=0.0,
                    help="fixed $ risk per trade; 0 = profit-window sizing")
    ap.add_argument("--save-baseline", action="store_true",
                    help="write data/baseline.json so the dashboard can plot "
                         "this backtest against the live forward-test record")
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
          f"rr={args.asia_rr}  macro-zone={args.asia_macro}")
    print(f"  Friction   : ${args.commission:.2f}/side commission, "
          f"{args.slippage_ticks}-tick slippage on entries + stop exits")
    print(f"  Config     : sessions={args.sessions or 'ALL'}  "
          f"target_rr={args.target_rr or 'session default'}  "
          f"fixed_risk={('$'+format(args.fixed_risk,'.0f')) if args.fixed_risk else 'profit-window'}")
    print()
    stats = simulate(df, args.symbol, args.session,
                     asia_kill_zone_only=not args.no_asia_kz_only,
                     asia_max_rr=args.asia_rr,
                     asia_require_macro_zone=args.asia_macro,
                     commission_per_side=args.commission,
                     slippage_ticks=args.slippage_ticks,
                     sessions=args.sessions.split(",") if args.sessions else None,
                     target_rr=args.target_rr,
                     fixed_risk=args.fixed_risk)
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

    if args.save_baseline:
        import json, os as _os
        from datetime import datetime as _dt
        days = int("".join(c for c in args.period if c.isdigit()) or 30)
        payload = {
            "generated_at": _utc_now().isoformat(),
            "symbol": args.symbol,
            "period": args.period,
            "days": days,
            "total_trades": stats["total_trades"],
            "win_rate": round(stats["win_rate"], 2),
            "profit_factor": round(pf, 3) if pf != float("inf") else None,
            "total_pnl": round(stats["total_pnl"], 2),
            "avg_win": round(stats["avg_win"], 2),
            "avg_loss": round(stats["avg_loss"], 2),
            "by_session": {k: round(v, 2) for k, v in stats["by_session"].items()},
            "commission_per_side": args.commission,
            "slippage_ticks": args.slippage_ticks,
            # WHICH SYSTEM this baseline describes. Without these the record
            # endpoint cannot tell whether the benchmark and the live engine
            # are even the same strategy — and it silently compared a
            # three-session backtest against a New-York-only live run.
            # Defaults to the full session set, matching run_v2()'s behaviour
            # when --sessions is omitted.
            "sessions": sorted(args.sessions.split(",")) if args.sessions
                        else ["ASIA", "LONDON", "NEW_YORK"],
            "target_rr": args.target_rr or None,
            "risk_per_trade": args.fixed_risk or None,
        }
        _os.makedirs("data", exist_ok=True)
        with open(_os.path.join("data", "baseline.json"), "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  ✅ Baseline saved to data/baseline.json — the dashboard will now")
        print(f"     plot live results against this backtest.")
        print("=" * 66)


if __name__ == "__main__":
    main()
