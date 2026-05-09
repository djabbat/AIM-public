"""tests/test_health_extended.py — G9 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import json
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("AIM_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "eval.db"))
    monkeypatch.setenv("AIM_BUDGET_DAILY_USD", "5")
    (tmp_path / "projects").mkdir()
    (tmp_path / "memory").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.project_archive",
              "agents.evals", "agents.memory_monitor",
              "agents.cost_ledger", "agents.stakeholder_tracker",
              "agents.deadline_scanner", "agents.health_extended"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── shape ─────────────────────────────────────────────────────────


def test_report_has_required_keys(isolated):
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    assert "ts" in r
    assert "overall" in r
    assert "subsystems" in r
    assert "warnings" in r
    for sub in ("self_health", "projects", "eval", "memory_hygiene",
                "cost", "stakeholders", "deadlines", "cron"):
        assert sub in r["subsystems"]


def test_report_json_serialises(isolated):
    from agents.health_extended import report_json
    out = report_json(today=dt.date(2026, 5, 3))
    parsed = json.loads(out)
    assert "subsystems" in parsed


# ── projects probe ───────────────────────────────────────────────


def test_projects_probe_counts(isolated):
    (isolated / "projects" / "A.yaml").write_text(textwrap.dedent("""
        name: A
        milestones:
          - id: hot
            deadline: 2026-05-05
            criticality: high
            status: pending
          - id: late
            deadline: 2026-04-25
            criticality: medium
            status: pending
    """).lstrip())
    (isolated / "projects" / "B.yaml").write_text("name: B\n")
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    p = r["subsystems"]["projects"]
    assert p["count"] == 2
    assert p["hot_milestones"] >= 1
    assert p["overdue_milestones"] >= 1


def test_projects_archive_count(isolated):
    (isolated / "projects" / "P.yaml").write_text("name: P\nphase: DRAFT\n")
    from agents import project_archive as pa
    pa.archive("P")
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    assert r["subsystems"]["projects"]["archived"] == 1


# ── memory probe ─────────────────────────────────────────────────


def test_memory_probe_counts_findings(isolated):
    md = isolated / "memory"
    (md / "broken.md").write_text(
        "---\ntype: reference\n---\nfile at `/tmp/no-such-path-xyz`\n")
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    mem = r["subsystems"]["memory_hygiene"]
    assert mem["scanned"] >= 1
    assert mem["broken_paths"] >= 1


# ── cost probe ───────────────────────────────────────────────────


def test_cost_probe_with_no_db(isolated):
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    cost = r["subsystems"]["cost"]
    assert cost.get("daily", 0.0) == 0.0
    assert cost.get("daily_pct") == 0.0


# ── deadlines probe ──────────────────────────────────────────────


def test_deadlines_probe(isolated, monkeypatch):
    (isolated / "projects" / "P.yaml").write_text(textwrap.dedent("""
        name: P
        milestones:
          - id: today-x
            deadline: 2026-05-03
            criticality: high
            status: pending
    """).lstrip())
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    d = r["subsystems"]["deadlines"]
    assert d["today"] >= 1


# ── overall classification ──────────────────────────────────────


def test_overall_warn_when_overdue_milestones(isolated):
    (isolated / "projects" / "P.yaml").write_text(textwrap.dedent("""
        name: P
        milestones:
          - id: late
            deadline: 2026-04-01
            criticality: high
            status: pending
    """).lstrip())
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    assert r["overall"] in ("warn", "degraded")
    assert any("overdue" in w for w in r["warnings"])


def test_overall_ok_in_clean_state(isolated):
    """No projects, no memory, no cost → minimal warnings."""
    from agents import health_extended as he
    r = he.report(today=dt.date(2026, 5, 3))
    assert r["overall"] in ("ok", "warn")  # warn allowed if memory has findings


# ── safe defaults on subsystem failure ──────────────────────────


def test_subsystem_failure_does_not_crash(isolated, monkeypatch):
    """If one probe explodes, the report still renders."""
    from agents import health_extended as he
    monkeypatch.setattr(he, "_probe_cost",
                        lambda today: (_ for _ in ()).throw(RuntimeError("boom")))
    r = he.report(today=dt.date(2026, 5, 3))
    # cost subsystem becomes empty dict via _safe fallback.
    assert r["subsystems"]["cost"] == {}
