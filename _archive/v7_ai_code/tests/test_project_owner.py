"""tests/test_project_owner.py — P1 Project Owner Agent (2026-05-02)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest

from agents import project_owner as po


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    return tmp_path


def write_yaml(projects_dir, name: str, body: str) -> None:
    (projects_dir / f"{name}.yaml").write_text(textwrap.dedent(body),
                                               encoding="utf-8")


# ── parsing & loading ────────────────────────────────────────────────


def test_list_projects_empty(projects_dir):
    assert po.list_projects() == []


def test_list_projects_returns_stem_names(projects_dir):
    write_yaml(projects_dir, "FCLC", "name: FCLC")
    write_yaml(projects_dir, "MCOA", "name: MCOA")
    assert po.list_projects() == ["FCLC", "MCOA"]


def test_load_missing_project_raises(projects_dir):
    with pytest.raises(FileNotFoundError):
        po.load("ghost")


def test_load_minimal_yaml(projects_dir):
    write_yaml(projects_dir, "P", "name: P")
    s = po.load("P")
    assert s.name == "P"
    assert s.phase == "DRAFT"
    assert s.goals == []
    assert s.milestones == []
    assert s.stakeholders == []


def test_load_full_yaml(projects_dir):
    write_yaml(projects_dir, "FCLC", """
        name: FCLC
        phase: SUBMITTED
        goals:
          - Get funded
        milestones:
          - id: eic-submit
            deadline: 2026-10-28T17:00:00+02:00
            status: pending
            criticality: high
            blockers:
              - Need 2 LoIs
        stakeholders:
          - name: Geiger
            role: Co-PI
            last_contact: 2026-04-23
            awaiting_reply: false
        daily_checks:
          - countdown
    """)
    s = po.load("FCLC")
    assert s.phase == "SUBMITTED"
    assert s.goals == ["Get funded"]
    assert len(s.milestones) == 1
    m = s.milestones[0]
    assert m.id == "eic-submit"
    assert m.criticality == "high"
    assert m.deadline.year == 2026 and m.deadline.month == 10 and m.deadline.day == 28
    assert m.blockers == ["Need 2 LoIs"]
    assert len(s.stakeholders) == 1
    assert s.stakeholders[0].name == "Geiger"
    assert s.daily_checks == ["countdown"]


def test_load_invalid_yaml_raises(projects_dir):
    write_yaml(projects_dir, "bad", "- this is a list, not mapping")
    with pytest.raises(ValueError):
        po.load("bad")


# ── Milestone hot detection ─────────────────────────────────────────


def test_milestone_is_hot_within_7_days():
    today = dt.date(2026, 5, 2)
    m = po.Milestone(
        id="x",
        deadline=dt.datetime(2026, 5, 8),  # 6 days
        status="pending",
        criticality="medium",
    )
    assert m.is_hot(today)


def test_milestone_high_criticality_hot_within_14_days():
    today = dt.date(2026, 5, 2)
    m = po.Milestone(
        id="x",
        deadline=dt.datetime(2026, 5, 13),  # 11 days
        status="pending",
        criticality="high",
    )
    assert m.is_hot(today)


def test_milestone_done_is_not_hot():
    today = dt.date(2026, 5, 2)
    m = po.Milestone(
        id="x",
        deadline=dt.datetime(2026, 5, 3),
        status="done",
        criticality="high",
    )
    assert not m.is_hot(today)


def test_milestone_overdue_is_still_hot():
    today = dt.date(2026, 5, 2)
    m = po.Milestone(
        id="x",
        deadline=dt.datetime(2026, 4, 29),  # -3 days
        status="pending",
        criticality="high",
    )
    assert m.is_hot(today)
    assert m.days_to_deadline(today) == -3


# ── Stakeholder follow-up logic ─────────────────────────────────────


def test_stakeholder_overdue_when_past_expected_reply():
    today = dt.date(2026, 5, 10)
    s = po.Stakeholder(
        name="Miguel",
        role="Co-PI",
        awaiting_reply=True,
        expected_response_by=dt.date(2026, 5, 5),
    )
    assert s.overdue(today) is True


def test_stakeholder_not_overdue_when_not_awaiting():
    today = dt.date(2026, 5, 10)
    s = po.Stakeholder(name="x", awaiting_reply=False,
                      expected_response_by=dt.date(2026, 5, 5))
    assert s.overdue(today) is False


def test_overdue_followups_lists_them(projects_dir):
    write_yaml(projects_dir, "P", """
        name: P
        stakeholders:
          - name: Late
            role: Co-PI
            awaiting_reply: true
            expected_response_by: 2026-04-25
          - name: OnTime
            role: Co-PI
            awaiting_reply: true
            expected_response_by: 2026-05-10
    """)
    out = po.overdue_followups("P", today=dt.date(2026, 5, 2))
    assert any("Late" in s for s in out)
    assert not any("OnTime" in s for s in out)


# ── Brief rendering ─────────────────────────────────────────────────


def test_brief_includes_hot_milestones(projects_dir):
    write_yaml(projects_dir, "P", """
        name: P
        phase: SUBMITTED
        milestones:
          - id: deadline-soon
            deadline: 2026-05-05
            criticality: high
            status: pending
            blockers: [partner_signoff]
    """)
    brief = po.morning_brief("P", today=dt.date(2026, 5, 2))
    assert "P" in brief
    assert "🔥 hot milestones" in brief
    assert "deadline-soon" in brief
    assert "partner_signoff" in brief
    assert "in 3d" in brief
    assert "[high]" in brief


def test_brief_separates_overdue_and_awaiting(projects_dir):
    write_yaml(projects_dir, "P", """
        name: P
        stakeholders:
          - name: Late
            role: Co-PI
            awaiting_reply: true
            expected_response_by: 2026-04-25
            last_contact: 2026-04-15
          - name: OnTime
            role: Co-PI
            awaiting_reply: true
            expected_response_by: 2026-05-10
            last_contact: 2026-04-28
    """)
    brief = po.morning_brief("P", today=dt.date(2026, 5, 2))
    assert "📮 overdue follow-ups" in brief
    assert "Late" in brief
    assert "⏳ awaiting reply" in brief
    assert "OnTime" in brief


def test_brief_calm_when_nothing_hot(projects_dir):
    write_yaml(projects_dir, "P", """
        name: P
        milestones:
          - id: far-future
            deadline: 2027-01-01
            status: pending
            criticality: low
        stakeholders:
          - name: Quiet
            awaiting_reply: false
    """)
    brief = po.morning_brief("P", today=dt.date(2026, 5, 2))
    assert "nothing on fire" in brief
    assert "🔥" not in brief
    assert "📮" not in brief


def test_all_briefs_iterates_every_project(projects_dir):
    write_yaml(projects_dir, "P1", "name: P1")
    write_yaml(projects_dir, "P2", "name: P2")
    out = po.all_briefs(today=dt.date(2026, 5, 2))
    assert "P1" in out and "P2" in out


# ── FCLC pilot config sanity check ──────────────────────────────────


def test_fclc_pilot_config_is_valid():
    """The shipped USER/projects/FCLC.yaml must load cleanly. This guards
    against hand-edits introducing YAML or schema breakage."""
    # Use the real USER/projects dir, not the tmp one.
    state = po.load("FCLC")
    assert state.name == "FCLC"
    assert state.phase
    assert state.milestones, "FCLC pilot must declare milestones"
    assert state.stakeholders, "FCLC pilot must declare stakeholders"
    # Sanity: at least one Co-PI listed.
    assert any("Co-PI" in s.role for s in state.stakeholders)
