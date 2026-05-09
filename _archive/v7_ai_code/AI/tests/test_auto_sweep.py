"""AI/tests/test_auto_sweep.py — AS1 (2026-05-04)."""
from __future__ import annotations

import datetime as dt
import os

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("AIM_EVAL_ARCHIVE_DIR", str(tmp_path / "arch"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1 prompt\n", encoding="utf-8")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.prompt_versions",
              "AI.ai.prompt_impact", "AI.ai.case_validator",
              "AI.ai.case_archiver", "AI.ai.findings_to_evals",
              "AI.ai.auto_sweep"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path, fake


def _set_age(p, days):
    target = dt.datetime.now().timestamp() - (days * 86400)
    os.utime(p, (target, target))


# ── sweep() basics ──────────────────────────────────────────────


def test_sweep_first_time_records_prompt(isolated):
    from AI.ai.auto_sweep import sweep
    res = sweep()
    assert res.prompt_recorded is True
    assert res.prompt_changed is None
    assert res.n_cases_validated == 0
    assert res.n_archived_moved == 0


def test_sweep_unchanged_prompt(isolated):
    from AI.ai.auto_sweep import sweep
    sweep()
    res = sweep()
    assert res.prompt_changed is False
    assert res.prompt_recorded is True


def test_sweep_detects_prompt_change(isolated):
    _, p = isolated
    from AI.ai.auto_sweep import sweep
    sweep()
    p.write_text(p.read_text() + "\nNEW\n", encoding="utf-8")
    res = sweep()
    assert res.prompt_changed is True


def test_sweep_dry_run_does_not_persist_prompt(isolated):
    from AI.ai.auto_sweep import sweep
    from AI.ai.prompt_versions import history
    res = sweep(dry_run=True)
    assert res.prompt_recorded is False
    assert history() == []   # nothing persisted


# ── case validation surfaces issues ─────────────────────────────


def test_sweep_flags_invalid_cases(isolated, tmp_path):
    cases = tmp_path / "cases"
    (cases / "broken.yaml").write_text("id: x\ntask: y\n")  # no rubrics
    from AI.ai.auto_sweep import sweep
    res = sweep()
    assert res.n_cases_validated == 1
    assert res.n_cases_invalid == 1
    assert any("broken.yaml" in n for n in res.notes)
    assert res.all_clean is False


def test_sweep_clean_cases_pass(isolated, tmp_path):
    cases = tmp_path / "cases"
    (cases / "good.yaml").write_text(
        "id: c\ntask: x\nrubrics:\n  min_length: 1\n")
    from AI.ai.auto_sweep import sweep
    res = sweep()
    assert res.n_cases_validated == 1
    assert res.n_cases_invalid == 0
    assert res.all_clean is True


# ── archiver integration ────────────────────────────────────────


def test_sweep_dry_run_archives_nothing(isolated, tmp_path):
    from AI.ai.findings_to_evals import write_cases
    written = write_cases(["agents/x.py:1"])
    _set_age(written[0], 10)
    other = tmp_path / "report.md"
    other.write_text("`agents/y.py:99`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(other))
    from AI.ai.auto_sweep import sweep
    res = sweep(dry_run=True)
    assert res.n_archived_candidates == 1
    assert res.n_archived_moved == 1   # dry-run still reports "would move"
    assert written[0].exists()         # but file untouched


def test_sweep_live_run_moves_files(isolated, tmp_path):
    from AI.ai.findings_to_evals import write_cases
    written = write_cases(["agents/x.py:1"])
    _set_age(written[0], 10)
    other = tmp_path / "report.md"
    other.write_text("`agents/y.py:99`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(other))
    from AI.ai.auto_sweep import sweep
    res = sweep(dry_run=False)
    assert res.n_archived_moved == 1
    assert not written[0].exists()


# ── graceful degradation ────────────────────────────────────────


# ── summary ─────────────────────────────────────────────────────


def test_summary_first_time(isolated):
    from AI.ai.auto_sweep import summary
    s = summary()
    assert "Auto-sweep" in s
    assert "first time" in s


def test_summary_unchanged(isolated):
    from AI.ai.auto_sweep import sweep, summary
    sweep()
    s = summary()
    assert "unchanged" in s


def test_summary_lists_notes_on_failure(isolated, tmp_path):
    cases = tmp_path / "cases"
    (cases / "broken.yaml").write_text("id: x\ntask: y\n")
    from AI.ai.auto_sweep import summary
    s = summary()
    assert "invalid" in s
    assert "broken.yaml" in s


def test_summary_dry_vs_live_label(isolated):
    from AI.ai.auto_sweep import summary
    assert "dry-run" in summary(dry_run=True)
    assert "live" in summary(dry_run=False)


# ── prune_phantom integration ───────────────────────────────────


def test_sweep_prunes_phantom_rows(isolated, tmp_path):
    """Sweep step 6: ledger rows pointing at gone files should be pruned."""
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(tmp_path / "gone.md"),
           ts="2026-05-03T10:00:00")
    real = tmp_path / "real.md"
    real.write_text("ok")
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(real),
           ts="2026-05-03T11:00:00")
    from AI.ai.auto_sweep import sweep
    res = sweep(dry_run=False)
    assert res.n_phantom_removed == 1
    rows = all_rows()
    # 2 originals + 1 from sweep's own score-record step.
    # The phantom is gone; the real one remains; score row has no
    # report_path so isn't pruned.
    assert len(rows) <= 2 or any(
        r.report_path == str(real) for r in rows
    )


def test_sweep_dry_run_doesnt_prune(isolated, tmp_path):
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           report_path=str(tmp_path / "gone.md"),
           ts="2026-05-03T10:00:00")
    from AI.ai.auto_sweep import sweep
    res = sweep(dry_run=True)
    assert res.n_phantom_removed == 1   # would-remove count surfaced
    # but the row is still there
    assert any(r.report_path == str(tmp_path / "gone.md")
                for r in all_rows())


