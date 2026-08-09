"""
A benchmark is only a benchmark if it describes the running system AND beating
it means something.

/api/record scaled a stored backtest into an "expected to date" figure and
published it next to live results with no validity check at all. By Aug 2026 the
regenerated baseline was PF 0.96 / -$932.53 over 30 days, produced across ALL
THREE sessions, while the engine ran NEW_YORK only at 3.0R. The dashboard
therefore showed expected -$310.84 against actual +$886.00 — reading as
"beating expectations by ~$1,200" when the benchmark was a losing system
measuring a different strategy. Any positive number beats a negative bar.
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from datetime import date, datetime
from unittest import mock

from tests.support import (add_trade, frozen_et, make_session, seed_account,
                           temp_project_dir)


def _write_campaign():
    with open(os.path.join("data", "forward_test.json"), "w") as f:
        json.dump({"start_date": "2026-07-28", "target_days": 60,
                   "strategy": "multi_session", "symbols": ["MNQ"],
                   "start_equity": 50000.0}, f)


def _write_baseline(**overrides):
    payload = {
        "generated_at": "2026-07-29T21:44:07",
        "symbol": "MNQ", "period": "30d", "days": 30,
        "total_trades": 95, "win_rate": 29.47, "profit_factor": 0.96,
        "total_pnl": -932.53, "avg_win": 798.76, "avg_loss": -347.73,
        "by_session": {"LONDON": -1391.8, "NEW_YORK": 669.51, "ASIA": -210.23},
        "commission_per_side": 1.5, "slippage_ticks": 1,
    }
    payload.update(overrides)
    with open(os.path.join("data", "baseline.json"), "w") as f:
        json.dump(payload, f)
    return payload


class TestBaselineComparability(unittest.TestCase):
    def _record(self, db):
        from backend.main import record
        return asyncio.run(record(db=db))

    def _run(self, db, *, sessions=None, target_rr=0.0):
        from backend.config import settings
        with mock.patch.object(settings, "V2_SESSIONS", sessions or ["NEW_YORK"]), \
             mock.patch.object(settings, "V2_TARGET_RR", target_rr):
            return self._record(db)

    def test_the_exact_live_situation_is_flagged_not_comparable(self):
        """The real Aug 2026 state: losing baseline, wrong session set."""
        with temp_project_dir():
            _write_campaign()
            _write_baseline()          # PF 0.96, no `sessions` key recorded
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)

                exp = out["expected"]
                self.assertFalse(exp["comparable"])
                joined = " ".join(exp["warnings"])
                self.assertIn("UNPROFITABLE", joined)
                self.assertIn("0.96", joined)

    def test_unprofitable_baseline_is_called_out(self):
        with temp_project_dir():
            _write_campaign()
            _write_baseline(profit_factor=0.96, sessions=["NEW_YORK"])
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)
                exp = out["expected"]
                self.assertFalse(exp["comparable"])
                self.assertTrue(any("UNPROFITABLE" in w for w in exp["warnings"]))

    def test_session_mismatch_is_called_out(self):
        """
        A three-session backtest cannot benchmark a one-session live run — the
        per-day P&L and trade frequency are simply different quantities.
        """
        with temp_project_dir():
            _write_campaign()
            _write_baseline(profit_factor=1.34, total_pnl=5127.0,
                            sessions=["ASIA", "LONDON", "NEW_YORK"])
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db, sessions=["NEW_YORK"])
                exp = out["expected"]
                self.assertFalse(exp["comparable"])
                joined = " ".join(exp["warnings"])
                self.assertIn("NEW_YORK", joined)
                self.assertIn("not comparable", joined)

    def test_missing_session_metadata_is_not_silently_trusted(self):
        """An unverifiable benchmark must not present as verified."""
        with temp_project_dir():
            _write_campaign()
            _write_baseline(profit_factor=1.34, total_pnl=5127.0)  # no sessions key
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)
                exp = out["expected"]
                self.assertFalse(exp["comparable"])
                self.assertTrue(any("records no session set" in w for w in exp["warnings"]))

    def test_target_rr_mismatch_is_called_out(self):
        with temp_project_dir():
            _write_campaign()
            _write_baseline(profit_factor=1.34, total_pnl=5127.0,
                            sessions=["NEW_YORK"], target_rr=2.0)
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db, sessions=["NEW_YORK"], target_rr=3.0)
                exp = out["expected"]
                self.assertFalse(exp["comparable"])
                self.assertTrue(any("3.0R" in w or "2.0R" in w for w in exp["warnings"]))

    def test_a_genuinely_matching_profitable_baseline_is_comparable(self):
        """
        The guard must not simply always say 'no'. A profitable baseline that
        matches the live config is a legitimate benchmark.
        """
        with temp_project_dir():
            _write_campaign()
            _write_baseline(profit_factor=1.34, total_pnl=5127.0,
                            sessions=["NEW_YORK"], target_rr=3.0)
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db, sessions=["NEW_YORK"], target_rr=3.0)
                exp = out["expected"]
                self.assertTrue(exp["comparable"], exp["warnings"])
                self.assertEqual(exp["warnings"], [])


class TestExpectedScaling(unittest.TestCase):
    def _run(self, db):
        from backend.config import settings
        from backend.main import record
        with mock.patch.object(settings, "V2_SESSIONS", ["NEW_YORK"]), \
             mock.patch.object(settings, "V2_TARGET_RR", 3.0):
            return asyncio.run(record(db=db))

    def test_day_index_and_days_elapsed_are_both_published_and_differ_by_one(self):
        with temp_project_dir():
            _write_campaign()
            _write_baseline()
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)
                self.assertEqual(out["day_index"], 10)
                self.assertEqual(out["days_elapsed"], 9)

    def test_on_the_start_date_zero_days_have_elapsed(self):
        """The old field returned 1 here, inflating every scaled figure."""
        with temp_project_dir():
            _write_campaign()
            _write_baseline()
            with frozen_et(datetime(2026, 7, 28, 18, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)
                self.assertEqual(out["day_index"], 1)
                self.assertEqual(out["days_elapsed"], 0)

    def test_expected_to_date_uses_day_index(self):
        with temp_project_dir():
            _write_campaign()
            _write_baseline()   # -932.53 over 30d = -31.084/day
            with frozen_et(datetime(2026, 8, 6, 1, 0)):
                db = make_session()
                seed_account(db)
                out = self._run(db)
                exp = out["expected"]
                self.assertEqual(exp["per_day"], -31.08)
                self.assertAlmostEqual(exp["to_date"], round(-932.53 / 30 * 10, 2), places=2)


if __name__ == "__main__":
    unittest.main()
