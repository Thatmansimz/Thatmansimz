"""Synthetic supervisor lifecycle; no SDK/network service is started."""
import contextlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.paperlab.continuous import register
from scripts import continuous_paper as cli

ROOT = Path(__file__).resolve().parents[1]

class PaperSupervisor(unittest.TestCase):
    def test_stuck_connector_exits_for_supervised_recovery_without_thread_leak(self):
        instances = []
        class StuckFeed:
            def __init__(self, key):
                self.closed = threading.Event()
                self.connection_done = threading.Event()
                self.connection_error = None
                instances.append(self)
            def begin(self): pass
            def close(self): self.closed.set()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';env=Path(tmp)/'private.env'
            register(root,json.loads((ROOT/'evidence/continuous-paper-protocol.json').read_text()))
            env.write_text('DATABENTO_API_KEY=synthetic\n')
            args=SimpleNamespace(run_dir=root,env_file=env,port=0,max_seconds=None)
            with patch.object(cli,'DatabentoFeed',StuckFeed), patch.object(cli.time,'monotonic',side_effect=itertools.count(0,30)), patch.object(cli.signal,'signal'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'feed_connect_cleanup_timeout'):
                    cli.run(args)
            self.assertEqual(len(instances),1)
            self.assertTrue(instances[0].closed.is_set())
            status=json.loads((root/'status.json').read_text())
            self.assertEqual(status['connection'],'stopped')
            self.assertEqual(status['last_error'],'feed_connect_timeout')
            self.assertTrue(all(s['account']['position']==0 and s['orders']==0 for s in status['scenarios']))

if __name__ == '__main__': unittest.main()
