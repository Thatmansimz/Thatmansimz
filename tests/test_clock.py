"""
The clock: storage in UTC, decisions and display in ET.

These are the invariants that were silently violated while three clocks ran at
once — logs on host-local, the record on ET, timestamps on naive UTC.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import pytz

from backend import clock

ET = pytz.timezone("America/New_York")


class TestStorageIsUTC(unittest.TestCase):
    def test_utc_now_is_naive(self):
        """DB columns hold naive values; an aware one would change on write."""
        self.assertIsNone(clock.utc_now().tzinfo)

    def test_utc_now_actually_is_utc_not_local(self):
        """
        The value must be UTC, not the host's local time.

        On the Phoenix trading machine a local-time 'utcnow' would be 7 hours
        early and nothing in the schema would reveal it.
        """
        delta = abs((clock.utc_now() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds())
        self.assertLess(delta, 5, "utc_now() drifted from real UTC")

    def test_utc_now_matches_the_utcnow_it_replaced(self):
        """Byte-compatible with the deprecated call, so stored values keep meaning."""
        legacy = datetime.now(timezone.utc).replace(tzinfo=None)
        self.assertLess(abs((clock.utc_now() - legacy).total_seconds()), 5)


class TestDecisionsAreET(unittest.TestCase):
    def test_trading_day_is_the_et_date(self):
        self.assertEqual(clock.trading_day(), datetime.now(ET).date())

    def test_trading_day_can_differ_from_host_local_date(self):
        """
        The whole 'is it day 9 or day 10' confusion in one assertion.

        This does not assert they differ right now — it asserts the system is
        keyed to ET, so that when the host is Phoenix and it is past 9 PM local,
        the campaign day is already tomorrow's. That is correct behaviour, not
        an off-by-one.
        """
        et_9pm_phoenix = ET.localize(datetime(2026, 8, 5, 23, 30))  # 8:30 PM MST
        self.assertEqual(et_9pm_phoenix.date(), date(2026, 8, 5))
        phoenix = pytz.timezone("America/Phoenix")
        self.assertEqual(et_9pm_phoenix.astimezone(phoenix).date(), date(2026, 8, 5))
        # …and three hours later ET has rolled over while Phoenix has not.
        later = ET.localize(datetime(2026, 8, 6, 1, 30))
        self.assertEqual(later.date(), date(2026, 8, 6))
        self.assertEqual(later.astimezone(phoenix).date(), date(2026, 8, 5))


class TestDisplayConversion(unittest.TestCase):
    def test_naive_input_is_read_as_utc(self):
        stored = datetime(2026, 8, 6, 5, 0, 0)          # naive, as written to DB
        as_et = clock.utc_to_et(stored)
        self.assertEqual(as_et.hour, 1)                  # 05:00 UTC = 01:00 EDT
        self.assertEqual(as_et.date(), date(2026, 8, 6))

    def test_the_day_disagreement_this_fixes(self):
        """
        A trade entered 9 PM ET stores 01:00 UTC the NEXT calendar day.

        Read raw, its timestamp claims a different day than its own trade_date.
        Converted, the day agrees again — which is the bug this closes.
        """
        entry_et = ET.localize(datetime(2026, 8, 5, 21, 0))
        stored_naive_utc = entry_et.astimezone(timezone.utc).replace(tzinfo=None)
        self.assertEqual(stored_naive_utc.date(), date(2026, 8, 6))   # raw: Aug 6
        self.assertEqual(clock.utc_to_et(stored_naive_utc).date(), date(2026, 8, 5))

    def test_aware_input_is_converted_not_reinterpreted(self):
        aware = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(clock.utc_to_et(aware).hour, 1)

    def test_none_passes_through(self):
        self.assertIsNone(clock.utc_to_et(None))
        self.assertIsNone(clock.et_iso(None))

    def test_et_iso_is_labelled(self):
        """An unlabelled timestamp is how the clocks hid. Offset is mandatory."""
        out = clock.et_iso(datetime(2026, 8, 6, 5, 0, 0))
        self.assertTrue(out.endswith("-04:00") or out.endswith("-05:00"), out)


class TestExpectedCycles(unittest.TestCase):
    def test_past_day_is_a_full_day(self):
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.expected_cycles(yesterday), 1440)

    def test_today_is_only_the_elapsed_part(self):
        """
        The 3%-vs-100% bug. A healthy engine 43 minutes into the ET day has
        completed 43 of 43 possible cycles, not 43 of 1440.
        """
        now = datetime.now(ET)
        elapsed = max(1, now.hour * 60 + now.minute)
        self.assertEqual(clock.expected_cycles(clock.trading_day()), elapsed)
        self.assertLessEqual(clock.expected_cycles(clock.trading_day()), 1440)

    def test_future_day_does_not_divide_by_zero(self):
        ahead = clock.trading_day() + timedelta(days=5)
        self.assertGreaterEqual(clock.expected_cycles(ahead), 1)

    def test_denominator_follows_the_configured_interval(self):
        """
        Derived, not hardcoded. A 30s cycle doubles the cycles a healthy day
        produces; a hardcoded 1440 would silently halve every uptime figure.
        """
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.expected_cycles(yesterday, cycle_seconds=30), 2880)
        self.assertEqual(clock.expected_cycles(yesterday, cycle_seconds=120), 720)


class TestUptimePct(unittest.TestCase):
    def test_full_past_day_is_100(self):
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.uptime_pct(1440, yesterday), 100.0)

    def test_partial_past_day(self):
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.uptime_pct(1290, yesterday), 89.6)

    def test_healthy_engine_early_in_the_day_reads_100_not_3(self):
        """
        The exact regression. 43 cycles at 00:43 ET is a perfectly healthy
        engine — it used to render as 3% (43/1440) in the snapshot rows.
        """
        with mock.patch("backend.clock.et_now",
                        return_value=ET.localize(datetime(2026, 8, 6, 0, 43))), \
             mock.patch("backend.clock.trading_day",
                        return_value=date(2026, 8, 6)):
            self.assertEqual(clock.uptime_pct(43, date(2026, 8, 6)), 100.0)
            self.assertAlmostEqual(round(43 / 1440 * 100, 1), 3.0, places=1)

    def test_never_exceeds_100(self):
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.uptime_pct(99999, yesterday), 100.0)

    def test_none_cycles_is_zero(self):
        self.assertEqual(clock.uptime_pct(None, clock.trading_day() - timedelta(days=1)), 0.0)


class TestCadenceAssumption(unittest.TestCase):
    """
    Uptime is only as correct as the assumed seconds-per-cycle. The live engine
    cycles every ~120s (sleep 60s THEN fetch), so against a 60s assumption a
    continuously-running day reads ~56% instead of ~100%.
    """

    def test_default_is_60_seconds(self):
        self.assertEqual(clock.DEFAULT_CYCLE_SECONDS, 60)

    def test_settings_can_override_the_cadence(self):
        from backend.config import settings
        with mock.patch.object(settings, "SCHEDULER_CYCLE_SECONDS", 120):
            self.assertEqual(clock.configured_cycle_seconds(), 120)

    def test_a_nonsense_cadence_falls_back_to_the_default(self):
        from backend.config import settings
        for bad in (0, -5):
            with mock.patch.object(settings, "SCHEDULER_CYCLE_SECONDS", bad):
                self.assertEqual(clock.configured_cycle_seconds(),
                                 clock.DEFAULT_CYCLE_SECONDS)

    def test_the_live_discrepancy_is_reproducible(self):
        """
        Aug 5 recorded 807 cycles on a day the engine ran throughout. The
        assumption alone moves that between 'degraded' and 'healthy'.
        """
        yesterday = clock.trading_day() - timedelta(days=1)
        self.assertEqual(clock.uptime_pct(807, yesterday, 60), 56.0)
        self.assertEqual(clock.uptime_pct(807, yesterday, 120), 100.0)

    def test_the_assumption_is_published_with_the_number(self):
        """An uptime% without its denominator's basis is uninterpretable."""
        from backend.models.trade import EquitySnapshot
        snap = EquitySnapshot(date=clock.trading_day() - timedelta(days=1),
                              cycles=807, balance=0.0, equity=0.0)
        d = snap.to_dict()
        self.assertIn("cycle_seconds_assumed", d)
        self.assertIn("expected_cycles", d)
        self.assertEqual(d["cycle_seconds_assumed"], clock.configured_cycle_seconds())

    def test_uptime_is_not_self_calibrating(self):
        """
        Guard against a tempting 'fix': inferring the cadence from observed
        cycles would make the denominator track the numerator and every day
        would read 100%, destroying the only downtime signal there is.
        """
        yesterday = clock.trading_day() - timedelta(days=1)
        healthy = clock.uptime_pct(1440, yesterday, 60)
        degraded = clock.uptime_pct(200, yesterday, 60)
        self.assertEqual(healthy, 100.0)
        self.assertLess(degraded, 20.0,
                        "a mostly-down day must not report as healthy")


if __name__ == "__main__":
    unittest.main()
