"""tests/test_kpi_tracker.py — K1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    import importlib
    for m in ["agents.project_owner", "agents.kpi_tracker"]:
        if m in __import__("sys").modules:
            importlib.reload(__import__("sys").modules[m])
    return tmp_path


def write_proj(setup, name, body):
    (setup / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── KPI dataclass ────────────────────────────────────────────────


def test_current_returns_latest(isolated):
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, history=[
        KPIPoint(dt.date(2026, 4, 1), 3),
        KPIPoint(dt.date(2026, 5, 1), 7),
    ])
    assert k.current == 7


def test_current_none_when_no_history(isolated):
    from agents.kpi_tracker import KPI
    assert KPI(id="x", target=10).current is None


def test_progress_floor():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, history=[KPIPoint(dt.date.today(), 7)])
    assert k.progress == pytest.approx(0.7)


def test_progress_ceiling():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="cost", target=20, target_kind="ceiling",
             history=[KPIPoint(dt.date.today(), 15)])
    assert k.progress == 1.0   # under ceiling
    k.history = [KPIPoint(dt.date.today(), 30)]
    assert k.progress == 0.5   # 50% over ceiling


def test_status_floor():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, history=[KPIPoint(dt.date.today(), 10)])
    assert k.status == "met"
    k.history = [KPIPoint(dt.date.today(), 9)]
    assert k.status == "near"
    k.history = [KPIPoint(dt.date.today(), 4)]
    assert k.status == "behind"


def test_status_ceiling():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, target_kind="ceiling",
             history=[KPIPoint(dt.date.today(), 5)])
    assert k.status == "ok"
    k.history = [KPIPoint(dt.date.today(), 9)]
    assert k.status == "warn"
    k.history = [KPIPoint(dt.date.today(), 13)]
    assert k.status == "breach"


def test_velocity_per_week():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, history=[
        KPIPoint(dt.date(2026, 4, 1), 3),
        KPIPoint(dt.date(2026, 5, 1), 7),
    ])
    v = k.velocity_per_week()
    # Δ=4 over 30 days = ~0.93/week
    assert v == pytest.approx(4 / (30/7), rel=0.05)


def test_velocity_none_with_one_point():
    from agents.kpi_tracker import KPI, KPIPoint
    k = KPI(id="x", target=10, history=[KPIPoint(dt.date.today(), 5)])
    assert k.velocity_per_week() is None


# ── load / persist ───────────────────────────────────────────────


def test_load_parses_yaml(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: pubs
            target: 8
            unit: count
            history:
              - {date: 2026-04-01, value: 5}
              - {date: 2026-05-01, value: 7}
          - id: cost
            target: 25.0
            unit: usd
            target_kind: ceiling
    """)
    from agents.kpi_tracker import load
    ks = load("P")
    assert len(ks) == 2
    pubs = next(k for k in ks if k.id == "pubs")
    assert pubs.target == 8
    assert pubs.current == 7
    cost = next(k for k in ks if k.id == "cost")
    assert cost.target_kind == "ceiling"
    assert cost.history == []


def test_load_skips_invalid_target(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: bad
            target: not-a-number
          - id: good
            target: 10
    """)
    from agents.kpi_tracker import load
    ks = load("P")
    assert [k.id for k in ks] == ["good"]


def test_load_skips_invalid_history_points(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: x
            target: 10
            history:
              - {date: 2026-05-01, value: 5}
              - {date: bad, value: 1}
              - {date: 2026-05-02, value: not-a-number}
    """)
    from agents.kpi_tracker import load
    [k] = load("P")
    assert len(k.history) == 1
    assert k.history[0].value == 5


def test_record_appends_history(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: pubs
            target: 8
            history: []
    """)
    from agents.kpi_tracker import record, load
    record("P", "pubs", 5.0, date=dt.date(2026, 5, 1))
    record("P", "pubs", 6.0, date=dt.date(2026, 5, 8))
    [k] = load("P")
    assert k.current == 6.0
    assert len(k.history) == 2


def test_record_unknown_kpi_raises(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: x
            target: 1
    """)
    from agents.kpi_tracker import record
    with pytest.raises(KeyError):
        record("P", "ghost", 1)


def test_record_missing_project_raises(isolated):
    from agents.kpi_tracker import record
    with pytest.raises(FileNotFoundError):
        record("ghost", "x", 1)


# ── summary string ──────────────────────────────────────────────


def test_summary_renders_bar_and_status(isolated):
    write_proj(isolated, "P", """
        name: P
        kpis:
          - id: pubs
            target: 8
            unit: count
            history:
              - {date: 2026-05-01, value: 8}
          - id: cost
            target: 25.0
            target_kind: ceiling
            history:
              - {date: 2026-05-01, value: 30}
    """)
    from agents.kpi_tracker import summary
    s = summary("P")
    assert "pubs" in s and "8" in s
    assert "met" in s
    assert "cost" in s
    assert "breach" in s


def test_summary_empty_when_no_kpis(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.kpi_tracker import summary
    assert summary("P") == ""


# ── morning_brief integration ──────────────────────────────────


def test_morning_brief_includes_kpi_block(isolated):
    write_proj(isolated, "P", """
        name: P
        phase: SUBMITTED
        kpis:
          - id: pubs
            target: 8
            unit: count
            history:
              - {date: 2026-05-01, value: 7}
    """)
    from agents import project_owner as po
    text = po.morning_brief("P", today=dt.date(2026, 5, 3))
    assert "📈 KPIs" in text
    assert "pubs" in text
