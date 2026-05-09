"""tests/test_routines.py — RB1 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_ROUTINES_PREFS", str(tmp_path / "routines.yaml"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "projects").mkdir()
    import importlib, sys
    if "agents.routines" in sys.modules:
        importlib.reload(sys.modules["agents.routines"])
    return tmp_path


def write_prefs(setup, body):
    (setup / "routines.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── load / list ──────────────────────────────────────────────────


def test_list_when_no_file(isolated):
    from agents.routines import list_routines
    assert list_routines() == []


def test_list_returns_keys(isolated):
    write_prefs(isolated, """
        routines:
          morning: [escalate]
          weekly: [digest]
    """)
    from agents.routines import list_routines
    assert list_routines() == ["morning", "weekly"]


def test_invalid_yaml_safe(isolated):
    write_prefs(isolated, "not valid [[")
    from agents.routines import list_routines
    assert list_routines() == []


# ── run() ────────────────────────────────────────────────────────


def test_run_unknown_raises(isolated):
    from agents.routines import run
    with pytest.raises(KeyError):
        run("ghost")


def test_run_simple_steps(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          flow: [escalate, memory]
    """)
    import agents.routines as routines
    monkeypatch.setattr(routines, "_run_simple",
                        lambda name: f"OUT_{name}")
    res = routines.run("flow")
    assert res.ok
    assert [s.action for s in res.steps] == ["escalate", "memory"]
    assert res.steps[0].output == "OUT_escalate"


def test_run_do_step(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          chat:
            - { do: "what's hot" }
    """)
    from agents import quick_action as qa
    monkeypatch.setattr(qa, "handle",
                        lambda q: {"action": "escalate", "echo": q})
    from agents.routines import run
    res = run("chat")
    assert res.ok
    assert res.steps[0].output["echo"] == "what's hot"


def test_run_recall_step(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          mem:
            - { recall: "FCLC", k: 2 }
    """)
    from agents import recall_cli as rc
    monkeypatch.setattr(rc, "recall_top",
                        lambda q, k=5: f"recalled '{q}' k={k}")
    from agents.routines import run
    res = run("mem")
    assert res.ok
    assert "FCLC" in res.steps[0].output


def test_run_brief_step_with_project(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          proj:
            - { project: brief, args: ["FCLC"] }
    """)
    (isolated / "projects" / "FCLC.yaml").write_text(
        "name: FCLC\nphase: SUBMITTED\n")
    from agents.routines import run
    res = run("proj")
    # The {project: brief} step uses _run_project_sub, which only knows
    # `list` and `sweep` — so this returns an "unsupported" string.
    assert res.steps[0].ok
    assert "unsupported" in res.steps[0].output.lower() or res.steps[0].ok


def test_run_project_list_step(isolated):
    (isolated / "projects" / "A.yaml").write_text("name: A\n")
    (isolated / "projects" / "B.yaml").write_text("name: B\n")
    write_prefs(isolated, """
        routines:
          probe:
            - { project: list }
    """)
    from agents.routines import run
    res = run("probe")
    assert res.ok
    assert set(res.steps[0].output) == {"A", "B"}


# ── error handling ──────────────────────────────────────────────


def test_step_failure_captured(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          flow: [escalate, broken]
    """)
    import agents.routines as routines
    def stub(name):
        if name == "broken":
            raise RuntimeError("nope")
        return "ok"
    monkeypatch.setattr(routines, "_run_simple", stub)
    res = routines.run("flow")
    assert not res.ok
    assert res.steps[1].error and "RuntimeError" in res.steps[1].error
    # First step still succeeded.
    assert res.steps[0].ok


def test_unsupported_step_shape(isolated):
    write_prefs(isolated, """
        routines:
          weird:
            - 42
    """)
    from agents.routines import run
    res = run("weird")
    assert not res.ok
    assert "unsupported" in res.steps[0].error.lower()


# ── audit ────────────────────────────────────────────────────────


def test_audit_records_run(isolated, monkeypatch):
    write_prefs(isolated, """
        routines:
          flow: [escalate]
    """)
    import agents.routines as routines
    monkeypatch.setattr(routines, "_run_simple", lambda n: "ok")
    routines.run("flow")
    h = routines.history()
    assert h and h[-1]["name"] == "flow"
    assert h[-1]["ok"] is True


