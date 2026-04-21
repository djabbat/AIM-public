"""
AIM v7.0 — unit tests for agents/interactions.py

Runnable either as:
    cd ~/Desktop/AIM && source venv/bin/activate && pytest tests/test_interactions.py -v
or directly:
    cd ~/Desktop/AIM && python -m tests.test_interactions
"""

from __future__ import annotations

import sys
import os
import unittest

# Allow running as a script from within ~/Desktop/AIM
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.interactions import (  # noqa: E402
    Interaction,
    check_interaction,
    check_regimen,
    format_regimen_report,
    SEVERITY_ORDER,
    DISCLAIMER,
)


class InteractionAPITests(unittest.TestCase):
    """Core single-pair lookups."""

    def test_returns_interaction_dataclass(self):
        r = check_interaction("warfarin", "ibuprofen")
        self.assertIsInstance(r, Interaction)
        self.assertEqual(r.severity, "major")
        self.assertTrue(r.mechanism)
        self.assertTrue(r.recommendation)
        self.assertEqual(r.disclaimer, DISCLAIMER)

    def test_user_senolytic_combo_is_safe(self):
        """Dasatinib + quercetin: user's own protocol, must NOT be contraindicated/major."""
        r = check_interaction("dasatinib", "quercetin")
        self.assertIn(r.severity, {"minor", "no_known"})
        self.assertIn("38510429", r.source)  # PMID of editorial

    def test_known_contraindicated_pair(self):
        r = check_interaction("ssri", "maoi")
        self.assertEqual(r.severity, "contraindicated")
        self.assertIn("serotonin", r.mechanism.lower())

    def test_unknown_drug_yields_no_known(self):
        r = check_interaction("unobtainium", "kryptonite")
        self.assertEqual(r.severity, "no_known")
        self.assertEqual(r.source, "")     # never fabricate a cite
        self.assertIn("DrugBank", r.recommendation)  # points user to authoritative source

    def test_same_drug_twice(self):
        r = check_interaction("warfarin", "warfarin")
        self.assertEqual(r.severity, "no_known")
        self.assertIn("twice", r.mechanism.lower())

    def test_empty_drug_name(self):
        r = check_interaction("", "warfarin")
        self.assertEqual(r.severity, "no_known")

    def test_case_and_synonym_normalisation(self):
        """Brand names and case variations should hit the generic entry."""
        r1 = check_interaction("Coumadin", "Advil")         # brands
        r2 = check_interaction("warfarin", "ibuprofen")     # generics
        r3 = check_interaction("WARFARIN", "Ibuprofen")     # case
        self.assertEqual(r1.severity, r2.severity)
        self.assertEqual(r2.severity, r3.severity)
        self.assertEqual(r1.severity, "major")

    def test_order_independence(self):
        a = check_interaction("warfarin", "vitamin k")
        b = check_interaction("vitamin k", "warfarin")
        self.assertEqual(a.severity, b.severity)
        self.assertEqual(a.mechanism, b.mechanism)

    def test_st_johns_wort_ssri_major(self):
        r = check_interaction("St. John's Wort", "ssri")
        self.assertEqual(r.severity, "major")

    def test_every_table_entry_has_valid_source(self):
        """Any pair flagged more serious than 'no_known' MUST carry a source."""
        from agents.interactions import _TABLE
        for key, entry in _TABLE.items():
            with self.subTest(pair=tuple(key)):
                self.assertIn(entry["severity"], SEVERITY_ORDER)
                self.assertNotEqual(entry["severity"], "no_known",
                                    "'no_known' entries must not be stored in _TABLE")
                self.assertTrue(entry["source"],
                                f"Missing source for pair {tuple(key)}")
                # source must be a PMID: reference or a URL
                src = entry["source"]
                self.assertTrue(
                    src.startswith("PMID:") or src.startswith("http"),
                    f"Bad source format: {src}",
                )


class RegimenAPITests(unittest.TestCase):
    """Multi-drug regimen checks."""

    def test_empty_regimen(self):
        self.assertEqual(check_regimen([]), [])

    def test_single_drug_regimen(self):
        self.assertEqual(check_regimen(["warfarin"]), [])

    def test_regimen_pair_count(self):
        """N drugs → N*(N-1)/2 pairs."""
        meds = ["warfarin", "ibuprofen", "vitamin k", "omega3"]
        n = len(meds)
        results = check_regimen(meds)
        self.assertEqual(len(results), n * (n - 1) // 2)

    def test_regimen_sorted_by_severity(self):
        meds = ["quercetin", "warfarin", "ibuprofen", "dasatinib"]
        results = check_regimen(meds)
        severities = [SEVERITY_ORDER[r.severity] for r in results]
        self.assertEqual(severities, sorted(severities))

    def test_format_report_contains_disclaimer(self):
        meds = ["warfarin", "ibuprofen"]
        report = format_regimen_report(check_regimen(meds))
        self.assertIn(DISCLAIMER, report)
        self.assertIn("MAJOR", report)

    def test_format_report_hides_no_known_by_default(self):
        meds = ["unobtainium", "kryptonite"]
        report = format_regimen_report(check_regimen(meds))
        self.assertNotIn("NO_KNOWN", report)
        report_full = format_regimen_report(
            check_regimen(meds), include_no_known=True
        )
        self.assertIn("NO_KNOWN", report_full)


def _run():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(InteractionAPITests))
    suite.addTests(loader.loadTestsFromTestCase(RegimenAPITests))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(_run())
