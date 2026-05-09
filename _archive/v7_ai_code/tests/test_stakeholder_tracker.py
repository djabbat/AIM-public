"""tests/test_stakeholder_tracker.py — P3 contacts DB (2026-05-02)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the tracker at a tmp SQLite file. Reload module so any cached
    connections start fresh."""
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "contacts.db"))
    import importlib
    import agents.stakeholder_tracker as st
    importlib.reload(st)
    return st


@pytest.fixture
def isolated_projects(tmp_path, monkeypatch):
    proj = tmp_path / "projects"
    proj.mkdir()
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(proj))
    import importlib, agents.project_owner as po
    importlib.reload(po)
    return proj


# ── upsert & get ─────────────────────────────────────────────────────


def test_upsert_creates_new(isolated_db):
    cid = isolated_db.upsert("Alice", email="alice@example.com",
                             role="Co-PI", project="FCLC")
    c = isolated_db.get_by_email("alice@example.com")
    assert c is not None and c.id == cid
    assert c.name == "Alice"
    assert c.role == "Co-PI"


def test_upsert_is_idempotent(isolated_db):
    a = isolated_db.upsert("Alice", email="alice@example.com")
    b = isolated_db.upsert("Alice", email="alice@example.com")
    assert a == b


def test_upsert_updates_only_provided_fields(isolated_db):
    isolated_db.upsert("Alice", email="alice@example.com", role="X")
    isolated_db.upsert("Alice", email="alice@example.com", project="P1")
    c = isolated_db.get_by_email("alice@example.com")
    assert c.role == "X"           # not overwritten by None
    assert c.project == "P1"


def test_get_by_email_normalises(isolated_db):
    isolated_db.upsert("Bob", email="BOB@EXAMPLE.com")
    assert isolated_db.get_by_email("bob@example.com") is not None
    assert isolated_db.get_by_email("BOB@example.COM") is not None


def test_upsert_rejects_blank_name(isolated_db):
    with pytest.raises(ValueError):
        isolated_db.upsert("", email="x@example.com")


# ── lifecycle hooks ──────────────────────────────────────────────────


def test_on_email_sent_marks_awaiting(isolated_db):
    isolated_db.on_email_sent(name="Carol", email="carol@example.com",
                              expected_response_by="2026-05-10",
                              project="FCLC")
    c = isolated_db.get_by_email("carol@example.com")
    assert c.awaiting_reply is True
    assert c.expected_response_by == "2026-05-10"
    assert c.last_contact_at  # populated


def test_on_email_received_clears_awaiting(isolated_db):
    isolated_db.on_email_sent(name="Dave", email="dave@example.com",
                              expected_response_by="2026-05-10")
    assert isolated_db.on_email_received("dave@example.com")
    c = isolated_db.get_by_email("dave@example.com")
    assert c.awaiting_reply is False
    assert c.expected_response_by is None


def test_on_email_received_unknown_returns_false(isolated_db):
    assert isolated_db.on_email_received("nobody@example.com") is False


def test_on_meeting_only_bumps_last_contact(isolated_db):
    isolated_db.on_email_sent(name="Eve", email="eve@example.com",
                              expected_response_by="2026-05-10")
    isolated_db.on_meeting(email="eve@example.com")
    c = isolated_db.get_by_email("eve@example.com")
    # awaiting_reply preserved
    assert c.awaiting_reply is True


def test_on_email_sent_requires_name_or_email(isolated_db):
    with pytest.raises(ValueError):
        isolated_db.on_email_sent()


# ── queries ──────────────────────────────────────────────────────────


def test_overdue_followups(isolated_db):
    isolated_db.on_email_sent(name="Late", email="late@example.com",
                              expected_response_by="2026-04-25")
    isolated_db.on_email_sent(name="OnTime", email="ontime@example.com",
                              expected_response_by="2026-05-10")
    rows = isolated_db.overdue_followups(today=dt.date(2026, 5, 2))
    names = [r.name for r in rows]
    assert "Late" in names
    assert "OnTime" not in names


def test_silent_for_days(isolated_db):
    isolated_db.on_email_sent(name="Ghost", email="ghost@example.com")
    # Manually backdate last_contact_at via update.
    import sqlite3
    conn = sqlite3.connect(isolated_db.db_path())
    conn.execute("UPDATE contacts SET last_contact_at=? WHERE email=?",
                 ("2026-04-01T10:00:00", "ghost@example.com"))
    conn.commit(); conn.close()
    rows = isolated_db.silent_for(15, today=dt.date(2026, 5, 2))
    assert any(r.email == "ghost@example.com" for r in rows)


def test_by_project_filter(isolated_db):
    isolated_db.upsert("Alice", email="alice@example.com", project="FCLC")
    isolated_db.upsert("Bob", email="bob@example.com", project="MCOA")
    fclc = [c.name for c in isolated_db.by_project("FCLC")]
    mcoa = [c.name for c in isolated_db.by_project("MCOA")]
    assert fclc == ["Alice"]
    assert mcoa == ["Bob"]


# ── days_silent / overdue helpers ───────────────────────────────────


def test_contact_days_silent(isolated_db):
    isolated_db.on_email_sent(name="X", email="x@example.com")
    c = isolated_db.get_by_email("x@example.com")
    assert c.days_silent(today=dt.date.today()) == 0


def test_contact_overdue_helper(isolated_db):
    isolated_db.on_email_sent(name="X", email="x@example.com",
                              expected_response_by="2026-04-25")
    c = isolated_db.get_by_email("x@example.com")
    assert c.overdue(today=dt.date(2026, 5, 2)) is True
    assert c.overdue(today=dt.date(2026, 4, 20)) is False


# ── sync_from_yaml ──────────────────────────────────────────────────


def test_sync_imports_yaml_stakeholders(isolated_db, isolated_projects):
    (isolated_projects / "FCLC.yaml").write_text(textwrap.dedent("""
        name: FCLC
        stakeholders:
          - name: Geiger
            role: Co-PI
            last_contact: 2026-04-23
            awaiting_reply: false
          - name: Miguel
            role: Potential Co-PI
            last_contact: 2026-04-28
            awaiting_reply: true
            expected_response_by: 2026-05-05
    """), encoding="utf-8")
    n = isolated_db.sync_from_yaml()
    assert n == 2
    miguel = isolated_db.get_by_name("Miguel")
    assert len(miguel) == 1
    assert miguel[0].awaiting_reply is True
    assert miguel[0].expected_response_by == "2026-05-05"
    assert miguel[0].project == "FCLC"


def test_sync_is_idempotent(isolated_db, isolated_projects):
    (isolated_projects / "P.yaml").write_text(textwrap.dedent("""
        name: P
        stakeholders:
          - name: Solo
            role: Co-PI
    """), encoding="utf-8")
    isolated_db.sync_from_yaml()
    isolated_db.sync_from_yaml()
    rows = isolated_db.get_by_name("Solo")
    assert len(rows) == 1


def test_sync_handles_invalid_yaml(isolated_db, isolated_projects):
    (isolated_projects / "broken.yaml").write_text("- not a mapping\n",
                                                   encoding="utf-8")
    # Should skip silently rather than raise.
    n = isolated_db.sync_from_yaml()
    assert n == 0
