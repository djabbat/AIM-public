"""tests/test_cli_completion.py — G11 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_ROUTINES_PREFS", str(tmp_path / "routines.yaml"))
    (tmp_path / "projects").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.routines",
              "agents.cli_completion"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── source-of-truth lookups ──────────────────────────────────────


def test_list_subcommands_includes_core(isolated):
    from agents.cli_completion import list_subcommands
    cmds = set(list_subcommands())
    for required in ("brief", "recall", "project", "do",
                     "routine", "memory", "version"):
        assert required in cmds


def test_list_projects(isolated):
    (isolated / "projects" / "FCLC.yaml").write_text("name: FCLC\n")
    (isolated / "projects" / "Ze.yaml").write_text("name: Ze\n")
    from agents.cli_completion import list_projects
    assert sorted(list_projects()) == ["FCLC", "Ze"]


def test_list_projects_empty(isolated):
    from agents.cli_completion import list_projects
    assert list_projects() == []


def test_list_routines(isolated):
    (isolated / "routines.yaml").write_text(textwrap.dedent("""
        routines:
          morning: [escalate]
          evening: [memory]
    """))
    import importlib, agents.cli_completion as cc
    importlib.reload(cc)
    assert sorted(cc.list_routines()) == ["evening", "morning"]


# ── bash_script shape ────────────────────────────────────────────


def test_bash_script_contains_completion_function(isolated):
    from agents.cli_completion import bash_script
    out = bash_script()
    assert "_aim_complete()" in out
    assert "complete -F _aim_complete aim" in out


def test_bash_script_lists_subcommands(isolated):
    from agents.cli_completion import bash_script
    out = bash_script()
    assert "brief" in out
    assert "project" in out
    assert "routine" in out


def test_bash_script_includes_project_subs(isolated):
    from agents.cli_completion import bash_script
    out = bash_script()
    for sub in ("archive", "unarchive", "sweep", "transition"):
        assert sub in out


def test_bash_script_includes_phases(isolated):
    from agents.cli_completion import bash_script
    out = bash_script()
    for phase in ("DRAFT", "SUBMITTED", "PUBLISHED"):
        assert phase in out


# ── zsh wrapper ──────────────────────────────────────────────────


def test_zsh_script_loads_bashcompinit(isolated):
    from agents.cli_completion import zsh_script
    out = zsh_script()
    assert "bashcompinit" in out
    assert "_aim_complete" in out


# ── _main entrypoint ─────────────────────────────────────────────


def test_main_bash(isolated, capsys):
    import sys
    from agents.cli_completion import _main
    sys_argv = sys.argv
    try:
        sys.argv = ["cli_completion", "bash"]
        _main()
    finally:
        sys.argv = sys_argv
    out = capsys.readouterr().out
    assert "complete -F _aim_complete aim" in out


def test_main_zsh(isolated, capsys):
    import sys
    from agents.cli_completion import _main
    sys_argv = sys.argv
    try:
        sys.argv = ["cli_completion", "zsh"]
        _main()
    finally:
        sys.argv = sys_argv
    out = capsys.readouterr().out
    assert "bashcompinit" in out
