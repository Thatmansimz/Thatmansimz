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
        "created_at": datetime.utcnow().isoformat(),
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

    # Uptime for TODAY must be measured against minutes elapsed so far, not
    # the full 1440-minute day — otherwise a perfectly healthy engine reads
    # "15%" at 4 AM and slowly climbs, which reads as an outage when it isn't.
    now = datetime.now(ET)
    minutes_elapsed = max(1, now.hour * 60 + now.minute)
    uptime_today = 0.0
    if today_snap:
        uptime_today = round(min(100.0, (today_snap.cycles or 0) / minutes_elapsed * 100.0), 1)

    return {
        "active": True,
        "start_date": meta["start_date"],
        "strategy": meta.get("strategy"),
        "symbols": meta.get("symbols"),
        "day": max(1, day_number),
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
