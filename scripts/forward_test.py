#!/usr/bin/env python3
"""
Paper Forward-Test Mode
=======================

Replays the VALIDATED V1 ORB edge (Config 3: 5-min OR, 14:00 cutoff, 6
trades/day, re-entry, news filter on) over recent market data and records every
resulting trade into the live trades database AS PAPER TRADES.

The dashboard reads from that same database, so the moment this finishes the
Trade Insights panel, Win/Loss card, P&L chart and stats all light up with real
strategy-generated data — no waiting weeks for live fills to trickle in.

This is Stage 1 of the plan: prove the edge holds on a body of trades, with
zero money at risk, before anything goes live.

Usage:
    python3 scripts/forward_test.py                       # MNQ + NQ, last 30d
    python3 scripts/forward_test.py --symbols MNQ NQ MES --period 60d
    python3 scripts/forward_test.py --reset               # wipe prior paper run first
    python3 scripts/forward_test.py --reset-only          # just clear, don't run

Notes:
  • Needs Yahoo Finance access — run it on your Mac, not the cloud sandbox.
  • Trades are tagged strategy="orb_forward_test" so --reset only clears THESE,
    never any real trades you might add later.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FORWARD_TAG = "orb_forward_test"


def _naive_utc(dt):
    """Normalise a (possibly tz-aware) datetime to naive-UTC for storage."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _status_from_outcome(outcome: str) -> str:
    return {
        "win": "target_hit",
        "loss": "stopped_out",
        "breakeven": "closed",
        "timeout": "closed",
    }.get(outcome, "closed")


def build_args(symbol: str, period: str, max_stop: float, account: float) -> SimpleNamespace:
    """The validated Config 3, as a namespace run_orb_backtest understands."""
    from backend.config import settings
    return SimpleNamespace(
        symbol=symbol, period=period, interval="5m", account=account,
        strategy="orb", entry_mode="breakout", target_r=1.0,
        max_stop=max_stop, daily_target=1000.0, daily_loss_limit=2000.0,
        or_minutes=5, cutoff="14:00", max_trades_day=6, allow_reentry=True,
        min_gap=1, no_trend=True, no_news=False, no_breakeven=False,
        contracts=1, size_to_budget=True, risk_per_trade=None, v2_filter=False,
        threshold=0.65, train_split=0.4,
        # trading friction — must mirror the live engine's settings
        commission=settings.COMMISSION_PER_SIDE,
        slippage_ticks=settings.SLIPPAGE_TICKS,
    )


def reset_forward_trades(db) -> int:
    from backend.models.trade import Trade
    q = db.query(Trade).filter(Trade.strategy == FORWARD_TAG)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n


def record_trades(db, symbol: str, result: dict) -> int:
    from backend.models.trade import Trade

    written = 0
    for t in result["trades"]:
        entry_dt = _naive_utc(t.get("entry_time"))
        exit_dt = _naive_utc(t.get("exit_time"))
        trade_date = exit_dt.date() if exit_dt else (entry_dt.date() if entry_dt else None)
        pnl = float(t["pnl"])
        db.add(Trade(
            symbol=symbol,
            side=t["direction"],
            qty=int(t.get("contracts", 1)),
            entry_price=float(t["entry"]),
            exit_price=float(t["exit"]),
            stop_loss=float(t["stop"]),
            take_profit=float(t["target"]),
            status=_status_from_outcome(t["outcome"]),
            pnl=pnl,
            net_pnl=pnl,                       # commission already netted in sim
            commission=0.0,
            ai_confidence=float(t.get("confidence", 0.0)),
            strategy=FORWARD_TAG,
            entry_time=entry_dt,
            exit_time=exit_dt,
            trade_date=trade_date,
            exit_reason=t["outcome"],
        ))
        written += 1
    db.commit()
    return written


def rebuild_daily_stats(db, account: float) -> int:
    """Recompute DailyStats from all forward-test trades so the chart/today panel fill."""
    from backend.models.trade import Trade, DailyStats

    trades = db.query(Trade).filter(Trade.strategy == FORWARD_TAG).all()
    by_day: dict = defaultdict(list)
    for t in trades:
        if t.trade_date:
            by_day[t.trade_date].append(t)

    # wipe existing forward-test daily rows, then rebuild
    db.query(DailyStats).delete(synchronize_session=False)
    db.commit()

    running = account
    for day in sorted(by_day.keys()):
        day_trades = by_day[day]
        pnl = sum(t.net_pnl or 0 for t in day_trades)
        wins = sum(1 for t in day_trades if (t.net_pnl or 0) > 0)
        losses = sum(1 for t in day_trades if (t.net_pnl or 0) <= 0)
        start = running
        running += pnl
        db.add(DailyStats(
            date=day, starting_balance=start, current_balance=running,
            ending_balance=running, pnl=pnl, gross_pnl=pnl,
            trades_count=len(day_trades), wins=wins, losses=losses,
            signals_generated=len(day_trades), signals_taken=len(day_trades),
        ))
    db.commit()
    return len(by_day)


def run_forward_test(db, symbols, period="30d", account=50000.0,
                     max_stop=None, reset=True) -> dict:
    """
    Core engine — usable from the CLI and from the API. Replays the validated
    ORB edge over recent data for each symbol, records paper trades, rebuilds
    DailyStats, and returns a summary. Caller owns the db session lifecycle.
    """
    from backend.config import settings
    from scripts.backtest import run_orb_backtest, compute_stats
    from backend.services.market_data import MarketDataService

    if max_stop is None:
        max_stop = settings.MAX_STOP_LOSS_DOLLARS
    md = MarketDataService()

    cleared = reset_forward_trades(db) if reset else 0
    per_symbol, total = [], 0
    for symbol in symbols:
        df = md.get_historical(symbol, period=period, interval="5m")
        if df is None or df.empty:
            per_symbol.append({"symbol": symbol, "error": "no data"})
            continue
        df = md.add_indicators(df)
        result = run_orb_backtest(symbol, df, build_args(symbol, period, max_stop, account))
        stats = compute_stats(result, account)
        n = record_trades(db, symbol, result)
        total += n
        per_symbol.append({
            "symbol": symbol, "trades": n,
            "win_rate": None if "error" in stats else stats["win_rate_pct"],
            "profit_factor": None if "error" in stats else stats["profit_factor"],
            "total_pnl": None if "error" in stats else stats["total_pnl"],
        })
    days = rebuild_daily_stats(db, account)
    return {"recorded": total, "cleared": cleared, "trading_days": days,
            "symbols": per_symbol, "period": period, "max_stop": max_stop}


def main():
    ap = argparse.ArgumentParser(description="Paper forward-test the validated ORB edge")
    ap.add_argument("--symbols", nargs="+", default=["MNQ", "NQ"], help="Symbols (default: MNQ NQ)")
    ap.add_argument("--period", default="30d", help="Lookback period (default: 30d)")
    ap.add_argument("--account", type=float, default=50000.0, help="Starting paper balance")
    ap.add_argument("--max-stop", type=float, default=None, help="Max $ risk/trade (default: from config)")
    ap.add_argument("--reset", action="store_true", help="Clear prior forward-test trades first")
    ap.add_argument("--reset-only", action="store_true", help="Only clear forward-test trades, then exit")
    args = ap.parse_args()

    from backend.config import settings
    from backend.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()

    max_stop = args.max_stop if args.max_stop is not None else settings.MAX_STOP_LOSS_DOLLARS

    print("=" * 64)
    print("  TAJARI — Paper Forward-Test (validated V1 ORB, Config 3)")
    print("=" * 64)

    if args.reset or args.reset_only:
        cleared = reset_forward_trades(db)
        print(f"  Cleared {cleared} prior forward-test trades.")
        if args.reset_only:
            rebuild_daily_stats(db, args.account)
            db.close()
            print("  Done (reset-only).")
            return

    # main() already handled --reset above, so don't double-clear here
    summary = run_forward_test(db, args.symbols, period=args.period,
                               account=args.account, max_stop=max_stop, reset=False)
    for s in summary["symbols"]:
        if s.get("error"):
            print(f"\n  ── {s['symbol']} ── {s['error']} (run locally — sandbox blocks market data)")
        else:
            print(f"\n  ── {s['symbol']} ── recorded {s['trades']} paper trades | "
                  f"win rate {s['win_rate']:.1f}% | PF {s['profit_factor']:.2f} | "
                  f"P&L ${s['total_pnl']:+,.2f}")
    db.close()

    print("\n" + "=" * 64)
    print(f"  Wrote {summary['recorded']} paper trades across {summary['trading_days']} trading days.")
    print("  Refresh the dashboard — Trade Insights, Win/Loss and the P&L")
    print("  chart are now populated with real strategy data.")
    print("  Re-run anytime with --reset to start the sample fresh.")
    print("=" * 64)


if __name__ == "__main__":
    main()
