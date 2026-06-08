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
    parser.add_argument("--entry-mode", default="icc", choices=["icc", "breakout"], help="ORB entry model (default: icc)")
    parser.add_argument("--no-trend", action="store_true", help="Disable the ADX/EMA/VWAP regime filter")
    parser.add_argument("--no-breakeven", action="store_true", help="Disable move-stop-to-breakeven at +1R")
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
    if args.no_trend:
        strategy.require_trend = False
        strategy.use_ema_filter = False
        strategy.use_vwap_filter = False
    use_breakeven = not args.no_breakeven

    point_value_map = {"MES": 5.0, "MNQ": 2.0, "MGC": 10.0}
    point_value = point_value_map.get(symbol.upper(), 5.0)

    n = len(df)
    trades = []
    daily_pnl: dict = defaultdict(float)
    equity = args.account
    equity_curve = []

    taken_today: dict = defaultdict(set)   # date -> {"long","short"} already traded
    LOOKAHEAD = 78  # ~ rest of a session in 5m bars (6.5h = 78 bars)

    print(f"\n  Simulating ORB across {n} bars ...")

    for i in range(20, n - 1):
        ts = df.index[i]
        date_str = str(ts.date()) if hasattr(ts, "date") else str(i)

        if daily_pnl[date_str] <= -args.daily_loss_limit:
            continue
        if daily_pnl[date_str] >= args.daily_target:
            continue

        sub = df.iloc[max(0, i - 120):i + 1]
        signal = strategy.generate_signal(sub, symbol)
        if signal is None:
            continue

        direction = signal["direction"]
        if direction in taken_today[date_str]:
            continue  # already took this side today

        entry = signal["entry_price"]
        stop = signal["stop_loss"]
        target = signal["target_1"]
        taken_today[date_str].add(direction)

        risk = abs(entry - stop)
        be_level = entry + risk if direction == "long" else entry - risk  # +1R
        moved_to_be = False

        # Simulate outcome over the remainder of the session
        outcome = "timeout"
        exit_price = float(df.iloc[min(i + LOOKAHEAD, n - 1)]["close"])
        for j in range(1, LOOKAHEAD + 1):
            idx = i + j
            if idx >= n:
                break
            # stop if we cross into the next day
            if hasattr(df.index[idx], "date") and df.index[idx].date() != ts.date():
                exit_price = float(df.iloc[idx - 1]["close"])
                break
            fhigh = float(df.iloc[idx]["high"])
            flow = float(df.iloc[idx]["low"])
            if direction == "long":
                # Move stop to breakeven once +1R is reached
                if use_breakeven and not moved_to_be and fhigh >= be_level:
                    stop = entry
                    moved_to_be = True
                if fhigh >= target:
                    outcome, exit_price = "win", target; break
                if flow <= stop:
                    outcome = "breakeven" if moved_to_be else "loss"
                    exit_price = stop; break
            else:
                if use_breakeven and not moved_to_be and flow <= be_level:
                    stop = entry
                    moved_to_be = True
                if flow <= target:
                    outcome, exit_price = "win", target; break
                if fhigh >= stop:
                    outcome = "breakeven" if moved_to_be else "loss"
                    exit_price = stop; break

        if direction == "long":
            pnl = (exit_price - entry) * point_value
        else:
            pnl = (entry - exit_price) * point_value
        pnl -= 2.0  # commission

        equity += pnl
        daily_pnl[date_str] += pnl

        trades.append({
            "date": date_str, "bar": i, "direction": direction,
            "confidence": signal["confidence"], "entry": entry, "exit": exit_price,
            "stop": stop, "target": target, "rr": signal["risk_reward_ratio"],
            "outcome": outcome, "pnl": round(pnl, 2), "equity": round(equity, 2),
        })
        equity_curve.append({"date": date_str, "equity": equity})

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
