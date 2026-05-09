"""tests/test_brief_preferences.py — B2 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_BRIEF_PREFS", str(tmp_path / "brief.yaml"))
    import importlib, sys
    if "agents.brief_preferences" in sys.modules:
        importlib.reload(sys.modules["agents.brief_preferences"])
    return tmp_path


def write_prefs(setup, body):
    (setup / "brief.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── defaults ──────────────────────────────────────────────────────


def test_defaults_when_no_file(isolated):
    from agents.brief_preferences import load
    p = load()
    assert p.lang == "ru"
    assert "telegram" in p.daily_channels
    assert p.quiet_start is None and p.quiet_end is None
    assert p.include_projects == []


def test_invalid_yaml_falls_back_to_defaults(isolated):
    write_prefs(isolated, "not: valid: yaml [[[")
    from agents.brief_preferences import load
    p = load()
    assert p.lang == "ru"


def test_yaml_with_list_top_level_uses_defaults(isolated):
    write_prefs(isolated, "- not\n- a\n- mapping\n")
    from agents.brief_preferences import load
    p = load()
    assert p.lang == "ru"


# ── parsing ──────────────────────────────────────────────────────


def test_loads_lang_and_name(isolated):
    write_prefs(isolated, """
        lang: en
        user_name: Jaba
    """)
    from agents.brief_preferences import load
    p = load()
    assert p.lang == "en"
    assert p.user_name == "Jaba"


def test_loads_quiet_hours(isolated):
    write_prefs(isolated, """
        quiet_hours: ["23:00", "07:00"]
    """)
    from agents.brief_preferences import load
    p = load()
    assert p.quiet_start == "23:00"
    assert p.quiet_end == "07:00"


def test_loads_channels(isolated):
    write_prefs(isolated, """
        channels:
          daily: [telegram]
          weekly: [email, telegram]
    """)
    from agents.brief_preferences import load
    p = load()
    assert p.daily_channels == ["telegram"]
    assert p.weekly_channels == ["email", "telegram"]


def test_loads_include_exclude(isolated):
    write_prefs(isolated, """
        include:
          sections: [hot_milestones, deadlines]
          projects: [FCLC, MCOA]
        exclude:
          projects: [Ze]
    """)
    from agents.brief_preferences import load
    p = load()
    assert p.include_sections == ["hot_milestones", "deadlines"]
    assert p.include_projects == ["FCLC", "MCOA"]
    assert p.exclude_projects == ["Ze"]


def test_loads_digest_window(isolated):
    write_prefs(isolated, "digest:\n  window_days: 14\n")
    from agents.brief_preferences import load
    p = load()
    assert p.digest_window_days == 14


def test_invalid_digest_window_falls_back(isolated):
    write_prefs(isolated, "digest:\n  window_days: not-a-number\n")
    from agents.brief_preferences import load
    p = load()
    assert p.digest_window_days == 7


# ── visibility helpers ──────────────────────────────────────────


def test_project_visible_default_all(isolated):
    from agents.brief_preferences import Preferences
    p = Preferences()
    assert p.project_visible("anything")


def test_project_visible_whitelist(isolated):
    from agents.brief_preferences import Preferences
    p = Preferences(include_projects=["FCLC"])
    assert p.project_visible("FCLC")
    assert not p.project_visible("MCOA")


def test_project_visible_blacklist_overrides_whitelist(isolated):
    from agents.brief_preferences import Preferences
    p = Preferences(include_projects=["FCLC"], exclude_projects=["FCLC"])
    assert not p.project_visible("FCLC")


def test_section_visible_when_listed(isolated):
    from agents.brief_preferences import Preferences
    p = Preferences(include_sections=["kpis"])
    assert p.section_visible("kpis")
    assert not p.section_visible("deadlines")


# ── quiet-hours ──────────────────────────────────────────────────


def test_quiet_hours_simple_window(isolated):
    write_prefs(isolated, """
        quiet_hours: ["09:00", "12:00"]
    """)
    from agents.brief_preferences import in_quiet_hours, load
    p = load()
    assert in_quiet_hours(now=dt.time(10, 0), prefs=p)
    assert not in_quiet_hours(now=dt.time(13, 0), prefs=p)
    assert not in_quiet_hours(now=dt.time(8, 59), prefs=p)


def test_quiet_hours_wraps_midnight(isolated):
    write_prefs(isolated, """
        quiet_hours: ["23:00", "07:00"]
    """)
    from agents.brief_preferences import in_quiet_hours, load
    p = load()
    assert in_quiet_hours(now=dt.time(23, 30), prefs=p)
    assert in_quiet_hours(now=dt.time(2, 0), prefs=p)
    assert not in_quiet_hours(now=dt.time(8, 0), prefs=p)


def test_quiet_hours_disabled_when_unset(isolated):
    from agents.brief_preferences import in_quiet_hours
    assert in_quiet_hours(now=dt.time(3, 0)) is False


def test_quiet_hours_disabled_when_equal(isolated):
    write_prefs(isolated, """
        quiet_hours: ["09:00", "09:00"]
    """)
    from agents.brief_preferences import in_quiet_hours, load
    assert not in_quiet_hours(now=dt.time(9, 0), prefs=load())


def test_quiet_hours_invalid_format_treated_as_off(isolated):
    write_prefs(isolated, """
        quiet_hours: ["not-a-time", "07:00"]
    """)
    from agents.brief_preferences import in_quiet_hours, load
    assert not in_quiet_hours(now=dt.time(3, 0), prefs=load())


# ── channel helpers ─────────────────────────────────────────────


def test_daily_channels_returns_list(isolated):
    write_prefs(isolated, """
        channels:
          daily: [telegram, log]
    """)
    from agents.brief_preferences import daily_channels
    assert daily_channels() == ["telegram", "log"]


def test_weekly_channels_returns_list(isolated):
    write_prefs(isolated, """
        channels:
          weekly: [email]
    """)
    from agents.brief_preferences import weekly_channels
    assert weekly_channels() == ["email"]
