"""tests/test_kpi_auto_updater.py — P7 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import sqlite3
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "c.db"))
    (tmp_path / "projects").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.kpi_tracker",
              "agents.kpi_auto_updater", "agents.stakeholder_tracker",
              "agents.cost_ledger"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_proj(setup, name, body):
    (setup / "projects" / f"{name}.yaml").write_text(
        textwrap.dedent(body), encoding="utf-8")


# ── source bindings ──────────────────────────────────────────────


def test_stakeholder_total_source(isolated):
    from agents import stakeholder_tracker as st, kpi_auto_updater as kau
    st.upsert("Alice", email="a@x")
    st.upsert("Bob", email="b@x")
    val = kau._SOURCES["stakeholders.total"](dt.date(2026, 5, 3))
    assert val == 2.0


def test_unknown_source_returns_none_at_lookup(isolated):
    from agents.kpi_auto_updater import _SOURCES
    assert _SOURCES.get("ghost.source") is None


def test_eval_latest_source_when_empty(isolated):
    from agents.kpi_auto_updater import _SOURCES
    val = _SOURCES["eval.latest"](dt.date.today())
    # No DB rows → None.
    assert val is None


def test_cost_source_when_no_db(isolated):
    from agents.kpi_auto_updater import _SOURCES
    val = _SOURCES["cost.weekly"](dt.date.today())
    assert val == 0.0


# ── _kpi_source ──────────────────────────────────────────────────


def test_kpi_source_reads_field(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: x
            target: 10
            source: cost.weekly
    """)
    from agents.kpi_auto_updater import _kpi_source
    assert _kpi_source("P", "x") == "cost.weekly"


def test_kpi_source_missing_returns_none(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: x
            target: 10
    """)
    from agents.kpi_auto_updater import _kpi_source
    assert _kpi_source("P", "x") is None


# ── sync() ───────────────────────────────────────────────────────


def test_sync_pushes_value_into_history(isolated, monkeypatch):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: contacts
            target: 5
            source: stakeholders.total
    """)
    from agents import stakeholder_tracker as st
    st.upsert("Alice", email="a@x")
    st.upsert("Bob", email="b@x")
    st.upsert("Carol", email="c@x")
    from agents import kpi_auto_updater as kau
    out = kau.sync(today=dt.date(2026, 5, 3))
    assert out == {"P": [("contacts", 3.0)]}
    # YAML now has a history point.
    from agents import kpi_tracker as kt
    [k] = kt.load("P")
    assert k.current == 3.0


def test_sync_idempotent_within_day(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: contacts
            target: 5
            source: stakeholders.total
    """)
    from agents import stakeholder_tracker as st
    st.upsert("X", email="x@y")
    from agents import kpi_auto_updater as kau
    today = dt.date(2026, 5, 3)
    a = kau.sync(today=today)
    b = kau.sync(today=today)
    assert a == {"P": [("contacts", 1.0)]}
    assert b == {}   # no second push for the same date


def test_sync_handles_multiple_kpis(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: contacts
            target: 5
            source: stakeholders.total
          - id: weekly-cost
            target: 25.0
            source: cost.weekly
    """)
    from agents import stakeholder_tracker as st
    st.upsert("X", email="x@y")
    from agents import kpi_auto_updater as kau
    out = kau.sync(today=dt.date(2026, 5, 3))
    ids = {k for k, _v in out["P"]}
    assert ids == {"contacts", "weekly-cost"}


def test_sync_skips_unsourced_kpis(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: manual
            target: 10
    """)
    from agents import kpi_auto_updater as kau
    assert kau.sync(today=dt.date(2026, 5, 3)) == {}


def test_sync_skips_unknown_source(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: x
            target: 5
            source: ghost.source
    """)
    from agents import kpi_auto_updater as kau
    assert kau.sync(today=dt.date(2026, 5, 3)) == {}


def test_sync_swallows_source_errors(isolated, monkeypatch):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: ok
            target: 5
            source: stakeholders.total
          - id: broken
            target: 5
            source: weather.now
    """)
    import agents.kpi_auto_updater as kau

    def boom(_today):
        raise RuntimeError("nope")

    monkeypatch.setitem(kau._SOURCES, "weather.now", boom)
    out = kau.sync(today=dt.date(2026, 5, 3))
    # `ok` kpi pushed, broken one swallowed.
    ids = {k for k, _ in out.get("P", [])}
    assert "ok" in ids
    assert "broken" not in ids


def test_sync_ignores_invalid_projects(isolated):
    write_proj(isolated, "broken", "- not a mapping\n")
    write_proj(isolated, "good", """
        name: good
        kpis:
          - id: x
            target: 5
            source: stakeholders.total
    """)
    from agents.kpi_auto_updater import sync
    out = sync(today=dt.date(2026, 5, 3))
    assert "good" in out
    assert "broken" not in out
