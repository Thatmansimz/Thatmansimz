#!/usr/bin/env python3
"""
Backtest Engine
Simulates the full AI trading strategy on historical data and reports:
  - Per-day P&L
  - Win rate, profit factor, max drawdown
  - Sharpe ratio
  - Whether the $1000/day target is achievable

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --symbol MES --period 30d --account 50000
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("backtest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Trading Strategy Backtest")
    parser.add_argument("--symbol", default="MES", help="Symbol to backtest (default: MES)")
    parser.add_argument("--period", default="30d", help="Historical period (default: 30d)")
    parser.add_argument("--interval", default="5m", help="Bar interval (default: 5m)")
    parser.add_argument("--account", type=float, default=50000.0, help="Starting account balance")
    parser.add_argument("--threshold", type=float, default=0.65, help="AI confidence threshold")
    parser.add_argument("--max-stop", type=float, default=250.0, help="Max stop loss per trade ($)")
    parser.add_argument("--daily-target", type=float, default=1000.0, help="Daily profit target ($)")
    parser.add_argument("--daily-loss-limit", type=float, default=2000.0, help="Daily loss limit ($)")
    parser.add_argument("--train-split", type=float, default=0.4, help="Fraction used for training (default: 0.4)")
    parser.add_argument("--strategy", default="orb", choices=["orb", "ml"], help="Strategy to backtest (default: orb)")
    parser.add_argument("--entry-mode", default="breakout", choices=["icc", "breakout"], help="ORB entry model (default: breakout)")
    parser.add_argument("--no-trend", action="store_true", help="Disable the ADX/EMA/VWAP regime filter")
    parser.add_argument("--no-breakeven", action="store_true", help="Disable move-stop-to-breakeven at +1R")
    parser.add_argument("--no-news", action="store_true", help="Disable the red-folder news blackout filter")
    parser.add_argument("--target-r", type=float, default=1.0, help="Target as a multiple of risk (default: 1.0)")
    # ── Frequency levers ──
    parser.add_argument("--max-trades-day", type=int, default=2, help="Max trades per day (default: 2)")
    parser.add_argument("--allow-reentry", action="store_true", help="Allow multiple same-side breakouts per day")
    parser.add_argument("--min-gap", type=int, default=1, help="Min bars between entries (default: 1)")
    parser.add_argument("--or-minutes", type=int, default=5, help="Opening range length in minutes (default: 5)")
    parser.add_argument("--cutoff", default="14:00", help="Latest entry time ET, HH:MM (default: 14:00)")
    # ── Position sizing ──
    parser.add_argument("--contracts", type=int, default=1, help="Fixed contracts per trade (default: 1)")
    parser.add_argument("--size-to-budget", action="store_true", help="Auto-size contracts to use the full risk budget per trade")
    parser.add_argument("--risk-per-trade", type=float, default=None, help="$ risk budget per trade for sizing (default: --max-stop)")
    # ── V2 overlay ──
    parser.add_argument("--v2-filter", action="store_true",
                        help="Layer the V2 two-indications filter on top of the ORB signal "
                             "(HA flat-candle velocity break + total-engulfing confirmation)")
    return parser.parse_args()


def print_separator(char="─", width=70):
    print(char * width)


def print_header(title: str, width=70):
    print("\n" + "═" * width)
    print(f"  {title}")
    print("═" * width)


def run_backtest(
    symbol: str,
    df: pd.DataFrame,
    ai_engine,
    args: argparse.Namespace,
) -> dict:
    """
    Walk-forward backtest:
      • First train_split of data is used to train the model
      • Remainder is tested bar by bar
      • Each signal triggers a simulated trade checked over next N bars
    """
    from backend.services.market_data import MarketDataService

    point_value_map = {"MES": 5.0, "MNQ": 2.0, "MGC": 10.0}
    point_value = point_value_map.get(symbol.upper(), 5.0)

    n = len(df)
    split = int(n * args.train_split)

    # Train on first portion
    print(f"\n  Training on first {split} bars ({args.train_split*100:.0f}%) ...")
    train_df = df.iloc[:split]
    metrics = ai_engine.train(train_df, symbol)
    if not metrics:
        return {"error": "Training failed"}

    print(f"  Testing on remaining {n - split} bars ...")

    trades = []
    in_trade = False
    trade_entry = trade_stop = trade_target = trade_direction = None
    daily_pnl: dict[str, float] = defaultdict(float)
    equity = args.account
    equity_curve = []

    LOOKAHEAD = 12  # bars to check for stop/target
    MIN_BARS_BETWEEN_SIGNALS = 3
    last_signal_bar = -999

    for i in range(split, n - LOOKAHEAD):
        bar = df.iloc[i]
        date_str = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(i)

        # Don't enter if we're still in a trade
        if in_trade:
            continue

        # Throttle: don't fire a signal within 3 bars of the last one
        if i - last_signal_bar < MIN_BARS_BETWEEN_SIGNALS:
            continue

        # Daily loss limit
        if daily_pnl[date_str] <= -args.daily_loss_limit:
            continue

        # Daily profit target
        if daily_pnl[date_str] >= args.daily_target:
            continue

        # Get prediction on slice up to current bar
        sub = df.iloc[max(0, i - 200):i + 1]
        pred = ai_engine.predict(sub, symbol)

        if pred["direction"] == "neutral" or pred["confidence"] < args.threshold:
            continue

        close = float(bar["close"])
        atr = float(bar.get("atr", close * 0.002))

        if pred["direction"] == "long":
            entry = close
            stop = entry - atr * 1.5
            target = entry + atr * 3.0
        else:
            entry = close
            stop = entry + atr * 1.5
            target = entry - atr * 3.0

        stop_dist = abs(entry - stop)
        risk_dollars = stop_dist * point_value

        if risk_dollars > args.max_stop:
            continue

        rr = abs(target - entry) / stop_dist if stop_dist > 0 else 0
        if rr < 2.0:
            continue

        # Simulate trade outcome over next LOOKAHEAD bars
        outcome = "timeout"
        exit_price = float(df.iloc[i + LOOKAHEAD]["close"])
        for j in range(1, LOOKAHEAD + 1):
            idx = i + j
            if idx >= n:
                break
            future_high = float(df.iloc[idx]["high"])
            future_low = float(df.iloc[idx]["low"])

            if pred["direction"] == "long":
                if future_high >= target:
                    outcome = "win"
                    exit_price = target
                    break
                if future_low <= stop:
                    outcome = "loss"
                    exit_price = stop
                    break
            else:
                if future_low <= target:
                    outcome = "win"
                    exit_price = target
                    break
                if future_high >= stop:
                    outcome = "loss"
                    exit_price = stop
                    break

        if pred["direction"] == "long":
            pnl = (exit_price - entry) * point_value
        else:
            pnl = (entry - exit_price) * point_value

        pnl -= 2.0  # commission estimate per contract

        equity += pnl
        daily_pnl[date_str] += pnl
        last_signal_bar = i

        trades.append({
            "date": date_str,
            "bar": i,
            "direction": pred["direction"],
            "confidence": pred["confidence"],
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "target": target,
            "rr": round(rr, 2),
            "outcome": outcome,
            "pnl": round(pnl, 2),
            "equity": round(equity, 2),
        })

        equity_curve.append({"date": date_str, "equity": equity})

    return {
        "symbol": symbol,
        "period": args.period,
        "bars_total": n,
        "bars_trained": split,
        "bars_tested": n - split,
        "trades": trades,
        "daily_pnl": dict(daily_pnl),
        "final_equity": equity,
        "starting_equity": args.account,
        "equity_curve": equity_curve,
    }


def _v2_two_indications(sub: pd.DataFrame, direction: str) -> bool:
    """
    Returns True only if the business-partner V2 two-indications filter passes
    on the two most recent bars of `sub`.

    Indication 1 (bar n-1, prior bar):
      • Heikin Ashi candle is a STRONG candle in the signal direction:
          Long  → flat bottom (no lower shadow) and HA close above VWAP and EMA-12
          Short → flat top    (no upper shadow) and HA close below VWAP and EMA-12

    Indication 2 (bar n, current bar):
      • Current bar TOTALLY ENGULFS the prior bar:
          c_high > p_high  AND  c_low < p_low
      • Closes in the direction of the bias:
          Long  → close > open
          Short → close < open
    """
    if len(sub) < 3:
        return False

    # ── Heikin Ashi for the full slice (path-dependent) ──
    o = sub["open"].to_numpy(dtype=float)
    h = sub["high"].to_numpy(dtype=float)
    l = sub["low"].to_numpy(dtype=float)
    c = sub["close"].to_numpy(dtype=float)
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.empty(len(sub))
    ha_o[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(sub)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2.0
    ha_h = np.maximum.reduce([h, ha_o, ha_c])
    ha_l = np.minimum.reduce([l, ha_o, ha_c])

    # indicators on the full slice
    ema12 = sub["close"].ewm(span=12, adjust=False).mean()
    typical = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    vol = sub["volume"].replace(0, np.nan)
    vwap_series = (typical * sub["volume"]).cumsum() / vol.cumsum()
    vwap = float(vwap_series.iloc[-2])
    ema12_prev = float(ema12.iloc[-2])

    # bar n-1 HA values
    ha_o_prev = ha_o[-2]; ha_h_prev = ha_h[-2]
    ha_l_prev = ha_l[-2]; ha_c_prev = ha_c[-2]

    # shadow tolerance: 8% of a 14-bar ATR (or 1 tick minimum)
    recent = sub.tail(14)
    tr_series = pd.concat([
        recent["high"] - recent["low"],
        (recent["high"] - recent["close"].shift(1)).abs(),
        (recent["low"]  - recent["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_pts = float(tr_series.mean()) if not tr_series.empty else 1.0
    tol = max(atr_pts * 0.08, 0.25)

    # ── Indication 1 ──
    if direction == "long":
        flat_bottom = (ha_c_prev > ha_o_prev) and (min(ha_o_prev, ha_c_prev) - ha_l_prev <= tol)
        ind1 = flat_bottom and (ha_c_prev > vwap) and (ha_c_prev > ema12_prev)
    else:
        flat_top = (ha_c_prev < ha_o_prev) and (ha_h_prev - max(ha_o_prev, ha_c_prev) <= tol)
        ind1 = flat_top and (ha_c_prev < vwap) and (ha_c_prev < ema12_prev)

    if not ind1:
        return False

    # ── Indication 2 ──
    p_hi = float(sub["high"].iloc[-2]);  p_lo = float(sub["low"].iloc[-2])
    c_hi = float(sub["high"].iloc[-1]);  c_lo = float(sub["low"].iloc[-1])
    c_op = float(sub["open"].iloc[-1]);  c_cl = float(sub["close"].iloc[-1])

    total_engulf = (c_hi > p_hi) and (c_lo < p_lo)
    directional  = (c_cl > c_op) if direction == "long" else (c_cl < c_op)

    return total_engulf and directional


def run_orb_backtest(
    symbol: str,
    df: pd.DataFrame,
    args: argparse.Namespace,
) -> dict:
    """
    Bar-by-bar ORB backtest. No training needed (rule-based).
    Walks the full dataset, calls ORBStrategy.generate_signal on each rolling
    slice, then simulates the trade outcome over the rest of that session.
    Enforces: one trade per side per day, daily loss limit, daily profit target.
    """
    from backend.strategies.orb import ORBStrategy

    strategy = ORBStrategy(config=None)
    strategy.max_stop_dollars = args.max_stop
    strategy.entry_mode = args.entry_mode
    strategy.target_r_multiple = args.target_r
    # The min-R:R validation gate must not exceed the target we're testing,
    # otherwise every signal is rejected for "insufficient reward".
    strategy.min_rr = min(strategy.min_rr, args.target_r)
    # Frequency knobs
    strategy.or_minutes = args.or_minutes
    try:
        _h, _m = args.cutoff.split(":")
        from datetime import time as _dtime
        strategy.entry_cutoff = _dtime(int(_h), int(_m))
    except Exception:
        pass
    if args.no_trend:
        strategy.require_trend = False
        strategy.use_ema_filter = False
        strategy.use_vwap_filter = False
    if args.no_news:
        strategy.news_filter.enabled = False
    use_breakeven = not args.no_breakeven

    n_signals = 0

    point_value_map = {"MES": 5.0, "MNQ": 2.0, "MGC": 10.0}
    point_value = point_value_map.get(symbol.upper(), 5.0)

    n = len(df)
    trades = []
    daily_pnl: dict = defaultdict(float)
    equity = args.account
    equity_curve = []

    taken_today: dict = defaultdict(set)   # date -> {"long","short"} already traded
    trades_today: dict = defaultdict(int)  # date -> count of trades taken
    last_entry_bar = -10 ** 9
    busy_until = -1                          # no new entry while a trade is open
    LOOKAHEAD = 78  # ~ rest of a session in 5m bars (6.5h = 78 bars)

    print(f"\n  Simulating ORB across {n} bars ...")

    for i in range(20, n - 1):
        ts = df.index[i]
        date_str = str(ts.date()) if hasattr(ts, "date") else str(i)

        if daily_pnl[date_str] <= -args.daily_loss_limit:
            continue
        if daily_pnl[date_str] >= args.daily_target:
            continue
        if i <= busy_until:
            continue  # a position is still open — no overlapping trades
        if trades_today[date_str] >= args.max_trades_day:
            continue
        if i - last_entry_bar < args.min_gap:
            continue

        sub = df.iloc[max(0, i - 120):i + 1]
        signal = strategy.generate_signal(sub, symbol)
        if signal is None:
            continue
        n_signals += 1

        direction = signal["direction"]
        # Per-side cap unless re-entry is explicitly allowed
        if not args.allow_reentry and direction in taken_today[date_str]:
            continue

        # Optional V2 two-indications overlay (--v2-filter)
        if getattr(args, "v2_filter", False):
            if not _v2_two_indications(sub, direction):
                continue

        entry = signal["entry_price"]
        stop = signal["stop_loss"]
        target = signal["target_1"]
        taken_today[date_str].add(direction)

        # Position sizing — how many contracts for this trade
        per_contract_risk = abs(entry - stop) * point_value
        if args.size_to_budget and per_contract_risk > 0:
            budget = args.risk_per_trade if args.risk_per_trade else args.max_stop
            contracts = max(1, int(budget / per_contract_risk))
        else:
            contracts = max(1, args.contracts)

        risk = abs(entry - stop)
        be_level = entry + risk if direction == "long" else entry - risk  # +1R
        moved_to_be = False

        # Simulate outcome over the remainder of the session
        outcome = "timeout"
        exit_bar = min(i + LOOKAHEAD, n - 1)
        exit_price = float(df.iloc[exit_bar]["close"])
        for j in range(1, LOOKAHEAD + 1):
            idx = i + j
            if idx >= n:
                exit_bar = n - 1
                break
            # stop if we cross into the next day
            if hasattr(df.index[idx], "date") and df.index[idx].date() != ts.date():
                exit_price = float(df.iloc[idx - 1]["close"])
                exit_bar = idx - 1
                break
            fhigh = float(df.iloc[idx]["high"])
            flow = float(df.iloc[idx]["low"])
            if direction == "long":
                # Move stop to breakeven once +1R is reached
                if use_breakeven and not moved_to_be and fhigh >= be_level:
                    stop = entry
                    moved_to_be = True
                if fhigh >= target:
                    outcome, exit_price, exit_bar = "win", target, idx; break
                if flow <= stop:
                    outcome = "breakeven" if moved_to_be else "loss"
                    exit_price, exit_bar = stop, idx; break
            else:
                if use_breakeven and not moved_to_be and flow <= be_level:
                    stop = entry
                    moved_to_be = True
                if flow <= target:
                    outcome, exit_price, exit_bar = "win", target, idx; break
                if fhigh >= stop:
                    outcome = "breakeven" if moved_to_be else "loss"
                    exit_price, exit_bar = stop, idx; break

        if direction == "long":
            pnl = (exit_price - entry) * point_value * contracts
        else:
            pnl = (entry - exit_price) * point_value * contracts
        pnl -= 2.0 * contracts  # commission scales with size

        equity += pnl
        daily_pnl[date_str] += pnl
        trades_today[date_str] += 1
        last_entry_bar = i
        busy_until = exit_bar

        trades.append({
            "date": date_str, "bar": i, "direction": direction,
            "confidence": signal["confidence"], "entry": entry, "exit": exit_price,
            "stop": stop, "target": target, "rr": signal["risk_reward_ratio"],
            "contracts": contracts,
            "outcome": outcome, "pnl": round(pnl, 2), "equity": round(equity, 2),
        })
        equity_curve.append({"date": date_str, "equity": equity})

    if trades:
        avg_contracts = sum(t["contracts"] for t in trades) / len(trades)
        print(f"  Signals fired: {n_signals} | Trades taken: {len(trades)} | Avg contracts: {avg_contracts:.1f}")
    else:
        print(f"  Signals fired: {n_signals} | Trades taken: {len(trades)}")

    if n_signals == 0:
        print_header("DIAGNOSTIC — why zero signals?")
        diag = strategy.diagnose(df, symbol)
        for k, v in diag.items():
            print(f"  {k:<26}: {v}")
        print()
        print("  Read this as: index_tz tells us the data timezone. If")
        print("  bars_in_entry_window is 0, the 09:45-12:00 ET window isn't")
        print("  matching the data (timezone issue). If raw_breakouts_in_window")
        print("  is 0, the opening range never gets crossed. Either way we fix it.")

    return {
        "symbol": symbol, "period": args.period, "bars_total": n,
        "bars_trained": 0, "bars_tested": n,
        "trades": trades, "daily_pnl": dict(daily_pnl),
        "final_equity": equity, "starting_equity": args.account,
        "equity_curve": equity_curve,
    }


def compute_stats(result: dict, account: float) -> dict:
    trades = result["trades"]
    if not trades:
        return {"error": "No trades generated"}

    daily_pnl = result["daily_pnl"]
    daily_vals = list(daily_pnl.values())
    equity_curve = [e["equity"] for e in result["equity_curve"]]

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    breakevens = [t for t in trades if t["outcome"] == "breakeven"]

    total_pnl = sum(t["pnl"] for t in trades)
    gross_wins = sum(t["pnl"] for t in wins) if wins else 0
    gross_losses = abs(sum(t["pnl"] for t in losses)) if losses else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    avg_win = gross_wins / len(wins) if wins else 0
    avg_loss = -(gross_losses / len(losses)) if losses else 0

    # Drawdown
    peak = account
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (annualised daily returns)
    if len(daily_vals) > 1:
        daily_arr = np.array(daily_vals)
        mean_daily = daily_arr.mean()
        std_daily = daily_arr.std()
        sharpe = (mean_daily / std_daily * np.sqrt(252)) if std_daily > 0 else 0.0
    else:
        sharpe = 0.0

    trading_days = len(daily_pnl)
    avg_daily = total_pnl / trading_days if trading_days > 0 else 0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": len(timeouts),
        "breakevens": len(breakevens),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "gross_wins": round(gross_wins, 2),
        "gross_losses": round(gross_losses, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "trading_days": trading_days,
        "avg_daily_pnl": round(avg_daily, 2),
        "final_equity": round(result["final_equity"], 2),
        "return_pct": round((result["final_equity"] - account) / account * 100, 2),
    }


def print_daily_table(daily_pnl: dict, daily_target: float, loss_limit: float):
    print_separator()
    print(f"  {'Date':<12} {'P&L':>10} {'Status':<15}")
    print_separator("─")
    for date_str in sorted(daily_pnl.keys()):
        pnl = daily_pnl[date_str]
        if pnl >= daily_target:
            status = "TARGET HIT"
        elif pnl <= -loss_limit:
            status = "LIMIT BREACHED"
        elif pnl > 0:
            status = "Profitable"
        else:
            status = "Loss day"
        sign = "+" if pnl >= 0 else ""
        print(f"  {date_str:<12} {sign}${pnl:>8.2f}  {status}")
    print_separator()


def main():
    args = parse_args()

    print_header(f"Tajari Backtest — {args.symbol} [{args.strategy.upper()}]")
    print(f"  Strategy : {args.strategy.upper()}")
    print(f"  Account  : ${args.account:,.0f}")
    print(f"  Period   : {args.period} @ {args.interval}")
    if args.strategy == "ml":
        print(f"  AI conf  : >{args.threshold}")
    print(f"  Max stop : ${args.max_stop:.0f}")
    print(f"  Daily tgt: ${args.daily_target:,.0f}")
    print(f"  Daily lim: ${args.daily_loss_limit:,.0f}")
    if getattr(args, "v2_filter", False):
        print(f"  V2 filter: ON  (HA flat-candle + total-engulf gate)")

    from backend.services.market_data import MarketDataService

    md = MarketDataService()

    print(f"\n  Downloading {args.symbol} data ...")
    df = md.get_historical(args.symbol, period=args.period, interval=args.interval)
    if df.empty:
        print("  ERROR: No data available.")
        sys.exit(1)

    print(f"  Computing indicators on {len(df)} bars ...")
    df = md.add_indicators(df)
    print(f"  Ready: {len(df)} bars with {df.shape[1]} columns")

    if args.strategy == "orb":
        result = run_orb_backtest(args.symbol, df, args)
    else:
        from backend.services.ai_engine import AIEngine
        engine = AIEngine(confidence_threshold=args.threshold)
        result = run_backtest(args.symbol, df, engine, args)

    if "error" in result:
        print(f"\n  Error: {result['error']}")
        sys.exit(1)

    stats = compute_stats(result, args.account)

    if "error" in stats:
        print_header("Backtest Results")
        print(f"  {stats['error']} — see the DIAGNOSTIC block above.")
        sys.exit(0)

    print_header("Backtest Results")
    print(f"  Total trades   : {stats['total_trades']}")
    print(f"  Wins           : {stats['wins']}")
    print(f"  Losses         : {stats['losses']}")
    print(f"  Breakevens     : {stats.get('breakevens', 0)}")
    print(f"  Timeouts       : {stats['timeouts']}")
    print(f"  Win rate       : {stats['win_rate_pct']:.1f}%")
    print_separator()
    print(f"  Total P&L      : ${stats['total_pnl']:+,.2f}")
    print(f"  Avg win        : ${stats['avg_win']:+,.2f}")
    print(f"  Avg loss       : ${stats['avg_loss']:+,.2f}")
    print(f"  Profit factor  : {stats['profit_factor']:.2f}x")
    print(f"  Max drawdown   : ${stats['max_drawdown']:,.2f}")
    print(f"  Sharpe ratio   : {stats['sharpe_ratio']:.3f}")
    print_separator()
    print(f"  Trading days   : {stats['trading_days']}")
    print(f"  Avg daily P&L  : ${stats['avg_daily_pnl']:+,.2f}")
    print(f"  Final equity   : ${stats['final_equity']:,.2f}")
    print(f"  Return         : {stats['return_pct']:+.2f}%")

    # Daily breakdown
    if result["daily_pnl"]:
        print_header("Daily P&L Breakdown")
        print_daily_table(result["daily_pnl"], args.daily_target, args.daily_loss_limit)

    # Feasibility assessment
    print_header("$1,000/Day Target Assessment")
    avg = stats["avg_daily_pnl"]
    if avg >= args.daily_target:
        verdict = "ACHIEVABLE — average daily P&L exceeds the $1,000 target."
    elif avg >= args.daily_target * 0.5:
        verdict = "POSSIBLE — average daily P&L is within range of the target but needs improvement."
    else:
        verdict = "CHALLENGING — average daily P&L is below 50% of the target. Consider re-tuning."

    print(f"  Daily target   : ${args.daily_target:,.0f}")
    print(f"  Achieved avg   : ${avg:+,.2f}/day")
    print(f"  Verdict        : {verdict}")
    print()


if __name__ == "__main__":
    main()
