"""AI/tests/test_meta_evaluator.py — S12 (2026-05-03)."""
from __future__ import annotations

import pytest


# ── parse_report ────────────────────────────────────────────────


def test_parse_grade():
    from AI.ai.meta_evaluator import parse_report
    text = "Some preamble.\n\n**Overall Grade: D** because of crit findings."
    facts = parse_report(text)
    assert facts.grade == "D"


def test_parse_grade_lowercase():
    from AI.ai.meta_evaluator import parse_report
    text = "grade: A — clean run"
    assert parse_report(text).grade == "A"


def test_parse_grade_missing():
    from AI.ai.meta_evaluator import parse_report
    text = "no rubric mentioned anywhere here"
    assert parse_report(text).grade is None


def test_parse_totals():
    from AI.ai.meta_evaluator import parse_report
    text = """
Aggregate:
  crit:  3
  high:  7
  med:   9
  low:   5
"""
    t = parse_report(text).totals
    assert t == {"crit": 3, "high": 7, "med": 9, "low": 5}


def test_parse_totals_pipe_form():
    from AI.ai.meta_evaluator import parse_report
    text = "| CRIT | 1 |\n| HIGH | 5 |\n"
    t = parse_report(text).totals
    assert t["crit"] == 1
    assert t["high"] == 5


def test_parse_findings_path_line():
    from AI.ai.meta_evaluator import parse_report
    text = "See `agents/foo.py:42` for the issue. Also `AI/ai/bar.py:100`."
    refs = parse_report(text).findings
    assert "agents/foo.py:42" in refs
    assert "AI/ai/bar.py:100" in refs


def test_parse_findings_path_only():
    from AI.ai.meta_evaluator import parse_report
    text = "Module `agents/notify.py` is fine but `tests/test_x.py:5` flagged."
    refs = parse_report(text).findings
    assert "agents/notify.py" in refs
    assert "tests/test_x.py:5" in refs


def test_parse_findings_filters_noise():
    """Filename-only without slash and non-py extension should be filtered."""
    from AI.ai.meta_evaluator import parse_report
    text = "See data.csv for context. Real ref: `agents/x.py`."
    refs = parse_report(text).findings
    assert "agents/x.py" in refs


def test_parse_handles_non_string():
    from AI.ai.meta_evaluator import parse_report
    out = parse_report(None)  # type: ignore
    assert out.grade is None
    assert out.findings == set()


# ── line_compliance ──────────────────────────────────────────────


def test_line_compliance_full():
    from AI.ai.meta_evaluator import parse_report
    text = "Bug at `agents/x.py:42` and `agents/y.py:7`."
    f = parse_report(text)
    assert f.line_compliance == 1.0


def test_line_compliance_none():
    from AI.ai.meta_evaluator import parse_report
    text = "See `agents/x.py` for the issue, also `agents/y.py`."
    f = parse_report(text)
    assert f.line_compliance == 0.0


def test_line_compliance_partial():
    from AI.ai.meta_evaluator import parse_report
    text = "Refs: `agents/x.py:1`, `agents/y.py`."
    f = parse_report(text)
    assert f.line_compliance == 0.5


def test_line_compliance_empty_when_no_findings():
    from AI.ai.meta_evaluator import parse_report
    f = parse_report("plain text, no refs")
    assert f.line_compliance == 0.0


# ── measure() ────────────────────────────────────────────────────


def test_measure_requires_two_reports():
    from AI.ai.meta_evaluator import measure
    with pytest.raises(ValueError):
        measure(["only one"])


def test_measure_stable_runs():
    """Same grade, same finding set → stable verdict."""
    from AI.ai.meta_evaluator import measure
    body = ("Grade: B\n"
            "crit: 0\nhigh: 1\n"
            "see `agents/foo.py:10` and `AI/ai/bar.py:20`")
    m = measure([body, body, body])
    assert m.verdict == "stable"
    assert m.grade_variance == 1
    assert m.jaccard_findings == 1.0


def test_measure_noisy_grades():
    """Same findings but different grades → noisy."""
    from AI.ai.meta_evaluator import measure
    common = "see `agents/foo.py:10` and `agents/bar.py:20`"
    a = "Grade: A\n" + common
    b = "Grade: D\n" + common
    m = measure([a, b])
    assert m.grade_variance == 2
    assert m.verdict in ("noisy", "unstable")


def test_measure_noisy_findings():
    """Same grade but completely different file refs → noisy."""
    from AI.ai.meta_evaluator import measure
    a = "Grade: B\nsee `agents/a.py:1` and `agents/b.py:2`"
    b = "Grade: B\nsee `agents/c.py:3` and `agents/d.py:4`"
    m = measure([a, b])
    assert m.jaccard_findings == 0.0
    assert m.verdict in ("noisy", "unstable")


def test_measure_unstable_both():
    """Grade variance AND low jaccard → unstable."""
    from AI.ai.meta_evaluator import measure
    a = "Grade: A\nsee `agents/a.py:1`"
    b = "Grade: F\nsee `agents/z.py:99`"
    m = measure([a, b])
    assert m.verdict == "unstable"


def test_measure_shared_findings():
    from AI.ai.meta_evaluator import measure
    a = "Grade: B\n`agents/x.py:10` `agents/y.py:20`"
    b = "Grade: B\n`agents/x.py:10` `agents/z.py:30`"
    m = measure([a, b])
    assert m.shared_findings == {"agents/x.py:10"}
    assert "agents/y.py:20" in m.unique_findings
    assert "agents/z.py:30" in m.unique_findings


def test_measure_crit_stddev():
    """3 runs with different crit counts → non-zero stddev."""
    from AI.ai.meta_evaluator import measure
    rs = [
        "Grade: C\ncrit: 1\nhigh: 5\n`agents/a.py:1`",
        "Grade: F\ncrit: 3\nhigh: 8\n`agents/a.py:1`",
        "Grade: D\ncrit: 3\nhigh: 7\n`agents/a.py:1`",
    ]
    m = measure(rs)
    assert m.crit_counts == [1, 3, 3]
    assert m.crit_stddev > 0


def test_measure_signal_to_noise():
    from AI.ai.meta_evaluator import measure
    a = "G: B\n`agents/x.py:10` `agents/y.py:20` `agents/n1.py:1`"
    b = "G: B\n`agents/x.py:10` `agents/y.py:20` `agents/n2.py:2`"
    m = measure([a, b])
    # 2 shared, 2 unique → signal/noise = 1.0
    assert m.signal_to_noise() == 1.0


def test_measure_signal_to_noise_no_unique():
    from AI.ai.meta_evaluator import measure
    body = "G: B\n`agents/x.py:1`"
    m = measure([body, body])
    # No unique findings → infinity (or any large number)
    assert m.signal_to_noise() == float("inf")


# ── shared_only ─────────────────────────────────────────────────


def test_shared_only_returns_intersection():
    from AI.ai.meta_evaluator import shared_only
    a = "G: B\n`agents/x.py:10` `agents/a.py:1`"
    b = "G: B\n`agents/x.py:10` `agents/b.py:2`"
    c = "G: B\n`agents/x.py:10` `agents/y.py:20` `agents/c.py:3`"
    out = shared_only([a, b, c])
    assert out == {"agents/x.py:10"}


def test_shared_only_too_few_reports():
    from AI.ai.meta_evaluator import shared_only
    assert shared_only(["only one"]) == set()


# ── summary ──────────────────────────────────────────────────────


def test_summary_too_few_reports():
    from AI.ai.meta_evaluator import summary
    assert "at least 2" in summary(["just one"])


def test_summary_includes_metrics():
    from AI.ai.meta_evaluator import summary
    body = "Grade: B\ncrit: 0\nhigh: 1\n`agents/foo.py:10`"
    s = summary([body, body])
    assert "reproducibility" in s.lower()
    assert "verdict" in s.lower()


def test_summary_recommends_on_noisy():
    from AI.ai.meta_evaluator import summary
    a = "Grade: A\n`agents/a.py:1`"
    b = "Grade: F\n`agents/z.py:99`"
    s = summary([a, b])
    assert "Recommendation" in s
    assert "shared" in s.lower() or "signal" in s.lower()


# ── real-world: 3 reports actually look noisy ──────────────────


def test_real_world_three_audits_are_noisy():
    """Synthetic stand-in for the C/F/D pattern we observed in 3
    consecutive DeepSeek runs of the same code: model surrenders, finds
    different things each pass."""
    from AI.ai.meta_evaluator import measure
    common = "`agents/x.py:10`"
    extras = [
        f"Grade: C\ncrit: 1\nhigh: 5\n{common} `agents/a.py:1`",
        f"Grade: F\ncrit: 3\nhigh: 8\n{common} `agents/b.py:2` `agents/c.py:3`",
        f"Grade: D\ncrit: 3\nhigh: 7\n{common} `agents/d.py:4`",
    ]
    m = measure(extras)
    assert m.verdict in ("noisy", "unstable")
    assert m.shared_findings == {"agents/x.py:10"}
    assert m.grade_variance == 3
