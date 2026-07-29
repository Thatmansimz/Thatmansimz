#!/usr/bin/env python3
"""
Tajari Research Harness — anti-overfitting by construction
==========================================================

WHY THIS EXISTS
---------------
Yahoo serves 5-minute bars for the last 60 DAYS only. That is the entire
dataset. With ~171 trades and a dozen tunable parameters, a plain parameter
sweep WILL find a configuration showing PF 1.8 — and it will be fiction. This
harness makes that specific mistake hard to commit:

  1. TRAIN/TEST SPLIT is mandatory and chronological. Every sweep reports the
     train result AND the held-out test result side by side. A config that only
     works in train is labelled OVERFIT, loudly.
  2. ROBUSTNESS is scored, not just performance. An edge should be a PLATEAU
     across neighbouring parameter values, not a SPIKE at one value. Spikes are
     noise. The harness computes neighbour agreement and flags spikes.
  3. COST SENSITIVITY is reported. Any edge that dies when commission or
     slippage rises slightly was never an edge — it was a rounding artifact.
  4. MULTIPLE TESTING is counted and disclosed. Test 20 configs and ~1 will
     look good at p<0.05 by luck; the harness tells you how much of your best
     result is explainable that way.
  5. NOISE FLOOR is computed. If a claimed improvement sits inside the
     confidence interval of the baseline, the harness says the data cannot
     resolve it.

USAGE
-----
    # 1. Establish the honest baseline with split reporting
    python3 scripts/research.py baseline --symbol MNQ

    # 2. Sweep ONE parameter at a time (mechanism first, always)
    python3 scripts/research.py sweep --param min_stop_points --values 0,5,10,15,20,25
    python3 scripts/research.py sweep --param kill_zone_only --values 0,1
    python3 scripts/research.py sweep --param asia_max_rr   --values 1.5,2.0,2.5,3.0

    # 3. Session isolation with split discipline
    python3 scripts/research.py sessions --symbol MNQ

    # 4. Cost stress on a candidate config
    python3 scripts/research.py costs --min-stop 15 --kill-zone-only 1

    # 5. Walk-forward: rolling train->test windows
    python3 scripts/research.py walkforward --param min_stop_points --values 0,10,20

Run locally — the cloud sandbox blocks market data.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from scripts.v2_backtest import simulate as _simulate_base
from backend.strategies.v2 import MultiSessionStrategy
from backend.strategies.v2 import sessions as S
from backend.strategies.v2.strategy import SPECS
from backend.services.costs import slip_entry, slip_stop_exit, round_trip_commission

BAR = "=" * 78
SUB = "-" * 78


# ──────────────────────────────────────────────────────────────────────────────
# Core simulation with research knobs. Mirrors scripts/v2_backtest.simulate()
# exactly, plus the extra gates under study. Defaults reproduce the baseline.
# ──────────────────────────────────────────────────────────────────────────────
def simulate(df, symbol, cfg) -> dict:
    strat = MultiSessionStrategy()
    strat.asia_kill_zone_only = cfg.get("asia_kill_zone_only", True)
    strat.asia_max_rr = cfg.get("asia_max_rr", 2.0)
    strat.asia_require_macro_zone = cfg.get("asia_require_macro_zone", False)
    if "flat_tol_frac" in cfg:
        strat.flat_tol_frac = cfg["flat_tol_frac"]
    if "max_contracts" in cfg:
        strat.max_contracts = int(cfg["max_contracts"])

    only_session = cfg.get("only_session")
    min_stop_points = float(cfg.get("min_stop_points", 0.0))
    kill_zone_only = bool(cfg.get("kill_zone_only", False))
    target_rr = cfg.get("target_rr")            # override t2 multiple
    commission = float(cfg.get("commission", 1.50))
    slip_ticks = int(cfg.get("slippage_ticks", 1))
    fixed_risk = cfg.get("fixed_risk_dollars")  # constant-risk sizing instead of profit window

    spec = SPECS.get(symbol.upper(), SPECS["MNQ"])
    pv = spec["point_value"]

    trades, open_pos = [], None
    et = df.index if df.index.tz is None else df.index.tz_convert("America/New_York")

    for i in range(25, len(df)):
        window = df.iloc[: i + 1]
        bar = df.iloc[i]
        hi, lo, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        if open_pos:
            d = open_pos
            exited, pnl = False, 0.0
            if d["dir"] == "long":
                if lo <= d["stop"]:
                    fill = slip_stop_exit(symbol, "long", d["stop"], slip_ticks)
                    pnl = (fill - d["entry"]) * pv * d["contracts"]; exited = True
                elif hi >= d["t2"]:
                    pnl = (d["t2"] - d["entry"]) * pv * d["contracts"]; exited = True
            else:
                if hi >= d["stop"]:
                    fill = slip_stop_exit(symbol, "short", d["stop"], slip_ticks)
                    pnl = (d["entry"] - fill) * pv * d["contracts"]; exited = True
                elif lo <= d["t2"]:
                    pnl = (d["entry"] - d["t2"]) * pv * d["contracts"]; exited = True

            if exited:
                pnl -= round_trip_commission(d["contracts"], commission)
                trades.append({"pnl": pnl, "session": d["session"], "dir": d["dir"],
                               "r": pnl / d["risk_dollars"] if d["risk_dollars"] else 0.0,
                               "stop_pts": d["risk_pts"], "contracts": d["contracts"],
                               "idx": i})
                open_pos = None
            else:
                r = d["risk_pts"]
                ema = float(window["close"].ewm(span=12, adjust=False).mean().iloc[-1])
                if d["dir"] == "long":
                    if close >= d["entry"] + r and d["stop"] < d["entry"]:
                        d["stop"] = d["entry"]
                    d["stop"] = max(d["stop"], min(ema, close - r * 0.25))
                else:
                    if close <= d["entry"] - r and d["stop"] > d["entry"]:
                        d["stop"] = d["entry"]
                    d["stop"] = min(d["stop"], max(ema, close + r * 0.25))
                continue

        sig = strat.generate_signal(window, symbol)
        if not sig:
            continue
        if only_session and sig["session"] != only_session:
            continue

        # ── research gate: kill-zone-only across ALL sessions ──
        if kill_zone_only and not sig.get("kill_zone"):
            continue

        entry_fill = slip_entry(symbol, sig["direction"], sig["entry_price"], slip_ticks)
        risk_pts = abs(entry_fill - sig["stop_loss"])
        if risk_pts <= 0:
            continue

        # ── research gate: minimum stop width (cost-arithmetic filter) ──
        if risk_pts < min_stop_points:
            continue

        contracts = sig["contracts"]
        if fixed_risk:
            contracts = max(1, min(strat.max_contracts,
                                   int(float(fixed_risk) / (risk_pts * pv))))

        t2 = sig["target_2"]
        if target_rr:
            rr = float(target_rr)
            t2 = entry_fill + risk_pts * rr if sig["direction"] == "long" \
                else entry_fill - risk_pts * rr

        open_pos = {"entry": entry_fill, "stop": sig["stop_loss"], "t2": t2,
                    "dir": sig["direction"], "contracts": contracts,
                    "risk_pts": risk_pts, "risk_dollars": risk_pts * pv * contracts,
                    "session": sig["session"]}

    return stats(trades, symbol)


def stats(trades, symbol="MNQ") -> dict:
    if not trades:
        return {"trades": 0, "wr": 0.0, "pf": 0.0, "pnl": 0.0, "avg_win": 0.0,
                "avg_loss": 0.0, "expectancy": 0.0, "max_dd": 0.0,
                "by_session": {}, "raw": []}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    by_session = {}
    for t in trades:
        by_session.setdefault(t["session"], 0.0)
        by_session[t["session"]] += t["pnl"]
    return {
        "trades": len(trades),
        "wr": 100.0 * len(wins) / len(trades),
        "pf": (gw / gl) if gl else float("inf"),
        "pnl": sum(pnls),
        "avg_win": (gw / len(wins)) if wins else 0.0,
        "avg_loss": (-gl / len(losses)) if losses else 0.0,
        "expectancy": sum(pnls) / len(trades),
        "max_dd": mdd,
        "by_session": {k: round(v, 2) for k, v in by_session.items()},
        "raw": trades,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Statistics — the noise floor. Everything is judged against this.
# ──────────────────────────────────────────────────────────────────────────────
def wr_ci(wins: int, n: int, z: float = 1.96):
    """95% CI on win rate (Wilson interval — correct for small n)."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, c - h), 100 * min(1.0, c + h))


def pnl_ci(trades, z: float = 1.96):
    """CI on total P&L from per-trade variance — the honest error bar."""
    pnls = [t["pnl"] for t in trades]
    n = len(pnls)
    if n < 2:
        return (0.0, 0.0, 0.0)
    m, sd = mean(pnls), stdev(pnls)
    se_total = sd * math.sqrt(n)
    return (sum(pnls) - z * se_total, sum(pnls) + z * se_total, sd / math.sqrt(n))


def is_resolvable(base, cand) -> bool:
    """
    Can this dataset tell these two configs apart at all? If the candidate's
    P&L sits inside the baseline's confidence interval, the answer is no —
    and no amount of staring at the number changes that.
    """
    if base["trades"] < 2 or cand["trades"] < 2:
        return False
    lo, hi, _ = pnl_ci(base["raw"])
    return not (lo <= cand["pnl"] <= hi)


# ──────────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────────
def fmt(s: dict) -> str:
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"{s['trades']:>4d}t  WR {s['wr']:>4.1f}%  PF {pf:>5s}  "
            f"${s['pnl']:>10,.2f}  exp ${s['expectancy']:>7,.2f}  DD ${s['max_dd']:>8,.2f}")


def split_df(df, frac=0.5):
    cut = int(len(df) * frac)
    return df.iloc[:cut], df.iloc[cut:]


def verdict(train: dict, test: dict, base_test: dict | None = None) -> str:
    """The whole point: does it hold up OUT of sample?"""
    if train["trades"] < 10 or test["trades"] < 10:
        return "INSUFFICIENT — too few trades in one half to judge"
    tr_ok = train["pf"] > 1.0
    te_ok = test["pf"] > 1.0
    if tr_ok and te_ok:
        return "HOLDS — profitable in BOTH halves"
    if tr_ok and not te_ok:
        return "OVERFIT — profitable in train, fails out of sample"
    if not tr_ok and te_ok:
        return "SUSPECT — only the test half worked (likely noise)"
    return "FAILS — unprofitable in both halves"


def load(symbol: str, period: str, interval: str = "5m"):
    from backend.services.market_data import MarketDataService
    md = MarketDataService()
    print(f"  downloading {symbol} {period} @ {interval} ...")
    df = md.get_historical(symbol, period=period, interval=interval)
    if df is None or df.empty:
        print("  ERROR: no market data. Run locally (the sandbox blocks yfinance).")
        sys.exit(1)
    print(f"  {len(df)} bars  [{df.index[0]} → {df.index[-1]}]\n")
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────
def cmd_baseline(args):
    df = load(args.symbol, args.period)
    tr, te = split_df(df)
    print(BAR); print("  BASELINE — current config, train/test split"); print(BAR)
    full = simulate(df, args.symbol, {})
    a = simulate(tr, args.symbol, {})
    b = simulate(te, args.symbol, {})
    print(f"  FULL   {fmt(full)}")
    print(f"  TRAIN  {fmt(a)}")
    print(f"  TEST   {fmt(b)}")
    print(f"\n  VERDICT: {verdict(a, b)}")
    print(SUB)
    wins = round(full["trades"] * full["wr"] / 100)
    lo, hi = wr_ci(wins, full["trades"])
    plo, phi, se = pnl_ci(full["raw"])
    print(f"  NOISE FLOOR (this is what the data can actually resolve):")
    print(f"    win rate {full['wr']:.1f}%  95% CI [{lo:.1f}%, {hi:.1f}%]")
    print(f"    total P&L ${full['pnl']:,.2f}  95% CI [${plo:,.0f}, ${phi:,.0f}]")
    print(f"    per-trade std error ${se:,.2f}")
    print(f"\n  => Any 'improvement' landing inside that P&L interval is NOT")
    print(f"     distinguishable from luck with {full['trades']} trades.")
    print(f"  sessions: {full['by_session']}")
    print(BAR)


def cmd_sweep(args):
    df = load(args.symbol, args.period)
    tr, te = split_df(df)
    vals = [float(v) if "." in v or v.replace("-", "").isdigit() else v
            for v in args.values.split(",")]
    print(BAR); print(f"  SWEEP — {args.param}  ({len(vals)} values)"); print(BAR)
    print(f"  Decision rule fixed BEFORE looking: pick the value with the best")
    print(f"  TEST-half PF whose neighbours also hold up (a plateau, not a spike).")
    print(SUB)
    print(f"  {'value':>12} | {'TRAIN':^52} | {'TEST':^52}")
    print(SUB)
    rows = []
    for v in vals:
        cfg = {args.param: v}
        a = simulate(tr, args.symbol, cfg)
        b = simulate(te, args.symbol, cfg)
        rows.append((v, a, b))
        print(f"  {str(v):>12} | {fmt(a)} | {fmt(b)}")
    print(SUB)

    # Plateau detection: an edge should not depend on hitting one exact value.
    print("  ROBUSTNESS (is it a plateau or a spike?)")
    best = max(rows, key=lambda r: r[2]["pf"] if r[2]["trades"] >= 10 else -1)
    bi = rows.index(best)
    neigh = [rows[j][2]["pf"] for j in (bi - 1, bi + 1) if 0 <= j < len(rows)
             and rows[j][2]["trades"] >= 10]
    print(f"    best TEST value: {best[0]}  (PF {best[2]['pf']:.2f})")
    if neigh:
        ok = sum(1 for p in neigh if p > 1.0)
        print(f"    neighbours' TEST PF: {[round(p,2) for p in neigh]}")
        if ok == len(neigh):
            print("    ✅ PLATEAU — neighbours also profitable. This looks structural.")
        elif ok:
            print("    ⚠ EDGE OF A PLATEAU — partially supported by neighbours.")
        else:
            print("    ❌ SPIKE — neighbours fail. Almost certainly curve-fit noise.")
    else:
        print("    (no comparable neighbours)")

    base = simulate(df, args.symbol, {})
    cand = simulate(df, args.symbol, {args.param: best[0]})
    print(SUB)
    print(f"  MULTIPLE TESTING: you just tested {len(vals)} values. With that many")
    print(f"  looks, roughly {max(1, round(len(vals)*0.05))} would appear 'significant' by chance alone.")
    print(f"  RESOLVABLE vs baseline? {'YES' if is_resolvable(base, cand) else 'NO — inside the noise interval'}")
    print(f"  VERDICT for {args.param}={best[0]}: {verdict(best[1], best[2])}")
    print(BAR)


def cmd_sessions(args):
    df = load(args.symbol, args.period)
    tr, te = split_df(df)
    print(BAR); print("  SESSION ISOLATION — with train/test discipline"); print(BAR)
    print(f"  {'session':>12} | {'TRAIN':^52} | {'TEST':^52}")
    print(SUB)
    for sess in (None, "NEW_YORK", "LONDON", "ASIA"):
        cfg = {"only_session": sess} if sess else {}
        a = simulate(tr, args.symbol, cfg)
        b = simulate(te, args.symbol, cfg)
        print(f"  {(sess or 'ALL'):>12} | {fmt(a)} | {fmt(b)}")
    print(SUB)
    print("  ⚠ SELECTION BIAS: choosing the best of 4 options on the same data")
    print("    inflates the winner. A session only earns trust if it is profitable")
    print("    in BOTH halves independently.")
    print(BAR)


def cmd_costs(args):
    df = load(args.symbol, args.period)
    cfg = {}
    if args.min_stop:        cfg["min_stop_points"] = args.min_stop
    if args.kill_zone_only:  cfg["kill_zone_only"] = True
    if args.session:         cfg["only_session"] = args.session
    if args.target_rr:       cfg["target_rr"] = args.target_rr
    if args.fixed_risk:      cfg["fixed_risk_dollars"] = args.fixed_risk

    print(BAR); print("  COST SENSITIVITY — does the edge survive worse friction?"); print(BAR)
    print(f"  config: {cfg or '(baseline)'}")
    print(SUB)
    print(f"  {'commission':>11} {'slip':>5} | {'result':<52}")
    print(SUB)
    for comm in (0.0, 1.50, 2.50, 4.00):
        for slip in (0, 1, 2):
            c = dict(cfg, commission=comm, slippage_ticks=slip)
            s = simulate(df, args.symbol, c)
            flag = ""
            if comm == 1.50 and slip == 1:
                flag = "  <- as modelled"
            print(f"  ${comm:>10.2f} {slip:>5d} | {fmt(s)}{flag}")
    print(SUB)
    print("  An edge that only exists at zero cost is not an edge. If PF drops")
    print("  below 1.0 by $2.50/side or 2 ticks, real-world execution will kill it.")
    print(BAR)


def cmd_walkforward(args):
    df = load(args.symbol, args.period)
    vals = [float(v) for v in args.values.split(",")]
    folds = args.folds
    n = len(df) // (folds + 1)
    print(BAR); print(f"  WALK-FORWARD — {folds} folds, {args.param}"); print(BAR)
    print("  Each fold: choose the best value on the TRAIN window, then score it")
    print("  on the NEXT window it has never seen. This is the honest test.")
    print(SUB)
    oos = []
    for k in range(folds):
        tr = df.iloc[: n * (k + 1)]
        te = df.iloc[n * (k + 1): n * (k + 2)]
        if len(te) < 100:
            continue
        picks = [(v, simulate(tr, args.symbol, {args.param: v})) for v in vals]
        best_v = max(picks, key=lambda p: p[1]["pf"] if p[1]["trades"] >= 5 else -1)[0]
        res = simulate(te, args.symbol, {args.param: best_v})
        oos.append(res)
        print(f"  fold {k+1}: chose {args.param}={best_v:<6} -> out-of-sample {fmt(res)}")
    print(SUB)
    if oos:
        tot = sum(r["pnl"] for r in oos)
        wins = sum(1 for r in oos if r["pnl"] > 0)
        print(f"  TOTAL out-of-sample P&L: ${tot:,.2f} across {len(oos)} folds "
              f"({wins}/{len(oos)} folds profitable)")
        print(f"  => {'PROMISING' if tot > 0 and wins > len(oos)/2 else 'NO EDGE DEMONSTRATED'}")
    print(BAR)


def main():
    ap = argparse.ArgumentParser(description="Tajari research harness (anti-overfitting)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--symbol", default="MNQ")
        p.add_argument("--period", default="60d")

    p = sub.add_parser("baseline"); common(p); p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("sessions"); common(p); p.set_defaults(fn=cmd_sessions)

    p = sub.add_parser("sweep"); common(p)
    p.add_argument("--param", required=True,
                   help="min_stop_points | kill_zone_only | asia_max_rr | target_rr | "
                        "max_contracts | flat_tol_frac | fixed_risk_dollars")
    p.add_argument("--values", required=True, help="comma-separated")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("costs"); common(p)
    p.add_argument("--min-stop", type=float, default=None)
    p.add_argument("--kill-zone-only", type=int, default=0)
    p.add_argument("--session", default=None)
    p.add_argument("--target-rr", type=float, default=None)
    p.add_argument("--fixed-risk", type=float, default=None)
    p.set_defaults(fn=cmd_costs)

    p = sub.add_parser("walkforward"); common(p)
    p.add_argument("--param", required=True)
    p.add_argument("--values", required=True)
    p.add_argument("--folds", type=int, default=3)
    p.set_defaults(fn=cmd_walkforward)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
