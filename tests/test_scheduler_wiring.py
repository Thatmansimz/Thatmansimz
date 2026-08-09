"""
The scheduler must CREATE today's funnel row, not merely look for it.

Testing the helper in isolation is not enough: the original bug was entirely in
the call site. execution.get_or_create_daily_stats could have existed and been
perfect, and the six silent days would still have had no bar counts, because
scheduler._run_cycle called `db.query(DailyStats)...first()` and passed the
possibly-None result into the scanner.

These are source-level assertions on the wiring. They are deliberately blunt —
a structural guard is what catches a refactor that reverts the call site while
every behavioural test still passes.
"""
from __future__ import annotations

import inspect
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCHEDULER = REPO / "backend" / "services" / "scheduler.py"


class TestSchedulerCreatesTheFunnelRow(unittest.TestCase):
    def setUp(self):
        self.src = SCHEDULER.read_text()

    def test_scheduler_calls_get_or_create(self):
        self.assertIn(
            "get_or_create_daily_stats", self.src,
            "the scheduler no longer creates today's DailyStats row — "
            "bars_evaluated will silently stop being recorded on quiet days",
        )

    def test_the_row_passed_to_the_scanner_comes_from_get_or_create(self):
        """
        Guards the ordering. today_stats must be reassigned from
        get_or_create_daily_stats BEFORE it reaches _scan_symbol.
        """
        create_at = self.src.find("today_stats = get_or_create_daily_stats(")
        scan_at = self.src.find("self._scan_symbol(")
        self.assertNotEqual(create_at, -1, "today_stats is not created at all")
        self.assertNotEqual(scan_at, -1, "_scan_symbol call vanished")
        self.assertLess(create_at, scan_at,
                        "the row is created after the scan — bars will not be counted")

    def test_row_is_created_after_the_can_trade_gate(self):
        """
        Ordering matters the other way too. Creating the row above the gate
        would manufacture empty rows on weekends and holidays, and an absent
        row is the signal that the market never opened. A present row with
        bars_evaluated == 0 must keep meaning 'the engine looked and saw
        nothing' — that is the blind-engine tell.
        """
        gate_at = self.src.find("can_trade, reason = self.risk_manager.check_can_trade(")
        create_at = self.src.find("today_stats = get_or_create_daily_stats(")
        self.assertNotEqual(gate_at, -1)
        self.assertLess(gate_at, create_at,
                        "row created before the market-open gate — weekends will "
                        "produce empty rows and mask real outages")

    def test_scanner_still_guards_against_a_missing_row(self):
        """The defensive `if daily_stats:` must remain — belt and braces."""
        scan_src = self.src[self.src.find("async def _scan_symbol"):]
        self.assertRegex(scan_src, r"if daily_stats:",
                         "lost the None-guard in _scan_symbol")

    def test_bars_evaluated_is_still_incremented(self):
        self.assertRegex(
            self.src, r"daily_stats\.bars_evaluated\s*=\s*\(daily_stats\.bars_evaluated or 0\)\s*\+\s*1",
            "the bar counter increment was removed",
        )


class TestSchedulerImportsAreSane(unittest.TestCase):
    def test_no_duplicate_local_et_definition(self):
        """The scheduler should not mint its own timezone."""
        from backend.services import scheduler
        self.assertTrue(hasattr(scheduler, "ET"), "scheduler lost its ET reference")

    def test_scheduler_module_imports(self):
        from backend.services import scheduler
        self.assertTrue(inspect.ismodule(scheduler))


if __name__ == "__main__":
    unittest.main()
