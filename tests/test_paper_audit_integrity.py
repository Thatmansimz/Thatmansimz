"""Independent journal/materialized-state checks using isolated synthetic ledgers."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from backend.paperlab.audit import audit
from backend.paperlab.simulator import Simulator
from backend.paperlab.storage import canonical
from backend.paperlab.worker import Worker

ROOT = Path(__file__).resolve().parents[1]


def bars():
    start = datetime(2022, 1, 3, 14, 30, tzinfo=timezone.utc)
    return [dict(ts=int((start + timedelta(minutes=i)).timestamp()), open=40000+i,
                 high=40001+i, low=39999+i, close=40000+i, volume=100) for i in range(63)]


class PaperAuditIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tajari-audit-integrity-")
        self.root = Path(self.temp.name)
        self.spec = json.loads((ROOT/"evidence/paper-milestone-protocol.json").read_text())
        self.input = bars()
        self.broker = self.worker = None
        self.processed = []

    def tearDown(self):
        if self.worker: self.worker.close()
        if self.broker: self.broker.close()
        self.temp.cleanup()

    def start(self, *, quantity=1, **options):
        self.spec = dict(self.spec, quantity=quantity)
        self.broker = Simulator(self.root/"simulator.sqlite", self.spec, **options)
        self.worker = Worker(self.root/"worker.sqlite", self.spec, self.broker)
        self.worker.recover()

    def send(self, events):
        for bar in events:
            self.broker.advance(bar); self.worker.step(bar)
            self.processed.append(bar)
        self.worker.reconcile()

    def result(self):
        mark = self.processed[-1]["close"] if self.processed else None
        return audit(self.root/"simulator.sqlite", self.root/"worker.sqlite", self.spec,
                     self.processed, self.worker.account(mark), allow_open=True)

    def assert_fails_with(self, message):
        result = self.result()
        self.assertEqual(result["status"], "fail", result)
        self.assertIn(message, result["errors"])

    def test_current_lot_identity_parent_price_stop_side_and_quantity_are_checked(self):
        self.start(); self.send(self.input[:17])
        self.assertEqual(self.result()["status"], "pass")
        original = dict(self.broker.db.execute("SELECT * FROM lots").fetchone())
        replacements = {"id": "another-lot", "parent": "another-order", "price": 1,
                        "stop": 1, "side": -1, "qty": 2}
        for field, value in replacements.items():
            with self.subTest(field=field):
                with self.broker.db:
                    self.broker.db.execute(f"UPDATE lots SET {field}=?", (value,))
                self.assert_fails_with("Current protective lot journal/table mismatch")
                with self.broker.db:
                    self.broker.db.execute(f"UPDATE lots SET {field}=?", (original[field],))
        self.assertEqual(self.result()["status"], "pass")

    def test_deleting_order_and_intent_cannot_erase_journal_history(self):
        self.start(); self.send(self.input[:15])
        self.assertEqual(self.result()["orders"], 1)
        with self.broker.db: self.broker.db.execute("DELETE FROM orders")
        with self.worker.db: self.worker.db.execute("DELETE FROM intents")
        self.assert_fails_with("Intent journal/table mismatch")
        self.assert_fails_with("Simulator order lifecycle journal/table mismatch")

    def test_matching_request_edits_in_both_tables_cannot_override_journals(self):
        self.start(); self.send(self.input[:15])
        request = json.loads(self.worker.db.execute("SELECT request FROM intents").fetchone()[0])
        request["expires_at"] += 60
        with self.broker.db: self.broker.db.execute("UPDATE orders SET request=?", (canonical(request),))
        with self.worker.db: self.worker.db.execute("UPDATE intents SET request=?", (canonical(request),))
        self.assert_fails_with("Intent journal/table mismatch")
        self.assert_fails_with("Simulator order lifecycle journal/table mismatch")

    def test_matching_state_edits_cannot_fabricate_a_cancellation(self):
        self.start(); self.send(self.input[:15])
        with self.broker.db: self.broker.db.execute("UPDATE orders SET state='cancelled'")
        with self.worker.db: self.worker.db.execute("UPDATE intents SET state='cancelled'")
        self.assert_fails_with("Worker order state journal/table mismatch")
        self.assert_fails_with("Simulator order lifecycle journal/table mismatch")

    def test_partial_entry_and_partial_exit_leave_exact_remaining_lots(self):
        self.start(quantity=2, fill_cap=1)
        self.send(self.input[:17])
        self.assertEqual(self.result()["status"], "pass")
        self.assertEqual(self.result()["order_states"], {"partially_filled": 1})
        self.send(self.input[17:47])
        self.assertEqual(self.result()["status"], "pass")
        lot = dict(self.broker.db.execute("SELECT * FROM lots").fetchone())
        self.assertEqual((lot["id"], lot["qty"], lot["price"]), ("fill-000002", 1, 40018))
        self.send(self.input[47:])
        self.assertEqual(self.result()["status"], "pass")
        self.assertEqual(self.result()["completed_contract_units"], 2)

    def test_stop_removes_targeted_lot_not_the_fifo_accounting_lot(self):
        self.start(quantity=2, fill_cap=1)
        # The newer entry has a one-tick-higher stop. It stops while the older
        # protected lot remains, even though realized P&L is accounted FIFO.
        self.input[17]["low"] = 39938
        self.send(self.input[:18])
        self.assertEqual(self.result()["status"], "pass", self.result())
        lot = dict(self.broker.db.execute("SELECT * FROM lots").fetchone())
        self.assertEqual((lot["id"], lot["price"], lot["stop"]), ("fill-000001", 40017, 39937))
        self.send(self.input[18:])
        self.assertEqual(self.result()["status"], "pass", self.result())

    def test_partial_entry_expiry_preserves_its_filled_lot(self):
        self.start(quantity=2, fill_cap=1)
        for i in (17, 18, 19): self.input[i]["volume"] = 0
        self.send(self.input[:20])
        self.assertEqual(self.result()["status"], "pass", self.result())
        self.assertEqual(self.result()["order_states"], {"expired": 1})
        self.assertEqual(self.result()["account"]["position"], 1)

    def test_rejected_protection_is_a_valid_journal_lifecycle(self):
        self.start(reject="protection_rejected"); self.send(self.input)
        self.assertEqual(self.result()["status"], "pass", self.result())
        self.assertEqual(self.result()["order_states"], {"rejected": 1})

    def test_recovery_accepts_lost_acknowledgment_and_later_fill_observation(self):
        self.start(); self.send(self.input[:14])
        def interrupt(): raise RuntimeError("synthetic lost acknowledgment")
        self.worker.after_accept = interrupt
        bar = self.input[14]
        self.broker.advance(bar)
        with self.assertRaisesRegex(RuntimeError, "lost acknowledgment"): self.worker.step(bar)
        self.processed.append(bar)
        self.assertEqual(self.worker.db.execute("SELECT state FROM intents").fetchone()[0], "pending")
        # The simulated venue advances while the worker is unavailable.
        for bar in self.input[15:17]: self.broker.advance(bar)
        self.worker.close()
        self.worker = Worker(self.root/"worker.sqlite", self.spec, self.broker)
        self.worker.recover()
        self.assertEqual(self.worker.db.execute("SELECT state FROM intents").fetchone()[0], "filled")
        # Recovery can observe a terminal state without intermediate ACKs.
        self.send(self.input[15:])
        self.assertEqual(self.result()["status"], "pass", self.result())


if __name__ == "__main__": unittest.main()
