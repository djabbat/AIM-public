"""tests/test_deadline_scanner.py — P2 calendar-aware deadlines (2026-05-02)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest

from agents import deadline_scanner as ds


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    return tmp_path


def write_yaml(projects_dir, name, body):
    (projects_dir / f"{name}.yaml").write_text(textwrap.dedent(body),
                                               encoding="utf-8")


# ── text extraction ──────────────────────────────────────────────────


def test_extract_simple_iso_date():
    text = "We need to ship by 2026-10-28 to make it."
    d = list(ds._extract_deadlines_from_text(text, "<test>"))
    assert len(d) == 1
    assert d[0].when == dt.date(2026, 10, 28)
    assert d[0].kind == "memory"


def test_extract_deadline_marker_high_criticality():
    text = "**Deadline:** 2026-10-28 17:00 CET"
    d = list(ds._extract_deadlines_from_text(text, "<test>"))
    assert len(d) == 1
    assert d[0].criticality == "high"


def test_extract_dedupes_repeated_lines():
    text = "Foo 2026-05-10\nFoo 2026-05-10\n"
    d = list(ds._extract_deadlines_from_text(text, "<test>"))
    assert len(d) == 1


def test_extract_skips_implausible_year():
    # Pre-1900 / phone-like (1234567) shouldn't match.
    text = "Phone: 1234567 (extension 0042)"
    assert list(ds._extract_deadlines_from_text(text, "<t>")) == []


def test_extract_handles_multiple_distinct_dates():
    text = "First 2026-05-10. Then 2026-06-15."
    out = list(ds._extract_deadlines_from_text(text, "<t>"))
    assert {d.when for d in out} == {dt.date(2026, 5, 10), dt.date(2026, 6, 15)}


# ── yaml scanner ─────────────────────────────────────────────────────


def test_scan_yaml_pulls_milestone_deadlines(projects_dir):
    write_yaml(projects_dir, "FCLC", """
        name: FCLC
        milestones:
          - id: a
            deadline: 2026-10-28T17:00:00+02:00
            criticality: high
            blockers: [LoIs, PATE]
          - id: b
            deadline: 2026-08-31
            criticality: medium
          - id: no-deadline
            criticality: low
    """)
    out = ds.scan_yaml(today=dt.date(2026, 5, 2))
    ids = {d.label.split(": ", 1)[1].split(" ", 1)[0] for d in out}
    assert ids == {"a", "b"}
    a = next(d for d in out if "a —" in d.label)
    assert a.criticality == "high"
    assert "LoIs" in a.label


# ── calendar scanner ─────────────────────────────────────────────────


def test_scan_calendar_filters_past_and_far_future():
    today = dt.date(2026, 5, 2)
    events = [
        {"summary": "Past meeting",   "start": "2026-04-01"},
        {"summary": "Today's call",   "start": "2026-05-02"},
        {"summary": "Next week",      "start": "2026-05-08"},
        {"summary": "Way off",        "start": "2027-08-01"},
        {"summary": "Bad date",       "start": "not-a-date"},
        {"summary": "No date"},
    ]
    out = ds.scan_calendar(today, lambda: events, horizon_fwd=60)
    summaries = {d.label for d in out}
    assert summaries == {"Today's call", "Next week"}


def test_scan_calendar_handles_pull_failure():
    def boom():
        raise RuntimeError("network down")
    out = ds.scan_calendar(dt.date.today(), boom)
    assert out == []


def test_scan_calendar_no_pull_returns_empty():
    assert ds.scan_calendar(dt.date.today(), None) == []


# ── horizon partitioning ────────────────────────────────────────────


def _d(day_offset, label="x", kind="memory"):
    return ds.Deadline(
        when=dt.date(2026, 5, 2) + dt.timedelta(days=day_offset),
        label=label, source="t", kind=kind,
    )


def test_by_horizon_buckets():
    today = dt.date(2026, 5, 2)
    items = [_d(-3, "old"), _d(0, "today"), _d(5, "week"),
             _d(20, "month"), _d(99, "later")]
    bk = ds.by_horizon(items, today)
    assert [d.label for d in bk["overdue"]]    == ["old"]
    assert [d.label for d in bk["today"]]      == ["today"]
    assert [d.label for d in bk["this_week"]]  == ["week"]
    assert [d.label for d in bk["this_month"]] == ["month"]
    assert [d.label for d in bk["later"]]      == ["later"]


# ── full pipeline & dedup ──────────────────────────────────────────


def test_scan_all_dedupes_milestone_vs_memory(projects_dir, monkeypatch):
    """When the same date+label appears via YAML and memory, the milestone
    source wins (more authoritative)."""
    write_yaml(projects_dir, "FCLC", """
        name: FCLC
        milestones:
          - id: eic-submit
            deadline: 2026-10-28
            criticality: high
    """)
    monkeypatch.setattr(ds, "scan_memory",
                        lambda today: [ds.Deadline(
                            when=dt.date(2026, 10, 28),
                            label="FCLC: eic-submit",
                            source="<memory>",
                            kind="memory")])
    out = ds.scan_all(today=dt.date(2026, 5, 2))
    eic = [d for d in out if "eic-submit" in d.label]
    assert len(eic) == 1
    assert eic[0].kind == "milestone"


def test_summary_renders(projects_dir, monkeypatch):
    write_yaml(projects_dir, "P", """
        name: P
        milestones:
          - id: hot
            deadline: 2026-05-05
            criticality: high
          - id: month-out
            deadline: 2026-05-25
            criticality: medium
    """)
    # Disable real-memory scan so the test asserts on isolated YAML only.
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    s = ds.summary(today=dt.date(2026, 5, 2),
                   calendar_pull=lambda: [])
    assert "📅 this week" in s
    assert "hot" in s
    assert "month-out" in s


def test_summary_empty_when_nothing(projects_dir, monkeypatch):
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    s = ds.summary(today=dt.date(2026, 5, 2),
                   calendar_pull=lambda: [])
    assert "Deadlines as of 2026-05-02" in s
    assert "(no deadlines on the radar)" in s


# ── CT1 conflict detection ───────────────────────────────────────


def _today_d(day_offset, label, kind="memory"):
    return ds.Deadline(
        when=dt.date.today() + dt.timedelta(days=day_offset),
        label=label, source="t", kind=kind,
    )


def test_conflicts_detects_same_day(monkeypatch):
    items = [
        _today_d(0, "a"),
        _today_d(0, "b"),
        _today_d(1, "lone"),
    ]
    out = ds.conflicts(items)
    assert len(out) == 1
    date, packed = out[0]
    assert date == dt.date.today()
    assert {d.label for d in packed} == {"a", "b"}


def test_conflicts_skips_days_with_one_item():
    items = [_today_d(0, "a"), _today_d(1, "b")]
    assert ds.conflicts(items) == []


def test_conflicts_respects_window():
    items = [_today_d(0, "a"), _today_d(0, "b"),
             _today_d(15, "far_a"), _today_d(15, "far_b")]
    out = ds.conflicts(items, window_days=7)
    assert len(out) == 1
    assert out[0][0] == dt.date.today()


def test_conflicts_skips_overdue():
    """We don't surface overdue clusters; the brief already does that."""
    items = [_today_d(-5, "old1"), _today_d(-5, "old2")]
    assert ds.conflicts(items) == []


def test_conflicts_threshold():
    items = [_today_d(0, "a"), _today_d(0, "b")]
    assert ds.conflicts(items, min_critical_per_day=3) == []
    assert len(ds.conflicts(items, min_critical_per_day=2)) == 1
