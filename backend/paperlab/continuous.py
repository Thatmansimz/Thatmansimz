"""Durable, forward-only streaming paper service. No external order endpoint.

Provider receipts are committed before either paper ledger is advanced. A crash
can repeat an unfinished receipt, but cannot create a second order or fill.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .audit import audit
from .simulator import Simulator
from .storage import canonical, connect, digest, record, verify_journal
from .worker import Worker

NS = 1_000_000_000
ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]


def utc(ns=None):
    return datetime.fromtimestamp((ns if ns is not None else time.time_ns()) / NS, timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".writing")
    with tmp.open("w") as out:
        os.chmod(tmp, 0o600)
        out.write(canonical(value) + "\n"); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, path)


def code_hashes():
    files = sorted((ROOT / "backend/paperlab").glob("*.py"))
    files += [ROOT / "scripts/continuous_paper.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def runtime_versions():
    versions = {}
    for package in ("databento", "databento-dbn"):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: versions[package] = "not_installed"
    return {"python": sys.version, "packages": versions}


def validate_protocol(spec):
    if spec.get("purpose") != "engineering_forward_paper" or spec.get("live_order_routing") is not False:
        raise ValueError("Only registered engineering forward paper is supported")
    if spec.get("broker_adapter") != "internal_ohlcv_simulator":
        raise ValueError("No external broker order route is available")
    if spec.get("feed") != {"provider": "databento", "dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "stype_in": "continuous", "symbol": "MNQ.v.0", "replay": False}:
        raise ValueError("Unregistered feed, symbol, schema or replay setting")
    if spec.get("experiment_family") != ["baseline", "worse_costs"]:
        raise ValueError("Both predeclared scenarios must be retained")
    if spec.get("quantity") != 1 or spec.get("max_quantity") != 1 or spec.get("tick_value_cents") != 50 or spec.get("tick_size") != "0.25":
        raise ValueError("Forward paper is capped at one MNQ contract with its fixed tick value")
    for k in ("max_bar_delay_seconds", "heartbeat_timeout_seconds", "price_timeout_seconds", "report_interval_seconds"):
        if type(spec.get(k)) is not int or spec[k] <= 0:
            raise ValueError(f"Invalid protocol interval: {k}")


def register(directory, spec, *, now_ns=None, implementation=None, preflight=None):
    """Must complete before a price subscription is started; never overwrites."""
    validate_protocol(spec)
    directory = Path(directory)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", directory.name):
        raise ValueError("Run ID must contain only letters, numbers, hyphens and underscores")
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = now_ns if now_ns is not None else time.time_ns()
    manifest = {"run_id": directory.name, "registered_at": utc(started), "registered_at_ns": started,
                "protocol_sha256": digest(spec), "code_sha256": implementation if implementation is not None else code_hashes(),
                "runtime": runtime_versions(),
                "data_access": "Newly arriving live bars only; connectivity preflight is excluded from evaluation",
                "preflight": preflight or {}, "custody": "Local hashes; not independent attestation"}
    atomic_json(directory / "protocol.json", spec)
    atomic_json(directory / "registration.json", manifest)
    return manifest


class ForwardWorker(Worker):
    def _intent(self, day, kind, side, qty, bar):
        key = f"{day}/{kind}"
        existing = self.db.execute("SELECT id,state FROM intents WHERE id=? OR id LIKE ? ORDER BY rowid", (key, key+"/retry-%")).fetchall()
        if existing:
            if kind == "entry" or existing[-1]["state"] in ("pending", "accepted", "partially_filled", "filled"):
                return
            key += f"/retry-{len(existing)}"
        submitted = bar["ts"] + 60
        received = self.received_at_ns
        eligible = max(submitted + self.spec["latency_bars"] * 60, math.ceil(received / (60 * NS)) * 60)
        req = {"id": key, "kind": kind, "side": side, "qty": qty,
               "submitted_at": submitted, "decision_received_at_ns": received,
               "eligible_at": eligible, "expires_at": eligible + (180 if kind == "entry" else 1800),
               "symbol": bar["symbol"], "instrument_id": bar["instrument_id"]}
        self.db.execute("INSERT INTO intents(id,request) VALUES(?,?)", (key, canonical(req)))
        record(self.db, "intent_committed", req)


class ContinuousPaper:
    def __init__(self, directory, *, implementation=None, after_receipt=None, after_scenario=None, clock_ns=None):
        self.clock_ns = clock_ns or time.time_ns
        self.root = Path(directory)
        self.spec = json.loads((self.root / "protocol.json").read_text())
        self.registration = json.loads((self.root / "registration.json").read_text())
        validate_protocol(self.spec)
        if digest(self.spec) != self.registration["protocol_sha256"]:
            raise ValueError("Registered protocol was changed")
        if (implementation if implementation is not None else code_hashes()) != self.registration["code_sha256"]:
            raise ValueError("Implementation differs from the registered run; review required")
        if runtime_versions() != self.registration["runtime"]:
            raise ValueError("Python or Databento runtime differs from the registered run")
        self.lock = (self.root / "worker.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("Another worker owns this paper run") from None
        self.db = connect(self.root / "receipts.sqlite")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS mappings(instrument_id INTEGER, start_ns INTEGER,
            end_ns INTEGER, symbol TEXT, PRIMARY KEY(instrument_id,start_ns));
          CREATE TABLE IF NOT EXISTS receipts(ts INTEGER PRIMARY KEY, received_ns INTEGER NOT NULL,
            payload TEXT NOT NULL, disposition TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS daily_audits(day TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS opportunities(day TEXT PRIMARY KEY, eligible INTEGER, reason TEXT);
        """)
        verify_journal(self.db)
        self.after_receipt, self.after_scenario = after_receipt, after_scenario
        self.scenarios = {}
        self.last_message_ns = 0
        self.last_bar_received_ns = 0
        self.connection = "starting"
        self.last_error = None
        self.audit_results = {}
        for name in self.spec["experiment_family"]:
            s = dict(self.spec, symbol="RESOLVE_FROM_DATED_MAPPING", scenario=name)
            s.update(self.spec["stress_overrides"].get(name, {}))
            broker = Simulator(self.root / f"{name}-simulator.sqlite", s)
            worker = ForwardWorker(self.root / f"{name}-worker.sqlite", s, broker)
            worker.recover()
            self.scenarios[name] = (s, broker, worker)
        # Complete only receipts durably received before the crash; no backfill.
        for row in self.db.execute("SELECT * FROM receipts WHERE applied=0 ORDER BY ts").fetchall():
            self._apply(row)
        self.reconcile()
        with self.db:
            record(self.db, "process_started", {"at": utc(), "pid": os.getpid()})

    def close(self):
        for _, broker, worker in self.scenarios.values():
            worker.close(); broker.close()
        self.db.close()
        fcntl.flock(self.lock, fcntl.LOCK_UN); self.lock.close()

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, canonical(value)))

    def note(self, kind, payload):
        with self.db: record(self.db, kind, payload)

    def halt_day(self, reason, now_ns, *, hard=False):
        day = datetime.fromtimestamp(now_ns / NS, ET).date().isoformat()
        if hard: self.set_meta("hard_halt", reason)
        self.note("entry_halt", {"day": day, "reason": reason, "at": utc(now_ns), "hard": hard})
        for _, broker, worker in self.scenarios.values():
            worker.reconcile()
            # Materialize an unacknowledged durable intent before cancelling so
            # the two ledgers retain the same order identities after a crash.
            worker.dispatch()
            with broker.db:
                for row in broker.db.execute("SELECT id,request FROM orders WHERE state IN ('accepted','partially_filled')").fetchall():
                    if json.loads(row["request"])["kind"] == "entry":
                        broker.db.execute("UPDATE orders SET state='cancelled' WHERE id=?", (row["id"],))
                        record(broker.db, "order_cancelled", {"id": row["id"], "reason": reason})
            with worker.db:
                worker.db.execute("INSERT OR IGNORE INTO halted_days VALUES(?,?)", (day, reason))
                if hard: worker.db.execute("INSERT OR REPLACE INTO meta VALUES('risk_halted','true')")
            worker.reconcile()

    def mapping(self, instrument_id, symbol, start_ns, end_ns, received_ns):
        if not re.fullmatch(r"MNQ[HMUZ][0-9]{1,2}", symbol) or type(instrument_id) is not int or instrument_id <= 0:
            self.halt_day("invalid_contract_mapping", received_ns, hard=True)
            raise ValueError("Invalid actual MNQ contract mapping")
        start_ns = 0 if start_ns in (0, 2**64-1) else start_ns
        end_ns = 2**63-1 if end_ns == 2**64-1 else end_ns
        if end_ns <= start_ns:
            raise ValueError("Invalid mapping interval")
        with self.db:
            previous = self.db.execute("SELECT symbol FROM mappings WHERE instrument_id=? AND start_ns=?", (instrument_id, start_ns)).fetchone()
            if previous and previous[0] != symbol:
                raise ValueError("Conflicting actual contract mapping")
            self.db.execute("INSERT OR REPLACE INTO mappings VALUES(?,?,?,?)", (instrument_id, start_ns, end_ns, symbol))
            record(self.db, "symbol_mapping", {"instrument_id": instrument_id, "symbol": symbol,
                  "start_ns": start_ns, "end_ns": end_ns, "received_ns": received_ns})

    def connected(self, now_ns):
        self.connection = "connected_waiting_for_bar"
        self.last_message_ns = now_ns
        self.note("feed_connected", {"at": utc(now_ns)})

    def heartbeat(self, now_ns):
        self.last_message_ns = now_ns

    def disconnected(self, reason, now_ns):
        self.connection, self.last_error = "disconnected", reason
        self.note("feed_disconnected", {"at": utc(now_ns), "reason": reason})
        self.halt_day("feed_disconnected", now_ns)

    def receive(self, bar, received_ns):
        """Only complete minute bars; all input integers are in ticks/UTC seconds."""
        self.last_message_ns = received_ns
        if not all(type(bar.get(k)) is int for k in ("ts", "open", "high", "low", "close", "volume", "instrument_id")) or bar["ts"] % 60:
            self.halt_day("invalid_bar", received_ns, hard=True)
            raise ValueError("Invalid integer minute bar")
        if bar["volume"] < 0 or min(bar[k] for k in ("open", "high", "low", "close")) <= 0 or bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
            self.halt_day("invalid_ohlcv", received_ns, hard=True)
            raise ValueError("Invalid OHLCV range")
        rows = self.db.execute("SELECT symbol FROM mappings WHERE instrument_id=? AND start_ns<=? AND end_ns>?", (bar["instrument_id"], bar["ts"]*NS, bar["ts"]*NS)).fetchall()
        symbols = {r[0] for r in rows}
        if len(symbols) != 1:
            self.note("unmapped_bar", {"ts": bar["ts"], "instrument_id": bar["instrument_id"], "received_ns": received_ns})
            self.halt_day("missing_contract_mapping", received_ns)
            return
        bar = dict(bar, symbol=symbols.pop())
        old = self.db.execute("SELECT * FROM receipts WHERE ts=?", (bar["ts"],)).fetchone()
        if old:
            if old["payload"] != canonical(bar):
                self.halt_day("conflicting_duplicate", received_ns, hard=True)
                raise ValueError("Conflicting duplicate stream bar")
            if not old["applied"]: self._apply(old)
            return
        last = self.db.execute("SELECT MAX(ts) FROM receipts").fetchone()[0]
        if last is not None and bar["ts"] <= last:
            self.halt_day("out_of_order_bar", received_ns, hard=True)
            raise ValueError("Stream time moved backwards")
        decision_now = max(received_ns, self.clock_ns())
        delay_ns = received_ns - (bar["ts"] + 60) * NS
        disposition = "accepted"
        if bar["ts"] * NS < self.registration["registered_at_ns"]:
            disposition = "before_registration"
        elif delay_ns < -2 * NS:
            disposition = "incomplete_or_future_bar"
        elif delay_ns > self.spec["max_bar_delay_seconds"] * NS:
            disposition = "late_bar"
        elif decision_now - (bar["ts"]+60)*NS > self.spec["max_bar_delay_seconds"]*NS:
            disposition = "processing_lag"
        elif self.meta("hard_halt"):
            disposition = "hard_halted"
        else:
            local = datetime.fromtimestamp(bar["ts"], ET)
            minute = local.hour * 60 + local.minute
            any_position = any(w.account()["position"] for _, _, w in self.scenarios.values())
            if (local.weekday() >= 5 or not 570 <= minute < 960) and not any_position:
                disposition = "outside_strategy_session"
        with self.db:
            self.db.execute("INSERT INTO receipts VALUES(?,?,?,?,0)", (bar["ts"], received_ns, canonical(bar), disposition))
            record(self.db, "stream_receipt", {"bar": bar, "received_ns": received_ns, "disposition": disposition})
        if self.after_receipt: self.after_receipt()
        self._apply(self.db.execute("SELECT * FROM receipts WHERE ts=?", (bar["ts"],)).fetchone())
        self.last_bar_received_ns = received_ns
        self.set_meta("feed_contract", {"symbol": bar["symbol"], "instrument_id": bar["instrument_id"]})
        self.connection = "streaming" if disposition in ("accepted", "outside_strategy_session") else "data_review"

    def _apply(self, row):
        bar, received_ns = json.loads(row["payload"]), row["received_ns"]
        disposition = row["disposition"]
        if disposition in ("late_bar", "processing_lag", "incomplete_or_future_bar"):
            self.halt_day(disposition, max(received_ns, self.clock_ns()))
        if disposition == "accepted":
            prior_bar = self.db.execute("SELECT ts FROM receipts WHERE disposition='accepted' AND applied=1 AND ts<? ORDER BY ts DESC LIMIT 1", (bar["ts"],)).fetchone()
            if prior_bar and datetime.fromtimestamp(prior_bar[0], ET).date() == datetime.fromtimestamp(bar["ts"], ET).date() and bar["ts"]-prior_bar[0] != 60:
                # Cancel entry exposure before the simulator sees a post-gap
                # event; detecting the gap after advance would be too late.
                self.halt_day("missing_market_event", received_ns)
            contract = {"symbol": bar["symbol"], "instrument_id": bar["instrument_id"]}
            previous = self.meta("active_contract")
            if previous and previous != contract:
                exposure = any(w.account()["position"] for _, _, w in self.scenarios.values())
                self.halt_day("contract_roll", received_ns, hard=exposure)
                if exposure:
                    with self.db:
                        self.db.execute("UPDATE receipts SET disposition='roll_with_exposure',applied=1 WHERE ts=?", (bar["ts"],))
                        record(self.db, "receipt_excluded", {"ts": bar["ts"], "reason": "roll_with_exposure"})
                    return
                if any(b.db.execute("SELECT 1 FROM orders WHERE state IN ('accepted','partially_filled')").fetchone() for _, b, _ in self.scenarios.values()):
                    self.halt_day("contract_roll_pending_order", received_ns, hard=True)
                    raise ValueError("Contract roll has an unresolved order")
            self.set_meta("active_contract", contract)
            for name, (_, broker, worker) in self.scenarios.items():
                # Retain original receipt timing, but newly generated orders
                # must also respect actual processing time after a restart.
                worker.received_at_ns = max(received_ns, self.clock_ns())
                broker.advance(bar)
                worker.step(bar)
                worker.reconcile()
                if self.after_scenario: self.after_scenario(name)
            local = datetime.fromtimestamp(bar["ts"], ET)
            if (local.hour, local.minute) == (9, 44):
                day = local.date().isoformat()
                opening = self.db.execute("SELECT payload,disposition FROM receipts WHERE ts>=? AND ts<=? ORDER BY ts", (bar["ts"]-14*60, bar["ts"])).fetchall()
                eligible = len(opening)==15 and len({json.loads(r[0])["instrument_id"] for r in opening})==1 and all(r[1]=="accepted" and json.loads(r[0])["volume"]>0 for r in opening)
                eligible = eligible and not any(w.db.execute("SELECT 1 FROM halted_days WHERE day=?", (day,)).fetchone() or w.db.execute("SELECT 1 FROM meta WHERE key='risk_halted'").fetchone() for _, _, w in self.scenarios.values())
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO opportunities VALUES(?,?,?)", (day, int(eligible), "complete_at_decision" if eligible else "data_or_risk_exclusion"))
                    record(self.db, "opening_opportunity", {"day": day, "eligible": bool(eligible)})
        with self.db:
            self.db.execute("UPDATE receipts SET applied=1 WHERE ts=?", (bar["ts"],))
            record(self.db, "receipt_applied", {"ts": bar["ts"], "disposition": disposition})

    def check_health(self, now_ns):
        if self.connection in ("streaming", "data_review", "connected_waiting_for_bar"):
            if self.last_message_ns and now_ns-self.last_message_ns > self.spec["heartbeat_timeout_seconds"]*NS:
                self.disconnected("heartbeat_timeout", now_ns)
                return False
            anchor = self.last_bar_received_ns or self.last_message_ns
            if anchor and now_ns-anchor > self.spec["price_timeout_seconds"]*NS and self.connection != "data_review":
                self.connection = "data_review"
                self.halt_day("no_recent_price_bar", now_ns)
        return True

    def reconcile(self):
        verify_journal(self.db)
        rows = self.db.execute("SELECT * FROM receipts ORDER BY ts").fetchall()
        # Reconcile receipt journal against its materialized table separately.
        journal = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM journal WHERE kind='stream_receipt' ORDER BY seq")]
        if len(journal) != len(rows) or any(j["bar"] != json.loads(r["payload"]) or j["received_ns"] != r["received_ns"] or (j["disposition"] != r["disposition"] and not (r["disposition"]=="roll_with_exposure" and j["disposition"]=="accepted")) for j, r in zip(journal, rows)):
            raise ValueError("Provider receipt journal/table mismatch")
        bars = [json.loads(r["payload"]) for r in rows if r["disposition"] == "accepted" and r["applied"]]
        results = {}
        for name, (spec, broker, worker) in self.scenarios.items():
            worker.reconcile()
            account = worker.account(bars[-1]["close"] if bars else None)
            result = audit(self.root/f"{name}-simulator.sqlite", self.root/f"{name}-worker.sqlite", spec, bars, account, allow_open=True)
            if result["status"] != "pass":
                raise ValueError(f"{name}: independent reconciliation failed: " + "; ".join(result["errors"][:3]))
            results[name] = result
        self.audit_results = results
        self.set_meta("last_reconciled_at", utc())
        return results

    def snapshot(self, now_ns=None):
        now_ns = now_ns if now_ns is not None else time.time_ns()
        self.check_health(now_ns)
        rows = self.db.execute("SELECT ts,payload,disposition FROM receipts ORDER BY ts").fetchall()
        day_groups = {}
        for r in rows:
            local = datetime.fromtimestamp(r["ts"], ET)
            minute = local.hour*60+local.minute
            if local.weekday() < 5 and 570 <= minute <= 584:
                day_groups.setdefault(local.date().isoformat(), []).append(r)
        complete = self.db.execute("SELECT COUNT(*) FROM opportunities WHERE eligible=1").fetchone()[0]
        scenarios = []
        for name, (_, broker, worker) in self.scenarios.items():
            latest = broker.db.execute("SELECT payload FROM bars ORDER BY ts DESC LIMIT 1").fetchone()
            account = worker.account(json.loads(latest[0])["close"] if latest else None)
            scenarios.append({"name": name, "account": account,
              "orders": worker.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0],
              "fills": worker.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0],
              "completed_contract_units": self.audit_results.get(name, {}).get("completed_contract_units", 0),
              "halted_days": worker.db.execute("SELECT COUNT(*) FROM halted_days").fetchone()[0],
              "risk_halted": bool(worker.db.execute("SELECT 1 FROM meta WHERE key='risk_halted'").fetchone()),
              "reconciliation": "pass" if name in self.audit_results else "pending"})
        return {"schema_version": 1, "run_id": self.registration["run_id"], "observed_at": utc(now_ns),
          "registered_at": self.registration["registered_at"], "protocol_sha256": self.registration["protocol_sha256"],
          "mode": "streaming_internal_paper", "provider": "Databento", "dataset": "GLBX.MDP3", "feed_schema": "ohlcv-1m",
          "connection": "halted" if self.meta("hard_halt") else self.connection,
          "hard_halt": self.meta("hard_halt"), "last_error": self.last_error,
          "last_message_at": utc(self.last_message_ns) if self.last_message_ns else None,
          "last_bar_received_at": utc(self.last_bar_received_ns) if self.last_bar_received_ns else None,
          "last_reconciled_at": self.meta("last_reconciled_at"), "contract": self.meta("active_contract") or self.meta("feed_contract"),
          "receipts": len(rows), "excluded_receipts": sum(r["disposition"] not in ("accepted", "outside_strategy_session") for r in rows),
          "complete_opening_opportunities": complete, "observed_opening_dates": len(day_groups),
          "engineering_review_due": complete >= 20, "scenarios": scenarios,
          "external_broker_connected": False, "live_order_routing": False, "profitability_established": False,
          "host": "supervised_worker", "initial_balance_cents": self.spec["initial_balance_cents"],
          "disk_free_bytes": shutil.disk_usage(self.root).free,
          "scope": "Forward market stream with internal simulated fills. No real orders or external broker confirmation. All six live-pilot requirements remain unverified."}

    def close_day(self, now_ns):
        local = datetime.fromtimestamp(now_ns/NS, ET)
        day = local.date().isoformat()
        if local.weekday() >= 5 or local.hour < 16 or self.db.execute("SELECT 1 FROM daily_audits WHERE day=?", (day,)).fetchone():
            return
        results = self.reconcile()
        unresolved = any(w.account()["position"] or b.db.execute("SELECT 1 FROM orders WHERE state IN ('accepted','partially_filled')").fetchone() for _, b, w in self.scenarios.values())
        report = {"day": day, "at": utc(now_ns), "status": "unresolved" if unresolved else "reconciled", "scenarios": results}
        with self.db:
            self.db.execute("INSERT INTO daily_audits VALUES(?,?)", (day, canonical(report)))
            record(self.db, "daily_audit", report)
        atomic_json(self.root/f"daily-{day}.json", report)
        if unresolved: self.halt_day("unresolved_inventory_at_close", now_ns, hard=True)
