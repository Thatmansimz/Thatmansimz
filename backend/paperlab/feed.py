"""Databento adapter: bounded callbacks; no history replay or trading API."""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from .continuous import NS


class DatabentoFeed:
    def __init__(self, key):
        self.key, self.client = key, None
        self.events = queue.Queue(maxsize=4096)
        self.overflow = threading.Event()
        self.closed = threading.Event()
        self.connection_done = threading.Event()
        self.connection_error = None
        self.connection_thread = None

    def safe_error(self, exc):
        return re.sub(r"db-[A-Za-z0-9_-]+", "[redacted]", str(exc).replace(self.key, "[redacted]"))[:300]

    def _put(self, kind, payload, received=None):
        if self.closed.is_set(): return
        try: self.events.put_nowait((kind, payload, received if received is not None else time.time_ns()))
        except queue.Full: self.overflow.set()

    def begin(self):
        """Connect away from the supervisor so DNS/auth cannot block STOP/status."""
        if self.connection_thread is not None:
            raise ValueError("A feed connection may only be started once")
        def connect():
            try:
                self.start()
            except Exception as exc:
                self.connection_error = self.safe_error(exc)
            finally:
                if self.closed.is_set(): self._terminate()
                self.connection_done.set()
        self.connection_thread = threading.Thread(target=connect, daemon=True)
        self.connection_thread.start()

    def start(self):
        import databento as db
        # Do not allow SDK debug logs to include credentials or raw records.
        logging.getLogger("databento").setLevel(logging.CRITICAL)
        self.client = db.Live(key=self.key, heartbeat_interval_s=5, reconnect_policy="none")

        def callback(msg):
            received = time.time_ns()
            if isinstance(msg, db.ErrorMsg):
                self._put("error", self.safe_error(msg.err), received)
            elif isinstance(msg, db.SymbolMappingMsg):
                self._put("mapping", {"instrument_id": int(msg.instrument_id), "symbol": str(msg.stype_out_symbol),
                          "start_ns": int(msg.start_ts), "end_ns": int(msg.end_ts)}, received)
            elif isinstance(msg, db.OHLCVMsg):
                # DBN fixed-point prices are 1e-9 dollars; an MNQ tick is 0.25.
                fields = {k: int(getattr(msg, k)) for k in ("open", "high", "low", "close")}
                if int(msg.ts_event) % (60*NS) or any(v <= 0 or v % 250_000_000 for v in fields.values()):
                    self._put("invalid", "Unaligned Databento minute or tick", received)
                    return
                self._put("bar", {"ts": int(msg.ts_event)//NS, "instrument_id": int(msg.instrument_id),
                          "volume": int(msg.volume), **{k: v//250_000_000 for k, v in fields.items()}}, received)
            else:
                self._put("heartbeat", None, received)

        if self.closed.is_set(): return
        self.client.subscribe(dataset="GLBX.MDP3", schema="ohlcv-1m", stype_in="continuous", symbols=["MNQ.v.0"])
        if self.closed.is_set(): return
        self.client.add_callback(callback, exception_callback=lambda e: self._put("error", self.safe_error(e)))
        self.client.start()

    def _terminate(self):
        if self.client:
            try: self.client.terminate()
            except ValueError: pass  # SDK can refuse termination before subscribe.
            self.client = None

    def close(self):
        self.closed.set()
        # subscribe holds an SDK lock during DNS/auth. Never wait for that lock
        # on the supervisor thread. The connecting thread cleans up on return.
        if self.connection_thread is None or self.connection_done.is_set():
            threading.Thread(target=self._terminate, daemon=True).start()

    def is_connected(self):
        return bool(self.client and self.client.is_connected())
