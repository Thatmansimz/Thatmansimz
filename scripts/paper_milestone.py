#!/usr/bin/env python3
"""Run the frozen engineering replay; paid source bars stay outside Git/hosting.

prepare verifies the declared full-file digest and reads ONLY the registered
research slice. run executes real child processes, including crash/restart.
No API key is loaded; no market purchase or broker request is possible here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.paperlab.storage import canonical, digest
from backend.paperlab.simulator import Simulator
from backend.paperlab.worker import Worker
from backend.paperlab.audit import audit


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(args):
    import pandas as pd
    import pyarrow.parquet as pq
    spec = json.loads(args.protocol.read_text())
    source = args.dataset.resolve()
    with source.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != spec["dataset_sha256"]:
        raise ValueError("Dataset differs from frozen source; no observations read")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "access.json").exists():
        raise ValueError("Access record already exists; use the preserved prepared input")
    access = {"accessed_at": datetime.now(timezone.utc).isoformat(), "dataset_file": source.name,
              "dataset_sha256": actual, "protocol_sha256": digest(spec), "data_status": spec["data_status"],
              "requested_start": spec["start_date"], "requested_end_exclusive": spec["end_date_exclusive"],
              "purpose": spec["purpose"], "status": "access_started", "raw_data_published": False}
    save(args.output / "access.json", access)  # Before any price rows are read.
    start, end = pd.Timestamp(spec["start_date"], tz="UTC"), pd.Timestamp(spec["end_date_exclusive"], tz="UTC")
    table = pq.read_table(source, filters=[("timestamp", ">=", start.to_pydatetime()), ("timestamp", "<", end.to_pydatetime())])
    frame = table.to_pandas().sort_index()
    if frame.index.has_duplicates or frame.index.tz is None:
        raise ValueError("Duplicate or naive source timestamps")
    local = frame.index.tz_convert(spec["timezone"])
    minute = local.hour * 60 + local.minute
    frame = frame[(minute >= 570) & (minute <= 632)]
    from decimal import Decimal
    bars = []
    for ts, row in frame.iterrows():
        b = {"ts": int(ts.timestamp()), "volume": int(row["volume"])}
        for key in ("open", "high", "low", "close"):
            ticks = Decimal(str(row[key])) / Decimal(spec["tick_size"])
            if not ticks.is_finite() or ticks != ticks.to_integral_value():
                raise ValueError("Source price is not finite or tick aligned")
            b[key] = int(ticks)
        bars.append(b)
    save(args.output / "bars.json", bars)
    save(args.output / "protocol.json", spec)
    access.update(status="research_slice_prepared", selected_bars=len(bars),
                  selected_bars_sha256=digest(bars), first_ts=bars[0]["ts"], last_ts=bars[-1]["ts"])
    save(args.output / "access.json", access)
    print(json.dumps(access, indent=2))


class FaultTransport:
    def __init__(self, broker):
        self.broker, self.offline = broker, False
    def snapshot(self):
        if self.offline: raise ConnectionError("Injected transport disconnect")
        return self.broker.snapshot()
    def submit(self, request):
        if self.offline: raise ConnectionError("Injected transport disconnect")
        return self.broker.submit(request)


def worker_run(args):
    spec = json.loads((args.output / "protocol.json").read_text())
    bars = json.loads((args.output / "bars.json").read_text())
    broker = Simulator(args.output / "simulator.sqlite", spec, fill_cap=spec.get("fill_cap"), reject=spec.get("reject"))
    transport = FaultTransport(broker)
    def crash_once():
        marker = args.output / "crash-injected.txt"
        if not marker.exists():
            with marker.open("x") as stream:
                stream.write(spec["case"]); stream.flush(); os.fsync(stream.fileno())
            os._exit(87)
    worker = Worker(args.output / "worker.sqlite", spec, transport,
                    after_accept=crash_once if spec["case"] == "crash_after_accept" else None,
                    after_fill=crash_once if spec["case"] == "crash_after_fill" else None)
    worker.recover()
    from zoneinfo import ZoneInfo
    first_day = datetime.fromtimestamp(bars[0]["ts"], ZoneInfo(spec["timezone"])).date()
    for bar in bars:
        if worker.processed(bar): continue
        local = datetime.fromtimestamp(bar["ts"], ZoneInfo(spec["timezone"]))
        transport.offline = spec["case"] == "disconnect" and local.date() == first_day and local.hour == 9 and 46 <= local.minute <= 48
        broker.advance(bar)
        worker.step(bar)
    transport.offline = False
    worker.reconcile()
    save(args.output / "account.json", worker.account())
    worker.close(); broker.close()


def run(args):
    base = json.loads((args.output / "protocol.json").read_text())
    bars = json.loads((args.output / "bars.json").read_text())
    access = json.loads((args.output / "access.json").read_text())
    if digest(base) != access["protocol_sha256"] or digest(bars) != access["selected_bars_sha256"]:
        raise ValueError("Prepared protocol/input changed after access")
    def fingerprint():
        files = sorted((ROOT / "backend/paperlab").glob("*.py")) + [Path(__file__).resolve()]
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    implementation = {"captured_before_execution_at": datetime.now(timezone.utc).isoformat(),
                      "code_sha256": fingerprint(),
                      "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      "custody": "Local file hashes and Git history; not independent attestation"}
    if (args.output / "execution-manifest.json").exists():
        raise ValueError("Execution record already exists; previous attempts must be preserved")
    save(args.output / "execution-manifest.json", implementation)
    reports = []
    for case in base["experiment_family"]:
        folder = args.output / case
        if folder.exists(): raise ValueError(f"Refusing to overwrite {folder}; retain original results")
        folder.mkdir()
        spec = dict(base, case=case)
        spec.update(base["stress_overrides"].get(case, {}))
        if case in ("entry_rejected", "protection_rejected"): spec["reject"] = case
        selected = list(bars)
        if case == "missing_market_event": selected.pop(7)
        save(folder / "protocol.json", spec); save(folder / "bars.json", selected)
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--output", str(folder)]
        exits = []
        for attempt in range(2):
            result = subprocess.run(command, capture_output=True, text=True)
            exits.append(result.returncode)
            (folder / f"process-{attempt}.txt").write_text(result.stdout + result.stderr)
            if result.returncode != 87: break
        if result.returncode:
            reports.append({"case": case, "status": "fail", "process_exit_codes": exits, "errors": [result.stderr[-2000:]]})
            continue
        account = json.loads((folder / "account.json").read_text())
        report = audit(folder / "simulator.sqlite", folder / "worker.sqlite", spec, selected, account)
        report.update(case=case, process_exit_codes=exits)
        save(folder / "audit.json", report); reports.append(report)
    result = {"protocol": base["name"], "purpose": base["purpose"], "generated_at": datetime.now(timezone.utc).isoformat(),
              "data_access": access, "implementation": implementation, "initial_balance_cents": base["initial_balance_cents"], "scenarios": reports,
              "status": "pass" if len(reports) == len(base["experiment_family"]) and all(r["status"] == "pass" for r in reports) else "fail",
              "broker_connected": False, "live_trading_available": False, "profitability_established": False,
              "limits": base["limits"]}
    if implementation["code_sha256"] != fingerprint():
        result["status"] = "fail"
        result["execution_error"] = "Implementation changed during execution"
    save(args.output / "summary.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "worker"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evidence/paper-milestone-protocol.json")
    args = parser.parse_args()
    if args.action == "prepare": return prepare(args)
    if args.action == "worker": return worker_run(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
