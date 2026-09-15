"""Cloud-operation failure tests. Never contact Google or touch the actual run."""
from contextlib import ExitStack, closing
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'deploy/gcp'/f'{name}.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


class CloudOperationsTests(unittest.TestCase):
    def test_backup_verification_rejects_missing_changed_or_symlinked_files(self):
        verify = module('verify-backup').verify
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['receipts', 'baseline-worker', 'baseline-simulator', 'worse_costs-worker', 'worse_costs-simulator']:
                with closing(sqlite3.connect(root/f'{name}.sqlite')) as db: db.execute('CREATE TABLE test (id INTEGER)'); db.commit()
            (root/'registration.json').write_text(json.dumps({'run_id': 'synthetic', 'registered_at': 'synthetic', 'implementation_amendments': []}))
            (root/'protocol.json').write_text('{}')
            files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            (root/'manifest.json').write_text(json.dumps({'files': files}))
            self.assertEqual(verify(root)['files_verified'], 7)
            (root/'protocol.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'): verify(root)
            (root/'protocol.json').unlink()
            (root/'protocol.json').symlink_to(root/'registration.json')
            with self.assertRaisesRegex(ValueError, 'Unsafe'): verify(root)

    def maintenance(self, failure=None, stopped=False, hour=17):
        m = module('maintenance-backup')
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); run = root/'run'; run.mkdir(); backups = root/'backups'; backups.mkdir()
        config = root/'backup.json'; config.write_text('{"bucket":"synthetic-test-only"}')
        now = datetime(2026, 9, 15, hour, 15, tzinfo=ZoneInfo('America/New_York'))
        snapshot = {'protocol_sha256': m.PROTOCOL, 'hard_halt': None,
                    'observed_at': now.isoformat(), 'connection': 'streaming',
                    'scenarios': [{'account': {'position': 0}, 'reconciliation': 'pass'}]*2}
        (run/'status.json').write_text(json.dumps(snapshot))
        if stopped: (run/'STOP').write_text('Operator decision\n')
        actions = []
        def execute(*args):
            actions.append(args)
            if args[:2] == ('systemctl', 'stop'):
                (run/'status.json').write_text(json.dumps({**snapshot, 'connection': 'stopped'}))
            if 'backup' in args:
                if failure == 'backup': raise RuntimeError('synthetic backup failure')
                destination = Path(args[-1]); destination.mkdir(); (destination/'manifest.json').write_text('{}')
            if '--package-upload' in args:
                if failure == 'upload': raise RuntimeError('synthetic upload failure')
                return json.dumps({'status':'uploaded','backup':Path(args[-2]).name})
            if args[:2] == ('systemctl', 'start') and failure == 'start': raise RuntimeError('synthetic start failure')
        stack = ExitStack(); self.addCleanup(stack.close)
        for key,value in {'RUN':run,'BACKUPS':backups,'CONFIG':config,'MAINTENANCE_LOCK':root/'lock','MAINTENANCE_MARKER':root/'maintenance','BACKUP_REPORT':root/'report.json'}.items(): stack.enter_context(patch.object(m,key,value))
        stack.enter_context(patch.object(m.os,'geteuid',return_value=0))
        stack.enter_context(patch.object(m.time,'time',return_value=now.timestamp()))
        dt = stack.enter_context(patch.object(m,'datetime')); dt.now.return_value=now; dt.fromisoformat.side_effect=datetime.fromisoformat
        stack.enter_context(patch.object(m,'is_active',return_value=True))
        stack.enter_context(patch.object(m,'no_pending',return_value=True))
        stack.enter_context(patch.object(m,'execute',side_effect=execute))
        stack.enter_context(patch.object(m,'upload',side_effect=RuntimeError('synthetic upload failure') if failure=='upload' else None,return_value='synthetic-generation'))
        return m,run,actions

    def test_operator_stop_never_gets_removed_or_resumed(self):
        m,run,actions = self.maintenance(stopped=True)
        with self.assertRaisesRegex(ValueError,'Operator stop'):m.main()
        self.assertEqual((run/'STOP').read_text(),'Operator decision\n');self.assertFalse(actions)

    def test_morning_backup_cannot_exclude_the_next_opening(self):
        m,_,actions = self.maintenance(hour=8)
        with self.assertRaisesRegex(ValueError,'Maintenance allowed'):m.main()
        self.assertFalse(actions)

    def test_backup_or_upload_failure_fences_reboot_and_never_restarts(self):
        for failure in ['backup','upload']:
            with self.subTest(failure=failure):
                m,run,actions = self.maintenance(failure=failure)
                with self.assertRaises(RuntimeError):m.main()
                self.assertTrue(m.MAINTENANCE_MARKER.exists())
                self.assertFalse(any(a[:2]==('systemctl','start') for a in actions))

    def test_verified_uploaded_backup_can_resume(self):
        m,run,actions = self.maintenance()
        m.main();self.assertFalse((run/'STOP').exists())
        self.assertEqual(actions[-1],('systemctl','start','tajari-paper'))
        self.assertFalse(m.MAINTENANCE_MARKER.exists())

    def test_failed_restart_recreates_and_syncs_the_persistent_fence(self):
        m,_,actions = self.maintenance(failure='start')
        with patch.object(m.os, 'fsync', wraps=m.os.fsync) as sync:
            with self.assertRaisesRegex(RuntimeError, 'start failure'): m.main()
        self.assertEqual(actions[-1], ('systemctl','start','tajari-paper'))
        self.assertTrue(m.MAINTENANCE_MARKER.exists())
        # Initial file+directory, upload receipt, recreated file+directory.
        self.assertEqual(sync.call_count, 5)

    def test_abrupt_termination_during_stop_keeps_persistent_fence(self):
        m,_,_ = self.maintenance()
        with patch.object(m,'execute',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): m.main()
        self.assertTrue(m.MAINTENANCE_MARKER.exists())

    def test_existing_maintenance_fence_blocks_a_second_operation(self):
        m,_,actions=self.maintenance();m.MAINTENANCE_MARKER.write_text('prior-operation\n')
        with self.assertRaises(FileExistsError):m.main()
        self.assertFalse(actions)

    def test_open_position_cannot_be_stopped_by_maintenance(self):
        m,run,actions = self.maintenance()
        s=json.loads((run/'status.json').read_text());s['scenarios'][0]['account']['position']=1
        (run/'status.json').write_text(json.dumps(s))
        with self.assertRaisesRegex(ValueError,'Fresh, flat'):m.main()
        self.assertFalse(actions)


if __name__ == '__main__': unittest.main()
