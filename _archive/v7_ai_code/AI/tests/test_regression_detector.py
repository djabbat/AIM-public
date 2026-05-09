"""AI/tests/test_regression_detector.py — RD1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _write_report(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── detect() — empty / single-row ───────────────────────────────


def test_detect_no_baseline(isolated):
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.have_baseline is False
    assert r.regressed is False
    assert r.improved is False


def test_detect_single_row_is_no_baseline(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.have_baseline is False


# ── detect() — two rows ─────────────────────────────────────────


def test_detect_no_change(isolated, tmp_path):
    body = "Grade: B\ncrit: 0\n`agents/x.py:10`"
    p1 = _write_report(tmp_path, "r1.md", body)
    p2 = _write_report(tmp_path, "r2.md", body)
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.have_baseline is True
    assert r.new_findings == set()
    assert r.fixed_findings == set()
    assert r.regressed is False
    assert r.improved is False


def test_detect_new_finding_is_regression(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md",
                        "Grade: B\ncrit: 1\n`agents/x.py:10`")
    p2 = _write_report(tmp_path, "r2.md",
                        "Grade: D\ncrit: 2\n`agents/x.py:10` and `agents/y.py:99`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=1,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="D", n_refs=2, n_with_line=2, crit=2,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.regressed is True
    assert "agents/y.py:99" in r.new_findings
    assert r.fixed_findings == set()


def test_detect_fixed_finding_is_improvement(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md",
                        "Grade: D\ncrit: 2\n`agents/x.py:10` and `agents/y.py:99`")
    p2 = _write_report(tmp_path, "r2.md",
                        "Grade: B\ncrit: 1\n`agents/x.py:10`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="D", n_refs=2, n_with_line=2, crit=2,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=1,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.improved is True
    assert "agents/y.py:99" in r.fixed_findings
    assert r.new_findings == set()


def test_detect_crit_increase_is_regression_even_without_new_refs(
    isolated, tmp_path,
):
    """crit count goes up but finding-ref set is identical (model
    re-classified) → still regression."""
    p1 = _write_report(tmp_path, "r1.md",
                        "Grade: B\ncrit: 1\n`agents/x.py:10`")
    p2 = _write_report(tmp_path, "r2.md",
                        "Grade: B\ncrit: 3\n`agents/x.py:10`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=1,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=3,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.regressed is True


def test_detect_handles_missing_report_paths(isolated):
    """Records without report_path → empty finding sets, no crash."""
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=0, n_with_line=0, crit=0,
           ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=0, n_with_line=0, crit=0,
           ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.have_baseline is True
    assert r.new_findings == set()


def test_detect_handles_deleted_report_file(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md", "`agents/x.py:1`")
    p2 = _write_report(tmp_path, "r2.md", "`agents/y.py:2`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=p2, ts="2026-05-04T10:00:00")
    # Delete the prev file — detect() must not crash
    (tmp_path / "r1.md").unlink()
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.have_baseline is True
    # All curr findings appear "new" because prev file is gone
    assert "agents/y.py:2" in r.new_findings


# ── summary ─────────────────────────────────────────────────────


def test_summary_no_baseline(isolated):
    from AI.ai.regression_detector import summary
    s = summary()
    assert "no baseline" in s


def test_summary_regression_lists_new(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md", "`agents/x.py:1`")
    p2 = _write_report(tmp_path, "r2.md",
                        "`agents/x.py:1` and `agents/y.py:2`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="C", n_refs=2, n_with_line=2, crit=1,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import summary
    s = summary()
    assert "REGRESSED" in s
    assert "agents/y.py:2" in s


def test_summary_improvement_lists_fixed(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md",
                        "`agents/x.py:1` and `agents/y.py:2`")
    p2 = _write_report(tmp_path, "r2.md", "`agents/x.py:1`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="D", n_refs=2, n_with_line=2, crit=2,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=1,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import summary
    s = summary()
    assert "IMPROVED" in s
    assert "agents/y.py:2" in s


def test_grade_improvement_suppresses_regression(isolated, tmp_path):
    """D → C grade improvement with MORE findings = thorough model,
    not regression. RD1 must say 'not regressed'."""
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1` and `agents/new.py:42` "
                   "and `agents/another.py:99`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="D", n_refs=1, n_with_line=1, crit=3,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="C", n_refs=3, n_with_line=3, crit=2,
           report_path=str(p2), ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.grade_improved is True
    assert r.regressed is False
    assert r.improved is True


def test_grade_worsening_with_no_new_findings_still_flags(
    isolated, tmp_path,
):
    """If grade worsens but no new file:line refs (just crit count
    change), regression is via crit_count rule, not grade alone."""
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="C", n_refs=1, n_with_line=1, crit=1,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="D", n_refs=1, n_with_line=1, crit=4,
           report_path=str(p2), ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import detect
    r = detect()
    assert r.grade_worsened is True
    assert r.regressed is True   # crit went up


def test_summary_truncates_long_new_list(isolated, tmp_path):
    p1 = _write_report(tmp_path, "r1.md", "`agents/x.py:1`")
    refs = " ".join(f"`agents/m{i}.py:{i}`" for i in range(15))
    p2 = _write_report(tmp_path, "r2.md", refs)
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=p1, ts="2026-05-03T10:00:00")
    record(model="m", grade="D", n_refs=15, n_with_line=15, crit=5,
           report_path=p2, ts="2026-05-04T10:00:00")
    from AI.ai.regression_detector import summary
    s = summary()
    assert "+5 more" in s or "(+5" in s
