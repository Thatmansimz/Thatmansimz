"""
A row must not disagree with itself about what day it happened.

trade_date is the ET date; entry_time/exit_time are naive UTC. For any trade
entered between 8 PM and midnight ET — the Asia kill zone — the raw timestamp
lands on the NEXT calendar day, so the record appeared internally inconsistent
to anyone reconciling the two columns. Storage stays UTC (existing rows keep
their meaning); the fix is that the ET reading is now published alongside it.

Also guards the fourth clock: trade_date used to default to date.today(), the
HOST's local date, which on this Phoenix machine is a different calendar day
from ET for three hours every night.
"""
from __future__ import annotations

import pathlib
import re
import unittest
from datetime import date, datetime, timezone

import pytz

from backend import clock
from backend.models.trade import Trade
from tests.support import add_trade, make_session

ET = pytz.timezone("America/New_York")
REPO = pathlib.Path(__file__).resolve().parent.parent


class TestRowSelfConsistency(unittest.TestCase):
    def test_asia_kill_zone_trade_agrees_with_its_own_trade_date(self):
        """
        9 PM ET on Aug 5 stores 01:00 UTC on Aug 6. Raw, the timestamp says
        Aug 6 while trade_date says Aug 5. The ET reading must reconcile them.
        """
        entry_et = ET.localize(datetime(2026, 8, 5, 21, 0))
        stored = entry_et.astimezone(timezone.utc).replace(tzinfo=None)

        db = make_session()
        t = add_trade(db, trade_date=date(2026, 8, 5), entry_time=stored, net_pnl=250.0)
        d = t.to_dict()

        # The raw column really does name a different day — this is the trap.
        self.assertEqual(datetime.fromisoformat(d["entry_time"]).date(), date(2026, 8, 6))
        self.assertEqual(d["trade_date"], "2026-08-05")
        # …and the ET reading agrees with trade_date again.
        self.assertEqual(
            datetime.fromisoformat(d["entry_time_et"]).date(), date(2026, 8, 5),
            "entry_time_et must land on the same exchange day as trade_date",
        )

    def test_new_york_session_trade_is_unambiguous(self):
        """A 2 PM ET trade never crossed a day boundary; both readings match."""
        entry_et = ET.localize(datetime(2026, 7, 30, 14, 1))
        stored = entry_et.astimezone(timezone.utc).replace(tzinfo=None)

        db = make_session()
        t = add_trade(db, trade_date=date(2026, 7, 30), entry_time=stored, net_pnl=-350.0)
        d = t.to_dict()
        self.assertEqual(datetime.fromisoformat(d["entry_time_et"]).date(), date(2026, 7, 30))
        self.assertEqual(d["trade_date"], "2026-07-30")

    def test_et_fields_are_labelled_with_an_offset(self):
        db = make_session()
        t = add_trade(db, trade_date=date(2026, 8, 5),
                      entry_time=datetime(2026, 8, 6, 1, 0), net_pnl=1.0)
        d = t.to_dict()
        self.assertRegex(d["entry_time_et"], r"[-+]\d{2}:\d{2}$")

    def test_null_timestamps_do_not_crash(self):
        db = make_session()
        t = Trade(symbol="MNQ", side="long", qty=1, status="pending",
                  trade_date=date(2026, 8, 6))
        db.add(t)
        db.commit()
        d = t.to_dict()
        self.assertIsNone(d["exit_time"])
        self.assertIsNone(d["exit_time_et"])


class TestTradeDateDefaultIsExchangeTime(unittest.TestCase):
    def test_default_is_trading_day_not_date_today(self):
        """
        The fourth clock. date.today() is the host's local date; on Phoenix it
        disagrees with ET for three hours every night, so a trade created
        without an explicit trade_date would be filed under the wrong day.
        """
        default = Trade.__table__.c.trade_date.default
        self.assertIsNotNone(default, "trade_date lost its default")
        fn = default.arg
        self.assertTrue(callable(fn))
        # Identity fails here by design: SQLAlchemy wraps a zero-argument
        # callable in a shim that accepts the ExecutionContext, so .arg is a
        # functools.wraps wrapper rather than the original object. Assert on the
        # preserved identity instead, and unwrap when the attribute is present.
        target = getattr(fn, "__wrapped__", fn)
        self.assertEqual(getattr(target, "__name__", None), "trading_day",
                         f"trade_date defaults to {getattr(target, '__name__', target)!r}, "
                         "which is not the exchange clock")
        self.assertEqual(getattr(target, "__module__", None), "backend.clock")
        self.assertNotIn("today", getattr(target, "__name__", ""),
                         "trade_date is back on the host clock")

    def test_the_default_actually_produces_the_et_date(self):
        db = make_session()
        t = Trade(symbol="MNQ", side="long", qty=1, status="pending")
        db.add(t)
        db.commit()
        self.assertEqual(t.trade_date, clock.trading_day())


class TestNoRegressionToHiddenClocks(unittest.TestCase):
    """Static guards, so the clocks cannot quietly multiply again."""

    def _sources(self):
        for base in ("backend", "scripts"):
            for p in (REPO / base).rglob("*.py"):
                if "__pycache__" in p.parts:
                    continue
                yield p

    def test_no_naive_datetime_utcnow_anywhere(self):
        """
        Deprecated since Python 3.12 (this project runs 3.14) and the source of
        the undeclared-UTC problem. All storage goes through clock.utc_now().
        """
        offenders = []
        for p in self._sources():
            if p.name == "clock.py":
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if re.search(r'\butcnow\s*\(', line):
                    offenders.append(f"{p.relative_to(REPO)}:{i}")
        self.assertEqual(offenders, [], f"naive utcnow() reintroduced: {offenders}")

    def test_no_date_today_used_for_record_keying(self):
        """
        date.today() / datetime.now() without a timezone is the host clock.
        Permitted only where a host-local reading is the explicit intent.
        """
        allowed = {"backend/services/forward_test.py"}   # publishes host_local_date on purpose
        offenders = []
        for p in self._sources():
            rel = str(p.relative_to(REPO))
            if p.name == "clock.py" or rel in allowed:
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r'\bdate\.today\s*\(', line):
                    offenders.append(f"{rel}:{i}")
        self.assertEqual(offenders, [], f"host-clock date keying found: {offenders}")

    def test_clock_module_is_the_only_place_defining_et(self):
        """
        Every module used to localize its own pytz timezone. Duplicated
        definitions are how the ET/UTC/local split survived so long.
        """
        offenders = []
        for p in self._sources():
            if p.name == "clock.py":
                continue
            text = p.read_text()
            if 'pytz.timezone("America/New_York")' in text:
                offenders.append(str(p.relative_to(REPO)))
        # Not yet zero across the whole tree — assert the files this change
        # owns are clean, so the direction of travel is enforced.
        for owned in ("backend/services/execution.py", "backend/models/trade.py"):
            self.assertNotIn(owned, offenders,
                             f"{owned} still defines its own ET timezone")


if __name__ == "__main__":
    unittest.main()
