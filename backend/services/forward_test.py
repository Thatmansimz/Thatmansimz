"""
Forward-test campaign tracker.

The point of the 60-day live paper run is an AUDITED track record: a start
date that never moves, a daily equity snapshot the scheduler writes every
cycle, and an uptime heartbeat that makes gaps visible instead of silently
forgotten. Campaign metadata lives in data/forward_test.json; the equity
curve lives in the equity_snapshots table.
"""
from __future__ import annotations

import json
import os
import logging
from datetime import date, datetime

import pytz
from backend.models.trade import Trade, DailyStats, EquitySnapshot
from backend.services.execution import trading_day
from backend.clock import utc_now, uptime_pct

ET = pytz.timezone("America/New_York")

logger = logging.getLogger(__name__)

META_PATH = os.path.join("data", "forward_test.json")


def get_campaign() -> dict | None:
    try:
        with open(META_PATH) as f:
            meta = json.load(f)
        if "start_date" not in meta:
            return None
        return meta
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def begin_campaign(target_days: int, strategy: str, symbols: list[str],
                   start_equity: float) -> dict:
    meta = {
        "start_date": trading_day().isoformat(),
        "target_days": int(target_days),
        "strategy": strategy,
        "symbols": symbols,
        "start_equity": float(start_equity),
        "created_at": utc_now().isoformat(),
    }
    os.makedirs(os.path.dirname(META_PATH), exist_ok=True)
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Forward-test campaign started: %d days, strategy=%s, symbols=%s",
                target_days, strategy, symbols)
    return meta


def record_snapshot(db, balance: float, equity: float, unrealized: float):
    """Upsert today's equity snapshot and bump the cycle heartbeat."""
    today = trading_day()
    snap = db.query(EquitySnapshot).filter(EquitySnapshot.date == today).first()
    if not snap:
        snap = EquitySnapshot(date=today, cycles=0)
        db.add(snap)
    snap.balance = balance
    snap.equity = equity
    snap.unrealized_pnl = unrealized
    snap.cycles = (snap.cycles or 0) + 1
    db.commit()


def campaign_status(db) -> dict:
    meta = get_campaign()
    if not meta:
        return {"active": False}

    start = date.fromisoformat(meta["start_date"])
    today = trading_day()
    day_number = (today - start).days + 1  # day 1 on the start date
    target = meta.get("target_days", 60)

    snaps = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.date >= start)
        .order_by(EquitySnapshot.date.asc())
        .all()
    )
    today_snap = next((s for s in snaps if s.date == today), None)

    start_equity = meta.get("start_equity", 50000.0)
    current_equity = snaps[-1].equity if snaps else start_equity

    closed = (
        db.query(Trade)
        .filter(Trade.trade_date >= start, Trade.status != "open",
                Trade.exit_time.isnot(None))
        .all()
    )
    wins = sum(1 for t in closed if (t.net_pnl or 0) > 0)
    losses = sum(1 for t in closed if (t.net_pnl or 0) <= 0)
    total_pnl = sum((t.net_pnl or 0) for t in closed)

    # ONE uptime formula for the whole system, shared with
    # EquitySnapshot.to_dict(). These were two separate implementations —
    # this one measured today against minutes elapsed (correct), the model's
    # divided by a hardcoded 1440 (wrong for today) — so this endpoint used to
    # report the SAME day's uptime as both 100% and 3% in a single response.
    uptime_today = uptime_pct(today_snap.cycles, today) if today_snap else 0.0

    # The engine runs on ET; the operator does not necessarily. State both, so
    # "why does it say day 10 when my wall clock says the 5th?" is answerable
    # from the payload instead of being mistaken for a bug.
    local_today = datetime.now().date()

    return {
        "active": True,
        "start_date": meta["start_date"],
        "strategy": meta.get("strategy"),
        "symbols": meta.get("symbols"),
        "day": max(1, day_number),
        # day_number is a 1-based INDEX (day 1 on the start date), not a count
        # of days that have passed. Both are published because they differ by
        # one and the difference has already been read as an off-by-one bug.
        "days_elapsed": max(0, (today - start).days),
        "exchange_date": today.isoformat(),
        "host_local_date": local_today.isoformat(),
        "day_boundary_note": (
            "Campaign days are keyed to the exchange clock (America/New_York). "
            f"It is {today.isoformat()} in ET and {local_today.isoformat()} "
            "on this host."
        ) if local_today != today else None,
        "target_days": target,
        "days_remaining": max(0, target - day_number),
        "pct_complete": round(min(100.0, day_number / target * 100.0), 1),
        "start_equity": start_equity,
        "current_equity": current_equity,
        "total_pnl": round(total_pnl, 2),
        "trades_closed": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": round(100.0 * wins / len(closed), 1) if closed else 0.0,
        "uptime_today_pct": uptime_today,
        "snapshots": [s.to_dict() for s in snaps],
    }
