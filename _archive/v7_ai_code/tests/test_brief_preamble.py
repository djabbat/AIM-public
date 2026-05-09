"""tests/test_brief_preamble.py — B1 smart preamble (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest

from agents import brief_preamble as bp


# ── greeting time-of-day ────────────────────────────────────────


@pytest.mark.parametrize("hour,expected_prefix", [
    (3, "Спокойной ночи"),
    (8, "Доброе утро"),
    (14, "Добрый день"),
    (21, "Добрый вечер"),
])
def test_greeting_by_hour(hour, expected_prefix):
    g = bp._greeting(dt.datetime(2026, 5, 3, hour, 0))
    assert g.startswith(expected_prefix)
    assert "Джаба" in g


def test_greeting_custom_name():
    g = bp._greeting(dt.datetime(2026, 5, 3, 9, 0), name="Igor")
    assert "Igor" in g


# ── milestone line ──────────────────────────────────────────────


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    import importlib
    import agents.project_owner as po
    importlib.reload(po)
    return tmp_path


def write_proj(setup, name, body):
    (setup / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


def test_hot_milestone_picks_today(projects):
    write_proj(projects, "FCLC", """
        name: FCLC
        milestones:
          - id: today-thing
            deadline: 2026-05-03
            criticality: high
            status: pending
          - id: distant
            deadline: 2026-12-01
            criticality: high
            status: pending
    """)
    line = bp._hot_milestone_line(dt.date(2026, 5, 3))
    assert "СЕГОДНЯ" in line
    assert "today-thing" in line
    assert "FCLC" in line


def test_hot_milestone_skips_done(projects):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: was-hot
            deadline: 2026-05-03
            criticality: high
            status: done
    """)
    assert bp._hot_milestone_line(dt.date(2026, 5, 3)) is None


def test_hot_milestone_outside_window_ignored(projects):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: far
            deadline: 2027-01-01
            criticality: high
            status: pending
    """)
    assert bp._hot_milestone_line(dt.date(2026, 5, 3)) is None


def test_hot_milestone_prefers_high_criticality(projects):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: low-pri
            deadline: 2026-05-04
            criticality: low
            status: pending
          - id: hi-pri
            deadline: 2026-05-10
            criticality: high
            status: pending
    """)
    line = bp._hot_milestone_line(dt.date(2026, 5, 3))
    assert "hi-pri" in line


# ── stakeholder line ────────────────────────────────────────────


@pytest.fixture
def contacts(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "contacts.db"))
    import importlib
    import agents.stakeholder_tracker as st
    importlib.reload(st)
    return st


def test_stakeholder_line_when_overdue(contacts):
    contacts.on_email_sent(name="Miguel", email="m@x", role="Co-PI",
                            expected_response_by="2026-04-25")
    line = bp._stakeholder_line(dt.date(2026, 5, 3))
    assert line is not None
    assert "Miguel" in line
    assert "8д" in line


def test_stakeholder_line_none_when_clean(contacts):
    contacts.on_email_sent(name="X", email="x@y",
                            expected_response_by="2026-06-01")
    assert bp._stakeholder_line(dt.date(2026, 5, 3)) is None


# ── deadline horizon line ───────────────────────────────────────


def test_deadline_horizon_line_includes_counts(projects, monkeypatch):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: today-x
            deadline: 2026-05-03
            criticality: high
            status: pending
          - id: near
            deadline: 2026-05-08
            criticality: medium
            status: pending
    """)
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    line = bp._deadline_horizon_line(dt.date(2026, 5, 3))
    assert line is not None
    assert "1 сегодня" in line
    assert "1 в эту неделю" in line


def test_deadline_horizon_line_none_when_clean(projects, monkeypatch):
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    assert bp._deadline_horizon_line(dt.date(2026, 5, 3)) is None


# ── compose() integration ───────────────────────────────────────


def test_compose_combines_sources(projects, contacts, monkeypatch):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: today-x
            deadline: 2026-05-03
            criticality: high
            status: pending
    """)
    contacts.on_email_sent(name="Late", email="l@x", role="Co-PI",
                           expected_response_by="2026-04-20")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    text = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0))
    assert "Доброе утро" in text
    assert "today-x" in text
    assert "Late" in text


def test_compose_truncates_long(projects, contacts, monkeypatch):
    # Force several long stakeholder rows into the DB.
    for i in range(5):
        contacts.on_email_sent(
            name=f"PersonWithVeryLongName{i}",
            email=f"p{i}@x", role="A very long role description",
            expected_response_by="2026-04-01",
        )
    write_proj(projects, "P", "name: P")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    # Pin `now` to a morning hour so the greeting is deterministic
    # — without it, the test flakes whenever the suite runs in the
    # afternoon ("Добрый день") or evening.
    out = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0),
                      max_chars=120)
    # Greeting must always survive.
    assert "Доброе утро" in out or "Спокойной ночи" in out


def test_compose_calm_morning(projects, contacts, monkeypatch):
    """No milestones, no contacts, no deadlines → just a greeting."""
    write_proj(projects, "P", "name: P")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    out = bp.compose(today=dt.date(2026, 5, 3),
                     now=dt.datetime(2026, 5, 3, 9, 0))
    lines = out.splitlines()
    assert lines[0].startswith("Доброе утро")


# ── install_into_brief ────────────────────────────────────────


def test_install_sets_env(projects, monkeypatch):
    write_proj(projects, "P", "name: P")
    monkeypatch.delenv("AIM_BRIEF_HEAD", raising=False)
    import os
    text = bp.install_into_brief()
    assert os.environ.get("AIM_BRIEF_HEAD") == text


# ── U1 multi-language ────────────────────────────────────────────


def test_compose_english(projects, monkeypatch):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: today-x
            deadline: 2026-05-03
            criticality: high
            status: pending
    """)
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    out = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0),
                      lang="en")
    assert "Good morning" in out
    assert "TODAY" in out
    assert "СЕГОДНЯ" not in out


def test_compose_georgian(projects, monkeypatch):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: today-x
            deadline: 2026-05-03
            criticality: high
            status: pending
    """)
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    out = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0),
                      lang="ka")
    assert "დილა მშვიდობისა" in out
    assert "დღეს" in out


def test_compose_unknown_lang_falls_back_to_russian(projects, monkeypatch):
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    out = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0),
                      lang="xx-bogus")
    # Default RU greeting.
    assert any(x in out for x in ("Доброе утро", "Спокойной ночи",
                                    "Добрый день", "Добрый вечер"))


def test_compose_lang_env(projects, monkeypatch):
    monkeypatch.setenv("AIM_BRIEF_LANG", "en")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    out = bp.compose(today=dt.date(2026, 5, 3),
                      now=dt.datetime(2026, 5, 3, 9, 0))
    assert "Good morning" in out


def test_default_name_per_language(projects, monkeypatch):
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    ru = bp.compose(today=dt.date(2026, 5, 3),
                     now=dt.datetime(2026, 5, 3, 9, 0), lang="ru")
    en = bp.compose(today=dt.date(2026, 5, 3),
                     now=dt.datetime(2026, 5, 3, 9, 0), lang="en")
    ka = bp.compose(today=dt.date(2026, 5, 3),
                     now=dt.datetime(2026, 5, 3, 9, 0), lang="ka")
    assert "Джаба" in ru
    assert "Jaba" in en
    assert "ჯაბა" in ka


# ── auto-wire into daily_brief ───────────────────────────────


def test_daily_brief_auto_uses_preamble(projects, monkeypatch, capsys):
    write_proj(projects, "P", """
        name: P
        milestones:
          - id: hot-x
            deadline: 2026-05-03
            criticality: high
            status: pending
    """)
    monkeypatch.delenv("AIM_BRIEF_HEAD", raising=False)
    monkeypatch.setenv("AIM_TG_DRYRUN", "1")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    import importlib, scripts.daily_brief as db
    importlib.reload(db)
    text = db.render_brief(today=dt.date(2026, 5, 3))
    # The preamble's milestone reference shows up before the brief header.
    head_idx = text.index("AIM daily brief")
    preamble = text[:head_idx]
    assert "СЕГОДНЯ" in preamble
    assert "hot-x" in preamble
