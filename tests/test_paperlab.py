"""Behavioral acceptance: deterministic cents, crash recovery and hostile data."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.paperlab.audit import audit
from backend.paperlab.simulator import Simulator
from backend.paperlab.storage import canonical, digest
from backend.paperlab.worker import Worker

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    start = datetime(2022, 1, 3, 14, 30, tzinfo=timezone.utc)
    return [dict(ts=int((start + timedelta(minutes=i)).timestamp()), open=40000+i,
                 high=40001+i, low=39999+i, close=40000+i, volume=100) for i in range(63)]


class PaperLabAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = json.loads((ROOT / "evidence/paper-milestone-protocol.json").read_text())

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, bars=None, spec=None, **broker_options):
        bars = bars if bars is not None else fixture()
        spec = spec or self.spec
        broker = Simulator(self.root / "broker.sqlite", spec, **broker_options)
        worker = Worker(self.root / "worker.sqlite", spec, broker)
        worker.recover()
        for bar in bars:
            broker.advance(bar); worker.step(bar)
        worker.reconcile()
        account = worker.account()
        worker.close(); broker.close()
        return audit(self.root / "broker.sqlite", self.root / "worker.sqlite", spec, bars, account)

    def test_known_round_trip_matches_independent_cents(self):
        result = self.execute()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["fills"], 2)
        self.assertEqual(result["completed_contract_units"], 1)
        # Entry 40017, exit 40045: 28 ticks x $0.50, minus 2 x $0.62.
        self.assertEqual(result["account"]["net_pnl_cents"], 1276)
        self.assertEqual(result["account"]["equity_cents"], 5001276)

    def test_actual_process_crashes_recover_without_duplicate_orders(self):
        for case in ("crash_after_accept", "crash_after_fill"):
            with self.subTest(case=case):
                folder = self.root / case; folder.mkdir()
                spec = dict(self.spec, case=case)
                (folder / "protocol.json").write_text(canonical(spec))
                (folder / "bars.json").write_text(canonical(fixture()))
                cmd = [sys.executable, str(ROOT / "scripts/paper_milestone.py"), "worker", "--output", str(folder)]
                first = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(first.returncode, 87, first.stderr)
                second = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(second.returncode, 0, second.stderr)
                account = json.loads((folder / "account.json").read_text())
                result = audit(folder / "simulator.sqlite", folder / "worker.sqlite", spec, fixture(), account)
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["orders"], 2)
                self.assertEqual(result["account"]["net_pnl_cents"], 1276)

    def test_partial_fills_preserve_quantity_and_protection(self):
        result = self.execute(spec=dict(self.spec, quantity=2), fill_cap=1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["fills"], 4)
        self.assertEqual(result["completed_contract_units"], 2)

    def test_stop_cancels_remaining_partial_entry(self):
        bars = fixture(); bars[16]["low"] = 39800
        result = self.execute(bars, spec=dict(self.spec, quantity=2), fill_cap=1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["completed_contract_units"], 1)
        self.assertEqual(result["order_states"], {"cancelled": 1})

    def test_gap_through_stop_fills_at_adverse_open(self):
        bars = fixture(); bars[20].update(open=39800, high=39801, low=39799, close=39800)
        result = self.execute(bars)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["account"]["net_pnl_cents"], -11024)

    def test_missing_opening_event_suppresses_entry(self):
        bars = fixture(); bars.pop(7)
        result = self.execute(bars)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["orders"], 0)
        self.assertEqual(result["worker_events"]["market_gap"], 1)

    def test_rejected_protection_creates_no_exposure(self):
        result = self.execute(reject="protection_rejected")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["fills"], 0)
        self.assertEqual(result["account"]["equity_cents"], 5000000)
        self.assertEqual(result["order_states"], {"rejected": 1})

    def test_duplicate_and_conflicting_market_events(self):
        broker = Simulator(self.root / "broker.sqlite", self.spec)
        bar = fixture()[0]; broker.advance(bar); broker.advance(bar)
        self.assertEqual(broker.db.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            broker.advance(dict(bar, volume=999))
        with self.assertRaisesRegex(ValueError, "Out-of-order"):
            broker.advance(dict(bar, ts=bar["ts"] - 60))
        broker.close()

    def test_protocol_change_and_nonpaper_mode_rejected(self):
        broker = Simulator(self.root / "broker.sqlite", self.spec); broker.close()
        with self.assertRaisesRegex(ValueError, "Frozen protocol"):
            Simulator(self.root / "broker.sqlite", dict(self.spec, slippage_ticks=3))
        with self.assertRaises(ValueError):
            Simulator(self.root / "other.sqlite", dict(self.spec, purpose="live"))
        with self.assertRaises(ValueError):
            Simulator(self.root / "negative.sqlite", dict(self.spec, commission_per_side_cents=-1))

    def test_table_tampering_cannot_pass_independent_audit(self):
        result = self.execute(); self.assertEqual(result["status"], "pass")
        import sqlite3
        with sqlite3.connect(self.root / "worker.sqlite") as db:
            payload = json.loads(db.execute("SELECT payload FROM fills LIMIT 1").fetchone()[0])
            payload["fee_cents"] = 0
            db.execute("UPDATE fills SET payload=? WHERE id=?", (canonical(payload), payload["id"]))
        result = audit(self.root / "broker.sqlite", self.root / "worker.sqlite", self.spec, fixture(), result["account"])
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("Fill identity" in e for e in result["errors"]))

    def test_unexplained_broker_order_blocks_recovery(self):
        broker = Simulator(self.root / "broker.sqlite", self.spec)
        broker.submit(dict(id="unknown", kind="entry", qty=1, side=1, submitted_at=1, eligible_at=61, expires_at=241, symbol=self.spec["symbol"]))
        worker = Worker(self.root / "worker.sqlite", self.spec, broker)
        with self.assertRaisesRegex(ValueError, "Unexplained"):
            worker.recover()
        worker.close(); broker.close()

    def test_reusing_client_id_with_changed_order_is_rejected(self):
        broker = Simulator(self.root / "broker.sqlite", self.spec)
        req = dict(id="once", kind="entry", qty=1, side=1, submitted_at=1, eligible_at=61, expires_at=241, symbol=self.spec["symbol"])
        broker.submit(req); broker.submit(req)
        self.assertEqual(len(broker.snapshot()["orders"]), 1)
        with self.assertRaisesRegex(ValueError, "Idempotency"):
            broker.submit(dict(req, side=-1))
        broker.close()

    def test_unfilled_partial_quantity_expires_without_losing_position(self):
        bars = fixture()
        for i in (17, 18, 19): bars[i]["volume"] = 0
        result = self.execute(bars, spec=dict(self.spec, quantity=2), fill_cap=1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["completed_contract_units"], 1)
        self.assertEqual(result["order_states"], {"expired": 1, "filled": 1})

    def test_drawdown_halt_survives_into_next_session(self):
        bars = fixture(); bars[20].update(open=39800, high=39801, low=39799, close=39800)
        bars += [dict(b, ts=b["ts"]+86400) for b in fixture()]
        result = self.execute(bars, spec=dict(self.spec, drawdown_limit_cents=1000))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["completed_contract_units"], 1)

    def test_modified_account_cannot_pass_independent_audit(self):
        result = self.execute()
        fake = dict(result["account"], equity_cents=9999999)
        result = audit(self.root / "broker.sqlite", self.root / "worker.sqlite", self.spec, fixture(), fake)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("accounting" in error for error in result["errors"]))
