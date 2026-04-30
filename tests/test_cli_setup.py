"""tests/test_cli_setup.py — aim init + aim node setup wizards."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── env file roundtrip ───────────────────────────────────────────────────


def test_env_path_unix(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli import setup_wizard
    p = setup_wizard._env_path()
    assert ".aim_env" in str(p)


def test_env_read_write_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli import setup_wizard
    setup_wizard._set_env("FOO", "bar")
    setup_wizard._set_env("BAZ", "qux quux")
    env = setup_wizard._read_env()
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "qux quux"


def test_env_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli import setup_wizard
    setup_wizard._set_env("KEEP_ME", "original")
    setup_wizard._set_env("NEW_ONE", "added")
    env = setup_wizard._read_env()
    assert env["KEEP_ME"] == "original"
    assert env["NEW_ONE"] == "added"


# ── init wizard non-interactive ───────────────────────────────────────────


def test_init_wizard_non_interactive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli.setup_wizard import run_init_wizard
    rc = run_init_wizard(non_interactive=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "AIM init" in out


# ── node setup error paths ────────────────────────────────────────────────


def test_node_setup_requires_hub_url_in_non_interactive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli.setup_wizard import run_node_setup
    rc = run_node_setup(non_interactive=True)
    assert rc == 2
    err = capsys.readouterr().err
    assert "hub-url" in err.lower()


def test_node_setup_rejects_invalid_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from cli.setup_wizard import run_node_setup
    rc = run_node_setup(non_interactive=True,
                         hub_url="https://hub.example.com",
                         code="abcdef")
    assert rc == 2


# ── CLI dispatcher entry-points ───────────────────────────────────────────


def test_cli_help_lists_subcommands():
    from cli.__main__ import _build_parser
    p = _build_parser()
    # Walk the subparsers to verify all expected sub-commands are present
    actions = {a.dest: a for a in p._actions if hasattr(a, "choices")}
    sub = actions["cmd"].choices
    for cmd in ("init", "ai", "cli", "gui", "telegram",
                 "doctor", "web", "hub", "node"):
        assert cmd in sub, f"missing top-level command: {cmd}"


def test_cli_hub_subcommands():
    from cli.__main__ import _build_parser
    p = _build_parser()
    actions = {a.dest: a for a in p._actions if hasattr(a, "choices")}
    sub = actions["cmd"].choices
    hub = sub["hub"]
    hub_actions = {a.dest: a for a in hub._actions if hasattr(a, "choices")}
    hub_sub = hub_actions.get("hub_cmd")
    assert hub_sub and "start" in hub_sub.choices
    assert "pair" in hub_sub.choices
    assert "users" in hub_sub.choices


def test_cli_node_subcommands():
    from cli.__main__ import _build_parser
    p = _build_parser()
    actions = {a.dest: a for a in p._actions if hasattr(a, "choices")}
    sub = actions["cmd"].choices
    node = sub["node"]
    node_actions = {a.dest: a for a in node._actions if hasattr(a, "choices")}
    node_sub = node_actions.get("node_cmd")
    assert node_sub and "setup" in node_sub.choices and "status" in node_sub.choices
