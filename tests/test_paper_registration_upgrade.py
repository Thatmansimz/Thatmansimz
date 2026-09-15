"""A code fix can continue a stopped run without resetting its evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from backend.paperlab.continuous import ContinuousPaper, NS, code_hashes, register
from scripts.continuous_paper import amend_registration

ROOT = Path(__file__).resolve().parents[1]

class RegistrationUpgrade(unittest.TestCase):
    def test_backup_and_lineage_preserve_original_freeze_and_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp)/"run", Path(tmp)/"backup"
            spec = json.loads((ROOT/"evidence/continuous-paper-protocol.json").read_text())
            original = register(root, spec, implementation={"old.py":"old"}, now_ns=100*NS)
            service = ContinuousPaper(root, implementation={"old.py":"old"})
            (root/"STOP").write_text("review\n")
            with self.assertRaisesRegex(ValueError,"Stop the worker"):
                amend_registration(root, out, "Fix independently reproduced reconciliation defect")
            service.close()
            with contextlib.redirect_stdout(io.StringIO()):
                amend_registration(root, out, "Fix independently reproduced reconciliation defect")
            after = json.loads((root/"registration.json").read_text())
            self.assertEqual(after["registered_at_ns"], original["registered_at_ns"])
            self.assertEqual(after["protocol_sha256"], original["protocol_sha256"])
            self.assertEqual(after["code_sha256"], code_hashes())
            self.assertEqual(json.loads((out/"registration.json").read_text()), original)
            self.assertEqual(json.loads((root/after["implementation_amendments"][0]["previous_registration"]).read_text()), original)
            self.assertTrue((root/"STOP").exists())
            service = ContinuousPaper(root)
            self.assertEqual(service.snapshot()["scenarios"][0]["account"]["equity_cents"], 5000000)
            self.assertEqual(service.db.execute("SELECT count(*) FROM journal WHERE kind='implementation_amended'").fetchone()[0], 1)
            service.close()
            with self.assertRaisesRegex(ValueError, "already current"):
                amend_registration(root, Path(tmp)/"second", "Do not reset")

    def test_requires_stop_and_does_not_allow_protocol_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"run"
            spec = json.loads((ROOT/"evidence/continuous-paper-protocol.json").read_text())
            register(root,spec,implementation={"old.py":"old"})
            with self.assertRaisesRegex(ValueError,"deliberate STOP"):
                amend_registration(root,Path(tmp)/"backup","fix")
            (root/"STOP").touch()
            spec["stop_ticks"] += 1
            (root/"protocol.json").write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError,"cannot change"):
                amend_registration(root,Path(tmp)/"backup","fix")

if __name__ == "__main__": unittest.main()
