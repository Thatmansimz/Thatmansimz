"""A code fix can continue a stopped run without resetting its evidence."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from backend.paperlab.continuous import ContinuousPaper, NS, code_hashes, register
from backend.paperlab.storage import connect
from scripts.continuous_paper import amend_registration

ROOT = Path(__file__).resolve().parents[1]

class RegistrationUpgrade(unittest.TestCase):
    def stopped_run(self, root):
        spec = json.loads((ROOT/"evidence/continuous-paper-protocol.json").read_text())
        original = register(root, spec, implementation={"old.py": "old"}, now_ns=100*NS)
        service = ContinuousPaper(root, implementation={"old.py": "old"})
        service.close()
        (root/"STOP").write_text("review\n")
        return original

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

    def test_backup_of_amended_run_restores_its_complete_registration_chain(self):
        import shutil
        from scripts.continuous_paper import backup
        with tempfile.TemporaryDirectory() as tmp:
            root, out, restored = Path(tmp)/"run", Path(tmp)/"backup", Path(tmp)/"restored"
            spec=json.loads((ROOT/"evidence/continuous-paper-protocol.json").read_text())
            register(root,spec,implementation={"old.py":"old"})
            service=ContinuousPaper(root,implementation={"old.py":"old"});service.close()
            (root/"STOP").touch()
            with contextlib.redirect_stdout(io.StringIO()):
                amend_registration(root,Path(tmp)/"before-upgrade","Audit fixes")
                backup(root,out)
            shutil.copytree(out,restored)
            service=ContinuousPaper(restored)
            self.assertEqual(service.reconcile()["baseline"]["status"],"pass")
            self.assertEqual(service.snapshot()["registered_at"],json.loads((root/"registration.json").read_text())["registered_at"])
            service.close()

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

    def test_process_crash_after_amendment_journal_blocks_previous_code_before_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp)/"run", Path(tmp)/"backup"
            self.stopped_run(root)
            original_bytes = (root/"registration.json").read_bytes()
            source = r'''
import os,sys
from pathlib import Path
from scripts import continuous_paper as cli
root,backup=map(Path,sys.argv[1:])
save=cli.atomic_json
def interrupt(path,value):
    if path == root/'registration.json': os._exit(87)
    return save(path,value)
cli.atomic_json=interrupt
cli.amend_registration(root,backup,'Synthetic crash after durable amendment event')
'''
            crashed = subprocess.run([sys.executable, "-c", source, str(root), str(out)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(crashed.returncode, 87, crashed.stderr)
            self.assertEqual((root/"registration.json").read_bytes(), original_bytes)
            db = connect(root/"receipts.sqlite")
            try:
                self.assertEqual(db.execute("SELECT count(*) FROM journal WHERE kind='implementation_amended'").fetchone()[0], 1)
            finally: db.close()
            with patch("backend.paperlab.continuous.ForwardWorker.recover") as recover:
                with self.assertRaisesRegex(ValueError, "journal/manifest mismatch"):
                    ContinuousPaper(root, implementation={"old.py": "old"})
                recover.assert_not_called()

    def test_missing_or_tampered_archive_blocks_startup_before_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"run"
            self.stopped_run(root)
            with contextlib.redirect_stdout(io.StringIO()):
                amend_registration(root, Path(tmp)/"backup", "Synthetic normal upgrade")
            registration = json.loads((root/"registration.json").read_text())
            archive = root/registration["implementation_amendments"][0]["previous_registration"]
            saved = archive.read_bytes()
            for condition in ("missing", "tampered"):
                with self.subTest(condition=condition):
                    if condition == "missing": archive.unlink()
                    else: archive.write_bytes(saved+b" ")
                    with patch("backend.paperlab.continuous.ForwardWorker.recover") as recover:
                        with self.assertRaisesRegex(ValueError, "Registration archive"):
                            ContinuousPaper(root)
                        recover.assert_not_called()
                    archive.write_bytes(saved)
            # Rejected startup must release its lock, allowing a repaired run.
            service = ContinuousPaper(root)
            self.assertEqual(service.audit_state, "pass")
            service.close()

    def test_archive_binds_original_registration_time_and_access_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"run"
            self.stopped_run(root)
            with contextlib.redirect_stdout(io.StringIO()):
                amend_registration(root, Path(tmp)/"backup", "Synthetic normal upgrade")
            registration = json.loads((root/"registration.json").read_text())
            for field, changed in (("registered_at_ns", 0), ("preflight", {"changed": True})):
                with self.subTest(field=field):
                    (root/"registration.json").write_text(json.dumps(dict(registration, **{field: changed})))
                    with patch("backend.paperlab.continuous.ForwardWorker.recover") as recover:
                        with self.assertRaisesRegex(ValueError, "original freeze"):
                            ContinuousPaper(root)
                        recover.assert_not_called()
            (root/"registration.json").write_text(json.dumps(registration))
            service = ContinuousPaper(root)
            self.assertEqual(service.registration["registered_at_ns"], 100*NS)
            service.close()

    def test_multiple_successful_amendments_keep_complete_archive_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"run"
            original = self.stopped_run(root)
            with contextlib.redirect_stdout(io.StringIO()):
                with patch("backend.paperlab.continuous.code_hashes", return_value={"middle.py": "middle"}):
                    amend_registration(root, Path(tmp)/"backup-1", "Synthetic intermediate version")
                amend_registration(root, Path(tmp)/"backup-2", "Synthetic final version")
            service = ContinuousPaper(root)
            self.assertEqual(service.registration["registered_at_ns"], original["registered_at_ns"])
            self.assertEqual(len(service.registration["implementation_amendments"]), 2)
            self.assertEqual(service.audit_state, "pass")
            service.close()

if __name__ == "__main__": unittest.main()
