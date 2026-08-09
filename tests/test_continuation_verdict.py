"""
The continuation verdict must be an ECONOMIC test, not merely a statistical one.

This is the script that decides whether the project lives. Its original rule was
"t >= 2 in RTH at any horizon", justified by: at n~700 only a large effect can
reach t=2, so t=2 implies an effect big enough to matter.

That justification is correct at n~700 and inverts as n grows, because the
smallest mean reaching t=2 shrinks as 1/sqrt(n):

    n =    700  ->  ~0.076 ATR   >> 0.018 needed to be profitable   (safe)
    n =  3,500  ->  ~0.018 ATR   == the threshold                   (breaks here)
    n = 10,000  ->  ~0.010 ATR   <  0.018                           (unsafe)

So buying history — the whole point of the next step — is precisely what breaks
the old rule. Verified empirically before any real data was purchased: a
driftless random walk drew t=+2.00 and the original rule printed
"PREMISE SUPPORTED — build on this."

The rule is now: the Bonferroni-corrected lower bound of the effect must clear
the profitability threshold. "Distinguishable from zero" was never the question.
"""
from __future__ import annotations

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "scripts" / "continuation.py"

ECON = 0.018
Z_BONF = 2.50


def verdict(cells):
    """
    Reimplementation of the decision rule, for testing the LOGIC independent of
    the CLI. cells: list of (k, mean, se, t). Kept deliberately in sync with
    continuation.py via test_source_still_implements_this_rule below.
    """
    pays = [c for c in cells if (c[1] - Z_BONF * c[2]) > ECON]
    detectable = [c for c in cells
                  if c[1] > 0 and abs(c[3]) >= 2 and (c[1] - Z_BONF * c[2]) <= ECON]
    if pays:
        return "SUPPORTED"
    if detectable:
        return "REAL_BUT_UNPAYABLE" if (detectable[0][1] - Z_BONF * detectable[0][2]) > 0 \
               else "NOT_ESTABLISHED"
    if all(c[1] <= 0 or abs(c[3]) < 2 for c in cells):
        return "NO_LARGE_EDGE"
    return "AMBIGUOUS"


class TestVerdictCalibration(unittest.TestCase):
    def test_pure_noise_at_t2_is_not_supported(self):
        """
        The exact observed failure: n=10,291 driftless random walk, k=6 drew
        mean +0.0260, t=+2.00. Corrected lower bound -0.0065 — contains zero.
        """
        cells = [(6, 0.0260, 0.0130, 2.00)]
        self.assertEqual(verdict(cells), "NOT_ESTABLISHED")

    def test_real_but_unpayable_edge_is_not_a_green_light(self):
        """
        The genuinely dangerous middle case: the effect is real (lower bound
        above zero) but smaller than the friction it must cover. A statistically
        real edge that cannot fund itself is not a business.
        """
        cells = [(1, 0.0140, 0.0031, 4.52)]
        lo = 0.0140 - Z_BONF * 0.0031
        self.assertGreater(lo, 0)
        self.assertLess(lo, ECON)
        self.assertEqual(verdict(cells), "REAL_BUT_UNPAYABLE")

    def test_payable_edge_is_supported(self):
        """Measured from injected-edge synthetic data: lower bound +0.0507."""
        cells = [(1, 0.0645, 0.0055, 11.67)]
        self.assertEqual(verdict(cells), "SUPPORTED")

    def test_flat_data_reports_no_large_edge(self):
        cells = [(1, 0.0010, 0.0050, 0.20), (2, -0.0030, 0.0060, -0.50)]
        self.assertEqual(verdict(cells), "NO_LARGE_EDGE")

    def test_the_old_rule_and_the_new_rule_disagree_exactly_where_expected(self):
        """
        Guard the whole point of the amendment. At large n, t>=2 admits effects
        the economic test rejects — and that gap is what the fix closes.
        """
        noise = (6, 0.0260, 0.0130, 2.00)
        old_rule_says_yes = noise[1] > 0 and abs(noise[3]) >= 2
        self.assertTrue(old_rule_says_yes, "old rule would have greenlit this")
        self.assertEqual(verdict([noise]), "NOT_ESTABLISHED")

    def test_threshold_scales_the_right_way_with_sample_size(self):
        """
        Sanity-check the arithmetic behind the amendment: the smallest mean
        reaching t=2 falls below the profitability bar somewhere near n~3,500,
        which is why the old rule was safe at 700 and unsafe at 10,000.
        """
        import math
        sd = 0.53
        mde = lambda n: 2.0 * sd / math.sqrt(n)
        self.assertGreater(mde(700), ECON)      # old regime: t=2 implied a big effect
        self.assertLess(mde(10000), ECON)       # new regime: t=2 no longer does


class TestSourceStillImplementsThisRule(unittest.TestCase):
    """Structural guards — the CLI is slow to run, so pin the rule in source."""

    def setUp(self):
        self.src = SRC.read_text()

    def test_economic_threshold_is_present(self):
        self.assertRegex(self.src, r"econ\s*=\s*0\.018",
                         "the profitability threshold was removed")

    def test_bonferroni_correction_is_applied(self):
        self.assertRegex(self.src, r"z_bonf\s*=\s*2\.5",
                         "multiplicity correction was removed")

    def test_verdict_uses_a_lower_bound_not_just_t(self):
        # Must pin the SELECTION itself, not merely that the expression appears
        # somewhere in the file — it also appears in the print statements, so a
        # looser check passes even when the gate is reverted to `abs(t) >= 2`.
        # (Caught by mutation testing: that exact mutant survived a substring check.)
        self.assertRegex(
            self.src,
            r"pays\s*=\s*\[.*?\n\s*if \(m - z_bonf \* se\) > econ\]",
            "the PREMISE SUPPORTED gate no longer selects on the corrected "
            "lower bound — it may have reverted to the naked t>=2 rule")

    def test_the_naked_t2_gate_is_no_longer_the_sole_green_light(self):
        """
        The original line was:
            any_signal = any(m > 0 and abs(t) >= 2 for _, m, t in rth_pos)
        and it alone printed PREMISE SUPPORTED.
        """
        self.assertNotRegex(
            self.src, r"any_signal\s*=\s*any\(m > 0 and abs\(t\) >= 2",
            "the pre-amendment t>=2 gate is back")

    def test_the_amendment_is_documented_in_source(self):
        """A changed pre-registration must be auditable, not silent."""
        self.assertIn("AMENDMENT", self.src)
        self.assertRegex(self.src, r"BEFORE any purchased data",
                         "the amendment must record that it predates the data")

    def test_all_three_verdict_states_exist(self):
        for phrase in ("PREMISE SUPPORTED", "REAL BUT TOO SMALL TO PAY",
                       "NOT ESTABLISHED"):
            self.assertIn(phrase, self.src, f"verdict state missing: {phrase}")


class TestCsvLoaderIsWired(unittest.TestCase):
    """Purchased history must be able to enter the system at all."""

    def test_continuation_accepts_csv(self):
        self.assertIn("--csv", SRC.read_text())

    def test_research_accepts_csv(self):
        self.assertIn("--csv", (REPO / "scripts" / "research.py").read_text())

    def test_loader_module_exists_and_is_strict(self):
        src = (REPO / "backend" / "services" / "csv_data.py").read_text()
        for guard in ("CsvDataError", "OHLC invariants", "unparseable timestamps",
                      "ambiguous or nonexistent"):
            self.assertIn(guard, src, f"loader lost its {guard!r} check")


class TestLoaderActuallyRejectsBadData(unittest.TestCase):
    """
    Behavioural, not string-matching. Mutation testing killed the previous
    version of these: disabling the OHLC check entirely left its error MESSAGE
    in the source, so a substring assertion still passed while corrupt bars
    sailed through. A loader that silently accepts bad data would produce a
    confident, wrong verdict on the one question that decides the project.
    """

    def _write(self, rows):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(rows) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_rejects_high_below_low(self):
        from backend.services.csv_data import CsvDataError, load_bars
        path = self._write([
            "2024-01-02 09:30:00,100.0,101.0,99.0,100.5,10",
            "2024-01-02 09:31:00,100.5,98.0,102.0,100.7,10",   # high < low
        ])
        with self.assertRaises(CsvDataError) as ctx:
            load_bars(path)
        self.assertIn("OHLC", str(ctx.exception))

    def test_rejects_close_outside_the_bar_range(self):
        from backend.services.csv_data import CsvDataError, load_bars
        path = self._write([
            "2024-01-02 09:30:00,100.0,101.0,99.0,100.5,10",
            "2024-01-02 09:31:00,100.0,101.0,99.0,105.0,10",   # close > high
        ])
        with self.assertRaises(CsvDataError):
            load_bars(path)

    def test_rejects_unparseable_timestamps(self):
        from backend.services.csv_data import CsvDataError, load_bars
        path = self._write([
            "2024-01-02 09:30:00,100.0,101.0,99.0,100.5,10",
            "not-a-date,100.0,101.0,99.0,100.5,10",
        ])
        with self.assertRaises(CsvDataError):
            load_bars(path)

    def test_rejects_a_file_with_too_few_columns(self):
        from backend.services.csv_data import CsvDataError, load_bars
        path = self._write(["2024-01-02 09:30:00,100.0,101.0"])
        with self.assertRaises(CsvDataError):
            load_bars(path)

    def test_accepts_a_clean_file_and_lands_it_on_the_exchange_clock(self):
        """The happy path must still work, and must be tz-aware in ET."""
        from backend.services.csv_data import load_bars
        path = self._write([
            "2024-01-02 09:30:00,100.0,101.0,99.0,100.5,10",
            "2024-01-02 09:31:00,100.5,102.0,100.0,101.5,10",
        ])
        df = load_bars(path)
        self.assertEqual(len(df), 2)
        self.assertIsNotNone(df.index.tz)
        self.assertEqual(str(df.index.tz), "America/New_York")
        for col in ("open", "high", "low", "close"):
            self.assertIn(col, df.columns)

    def test_utc_file_is_converted_not_relabelled(self):
        """
        Getting the source timezone wrong shifts every bar into the wrong
        session and silently invalidates every session-bucketed result.
        """
        from backend.services.csv_data import load_bars
        path = self._write(["2024-01-02 14:30:00,100.0,101.0,99.0,100.5,10"])
        df = load_bars(path, tz="UTC")
        self.assertEqual(df.index[0].hour, 9)      # 14:30 UTC -> 09:30 EST
        self.assertEqual(df.index[0].minute, 30)


if __name__ == "__main__":
    unittest.main()
