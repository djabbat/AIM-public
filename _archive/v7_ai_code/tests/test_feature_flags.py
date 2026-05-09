"""tests/test_feature_flags.py — FX1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_FLAGS_DB", str(tmp_path / "flags.db"))
    import importlib, sys
    if "agents.feature_flags" in sys.modules:
        importlib.reload(sys.modules["agents.feature_flags"])
    return tmp_path


# ── add ──────────────────────────────────────────────────────────


def test_add_creates_flag(isolated):
    from agents.feature_flags import add, get
    add("new-pricing", project="P", owner="alice",
        cleanup_by="2026-08-01", notes="rollout v2")
    f = get("new-pricing")
    assert f is not None
    assert f.project == "P"
    assert f.owner == "alice"
    assert f.cleanup_by == "2026-08-01"


def test_add_is_upsert(isolated):
    from agents.feature_flags import add, get
    add("x", owner="a")
    add("x", owner="b")
    assert get("x").owner == "b"


def test_add_rejects_blank_id(isolated):
    from agents.feature_flags import add
    with pytest.raises(ValueError):
        add("")


def test_add_rejects_invalid_status(isolated):
    from agents.feature_flags import add
    with pytest.raises(ValueError):
        add("x", status="bogus")


# ── update ───────────────────────────────────────────────────────


def test_update_changes_fields(isolated):
    from agents.feature_flags import add, update, get
    add("x", status="active")
    assert update("x", status="ramping", notes="50% live") is True
    f = get("x")
    assert f.status == "ramping"
    assert f.notes == "50% live"


def test_update_unknown_returns_false(isolated):
    from agents.feature_flags import update
    assert update("ghost", status="active") is False


def test_update_invalid_status_raises(isolated):
    from agents.feature_flags import add, update
    add("x")
    with pytest.raises(ValueError):
        update("x", status="bogus")


# ── list & filter ────────────────────────────────────────────────


def test_list_filters_by_status(isolated):
    from agents.feature_flags import add, list_flags
    add("a", status="active")
    add("b", status="ramping")
    add("c", status="retired")
    active = [f.id for f in list_flags(status="active")]
    retired = [f.id for f in list_flags(status="retired")]
    assert active == ["a"]
    assert retired == ["c"]


def test_list_filters_by_project(isolated):
    from agents.feature_flags import add, list_flags
    add("a", project="FCLC")
    add("b", project="MCOA")
    fclc = [f.id for f in list_flags(project="FCLC")]
    assert fclc == ["a"]


# ── overdue logic ────────────────────────────────────────────────


def test_overdue_picks_past_cleanup(isolated):
    from agents.feature_flags import add, overdue
    add("late", cleanup_by="2026-04-01")
    add("future", cleanup_by="2027-01-01")
    add("retired-late", cleanup_by="2026-04-01", status="retired")
    rows = overdue(today=dt.date(2026, 5, 3), horizon_days=0)
    ids = {f.id for f in rows}
    assert "late" in ids
    assert "future" not in ids
    assert "retired-late" not in ids


def test_overdue_horizon_extends_window(isolated):
    from agents.feature_flags import add, overdue
    add("near", cleanup_by="2026-05-10")
    rows_zero = overdue(today=dt.date(2026, 5, 3), horizon_days=0)
    rows_horizon = overdue(today=dt.date(2026, 5, 3), horizon_days=14)
    assert "near" not in {f.id for f in rows_zero}
    assert "near" in {f.id for f in rows_horizon}


def test_overdue_skips_no_cleanup(isolated):
    from agents.feature_flags import add, overdue
    add("forever", cleanup_by=None)
    assert overdue(today=dt.date(2026, 5, 3)) == []


def test_flag_overdue_helper(isolated):
    from agents.feature_flags import Flag
    f = Flag(id="x", project=None, owner=None, status="active",
              cleanup_by="2026-04-01", notes=None)
    assert f.overdue(today=dt.date(2026, 5, 3)) is True
    assert f.overdue(today=dt.date(2026, 3, 1)) is False


# ── remove ───────────────────────────────────────────────────────


def test_remove_returns_bool(isolated):
    from agents.feature_flags import add, remove, get
    add("x")
    assert remove("x") is True
    assert get("x") is None
    assert remove("x") is False


# ── summary ──────────────────────────────────────────────────────


def test_summary_empty(isolated):
    from agents.feature_flags import summary
    assert "no feature flags" in summary()


def test_summary_includes_overdue(isolated):
    from agents.feature_flags import add, summary
    add("late", cleanup_by="2026-04-01", owner="ops")
    add("active-thing", status="ramping")
    s = summary(today=dt.date(2026, 5, 3))
    assert "🚩" in s
    assert "active-thing" not in s.split("⚠")[0] or "ramping" in s
    assert "overdue" in s
    assert "late" in s


def test_summary_status_breakdown(isolated):
    from agents.feature_flags import add, summary
    for i in range(3):
        add(f"a{i}", status="active")
    add("b", status="ramping")
    s = summary()
    assert "active: 3" in s
    assert "ramping: 1" in s
