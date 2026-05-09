"""AI/tests/test_prompt_impact.py — PI1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1 prompt", encoding="utf-8")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.prompt_versions",
              "AI.ai.prompt_impact"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path, fake


# ── impact_per_revision ─────────────────────────────────────────


def test_no_revisions(isolated):
    from AI.ai.prompt_impact import impact_per_revision
    assert impact_per_revision() == []


def test_single_revision_no_runs(isolated):
    from AI.ai.prompt_versions import record_current
    record_current(ts="2026-05-03T10:00:00")
    from AI.ai.prompt_impact import impact_per_revision
    rows = impact_per_revision()
    assert len(rows) == 1
    assert rows[0].n_runs_before == 0
    assert rows[0].n_runs_after == 0
    assert rows[0].avg_compliance_before is None
    assert rows[0].compliance_delta is None


def test_revision_partitions_runs_correctly(isolated):
    _, p = isolated
    from AI.ai.diagnostic_ledger import record
    from AI.ai.prompt_versions import record_current
    from AI.ai.prompt_impact import impact_per_revision

    # One run BEFORE the revision
    record(model="m", grade="D", n_refs=10, n_with_line=2, crit=3,
           ts="2026-05-03T08:00:00")
    # Revision at 09:00
    record_current(ts="2026-05-03T09:00:00")
    # Two runs AFTER the revision
    record(model="m", grade="B", n_refs=10, n_with_line=9, crit=1,
           ts="2026-05-03T10:00:00")
    record(model="m", grade="B", n_refs=10, n_with_line=10, crit=0,
           ts="2026-05-03T11:00:00")

    rows = impact_per_revision()
    assert len(rows) == 1
    r = rows[0]
    assert r.n_runs_before == 1
    assert r.n_runs_after == 2
    assert r.avg_compliance_before == 0.2
    assert r.avg_compliance_after == 0.95
    assert r.compliance_delta == pytest.approx(0.75)
    assert r.avg_crit_before == 3.0
    assert r.avg_crit_after == 0.5


def test_two_revisions_partition_independently(isolated):
    _, p = isolated
    from AI.ai.diagnostic_ledger import record
    from AI.ai.prompt_versions import record_current
    from AI.ai.prompt_impact import impact_per_revision

    record_current(ts="2026-05-03T09:00:00")
    record(model="m", grade="D", n_refs=10, n_with_line=2, crit=2,
           ts="2026-05-03T10:00:00")   # after rev1, before rev2
    p.write_text("v2 prompt different", encoding="utf-8")
    record_current(ts="2026-05-03T11:00:00")
    record(model="m", grade="B", n_refs=10, n_with_line=10, crit=0,
           ts="2026-05-03T12:00:00")   # after rev2

    rows = impact_per_revision()
    assert len(rows) == 2
    # rev1 window: empty before, 1 run after (between rev1 and rev2)
    assert rows[0].n_runs_before == 0
    assert rows[0].n_runs_after == 1
    assert rows[0].avg_compliance_after == 0.2
    # rev2 window: 1 run before (between rev1 and rev2), 1 run after
    assert rows[1].n_runs_before == 1
    assert rows[1].n_runs_after == 1
    assert rows[1].avg_compliance_before == 0.2
    assert rows[1].avg_compliance_after == 1.0


def test_runs_with_no_crit_value_handled(isolated):
    from AI.ai.diagnostic_ledger import record
    from AI.ai.prompt_versions import record_current
    from AI.ai.prompt_impact import impact_per_revision

    record(model="m", grade=None, n_refs=10, n_with_line=5, crit=None,
           ts="2026-05-03T08:00:00")
    record_current(ts="2026-05-03T09:00:00")
    rows = impact_per_revision()
    assert rows[0].avg_crit_before is None
    assert rows[0].avg_compliance_before == 0.5


# ── compliance_delta / crit_delta properties ────────────────────


def test_compliance_delta_none_when_one_window_empty(isolated):
    from AI.ai.prompt_impact import ImpactRow
    r = ImpactRow(
        revision_ts="x", sha_prefix="aaa", n_runs_before=0, n_runs_after=0,
        avg_compliance_before=None, avg_compliance_after=0.8,
        avg_crit_before=None, avg_crit_after=1.0,
    )
    assert r.compliance_delta is None
    assert r.crit_delta is None


def test_compliance_delta_negative_when_metric_dropped(isolated):
    from AI.ai.prompt_impact import ImpactRow
    r = ImpactRow(
        revision_ts="x", sha_prefix="bbb", n_runs_before=2, n_runs_after=2,
        avg_compliance_before=0.9, avg_compliance_after=0.5,
        avg_crit_before=0.0, avg_crit_after=2.0,
    )
    assert r.compliance_delta == pytest.approx(-0.4)
    assert r.crit_delta == pytest.approx(2.0)


# ── summary ─────────────────────────────────────────────────────


def test_summary_no_revisions(isolated):
    from AI.ai.prompt_impact import summary
    assert "no prompt revisions" in summary()


def test_summary_renders_revision(isolated):
    from AI.ai.diagnostic_ledger import record
    from AI.ai.prompt_versions import record_current
    from AI.ai.prompt_impact import summary

    record(model="m", grade="D", n_refs=10, n_with_line=2, crit=3,
           ts="2026-05-03T08:00:00")
    record_current(ts="2026-05-03T09:00:00")
    record(model="m", grade="B", n_refs=10, n_with_line=10, crit=0,
           ts="2026-05-03T10:00:00")
    s = summary()
    assert "rev " in s
    assert "compliance" in s
    assert "avg crit" in s


def test_summary_shows_delta_when_both_windows_present(isolated):
    from AI.ai.diagnostic_ledger import record
    from AI.ai.prompt_versions import record_current
    from AI.ai.prompt_impact import summary

    record(model="m", grade="D", n_refs=10, n_with_line=2, crit=2,
           ts="2026-05-03T08:00:00")
    record_current(ts="2026-05-03T09:00:00")
    record(model="m", grade="B", n_refs=10, n_with_line=10, crit=0,
           ts="2026-05-03T10:00:00")
    s = summary()
    assert "+80%" in s or "+80" in s
