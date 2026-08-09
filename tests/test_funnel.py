"""
The funnel must not report health from history, and must always record the top
of the funnel.

Two separate defects met here to produce six silent days that read as "Healthy":

  1. The scheduler only ever QUERIED for today's DailyStats row and passed the
     result (possibly None) into the scanner, which counts a bar only
     `if daily_stats:`. Rows are otherwise created only when a signal executes,
     so bars_evaluated was recorded exclusively on days that had already traded.
  2. Every funnel verdict branch read whole-campaign aggregates, so one trade a
     week ago still satisfied `taken > 0` and printed "Healthy" indefinitely.
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from datetime import date, datetime

from tests.support import (add_daily, frozen_et, make_session, seed_account,
                           temp_project_dir)


def _campaign_meta():
    with open(os.path.join("data", "forward_test.json"), "w") as f:
        json.dump({"start_date": "2026-07-28", "target_days": 60,
                   "strategy": "multi_session", "symbols": ["MNQ"],
                   "start_equity": 50000.0}, f)


class TestFunnelRowIsAlwaysCreated(unittest.TestCase):
    def test_get_or_create_creates_a_missing_row(self):
        """
        The fix for the blind spot. Before this the scheduler had no way to
        create the row, so on a quiet day there was nowhere to count bars.
        """
        from backend.models.trade import DailyStats
        from backend.services.execution import get_or_create_daily_stats

        with frozen_et(datetime(2026, 8, 6, 10, 0)):
            db = make_session()
            seed_account(db, balance=51236.0)
            self.assertIsNone(
                db.query(DailyStats).filter(DailyStats.date == date(2026, 8, 6)).first()
            )
            row = get_or_create_daily_stats(db)
            self.assertIsNotNone(row)
            self.assertEqual(row.date, date(2026, 8, 6))
            self.assertEqual(row.starting_balance, 51236.0)

    def test_it_is_idempotent(self):
        """Called every cycle — must not create a second row or reset counters."""
        from backend.models.trade import DailyStats
        from backend.services.execution import get_or_create_daily_stats

        with frozen_et(datetime(2026, 8, 6, 10, 0)):
            db = make_session()
            seed_account(db)
            first = get_or_create_daily_stats(db)
            first.bars_evaluated = 17
            db.commit()

            again = get_or_create_daily_stats(db)
            self.assertEqual(again.id, first.id)
            self.assertEqual(again.bars_evaluated, 17, "counters were clobbered")
            self.assertEqual(db.query(DailyStats).count(), 1)

    def test_bars_can_now_be_counted_on_a_day_with_no_trades(self):
        """
        The regression itself: a day that evaluates bars but takes no trade must
        leave a row proving the engine looked. That distinction — looked and
        found nothing, vs never looked — is the entire point of the counter.
        """
        from backend.services.execution import get_or_create_daily_stats

        with frozen_et(datetime(2026, 8, 6, 10, 0)):
            db = make_session()
            seed_account(db)
            row = get_or_create_daily_stats(db)
            for _ in range(84):
                row.bars_evaluated = (row.bars_evaluated or 0) + 1
            db.commit()

            self.assertEqual(row.bars_evaluated, 84)
            self.assertEqual(row.signals_taken or 0, 0)


class TestFunnelStaleness(unittest.TestCase):
    def _funnel(self, db):
        from backend.main import funnel
        return asyncio.run(funnel(db=db))

    def test_six_silent_days_are_not_healthy(self):
        """The live failure: last activity Jul 30, asked on Aug 6."""
        with temp_project_dir():
            _campaign_meta()
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                add_daily(db, on=date(2026, 7, 29), bars=84, signals=11, taken=3, pnl=1236.0)
                add_daily(db, on=date(2026, 7, 30), bars=84, signals=0, taken=1, pnl=-350.0)

                out = self._funnel(db)
                self.assertEqual(out["last_activity_date"], "2026-07-30")
                self.assertEqual(out["days_since_activity"], 7)
                self.assertIn("STALE", out["verdict"])
                self.assertNotIn("Healthy", out["verdict"])

    def test_fresh_activity_is_still_reported_healthy(self):
        """Staleness must not swallow the genuinely-fine case."""
        with temp_project_dir():
            _campaign_meta()
            with frozen_et(datetime(2026, 8, 6, 12, 0)):
                db = make_session()
                seed_account(db)
                add_daily(db, on=date(2026, 8, 6), bars=84, signals=11, taken=3, pnl=900.0)

                out = self._funnel(db)
                self.assertEqual(out["days_since_activity"], 0)
                self.assertIn("Healthy", out["verdict"])

    def test_two_quiet_days_are_not_yet_flagged(self):
        """
        The threshold matches the project's own tripwire: three trading days.
        Flagging at one day would cry wolf every weekend.
        """
        with temp_project_dir():
            _campaign_meta()
            with frozen_et(datetime(2026, 8, 6, 12, 0)):
                db = make_session()
                seed_account(db)
                add_daily(db, on=date(2026, 8, 4), bars=84, signals=5, taken=2, pnl=100.0)

                out = self._funnel(db)
                self.assertEqual(out["days_since_activity"], 2)
                self.assertNotIn("STALE", out["verdict"])

    def test_a_row_with_bars_but_no_signals_counts_as_activity(self):
        """
        Looking and finding nothing IS the engine working. It must reset the
        staleness clock, or a legitimately quiet week would be called an outage.
        """
        with temp_project_dir():
            _campaign_meta()
            with frozen_et(datetime(2026, 8, 6, 12, 0)):
                db = make_session()
                seed_account(db)
                add_daily(db, on=date(2026, 7, 30), bars=84, signals=0, taken=0)
                add_daily(db, on=date(2026, 8, 6), bars=84, signals=0, taken=0)

                out = self._funnel(db)
                self.assertEqual(out["last_activity_date"], "2026-08-06")
                self.assertEqual(out["days_since_activity"], 0)
                self.assertNotIn("STALE", out["verdict"])


if __name__ == "__main__":
    unittest.main()
