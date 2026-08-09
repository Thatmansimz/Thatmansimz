#!/usr/bin/env python3
"""
Continuation Statistic — does a strong directional close actually continue?
==========================================================================

WHY THIS IS THE MOST IMPORTANT SCRIPT IN THE REPO
-------------------------------------------------
V2's entire premise is "a strong directional close continues." Every parameter,
filter and session rule is downstream of that one assumption — and it has never
been tested. It has only ever been tested *indirectly*, through 171 trades whose
P&L confidence interval is so wide that nothing is resolvable:

    observed win rate        31.0%  [24.5%, 38.3%]
    break-even win rate      32.9%   <- inside the interval
    random-walk win rate     33.3%   <- ALSO inside the interval

So the trade-level data cannot tell the difference between "a real edge that
friction is eating" and "a coin flip." That distinction decides whether this
project continues, and it cannot be settled with trades.

But it CAN be settled with bars. The premise is a property of bar events, not
of trades — and there are ~700 qualifying events in 60 days instead of 171
trades, so the standard error is roughly 3.6x tighter. This script measures the
premise directly, with NO strategy code, NO entry rules, NO position sizing,
NO costs, and NO tunable parameters.

PRE-REGISTERED SPECIFICATION — fixed by definition, not searched
---------------------------------------------------------------
    event      : bar where true range > 1.0 x ATR(14)
                 AND the close falls in the outer third of the bar's range
                 (direction = up if closing in the top third, down if bottom)
    measurement: signed continuation of the close over the next k bars,
                 expressed in units of that bar's ATR
    horizons   : k in {1, 2, 3, 6}
    buckets    : session, and hour-of-day within regular trading hours

These four choices are declared BEFORE running and must not be re-specified.
Trying a second specification and reporting the better one is the exact
mechanism that manufactures false positives. If you want a different spec,
log it in docs/HYPOTHESES.md as a new hypothesis and accept the multiplicity
penalty.

POWER LIMITATION — read this before interpreting a null result
-------------------------------------------------------------
This test is ASYMMETRIC and it is important to know which direction it can
actually settle. Computed, not assumed:

    minimum detectable effect at n=700, SD 1.0 ATR, t=2 :  0.076 ATR
    economically required effect (to move 2R win rate
    from the driftless 33.3% to a PF-1.4-ish 37%)       :  0.018 ATR

The effect that would make this strategy profitable is roughly 4x SMALLER
than the smallest effect 700 events can resolve. Therefore:

    a clean POSITIVE (t >= 2) means a LARGE, unambiguous edge — strong news,
    worth building on immediately;

    a NULL does NOT prove the premise false. It rules out a large edge and
    leaves a small one unmeasured. It is discouraging evidence, not proof.

Note also what the trade data already implies: the observed 2R win rate is
31.0% while a pure driftless walk gives 33.3%. The strategy is currently
performing BELOW the no-edge baseline, which is consistent with the entry
carrying no continuation signal at all — and possibly with the stop placement
(inside the range price just traversed) actively harvesting noise.

INTERPRETATION, PRE-COMMITTED
-----------------------------
    continuation > 0 with |t| >= 2 in RTH at any horizon
        -> the premise is REAL and LARGE. The problem is friction or the exit
           logic, and the project has something concrete to work with.

    continuation ~= 0 or negative in RTH at EVERY horizon
        -> no large edge exists. Combined with a 2R win rate already below the
           random-walk baseline, the reasonable conclusion is that this entry
           does not carry signal at this timeframe. Do not spend the remaining
           data budget filtering it; the honest next move is more data or a
           different design.

Usage:
    python3 scripts/continuation.py --symbol MNQ --period 60d

Run locally — the cloud sandbox blocks market data.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
BAR = "=" * 80
SUB = "-" * 80

# Pre-registered constants. Do not tune these. They are the specification.
ATR_PERIOD = 14
TR_MULT = 1.0
OUTER_FRACTION = 1.0 / 3.0
HORIZONS = (1, 2, 3, 6)


def _pandas_interval(interval: str | None) -> str | None:
    """
    Map a yfinance-style interval ("5m") onto a pandas resample rule ("5min").

    Purchased history is normally 1-minute. The strategy, the backtest and the
    existing 60-day yfinance baseline are all 5-minute, so resampling on load is
    what keeps a CSV run comparable to everything already measured.
    """
    if not interval:
        return None
    s = str(interval).strip().lower()
    if s.endswith("m") and not s.endswith("mo"):
        return f"{s[:-1]}min"
    if s.endswith("h"):
        return f"{s[:-1]}h"
    if s.endswith("d"):
        return f"{s[:-1]}D"
    return s


def atr_series(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean(), tr


def session_of(ts) -> str:
    """V2's own session windows, so results map onto the strategy's buckets."""
    m = ts.hour * 60 + ts.minute
    def win(a, b):
        return (a <= m < b) if a <= b else (m >= a or m < b)
    if win(9 * 60 + 30, 16 * 60):
        return "RTH"          # US cash session — where NQ's real flow is
    if win(4 * 60, 9 * 60 + 30):
        return "LONDON"
    if win(20 * 60, 4 * 60):
        return "ASIA"
    return "OTHER"


def tstat(x: np.ndarray) -> tuple[float, float, float]:
    n = len(x)
    if n < 3:
        return (0.0, 0.0, 0.0)
    m = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    se = sd / math.sqrt(n) if sd > 0 else 0.0
    return (m, se, (m / se) if se > 0 else 0.0)


def trimmed_mean(x: np.ndarray, frac=0.10) -> float:
    if len(x) < 5:
        return float(np.mean(x)) if len(x) else 0.0
    k = int(len(x) * frac)
    s = np.sort(x)
    return float(np.mean(s[k: len(s) - k])) if len(s) - 2 * k > 0 else float(np.mean(s))


def main():
    ap = argparse.ArgumentParser(description="Strategy-free continuation statistic")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--period", default="60d")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--csv", default=None,
                    help="load bars from a purchased CSV instead of yfinance "
                         "(removes the 60-day/5m ceiling that makes this test "
                         "underpowered)")
    ap.add_argument("--csv-tz", default="America/New_York",
                    help="timezone the CSV's timestamps are written in "
                         "(FirstRate ships US/Eastern; some vendors ship UTC)")
    args = ap.parse_args()

    print(BAR)
    print("  CONTINUATION STATISTIC — is the entry premise real?")
    print(BAR)
    print(f"  PRE-REGISTERED SPEC (fixed before running, not searched):")
    print(f"    event   : true range > {TR_MULT} x ATR({ATR_PERIOD}), close in outer third")
    print(f"    measure : signed close move over next k bars, in ATR units")
    print(f"    horizons: {list(HORIZONS)}")
    print(f"    buckets : session, then hour within RTH")
    print(SUB)

    if args.csv:
        from backend.services.csv_data import load_bars
        df = load_bars(args.csv, tz=args.csv_tz, interval=_pandas_interval(args.interval),
                       symbol=args.symbol)
    else:
        from backend.services.market_data import MarketDataService
        md = MarketDataService()
        df = md.get_historical(args.symbol, period=args.period, interval=args.interval)
    if df is None or df.empty:
        print("  ERROR: no market data. Run locally (the sandbox blocks yfinance).")
        sys.exit(1)
    if not args.csv:
        # Only the live feed has a still-forming final bar. Purchased history is
        # complete by definition, and the class is not imported on that path.
        df = MarketDataService.drop_forming_bar(df)
    idx = df.index if df.index.tz is None else df.index.tz_convert(ET)
    df = df.copy(); df.index = idx
    print(f"  {len(df)} completed bars  [{df.index[0]} → {df.index[-1]}]")

    atr, tr = atr_series(df)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    pos_in_range = (df["close"] - df["low"]) / rng      # 1.0 = closed at high

    strong = tr > (TR_MULT * atr)
    up = strong & (pos_in_range >= 1.0 - OUTER_FRACTION)
    dn = strong & (pos_in_range <= OUTER_FRACTION)

    close = df["close"].to_numpy()
    atr_v = atr.to_numpy()
    n = len(df)

    events = []   # (i, session, hour, direction)
    for i in np.flatnonzero((up | dn).to_numpy()):
        if i + max(HORIZONS) >= n or not np.isfinite(atr_v[i]) or atr_v[i] <= 0:
            continue
        events.append((int(i), session_of(df.index[i]), df.index[i].hour,
                       1 if bool(up.iloc[i]) else -1))

    print(f"  qualifying events: {len(events)}  "
          f"({sum(1 for e in events if e[3] > 0)} up / {sum(1 for e in events if e[3] < 0)} down)")
    if len(events) < 50:
        print("\n  Too few events to say anything. Stopping.")
        sys.exit(0)

    def moves(subset, k):
        """Signed continuation in ATR units for each event in subset."""
        return np.array([d * (close[i + k] - close[i]) / atr_v[i] for i, _, _, d in subset])

    cells = 0

    def report(label, subset):
        nonlocal cells
        if len(subset) < 20:
            print(f"  {label:<14} n={len(subset):<4}  (too few — skipped)")
            return
        print(f"  {label:<14} n={len(subset)}")
        for k in HORIZONS:
            x = moves(subset, k)
            m, se, t = tstat(x)
            tm = trimmed_mean(x)
            med = float(np.median(x))
            # drop the single largest |move| — a real effect survives this
            j = int(np.argmax(np.abs(x)))
            x2 = np.delete(x, j)
            m2, _, t2 = tstat(x2)
            cells += 1
            flag = "  <-- SIGNAL" if abs(t) >= 2 and m > 0 else ""
            print(f"     k={k}: mean {m:+.4f} ATR  t={t:+5.2f}   "
                  f"median {med:+.4f}  trimmed {tm:+.4f}  "
                  f"drop-max t={t2:+5.2f}{flag}")

    print(); print(BAR); print("  BY SESSION"); print(BAR)
    for sess in ("RTH", "LONDON", "ASIA"):
        report(sess, [e for e in events if e[1] == sess])

    print(); print(BAR); print("  BY HOUR WITHIN RTH (ET)"); print(BAR)
    rth = [e for e in events if e[1] == "RTH"]
    for h in sorted({e[2] for e in rth}):
        report(f"{h:02d}:00 ET", [e for e in rth if e[2] == h])

    print(); print(BAR); print("  MULTIPLICITY"); print(BAR)
    print(f"  cells printed: {cells}")
    if cells:
        bonf = 1.96 if cells <= 1 else abs(round(2.807 if cells <= 10 else 3.29, 2))
        print(f"  With {cells} cells, the |t| bar for genuine significance is ~{bonf}")
        print(f"  (Bonferroni), NOT 1.96. One cell at |t|=2.1 out of {cells} is expected")
        print(f"  by chance and means nothing on its own.")

    print(); print(BAR); print("  PRE-COMMITTED READ"); print(BAR)
    rth_pos = []
    for k in HORIZONS:
        if len(rth) >= 20:
            m, se, t = tstat(moves(rth, k))
            rth_pos.append((k, m, se, t))
    if not rth_pos:
        print("  Not enough RTH events to judge.")
    else:
        # AMENDMENT (2026-08-06, BEFORE any purchased data was run through this
        # script — recorded here so the change is auditable and was not made
        # after seeing a result we disliked).
        #
        # The original rule was `t >= 2` in RTH at any horizon, and its stated
        # justification was: at n~700 only a LARGE effect can reach t=2, so t=2
        # implies an economically meaningful effect. That reasoning is correct
        # at n~700 and INVERTS as n grows:
        #
        #     n =    700  ->  smallest mean reaching t=2 is ~0.076 ATR  (>> 0.018, safe)
        #     n = 10,000  ->  smallest mean reaching t=2 is ~0.010 ATR  (<  0.018, UNSAFE)
        #
        # Past roughly n=3,500 the t>=2 bar is cleared by effects too small to
        # pay the commission — the test starts saying "build on this" about
        # edges that cannot fund themselves. Buying history, the entire point of
        # the next step, is what breaks the old threshold. Verified empirically:
        # a driftless random walk drew t=+2.00 and printed "PREMISE SUPPORTED".
        #
        # So the bar is now ECONOMIC, not merely statistical: the lower end of
        # the effect's confidence interval must clear the profitability
        # threshold, Bonferroni-corrected across the pre-registered horizons.
        # "Distinguishable from zero" was never the question worth asking.
        econ = 0.018
        z_bonf = 2.50          # 4 pre-registered horizons, two-sided alpha 0.05
        for k, m, se, t in rth_pos:
            lo = m - z_bonf * se
            print(f"    RTH k={k}: mean {m:+.4f} ATR, t={t:+.2f}, "
                  f"corrected 95% lower bound {lo:+.4f}")
        print()
        # Honest MDE for this actual sample, so the null can be read correctly.
        sd_obs = float(np.std(moves(rth, 1), ddof=1)) if len(rth) >= 20 else 1.0
        mde = 2.0 * sd_obs / math.sqrt(max(1, len(rth)))
        print(f"    [n={len(rth)} RTH events, SD {sd_obs:.2f} ATR"
              f" -> smallest detectable mean at t=2: {mde:.4f} ATR]")
        print(f"    [effect needed to make the strategy profitable: ~{econ} ATR]")
        if mde < econ:
            print(f"    [n is now large enough that t=2 no longer implies a payable")
            print(f"     edge — hence the lower-bound test below, not the t test]")
        print()

        pays = [(k, m, se, t) for k, m, se, t in rth_pos
                if (m - z_bonf * se) > econ]
        detectable_only = [(k, m, se, t) for k, m, se, t in rth_pos
                           if m > 0 and abs(t) >= 2 and (m - z_bonf * se) <= econ]
        all_flat = all(m <= 0 or abs(t) < 2 for _, m, _, t in rth_pos)

        if pays:
            k, m, se, t = pays[0]
            print("  ✅ PREMISE SUPPORTED — and large enough to pay for itself.")
            print(f"     RTH k={k}: even the pessimistic end of the interval "
                  f"({m - z_bonf * se:+.4f} ATR)")
            print(f"     clears the ~{econ} ATR needed to cover friction. The entry")
            print("     carries real, economically usable signal. Build on this.")
        elif detectable_only:
            k, m, se, t = detectable_only[0]
            lo = m - z_bonf * se
            if lo > 0:
                # Survives multiplicity: the effect is real, just not payable.
                print("  ⚠ REAL BUT TOO SMALL TO PAY — this is NOT a green light.")
                print(f"     RTH k={k}: t={t:+.2f} and the corrected lower bound {lo:+.4f}")
                print(f"     is above zero, so the effect is probably real — but it is")
                print(f"     below the ~{econ} ATR needed to cover commission and slippage.")
                print("     A statistically real edge that cannot fund itself is not a")
                print("     business.")
            else:
                # Reaches t=2 only before correcting for the pre-registered
                # horizons. This is the shape a pure random walk produces.
                print("  ⚠ NOT ESTABLISHED — reaches t>=2 only before correction.")
                print(f"     RTH k={k}: t={t:+.2f} looks significant on its own, but across")
                print(f"     the {len(rth_pos)} pre-registered horizons the corrected lower bound is")
                print(f"     {lo:+.4f} ATR — the interval still contains ZERO. One horizon at")
                print("     t~2 out of several is what noise looks like; a driftless random")
                print("     walk reproduces this readily.")
            print("     Under the ORIGINAL t>=2 rule this printed")
            print("     'PREMISE SUPPORTED — build on this'. It should not have.")
        elif all_flat:
            print("  ❌ NO LARGE EDGE DETECTED at any horizon in RTH.")
            print(f"     Read this correctly: the test can only resolve effects above")
            print(f"     ~{mde:.3f} ATR, and the economically required effect is ~0.018 ATR —")
            print("     about 4x smaller. So this does NOT prove the premise false; it")
            print("     rules out a LARGE edge and leaves a small one unmeasured.")
            print()
            print("     However, combine it with what is already known: the live 2R win")
            print("     rate is 31.0% against a driftless-walk baseline of 33.3%. The")
            print("     strategy performs BELOW no-edge. Continuing to filter and tune")
            print("     this entry on 60 days of data is not a good use of the budget.")
            print("     The honest moves are: buy more history, or change the design.")
        else:
            print("  ⚠ AMBIGUOUS — directionally positive but below the significance")
            print("     bar. Treat as NOT supported. Do not build on it.")
    print(BAR)


if __name__ == "__main__":
    main()
