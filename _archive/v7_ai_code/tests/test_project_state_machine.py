"""tests/test_project_state_machine.py — P5 phase machine (2026-05-02)."""
from __future__ import annotations

import json
import textwrap

import pytest

from agents import project_state_machine as sm


@pytest.fixture
def isolated_setup(tmp_path, monkeypatch):
    """Tmp projects dir + tmp audit log."""
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    (tmp_path / "projects").mkdir()
    return tmp_path


def write_proj(setup, name, phase="DRAFT", extra=""):
    body = f"name: {name}\nphase: {phase}\n{extra}"
    (setup / "projects" / f"{name}.yaml").write_text(textwrap.dedent(body),
                                                     encoding="utf-8")


# ── legal/illegal map ────────────────────────────────────────────────


@pytest.mark.parametrize("src,dst,legal", [
    ("DRAFT",     "REVIEW",    True),
    ("DRAFT",     "SUBMITTED", True),
    ("DRAFT",     "ACCEPTED",  False),  # must go through SUBMITTED
    ("REVIEW",    "DRAFT",     True),
    ("REVIEW",    "SUBMITTED", True),
    ("SUBMITTED", "ACCEPTED",  True),
    ("SUBMITTED", "REJECTED",  True),
    ("SUBMITTED", "REVIEW",    True),
    ("SUBMITTED", "PUBLISHED", False),  # must accept first
    ("ACCEPTED",  "PUBLISHED", True),
    ("PUBLISHED", "ARCHIVED",  True),
    ("PUBLISHED", "DRAFT",     False),  # terminal except ARCHIVED
    ("REJECTED",  "DRAFT",     True),
    ("ARCHIVED",  "DRAFT",     False),  # archived is terminal
    ("DRAFT",     "FOO",       False),  # unknown phase
    ("draft",     "review",    True),   # case-insensitive
])
def test_is_legal(src, dst, legal):
    assert sm.is_legal(src, dst) is legal


def test_phases_are_canonical():
    assert "DRAFT" in sm.PHASES
    assert len(sm.PHASES) == 7


# ── next_actions ─────────────────────────────────────────────────────


def test_next_actions_for_each_phase():
    for p in sm.PHASES:
        actions = sm.next_actions(p)
        assert isinstance(actions, list) and actions, f"empty for {p}"


def test_next_actions_unknown_phase_empty():
    assert sm.next_actions("NOPE") == []


def test_next_actions_case_insensitive():
    assert sm.next_actions("draft") == sm.next_actions("DRAFT")


# ── transition: persistence ──────────────────────────────────────────


def test_transition_writes_yaml_and_audit(isolated_setup):
    write_proj(isolated_setup, "P", "DRAFT")
    rec = sm.transition("P", "REVIEW", reason="ready for FCLC v11")
    assert rec["from"] == "DRAFT"
    assert rec["to"] == "REVIEW"
    assert rec["reason"] == "ready for FCLC v11"

    # YAML updated.
    body = (isolated_setup / "projects" / "P.yaml").read_text()
    assert "phase: REVIEW" in body

    # Audit log appended.
    audit = (isolated_setup / "home" / "phase_history.jsonl").read_text()
    rows = [json.loads(l) for l in audit.splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["project"] == "P"
    assert rows[0]["from"] == "DRAFT"
    assert rows[0]["to"] == "REVIEW"


def test_transition_rejects_illegal(isolated_setup):
    write_proj(isolated_setup, "P", "DRAFT")
    with pytest.raises(ValueError) as ei:
        sm.transition("P", "PUBLISHED")
    assert "illegal transition" in str(ei.value)


def test_transition_preserves_other_yaml_fields(isolated_setup):
    write_proj(isolated_setup, "P", "DRAFT", extra=textwrap.dedent("""
        goals:
          - keep me
        milestones:
          - id: m1
            criticality: high
        stakeholders:
          - name: Alice
            role: Co-PI
    """))
    sm.transition("P", "REVIEW")
    import yaml
    raw = yaml.safe_load((isolated_setup / "projects" / "P.yaml").read_text())
    assert raw["phase"] == "REVIEW"
    assert raw["goals"] == ["keep me"]
    assert raw["milestones"][0]["id"] == "m1"
    assert raw["stakeholders"][0]["name"] == "Alice"


def test_history_filters_by_project(isolated_setup):
    write_proj(isolated_setup, "A", "DRAFT")
    write_proj(isolated_setup, "B", "DRAFT")
    sm.transition("A", "REVIEW")
    sm.transition("B", "SUBMITTED")
    a = sm.history("A")
    b = sm.history("B")
    all_hist = sm.history()
    assert len(a) == 1 and a[0]["project"] == "A"
    assert len(b) == 1 and b[0]["project"] == "B"
    assert len(all_hist) == 2


def test_history_empty_when_no_log(isolated_setup):
    assert sm.history("X") == []


# ── morning_brief integration ────────────────────────────────────────


def test_morning_brief_includes_phase_actions(isolated_setup):
    write_proj(isolated_setup, "P", phase="SUBMITTED")
    from agents import project_owner as po
    import importlib; importlib.reload(po)  # re-read AIM_PROJECTS_DIR
    import datetime as dt
    text = po.morning_brief("P", today=dt.date(2026, 5, 2))
    assert "📐 phase SUBMITTED — next actions:" in text
    # Spot-check one canonical action.
    assert "decision date" in text or "response-to-reviewers" in text
