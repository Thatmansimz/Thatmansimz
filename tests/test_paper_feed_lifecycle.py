"""Isolated adapter lifecycle tests; never authenticate or subscribe externally."""
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from backend.paperlab.feed import DatabentoFeed


class FeedLifecycle(unittest.TestCase):
    def test_hung_auth_does_not_block_close_or_start_a_cancelled_stream(self):
        entered, release, terminated = threading.Event(), threading.Event(), threading.Event()
        calls = []
        class FakeLive:
            def __init__(self, **kwargs): pass
            def subscribe(self, **kwargs):
                entered.set()
                release.wait(3)
            def add_callback(self, *a, **kw): calls.append("callback")
            def start(self): calls.append("start")
            def terminate(self): terminated.set()
        with patch.dict(sys.modules, databento=types.SimpleNamespace(Live=FakeLive)):
            feed = DatabentoFeed("synthetic-key")
            try:
                feed.begin()
                self.assertTrue(entered.wait(1))
                before = time.monotonic()
                feed.close()
                self.assertLess(time.monotonic()-before, .2)
                self.assertFalse(feed.connection_done.is_set())
                with self.assertRaisesRegex(ValueError, "only be started once"): feed.begin()
            finally:
                release.set()
                self.assertTrue(feed.connection_done.wait(2))
            self.assertTrue(terminated.is_set())
            self.assertEqual(calls, [])
            feed._put("heartbeat", None)
            self.assertTrue(feed.events.empty())

    def test_connect_error_redacts_credential_and_finishes(self):
        class FakeLive:
            def __init__(self, **kwargs):
                raise RuntimeError("authentication failed for " + kwargs["key"])
        with patch.dict(sys.modules, databento=types.SimpleNamespace(Live=FakeLive)):
            feed = DatabentoFeed("private-test-key")
            feed.begin()
            self.assertTrue(feed.connection_done.wait(2))
            self.assertNotIn("private-test-key", feed.connection_error)
            self.assertIn("[redacted]", feed.connection_error)
            feed.close()

if __name__ == "__main__": unittest.main()
