"""AI/tests/test_case_archiver.py — CA1 (2026-05-04)."""
from __future__ import annotations

import datetime as dt
import os

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    monkeypatch.setenv("AIM_EVAL_ARCHIVE_DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.case_archiver",
              "AI.ai.findings_to_evals"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _age(p, days):
    """Set mtime to N days ago."""
    target = dt.datetime.now().timestamp() - (days * 86400)
    os.utime(p, (target, target))


def _seed_case(isolated, ref):
    """Generate one FE1 case for `ref`."""
    from AI.ai.findings_to_evals import write_cases
    written = write_cases([ref])
    assert written
    return written[0]


def _seed_report(isolated, refs):
    """Plant a ledger row + report file with given refs."""
    p = isolated / "report.md"
    p.write_text(" ".join(f"`{r}`" for r in refs), encoding="utf-8")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=len(refs), n_with_line=len(refs),
           crit=0, report_path=str(p))


# ── _ref_from_id / _normalise_ref round-trip ────────────────────


# ── candidates ──────────────────────────────────────────────────


def test_candidates_empty_when_no_cases(isolated):
    from AI.ai.case_archiver import candidates
    assert candidates() == []


def test_candidates_skips_young_cases(isolated):
    p = _seed_case(isolated, "agents/x.py:42")
    # Brand new (today) — even with no matching ledger row, age guard wins
    from AI.ai.case_archiver import candidates
    assert candidates(min_age_days=3) == []


def test_candidates_archives_when_finding_absent(isolated):
    p = _seed_case(isolated, "agents/x.py:42")
    _age(p, 5)
    # Recent reports have a DIFFERENT finding — original is gone
    _seed_report(isolated, ["agents/y.py:99"])
    from AI.ai.case_archiver import candidates
    cands = candidates(min_age_days=3)
    assert len(cands) == 1
    assert cands[0].case_id == "regr-agents-x-py-l42"


def test_candidates_keeps_active_findings(isolated):
    p = _seed_case(isolated, "agents/x.py:42")
    _age(p, 5)
    _seed_report(isolated, ["agents/x.py:42"])  # still flagged
    from AI.ai.case_archiver import candidates
    assert candidates(min_age_days=3) == []


def test_candidates_ignores_non_regr_yaml(isolated):
    """A user-authored case (no `regr-` prefix) is left alone."""
    (isolated / "cases" / "user-case.yaml").write_text(
        "id: user-case\ntask: x\nrubrics:\n  min_length: 1\n")
    _age(isolated / "cases" / "user-case.yaml", 30)
    from AI.ai.case_archiver import candidates
    assert candidates(min_age_days=3) == []


def test_candidates_handle_no_line_id(isolated):
    """Path-only case id without `:line` matches any line in the slug."""
    p = _seed_case(isolated, "agents/x.py")
    _age(p, 5)
    # No matching slug in recent reports → candidate
    _seed_report(isolated, ["agents/y.py:99"])
    from AI.ai.case_archiver import candidates
    cands = candidates(min_age_days=3)
    assert len(cands) == 1


def test_candidates_no_line_keeps_when_slug_present(isolated):
    """Path-only case kept if slug matches any current finding line."""
    p = _seed_case(isolated, "agents/x.py")
    _age(p, 5)
    _seed_report(isolated, ["agents/x.py:7"])  # different line, same file
    from AI.ai.case_archiver import candidates
    assert candidates(min_age_days=3) == []


# ── archive ─────────────────────────────────────────────────────


def test_archive_dry_run_lists_without_moving(isolated):
    p = _seed_case(isolated, "agents/x.py:1")
    _age(p, 5)
    _seed_report(isolated, ["agents/y.py:2"])
    from AI.ai.case_archiver import archive
    res = archive(min_age_days=3, dry_run=True)
    assert res.n_moved == 1
    assert p.exists()  # NOT moved


def test_archive_moves_files(isolated):
    p = _seed_case(isolated, "agents/x.py:1")
    _age(p, 5)
    _seed_report(isolated, ["agents/y.py:2"])
    from AI.ai.case_archiver import archive
    res = archive(min_age_days=3, dry_run=False)
    assert res.n_moved == 1
    assert not p.exists()
    assert res.archive_dir.exists()
    assert (res.archive_dir / "regr-agents-x-py-l1.yaml").exists()


def test_archive_no_op_when_nothing_to_do(isolated):
    from AI.ai.case_archiver import archive
    res = archive(min_age_days=3, dry_run=False)
    assert res.n_candidates == 0
    assert res.n_moved == 0


# ── summary ─────────────────────────────────────────────────────


def test_summary_calm_when_empty(isolated):
    from AI.ai.case_archiver import summary
    assert "no archive candidates" in summary()


def test_summary_lists_candidates(isolated):
    p = _seed_case(isolated, "agents/x.py:1")
    _age(p, 5)
    _seed_report(isolated, ["agents/y.py:2"])
    from AI.ai.case_archiver import summary
    s = summary()
    assert "ready to archive" in s
    assert "regr-agents-x-py-l1" in s
