"""tests/test_escalation_engine.py — P6 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    for mod in ["agents.project_owner", "agents.escalation_engine"]:
        if mod in __import__("sys").modules:
            importlib.reload(__import__("sys").modules[mod])
    return tmp_path


def write_proj(setup, name, body):
    (setup / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── DSL tokenizer ─────────────────────────────────────────────────


def test_tokenize_basic():
    from agents.escalation_engine import _tokenize
    assert _tokenize("a == 1 and b > 2") == ["a", "==", "1", "and", "b", ">", "2"]


def test_tokenize_quoted_strings():
    from agents.escalation_engine import _tokenize
    toks = _tokenize("role contains 'Co-PI'")
    assert toks == ["role", "contains", "'Co-PI'"]


def test_tokenize_dotted_names():
    from agents.escalation_engine import _tokenize
    toks = _tokenize("milestone.criticality == 'high'")
    assert "milestone.criticality" in toks


# ── DSL evaluator ────────────────────────────────────────────────


def test_eval_equals():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("x == 1", {"x": 1}) is True
    assert evaluate_rule("x == 1", {"x": 2}) is False


def test_eval_less_than():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("days <= 7", {"days": 3})
    assert not evaluate_rule("days <= 7", {"days": 8})


def test_eval_dotted_path():
    from agents.escalation_engine import evaluate_rule
    ctx = {"milestone": {"criticality": "high"}}
    assert evaluate_rule("milestone.criticality == 'high'", ctx)


def test_eval_and_or():
    from agents.escalation_engine import evaluate_rule
    ctx = {"x": 5, "y": "yes"}
    assert evaluate_rule("x > 3 and y == 'yes'", ctx)
    assert not evaluate_rule("x > 3 and y == 'no'", ctx)
    assert evaluate_rule("x > 3 or y == 'no'", ctx)


def test_eval_not():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("not x", {"x": False})
    assert not evaluate_rule("not x", {"x": True})


def test_eval_contains():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("role contains 'Co-PI'", {"role": "Co-PI EU"})
    assert not evaluate_rule("role contains 'Co-PI'", {"role": "advisor"})


def test_eval_in_string():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("'PI' in role", {"role": "Co-PI EU"})


def test_eval_bare_boolean():
    from agents.escalation_engine import evaluate_rule
    assert evaluate_rule("flag", {"flag": True})
    assert not evaluate_rule("flag", {"flag": False})


def test_eval_missing_var_safe():
    from agents.escalation_engine import evaluate_rule
    assert not evaluate_rule("nonexistent == 1", {})


def test_eval_parens():
    from agents.escalation_engine import evaluate_rule
    ctx = {"a": 1, "b": 0, "c": 1}
    assert evaluate_rule("(a == 1) and (b == 0 or c == 1)", ctx)


def test_eval_malformed_returns_false():
    from agents.escalation_engine import evaluate_rule
    assert not evaluate_rule("this is not @#$ valid", {})


# ── full project evaluation ──────────────────────────────────────


def test_evaluate_milestone_rule_fires(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: hot-thing
            deadline: 2026-05-05
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7 and milestone.criticality == 'high'"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    alerts = evaluate("P", today=dt.date(2026, 5, 2))
    assert len(alerts) == 1
    assert alerts[0].action == "telegram_alert"
    assert "hot-thing" in alerts[0].subject


def test_evaluate_skips_done_milestones(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: was-hot
            deadline: 2026-05-05
            criticality: high
            status: done
        escalation_rules:
          - when: "deadline_within_days <= 7 and milestone.criticality == 'high' and milestone.status == 'pending'"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    assert evaluate("P", today=dt.date(2026, 5, 2)) == []


def test_evaluate_stakeholder_rule_fires(isolated):
    write_proj(isolated, "P", """
        name: P
        stakeholders:
          - name: Late
            role: Co-PI EU
            awaiting_reply: true
            expected_response_by: 2026-04-25
        escalation_rules:
          - when: "stakeholder.overdue and stakeholder.role contains 'Co-PI'"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    alerts = evaluate("P", today=dt.date(2026, 5, 2))
    assert len(alerts) == 1
    assert "Late" in alerts[0].subject


def test_evaluate_no_rules_no_alerts(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.escalation_engine import evaluate
    assert evaluate("P", today=dt.date(2026, 5, 2)) == []


# ── dispatch ──────────────────────────────────────────────────────


def test_dispatch_callback_invoked(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: x
            deadline: 2026-05-05
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    sent = []
    evaluate("P", today=dt.date(2026, 5, 2),
             dispatch=lambda a: sent.append(a))
    assert len(sent) == 1
    assert sent[0].action == "telegram_alert"


# ── cooldown / dedup ─────────────────────────────────────────────


def test_cooldown_suppresses_duplicate(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: x
            deadline: 2026-05-05
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    today = dt.date(2026, 5, 2)
    a = evaluate("P", today=today, cooldown_hours=24)
    b = evaluate("P", today=today, cooldown_hours=24)
    assert len(a) == 1
    assert len(b) == 0   # cooldown hides repeat


def test_cooldown_zero_lets_through(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: x
            deadline: 2026-05-05
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate
    today = dt.date(2026, 5, 2)
    evaluate("P", today=today, cooldown_hours=0)
    second = evaluate("P", today=today, cooldown_hours=0)
    assert len(second) == 1


# ── evaluate_all + history ──────────────────────────────────────


def test_evaluate_all_iterates(isolated):
    write_proj(isolated, "A", """
        name: A
        milestones:
          - id: a1
            deadline: 2026-05-05
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    write_proj(isolated, "B", """
        name: B
        milestones:
          - id: b1
            deadline: 2026-05-04
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate_all
    alerts = evaluate_all(today=dt.date(2026, 5, 2))
    projects = {a.project for a in alerts}
    assert projects == {"A", "B"}


def test_history_records_alerts(isolated):
    write_proj(isolated, "P", """
        name: P
        milestones:
          - id: x
            deadline: 2026-05-04
            criticality: high
            status: pending
        escalation_rules:
          - when: "deadline_within_days <= 7"
            action: telegram_alert
    """)
    from agents.escalation_engine import evaluate, rule_history
    evaluate("P", today=dt.date(2026, 5, 2), cooldown_hours=0)
    h = rule_history("P")
    assert h and h[-1]["action"] == "telegram_alert"
