"""Small transactional store; hashes detect changes, not independent custody."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL,
        payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
    """)
    return db


def bind(db, spec):
    if spec.get("purpose") != "engineering_replay_only":
        raise ValueError("Only isolated engineering replay is supported")
    for key in ("initial_balance_cents", "tick_value_cents", "quantity", "max_quantity", "max_planned_risk_cents", "daily_loss_limit_cents", "drawdown_limit_cents", "stop_ticks", "latency_bars"):
        if type(spec.get(key)) is not int or spec[key] <= 0:
            raise ValueError(f"Invalid positive integer: {key}")
    for key in ("commission_per_side_cents", "slippage_ticks"):
        if type(spec.get(key)) is not int or spec[key] < 0:
            raise ValueError(f"Invalid nonnegative integer: {key}")
    if not spec["quantity"] <= spec["max_quantity"] <= 2:
        raise ValueError("Engineering exposure is capped at two contracts")
    expected = canonical(spec)
    row = db.execute("SELECT value FROM meta WHERE key='protocol'").fetchone()
    if row and row[0] != expected:
        raise ValueError("Frozen protocol differs from existing ledger")
    with db:
        db.execute("INSERT OR IGNORE INTO meta VALUES('protocol',?)", (expected,))


def record(db, kind, payload):
    last = db.execute("SELECT seq,hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
    seq, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
    encoded = canonical(payload)
    seal = digest([seq, kind, encoded, previous])
    db.execute("INSERT INTO journal VALUES(?,?,?,?,?)", (seq, kind, encoded, previous, seal))


def verify_journal(db):
    previous, seq = "0" * 64, 0
    for row in db.execute("SELECT * FROM journal ORDER BY seq"):
        seq += 1
        if row["seq"] != seq or row["previous"] != previous or row["hash"] != digest([seq, row["kind"], row["payload"], previous]):
            raise ValueError("Journal chain mismatch")
        previous = row["hash"]
    return previous
