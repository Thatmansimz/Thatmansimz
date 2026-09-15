#!/usr/bin/env python3
"""Register, supervise and inspect the streaming internal paper service."""
from __future__ import annotations

import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import queue
import signal
import sqlite3
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.paperlab.continuous import ContinuousPaper, NS, atomic_json, register, utc
from backend.paperlab.feed import DatabentoFeed


def load_env(path):
    """Read literal assignments without executing shell code or interpolating."""
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        key, sep, value = line.partition("=")
        if not sep: raise ValueError("Invalid environment assignment")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def serve_status(path, token, port):
    if not token or len(token) < 32:
        raise ValueError("Local status API requires a private token of at least 32 characters")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path != "/status": self.send_error(404); return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401); return
            try: body = path.read_bytes()
            except OSError: self.send_error(503); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            try:
                self.end_headers(); self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A reader leaving does not invalidate the durable status.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def publish(snapshot, env):
    endpoint, token = env.get("TAJARI_PAPER_STATUS_URL"), env.get("TAJARI_PAPER_STATUS_TOKEN")
    if not endpoint: return "not_configured"
    if urlparse(endpoint).scheme != "https" or not token:
        raise ValueError("Publishing requires HTTPS and a private status token")
    # Deliberate allowlist: never transmit the SQLite ledger or market prices.
    allowed = ("schema_version", "run_id", "observed_at", "registered_at", "protocol_sha256", "mode", "provider", "dataset", "feed_schema", "connection", "hard_halt", "last_error", "last_message_at", "last_bar_received_at", "last_reconciled_at", "last_audit_attempt_at", "contract", "receipts", "excluded_receipts", "complete_opening_opportunities", "observed_opening_dates", "engineering_review_due", "scenarios", "external_broker_connected", "live_order_routing", "profitability_established", "host", "initial_balance_cents", "scope")
    body = json.dumps({k: snapshot[k] for k in allowed}, allow_nan=False).encode()
    request = Request(endpoint, data=body, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=5) as response:
        if response.status != 200: raise ValueError("Snapshot publishing failed")
    return "published"


def run(args):
    os.umask(0o077)
    env = load_env(args.env_file)
    key = env.get("DATABENTO_API_KEY")
    if not key: raise ValueError("Databento key is missing from the private environment file")
    service = ContinuousPaper(args.run_dir)
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    server = serve_status(args.run_dir / "status.json", env.get("TAJARI_PAPER_LOCAL_TOKEN"), args.port) if args.port else None
    feed = None
    retry_at = 0
    retry_delay = 5
    last_report = 0
    connected_at = 0
    connect_deadline = 0
    stop_at = time.monotonic() + args.max_seconds if args.max_seconds else None
    interrupted = service.db.execute("SELECT COUNT(*) FROM journal WHERE kind='process_started'").fetchone()[0] > 1
    if interrupted: service.halt_day("process_restart_gap", time.time_ns())
    try:
        while not stopping.is_set() and not (args.run_dir / "STOP").exists():
            monotonic = time.monotonic()
            now_ns = time.time_ns()
            if stop_at and monotonic >= stop_at: break
            hard = service.meta("hard_halt")
            if not hard and feed is None and monotonic >= retry_at:
                feed = DatabentoFeed(key)
                connected_at = 0
                connect_deadline = monotonic + 45
                service.connection = "connecting"
                atomic_json(args.run_dir/"status.json", service.snapshot())
                feed.begin()
            if feed and not connected_at:
                if feed.connection_done.is_set():
                    if feed.connection_error or feed.closed.is_set():
                        if not feed.closed.is_set():
                            service.disconnected(feed.connection_error, time.time_ns())
                        feed.close(); feed = None
                        retry_at = time.monotonic() + retry_delay
                        retry_delay = min(retry_delay*2, 900)
                    else:
                        service.connected(time.time_ns()); connected_at = time.monotonic()
                elif monotonic >= connect_deadline and not feed.closed.is_set():
                    service.disconnected("feed_connect_timeout", time.time_ns())
                    feed.close()
                    # Retain the cancelled attempt until it finishes. A stuck
                    # SDK must not spawn an unbounded number of connectors.
                stopping.wait(0.1)
            if feed and connected_at:
                kind = None
                try:
                    if feed.overflow.is_set():
                        raise ValueError("Stream callback queue overflow; review required")
                    kind, payload, received = feed.events.get(timeout=0.5)
                    service.heartbeat(received)
                    if kind == "bar": service.receive(payload, received)
                    elif kind == "mapping": service.mapping(**payload, received_ns=received)
                    elif kind in ("error", "invalid"): raise ValueError(payload)
                except queue.Empty: pass
                except Exception as exc:
                    reason = feed.safe_error(exc)
                    service.note("processing_error", {"at": utc(), "reason": reason})
                    # Provider access errors are retriable. Invalid data or a
                    # reconciliation problem hard-halts the registered run.
                    if kind not in ("error",):
                        service.halt_day("processing_error", time.time_ns(), hard=True)
                    service.disconnected(reason, time.time_ns())
                    feed.close(); feed = None
                    retry_at = time.monotonic() + retry_delay
                    retry_delay = min(retry_delay*2, 900)
                if feed and (not feed.is_connected() or not service.check_health(time.time_ns())):
                    service.disconnected("feed_connection_lost", time.time_ns())
                    feed.close(); feed = None
                    retry_at = time.monotonic() + retry_delay
                    retry_delay = min(retry_delay*2, 900)
                if feed and time.monotonic()-connected_at > 300: retry_delay = 5
            else:
                stopping.wait(0.5)
            if monotonic-last_report >= service.spec["report_interval_seconds"]:
                try:
                    service.reconcile()
                    service.close_day(time.time_ns())
                except Exception as exc:
                    service.set_meta("hard_halt", "reconciliation_failed")
                    service.last_error = type(exc).__name__ + ": " + str(exc)[:200]
                    service.note("audit_failed", {"at": utc(), "reason": service.last_error})
                status = service.snapshot()
                atomic_json(args.run_dir/"status.json", status)
                try: outcome = publish(status, env)
                except Exception as exc: outcome = "failed:" + type(exc).__name__
                atomic_json(args.run_dir/"publisher.json", {"at": utc(), "status": outcome})
                print(json.dumps({"at": status["observed_at"], "state": status["connection"], "receipts": status["receipts"], "publisher": outcome}), flush=True)
                last_report = monotonic
    finally:
        if feed: feed.close()
        service.connection = "stopped"
        service.halt_day("service_stopped", time.time_ns())
        status = service.snapshot()
        atomic_json(args.run_dir/"status.json", status)
        try: publish(status, env)
        except Exception: pass
        service.note("process_stopped", {"at": utc()})
        service.close()
        if server: server.shutdown()


def backup(directory, output):
    lock = (directory/"worker.lock").open("a+")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise ValueError("Stop the worker before taking a coherent multi-ledger backup") from None
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {"at": utc(), "files": {}}
    for source in sorted(directory.glob("*.sqlite")):
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(output/source.name) as dest:
            src.backup(dest)
        manifest["files"][source.name] = hashlib.sha256((output/source.name).read_bytes()).hexdigest()
    for name in ("protocol.json", "registration.json"):
        (output/name).write_bytes((directory/name).read_bytes())
        manifest["files"][name] = hashlib.sha256((output/name).read_bytes()).hexdigest()
    atomic_json(output/"manifest.json", manifest)
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
    print(json.dumps({"backup": str(output), "files": len(manifest["files"])}))


def amend_registration(directory, output, reason):
    """Explicit stopped-run code upgrade: preserve balances, receipts and freeze."""
    from backend.paperlab.continuous import code_hashes, runtime_versions
    from backend.paperlab.storage import digest, record, connect, verify_journal
    if not reason.strip() or len(reason) > 500: raise ValueError("A concise upgrade reason is required")
    if not (directory/"STOP").exists(): raise ValueError("A deliberate STOP is required before amendment")
    lock = (directory/"worker.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise ValueError("Stop the worker before amending its registration") from None
    try:
        original = (directory/"registration.json").read_bytes()
        manifest = json.loads(original)
        if digest(json.loads((directory/"protocol.json").read_text())) != manifest["protocol_sha256"]:
            raise ValueError("A code amendment cannot change the frozen protocol")
        new_code, new_runtime = code_hashes(), runtime_versions()
        if new_code == manifest["code_sha256"] and new_runtime == manifest["runtime"]:
            raise ValueError("The registered implementation is already current")
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        saved = {"at": utc(), "files": {}}
        for source in sorted(directory.glob("*.sqlite")):
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(output/source.name) as dest:
                if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Database integrity check failed")
                src.backup(dest)
            saved["files"][source.name] = hashlib.sha256((output/source.name).read_bytes()).hexdigest()
        for name in ("protocol.json", "registration.json"):
            (output/name).write_bytes((directory/name).read_bytes())
            saved["files"][name] = hashlib.sha256((output/name).read_bytes()).hexdigest()
        atomic_json(output/"manifest.json", saved)
        previous_hash = hashlib.sha256(original).hexdigest()
        archive = "registration-" + previous_hash + ".json"
        if not (directory/archive).exists():
            with (directory/archive).open("xb") as f: f.write(original); f.flush(); os.fsync(f.fileno())
        amendment = {"at": utc(), "reason": reason, "previous_registration": archive,
                     "previous_registration_sha256": previous_hash,
                     "code_sha256": new_code, "runtime": new_runtime,
                     "backup_manifest_sha256": hashlib.sha256((output/"manifest.json").read_bytes()).hexdigest()}
        db = connect(directory/"receipts.sqlite")
        try:
            verify_journal(db)
            with db: record(db, "implementation_amended", amendment)
        finally: db.close()
        manifest["code_sha256"], manifest["runtime"] = new_code, new_runtime
        manifest.setdefault("implementation_amendments", []).append(amendment)
        atomic_json(directory/"registration.json", manifest)
        # STOP remains. Continuing requires an explicit operator decision after
        # validation; an amendment never starts a feed or resets an account.
        print(json.dumps({"run_id": manifest["run_id"], "backup": str(output), "amended": True}))
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--protocol", type=Path, default=ROOT/"evidence/continuous-paper-protocol.json")
    reg.add_argument("--run-dir", type=Path, required=True)
    reg.add_argument("--preflight", type=Path)
    worker = sub.add_parser("run")
    worker.add_argument("--run-dir", type=Path, required=True)
    worker.add_argument("--env-file", type=Path, required=True)
    worker.add_argument("--port", type=int, default=8022)
    worker.add_argument("--max-seconds", type=int, help="Bounded connection smoke test; omit for continuous service")
    status = sub.add_parser("status")
    status.add_argument("--run-dir", type=Path, required=True)
    back = sub.add_parser("backup")
    back.add_argument("--run-dir", type=Path, required=True)
    back.add_argument("--output", type=Path, required=True)
    amend = sub.add_parser("amend-registration")
    amend.add_argument("--run-dir", type=Path, required=True)
    amend.add_argument("--output", type=Path, required=True, help="New coherent backup directory")
    amend.add_argument("--reason", required=True)
    stop = sub.add_parser("stop")
    stop.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "register":
        manifest = register(args.run_dir, json.loads(args.protocol.read_text()), preflight=json.loads(args.preflight.read_text()) if args.preflight else None)
        print(json.dumps(manifest, indent=2))
    elif args.command == "run": run(args)
    elif args.command == "status": print((args.run_dir/"status.json").read_text())
    elif args.command == "backup": backup(args.run_dir, args.output)
    elif args.command == "amend-registration": amend_registration(args.run_dir, args.output, args.reason)
    elif args.command == "stop": (args.run_dir/"STOP").write_text(utc()+"\n")


if __name__ == "__main__":
    main()
