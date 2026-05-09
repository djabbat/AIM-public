"""tests/test_follow_up_generator.py — E1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    for m in ["agents.stakeholder_tracker",
              "agents.follow_up_generator"]:
        if m in __import__("sys").modules:
            importlib.reload(__import__("sys").modules[m])
    return tmp_path


# ── language detection ───────────────────────────────────────────


def test_detect_lang_russian(isolated):
    from agents.follow_up_generator import _detect_lang
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="Иван", email="i@x", role="ко-PI",
                project=None, last_contact_at=None,
                awaiting_reply=True, expected_response_by=None,
                notes="Tbilisi clinical partner")
    assert _detect_lang(c) == "ru"


def test_detect_lang_georgian_email(isolated):
    from agents.follow_up_generator import _detect_lang
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="X", email="prof@tsu.ge", role="advisor",
                project=None, last_contact_at=None,
                awaiting_reply=True, expected_response_by=None,
                notes="")
    assert _detect_lang(c) == "ka"


def test_detect_lang_default_english(isolated):
    from agents.follow_up_generator import _detect_lang
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="Hartmut", email="h@uni-ulm.de",
                role="Professor of Stem Cell Biology",
                project=None, last_contact_at=None,
                awaiting_reply=True, expected_response_by=None,
                notes="")
    assert _detect_lang(c) == "en"


# ── basic generation ────────────────────────────────────────────


def test_generate_english_template(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="Hartmut Geiger", email="h@uni-ulm.de",
                role="Co-PI Phase B", project="FCLC",
                last_contact_at="2026-04-01T00:00:00", awaiting_reply=True,
                expected_response_by="2026-04-25",
                notes="LoS signed; Co-PI conditional Phase A Go")
    d = generate(c, today=dt.date(2026, 5, 3))
    assert d is not None
    assert d.lang == "en"
    assert "Hartmut" in d.body
    assert "32 days" in d.body or "32 days" not in d.body  # may vary
    assert "Best,\nJaba Tkemaladze" in d.body
    assert d.subject.startswith("Quick follow-up")


def test_generate_russian_template(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="Иван Иванов", email="i@example.ru",
                role="Co-PI", project=None,
                last_contact_at="2026-04-15T00:00:00",
                awaiting_reply=True,
                expected_response_by="2026-04-25",
                notes="Tbilisi обсуждение")
    d = generate(c, today=dt.date(2026, 5, 3))
    assert d.lang == "ru"
    assert "Иван" in d.body
    assert "С уважением" in d.body


def test_generate_georgian_template(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="ჯაბა", email="x@tsu.ge",
                role="advisor", project=None,
                last_contact_at="2026-04-15T00:00:00",
                awaiting_reply=True,
                expected_response_by="2026-04-25",
                notes="")
    d = generate(c, today=dt.date(2026, 5, 3))
    assert d.lang == "ka"
    assert "ძვირფასო" in d.body
    assert "პატივისცემით" in d.body


def test_generate_skips_when_no_email(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="Anonymous", email=None, role="x",
                project=None, last_contact_at=None,
                awaiting_reply=True,
                expected_response_by="2026-04-25", notes="")
    assert generate(c, today=dt.date(2026, 5, 3)) is None


def test_subject_is_truncated(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="X", email="x@y", role="x" * 200,
                project=None, last_contact_at=None,
                awaiting_reply=True,
                expected_response_by="2026-04-25", notes="")
    d = generate(c, today=dt.date(2026, 5, 3))
    assert len(d.subject) <= 78


# ── llm polish hook ─────────────────────────────────────────────


def test_llm_hook_replaces_subject_and_body(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="X", email="x@y", role="r",
                project=None, last_contact_at="2026-04-01T00:00:00",
                awaiting_reply=True, expected_response_by="2026-04-25",
                notes="")

    def fake_llm(prompt: str) -> str:
        return "Subject: Polished subject\n\nPolished body."

    d = generate(c, today=dt.date(2026, 5, 3), llm=fake_llm)
    assert d.subject == "Polished subject"
    assert "Polished body" in d.body


def test_llm_hook_failure_falls_back(isolated):
    from agents.follow_up_generator import generate
    from agents.stakeholder_tracker import Contact
    c = Contact(id=1, name="X", email="x@y", role="r",
                project=None, last_contact_at=None,
                awaiting_reply=True, expected_response_by="2026-04-25",
                notes="")
    def boom(prompt): raise RuntimeError("nope")
    d = generate(c, today=dt.date(2026, 5, 3), llm=boom)
    assert d.subject.startswith("Quick follow-up")


# ── generate_all integration ────────────────────────────────────


def test_generate_all_iterates(isolated):
    from agents import stakeholder_tracker as st
    st.on_email_sent(name="Late", email="l@x.com",
                     expected_response_by="2026-04-25",
                     role="Co-PI")
    st.on_email_sent(name="OnTime", email="o@x.com",
                     expected_response_by="2026-05-15",
                     role="Co-PI")
    from agents.follow_up_generator import generate_all
    drafts = generate_all(today=dt.date(2026, 5, 3))
    assert {d.contact_name for d in drafts} == {"Late"}


# ── save_drafts (with stub email_agent) ─────────────────────────


def _patch_email_agent(monkeypatch, fake):
    """`from agents import email_agent` resolves via the `agents` package
    attribute first, falling back to sys.modules — patch BOTH so the
    stub wins regardless of whether the real module was already
    imported by an earlier test."""
    import sys, agents as _agents_pkg
    monkeypatch.setitem(sys.modules, "agents.email_agent", fake)
    monkeypatch.setattr(_agents_pkg, "email_agent", fake, raising=False)


def test_save_drafts_calls_email_agent(isolated, monkeypatch):
    from agents.follow_up_generator import Draft, save_drafts
    captured = []
    class FakeAgent:
        @staticmethod
        def create_draft(to, subject, body):
            captured.append({"to": to, "subject": subject, "body": body})
            return "draft-123"
    _patch_email_agent(monkeypatch, FakeAgent)
    ids = save_drafts([
        Draft(contact_name="X", contact_email="x@y",
              subject="S", body="B", lang="en", days_silent=5),
    ])
    assert ids == ["draft-123"]
    assert captured[0]["to"] == "x@y"


def test_save_drafts_returns_empty_when_agent_missing(isolated, monkeypatch):
    from agents.follow_up_generator import Draft, save_drafts
    import sys
    _patch_email_agent(monkeypatch, type(sys)("agents.email_agent"))
    ids = save_drafts([
        Draft(contact_name="X", contact_email="x@y",
              subject="S", body="B", lang="en", days_silent=5),
    ])
    assert ids == []
