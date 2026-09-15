"""Fault tests for genuinely forward receipts; all market inputs are synthetic."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

from backend.paperlab.continuous import ContinuousPaper, NS, code_hashes, register

ROOT = Path(__file__).resolve().parents[1]


def bars(count=63):
    start = int(datetime(2026, 9, 14, 9, 30, tzinfo=ZoneInfo("America/New_York")).timestamp())
    return [dict(ts=start+60*i, open=40000+i, high=40001+i, low=39999+i,
                 close=40000+i, volume=100, instrument_id=101) for i in range(count)]


class ContinuousAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/"registered-run"
        self.spec = json.loads((ROOT/"evidence/continuous-paper-protocol.json").read_text())
        self.input = bars()
        register(self.root, self.spec, now_ns=(self.input[0]["ts"]-120)*NS)
        self.now_ns = self.input[0]["ts"]*NS
        self.service = ContinuousPaper(self.root, clock_ns=lambda: self.now_ns)
        self.map()

    def tearDown(self):
        if self.service: self.service.close()
        self.temp.cleanup()

    def map(self, instrument=101, symbol="MNQU6", start=0):
        self.service.mapping(instrument, symbol, start, 2**64-1, self.input[0]["ts"]*NS)

    def send(self, b, delay_ns=500_000_000):
        self.now_ns = (b["ts"]+60)*NS+delay_ns
        self.service.receive(b, self.now_ns)

    def test_complete_forward_round_trip_and_worse_costs(self):
        for b in self.input: self.send(b)
        audit = self.service.reconcile()
        self.assertEqual(audit["baseline"]["account"]["net_pnl_cents"], 1276)
        self.assertEqual(audit["worse_costs"]["account"]["net_pnl_cents"], 852)
        self.assertEqual(audit["baseline"]["completed_contract_units"], 1)
        snap = self.service.snapshot((self.input[-1]["ts"]+61)*NS)
        self.assertEqual(snap["complete_opening_opportunities"], 1)
        self.assertFalse(snap["external_broker_connected"])
        self.assertFalse(snap["live_order_routing"])
        worker = self.service.scenarios["baseline"][2]
        order = json.loads(worker.db.execute("SELECT request FROM intents LIMIT 1").fetchone()[0])
        self.assertEqual(order["symbol"], "MNQU6")
        self.assertEqual(order["instrument_id"], 101)
        self.assertGreater(order["eligible_at"]*NS, order["decision_received_at_ns"])
        self.service.halt_day("later_disconnect", (self.input[-1]["ts"]+61)*NS)
        self.assertEqual(self.service.snapshot((self.input[-1]["ts"]+61)*NS)["complete_opening_opportunities"], 1)

    def test_late_opening_bar_excludes_session_and_never_backfills(self):
        for i,b in enumerate(self.input): self.send(b, 45*NS if i==7 else 500_000_000)
        result = self.service.reconcile()["baseline"]
        self.assertEqual(result["orders"], 0)
        self.assertEqual(result["account"]["net_pnl_cents"], 0)
        self.assertEqual(self.service.snapshot((self.input[-1]["ts"]+61)*NS)["excluded_receipts"], 1)

    def test_missing_event_cancels_entry_before_post_gap_fill(self):
        for b in self.input[:15]: self.send(b)
        # Entry is pending for minute 16. Missing minute 15 means it must be
        # cancelled before the simulator considers the minute-16 open.
        self.send(self.input[16])
        result = self.service.reconcile()["baseline"]
        self.assertEqual(result["fills"], 0)
        self.assertEqual(result["order_states"], {"cancelled": 1})

    def test_disconnect_cancels_pending_entry_and_preserves_ledger(self):
        for b in self.input[:15]: self.send(b)
        self.service.disconnected("synthetic disconnect", (self.input[14]["ts"]+61)*NS)
        for b in self.input[15:]: self.send(b)
        result = self.service.reconcile()["baseline"]
        self.assertEqual(result["fills"], 0)
        self.assertEqual(result["order_states"], {"cancelled": 1})

    def test_unmapped_bar_halts_entries_without_inventing_contract(self):
        self.send(dict(self.input[0], instrument_id=999))
        self.assertIsNone(self.service.meta("active_contract"))
        self.assertEqual(self.service.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 0)
        self.assertEqual(self.service.scenarios["baseline"][2].db.execute("SELECT reason FROM halted_days").fetchone()[0], "missing_contract_mapping")

    def test_roll_with_inventory_never_marks_or_fills_new_contract(self):
        for b in self.input[:17]: self.send(b)
        before = self.service.reconcile()["baseline"]["account"]
        self.assertEqual(before["position"], 1)
        self.map(202, "MNQZ6", self.input[17]["ts"]*NS)
        new = dict(self.input[17], instrument_id=202, open=41000, high=41001, low=40999, close=41000)
        self.send(new)
        after = self.service.reconcile()["baseline"]["account"]
        self.assertEqual(after, before)
        self.assertEqual(self.service.meta("hard_halt"), "contract_roll")

    def test_flat_roll_is_recorded_and_opening_entry_suppressed(self):
        for b in self.input[:7]: self.send(b)
        self.map(202, "MNQZ6", self.input[7]["ts"]*NS)
        for b in self.input[7:]: self.send(dict(b, instrument_id=202))
        self.assertEqual(self.service.reconcile()["baseline"]["orders"], 0)
        self.assertEqual(self.service.meta("active_contract")["symbol"], "MNQZ6")

    def test_duplicate_is_idempotent_but_conflicting_receipt_hard_halts(self):
        self.send(self.input[0]); self.send(self.input[0])
        self.assertEqual(self.service.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            self.send(dict(self.input[0], close=40001))
        self.assertEqual(self.service.meta("hard_halt"), "conflicting_duplicate")

    def test_registration_rejects_history_resets_and_implementation_changes(self):
        with self.assertRaises(FileExistsError): register(self.root, self.spec)
        self.service.close(); self.service = None
        with self.assertRaisesRegex(ValueError, "Implementation differs"):
            ContinuousPaper(self.root, implementation={"tampered": "yes"})
        other = Path(self.temp.name)/"live"
        with self.assertRaises(ValueError): register(other, dict(self.spec, live_order_routing=True))

    def test_exclusive_process_lock(self):
        code = "from backend.paperlab.continuous import ContinuousPaper; import sys; ContinuousPaper(sys.argv[1])"
        result = subprocess.run([sys.executable, "-c", code, str(self.root)], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Another worker owns", result.stderr)

    def test_real_process_crash_recovers_receipt_and_each_scenario(self):
        self.service.close(); self.service = None
        for boundary in ("receipt", "scenario"):
            with self.subTest(boundary=boundary):
                run = Path(self.temp.name)/boundary
                register(run, self.spec, now_ns=(self.input[0]["ts"]-120)*NS)
                source = r'''
import json,os,sys
from pathlib import Path
from backend.paperlab.continuous import ContinuousPaper,NS
root=Path(sys.argv[1]); boundary=sys.argv[2]; bars=json.loads(sys.argv[3])
def fail(*args):
 if not (root/'crashed').exists():
  (root/'crashed').write_text('crash')
  os._exit(87)
clock=[bars[0]['ts']*NS]
s=ContinuousPaper(root,after_receipt=fail if boundary=='receipt' else None,after_scenario=fail if boundary=='scenario' else None,clock_ns=lambda:clock[0])
s.mapping(101,'MNQU6',0,2**64-1,bars[0]['ts']*NS)
for b in bars:
 clock[0]=(b['ts']+60)*NS+500000000
 s.receive(b,clock[0])
result=s.reconcile(); print(json.dumps(result));s.close()
'''
                command = [sys.executable, "-c", source, str(run), boundary, json.dumps(self.input)]
                first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(first.returncode, 87, first.stderr)
                second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(second.returncode, 0, second.stderr)
                result = json.loads(second.stdout)
                self.assertEqual(result["baseline"]["account"]["net_pnl_cents"], 1276)
                self.assertEqual(result["baseline"]["fills"], 2)

    def test_source_table_tampering_is_detected_independently(self):
        self.send(self.input[0])
        with self.service.db:
            self.service.db.execute("UPDATE receipts SET received_ns=received_ns+1")
        with self.assertRaisesRegex(ValueError, "journal/table mismatch"): self.service.reconcile()

    def test_timely_receipt_processed_late_cannot_create_retrospective_order(self):
        for b in self.input[:14]: self.send(b)
        b = self.input[14]
        received = (b["ts"]+60)*NS
        self.now_ns = received+5*60*NS
        self.service.receive(b, received)
        self.assertEqual(self.service.reconcile()["baseline"]["orders"], 0)
        self.assertEqual(self.service.db.execute("SELECT disposition FROM receipts WHERE ts=?", (b["ts"],)).fetchone()[0], "processing_lag")

    def test_heartbeat_failure_disables_entries(self):
        now = self.input[0]["ts"]*NS
        self.service.connected(now)
        self.assertFalse(self.service.check_health(now+31*NS))
        self.assertEqual(self.service.connection, "disconnected")
        self.assertEqual(self.service.last_error, "heartbeat_timeout")

    def test_heartbeats_without_first_price_trigger_stable_watchdog(self):
        now = self.input[0]["ts"]*NS
        self.service.connected(now)
        for elapsed in range(5, 160, 5):
            self.service.heartbeat(now+elapsed*NS)
            self.service.check_health(now+elapsed*NS)
        self.assertEqual(self.service.connection, "data_review")
        self.assertEqual(self.service.scenarios["baseline"][2].db.execute("SELECT reason FROM halted_days").fetchone()[0], "no_recent_price_bar")

    def test_reconnect_gets_first_price_window_without_erasing_prior_timestamp(self):
        self.send(self.input[0])
        prior = self.service.last_bar_received_ns
        now = prior+600*NS
        self.service.connected(now)
        self.assertTrue(self.service.check_health(now+5*NS))
        self.assertEqual(self.service.connection, "connected_waiting_for_bar")
        self.assertEqual(self.service.last_bar_received_ns, prior)
        self.service.heartbeat(now+151*NS)
        self.service.check_health(now+151*NS)
        self.assertEqual(self.service.connection, "data_review")

    def test_failed_audit_does_not_publish_previous_pass(self):
        self.send(self.input[0])
        self.service.reconcile()
        previous = self.service.meta("last_reconciled_at")
        with self.service.db:
            self.service.db.execute("UPDATE receipts SET received_ns=received_ns+1")
        with self.assertRaisesRegex(ValueError, "journal/table mismatch"):
            self.service.reconcile()
        snapshot = self.service.snapshot(self.now_ns)
        self.assertEqual({s["reconciliation"] for s in snapshot["scenarios"]}, {"fail"})
        self.assertEqual(snapshot["last_reconciled_at"], previous)
        self.assertIsNotNone(snapshot["last_audit_attempt_at"])

    def test_daily_close_reports_and_halts_unresolved_inventory(self):
        for b in self.input[:17]: self.send(b)
        end = int(datetime(2026,9,14,16,1,tzinfo=ZoneInfo("America/New_York")).timestamp())*NS
        self.service.close_day(end)
        report = json.loads((self.root/"daily-2026-09-14.json").read_text())
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(self.service.meta("hard_halt"), "unresolved_inventory_at_close")


if __name__ == "__main__": unittest.main()
