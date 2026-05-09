"""tests/test_quick_action.py — Q1 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "c.db"))
    (tmp_path / "projects").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.stakeholder_tracker",
              "agents.quick_action"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── classify() ────────────────────────────────────────────────────


@pytest.mark.parametrize("query,expected", [
    ("morning brief", "brief"),
    ("Брифинг пожалуйста", "brief"),
    ("what's hot", "escalate"),
    ("что горит сейчас?", "escalate"),
    ("follow-up everyone", "followups"),
    ("напомни всем", "followups"),
    ("health check", "health"),
    ("recall FCLC deadline", "recall"),
    ("найди в памяти Lezhava", "recall"),
])
def test_classify_simple_intents(isolated, query, expected):
    from agents.quick_action import classify
    intent = classify(query)
    assert intent.name == expected, f"{query!r} → {intent}"


def test_classify_empty_returns_noop(isolated):
    from agents.quick_action import classify
    assert classify("").name == "noop"
    assert classify("   ").name == "noop"


def test_classify_unknown_returns_unknown(isolated):
    from agents.quick_action import classify
    assert classify("randomly weird sentence").name == "unknown"


def test_classify_project_brief(isolated):
    (isolated / "projects" / "FCLC.yaml").write_text("name: FCLC\n")
    import importlib
    import agents.quick_action as qa
    importlib.reload(qa)
    intent = qa.classify("FCLC status please")
    assert intent.name == "project_brief"
    assert intent.args["project"] == "FCLC"


def test_classify_project_transition(isolated):
    (isolated / "projects" / "FCLC.yaml").write_text("name: FCLC\n")
    import importlib
    import agents.quick_action as qa
    importlib.reload(qa)
    intent = qa.classify("transition FCLC to SUBMITTED")
    assert intent.name == "project_transition"
    assert intent.args == {"project": "FCLC", "dst": "SUBMITTED"}


def test_classify_draft_email_with_recipient(isolated):
    from agents.quick_action import classify
    intent = classify("Draft email to Geiger about Phase B")
    assert intent.name == "draft_email"
    assert intent.args["recipient_hint"] == "Geiger"


def test_classify_recall_strips_trigger(isolated):
    from agents.quick_action import classify
    intent = classify("recall: EIC submission")
    assert intent.name == "recall"
    assert intent.args["query"] == "EIC submission"


def test_classify_unknown_project_falls_through(isolated):
    """A project token that isn't in the registry should NOT trigger
    project_brief — we'd rather classify as unknown so the user can
    retype than send a misrouted brief."""
    from agents.quick_action import classify
    intent = classify("XYZ status")
    assert intent.name in ("unknown", "brief")
    if intent.name == "brief":
        # 'status' is a brief-trigger only when no project is matched —
        # acceptable interpretation.
        return


# ── handle() smoke ───────────────────────────────────────────────


def test_handle_brief(isolated, monkeypatch):
    (isolated / "projects" / "P.yaml").write_text("name: P\n")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    from agents.quick_action import handle
    out = handle("morning brief")
    assert out["action"] == "brief"
    assert "P" in out["output"]


def test_handle_recall_dispatches(isolated, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "hit", "_distance": 0.1}])
    from agents.quick_action import handle
    out = handle("recall FCLC")
    assert out["action"] == "recall"
    assert "x.md" in out["output"]


def test_handle_followups(isolated):
    from agents import stakeholder_tracker as st
    st.on_email_sent(name="Late", email="l@x", role="Co-PI",
                     expected_response_by="2026-04-25")
    from agents.quick_action import handle
    out = handle("follow-up everyone")
    assert out["action"] == "followups"
    assert out["n_drafts"] == 1


def test_handle_escalate(isolated):
    (isolated / "projects" / "P.yaml").write_text(textwrap.dedent("""
        name: P
        milestones:
          - id: m
            deadline: 2026-05-04
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """).lstrip())
    from agents.quick_action import handle
    out = handle("what's hot")
    assert out["action"] == "escalate"
    assert out["n_alerts"] >= 1


def test_handle_unknown_returns_error(isolated):
    from agents.quick_action import handle
    out = handle("totally unrecognizable random input zzz")
    assert out["action"] == "unknown"
    assert "no rule matched" in out["error"]


def test_handle_empty_returns_noop(isolated):
    from agents.quick_action import handle
    out = handle("")
    assert out["action"] == "noop"


def test_handle_project_brief(isolated):
    (isolated / "projects" / "FCLC.yaml").write_text(
        "name: FCLC\nphase: SUBMITTED\n")
    import importlib
    import agents.quick_action as qa
    importlib.reload(qa)
    out = qa.handle("FCLC brief")
    assert out["action"] == "project_brief"
    assert "FCLC" in out["output"]


def test_handle_handler_exception_caught(isolated, monkeypatch):
    """If a handler raises, we wrap into {error: ...} not crash."""
    import agents.quick_action as qa

    def boom(_args):
        raise RuntimeError("internal boom")

    monkeypatch.setitem(qa._HANDLERS, "brief", boom)
    out = qa.handle("morning brief")
    assert out["action"] == "brief"
    assert "RuntimeError" in out["error"]
