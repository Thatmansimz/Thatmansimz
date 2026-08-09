"""
One day must not have two different uptime numbers.

/api/forward-test/status reported today's uptime as 100.0 at the top level and
3.0 in the snapshot row for the same date, in the same response, because the two
call sites had independent formulas: forward_test divided by minutes elapsed
(right) and EquitySnapshot.to_dict by a hardcoded 1440 (wrong for today).
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date, datetime, timedelta

from tests.support import (add_snapshot, frozen_et, make_session, seed_account,
                           temp_project_dir)


class TestUptimeAgreesAcrossCallSites(unittest.TestCase):
    def test_snapshot_row_and_top_level_agree_for_today(self):
        from backend.services.forward_test import campaign_status

        # 00:43 ET — 43 minutes into the exchange day, 43 cycles completed.
        # A perfectly healthy engine.
        with temp_project_dir():
            with open(os.path.join("data", "forward_test.json"), "w") as f:
                json.dump({"start_date": "2026-07-28", "target_days": 60,
                           "strategy": "multi_session", "symbols": ["MNQ"],
                           "start_equity": 50000.0}, f)

            with frozen_et(datetime(2026, 8, 6, 0, 43)):
                db = make_session()
                seed_account(db)
                snap = add_snapshot(db, on=date(2026, 8, 6), cycles=43)

                status = campaign_status(db)
                row = next(s for s in status["snapshots"]
                           if s["date"] == "2026-08-06")

                self.assertEqual(
                    row["uptime_pct"], status["uptime_today_pct"],
                    "snapshot row and top-level uptime disagree for the same day",
                )
                self.assertEqual(status["uptime_today_pct"], 100.0)
                # And prove the old formula would have said something else.
                self.assertEqual(round(43 / 1440 * 100, 1), 3.0)

    def test_past_day_still_measured_against_the_whole_day(self):
        """Fixing today must not inflate history: a past day keeps 1440."""
        from backend.services.forward_test import campaign_status

        with temp_project_dir():
            with open(os.path.join("data", "forward_test.json"), "w") as f:
                json.dump({"start_date": "2026-07-28", "target_days": 60,
                           "strategy": "multi_session", "symbols": ["MNQ"],
                           "start_equity": 50000.0}, f)

            with frozen_et(datetime(2026, 8, 6, 0, 43)):
                db = make_session()
                seed_account(db)
                add_snapshot(db, on=date(2026, 8, 5), cycles=1290)
                add_snapshot(db, on=date(2026, 8, 6), cycles=43)

                status = campaign_status(db)
                rows = {s["date"]: s for s in status["snapshots"]}
                self.assertEqual(rows["2026-08-05"]["uptime_pct"], 89.6)
                self.assertEqual(rows["2026-08-06"]["uptime_pct"], 100.0)

    def test_a_genuinely_degraded_day_is_still_reported_as_degraded(self):
        """
        The fix must not simply force 100%. Half the cycles for the elapsed
        window is 50%, not a healthy reading.
        """
        from backend.services.forward_test import campaign_status

        with temp_project_dir():
            with open(os.path.join("data", "forward_test.json"), "w") as f:
                json.dump({"start_date": "2026-07-28", "target_days": 60,
                           "strategy": "multi_session", "symbols": ["MNQ"],
                           "start_equity": 50000.0}, f)

            with frozen_et(datetime(2026, 8, 6, 10, 0)):   # 600 minutes elapsed
                db = make_session()
                seed_account(db)
                add_snapshot(db, on=date(2026, 8, 6), cycles=300)
                status = campaign_status(db)
                self.assertEqual(status["uptime_today_pct"], 50.0)


class TestDayCounting(unittest.TestCase):
    def test_day_index_is_one_based_and_days_elapsed_is_a_count(self):
        """
        On the start date it is day 1, but ZERO days have elapsed. The field was
        named days_elapsed while holding the index, so it claimed a day had
        passed before any had — and every multiplication inherited that.
        """
        from backend.services.forward_test import campaign_status

        with temp_project_dir():
            with open(os.path.join("data", "forward_test.json"), "w") as f:
                json.dump({"start_date": "2026-07-28", "target_days": 60,
                           "strategy": "multi_session", "symbols": ["MNQ"],
                           "start_equity": 50000.0}, f)

            with frozen_et(datetime(2026, 7, 28, 12, 0)):
                db = make_session()
                seed_account(db)
                status = campaign_status(db)
                self.assertEqual(status["day"], 1)
                self.assertEqual(status["days_elapsed"], 0)

            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                status = campaign_status(db)
                self.assertEqual(status["day"], 10)
                self.assertEqual(status["days_elapsed"], 9)

    def test_both_clocks_are_published_when_they_disagree(self):
        """
        At 01:00 ET the host in Phoenix is still on the previous date. Publish
        both so 'why does it say day 10' is answerable from the payload rather
        than looking like an off-by-one bug.
        """
        from backend.services.forward_test import campaign_status

        with temp_project_dir():
            with open(os.path.join("data", "forward_test.json"), "w") as f:
                json.dump({"start_date": "2026-07-28", "target_days": 60,
                           "strategy": "multi_session", "symbols": ["MNQ"],
                           "start_equity": 50000.0}, f)

            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                status = campaign_status(db)
                self.assertEqual(status["exchange_date"], "2026-08-06")
                self.assertIn("host_local_date", status)


if __name__ == "__main__":
    unittest.main()
