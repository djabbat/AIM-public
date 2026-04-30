"""tests/test_generalist_v2_extras.py — D1/D2/A3/C4/E2/F1/F2."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── D2: scratchpad note/recall ─────────────────────────────────────────────


def test_scratchpad_note_recall():
    from agents.generalist import _t_note, _t_recall
    import agents.generalist as G
    tok = G._RUN_ID_VAR.set("test_run_xyz")
    try:
        assert _t_note("plan", "step 1: read file").startswith("OK")
        assert _t_note("count", "42").startswith("OK")
        assert "step 1" in _t_recall("plan")
        assert _t_recall("count") == "42"
        assert "plan" in _t_recall("")    # list keys
        assert _t_recall("missing").startswith("ERROR")
    finally:
        with G._STATE_LOCK:
            G._SCRATCHPADS.pop("test_run_xyz", None)
        G._RUN_ID_VAR.reset(tok)


def test_scratchpad_no_run_returns_error():
    from agents.generalist import _t_note
    import agents.generalist as G
    tok = G._RUN_ID_VAR.set(None)
    try:
        assert _t_note("k", "v").startswith("ERROR")
    finally:
        G._RUN_ID_VAR.reset(tok)


# ── F1: examples render in tools block ─────────────────────────────────────


def test_tool_registry_carries_examples():
    from agents.generalist import _TOOLS, _format_tools_block
    block = _format_tools_block()
    assert "AVAILABLE TOOLS" in block
    assert "apply_patch" in block
    # apply_patch has an example registered
    assert "example:" in block


# ── A3: multi-action parser smoke ──────────────────────────────────────────


def test_action_parser_handles_multi_action():
    from agents.generalist import _parse_action
    raw = ('{"actions": [ {"tool": "read_file", "args": {"path": "/tmp/x"}},'
           '{"parallel": [{"tool": "verify_pmid", "args": {"pmid": "1"}},'
           '{"tool": "verify_pmid", "args": {"pmid": "2"}}] } ]}')
    a = _parse_action(raw)
    assert isinstance(a.get("actions"), list) and len(a["actions"]) == 2
    assert a["actions"][0]["tool"] == "read_file"
    assert isinstance(a["actions"][1]["parallel"], list)


def test_action_parser_returns_empty_on_bad_json():
    from agents.generalist import _parse_action
    a = _parse_action("not JSON, not even close.")
    assert a == {}   # not {"final": "..."} anymore


# ── C4: bash_async / bash_status / bash_output / bash_kill ────────────────


def test_bash_async_lifecycle():
    from agents.generalist import (_t_bash_async, _t_bash_status,
                                    _t_bash_output, _t_bash_kill)
    out = _t_bash_async("echo hello && sleep 0.3 && echo world")
    assert out.startswith("OK")
    job_id = out.split("=")[1].split()[0]
    # Should be running (or just finished)
    s = _t_bash_status(job_id)
    assert "running" in s or "exited" in s
    time.sleep(0.6)
    s = _t_bash_status(job_id)
    assert "exited" in s and "rc=0" in s
    o = _t_bash_output(job_id)
    assert "hello" in o and "world" in o


def test_bash_async_rejects_unwhitelisted():
    from agents.generalist import _t_bash_async
    out = _t_bash_async("rm -rf /tmp/anything")
    assert out.startswith("ERROR")


def test_bash_kill_terminates_long_running():
    from agents.generalist import _t_bash_async, _t_bash_kill, _t_bash_status
    out = _t_bash_async("python3 -c 'import time; time.sleep(30)'")
    assert out.startswith("OK")
    job_id = out.split("=")[1].split()[0]
    killed = _t_bash_kill(job_id)
    assert killed.startswith("OK killed")
    s = _t_bash_status(job_id)
    assert "exited" in s


# ── E2: SIGINT request_interrupt API ──────────────────────────────────────


def test_request_interrupt_sets_flag():
    from agents import generalist as G
    G._INTERRUPTED.clear()
    tok = G._RUN_ID_VAR.set("run_for_interrupt_test")
    try:
        G.request_interrupt()
        assert G._INTERRUPTED.get("run_for_interrupt_test") is True
    finally:
        G._RUN_ID_VAR.reset(tok)
        G._INTERRUPTED.clear()


def test_request_interrupt_specific_run_id():
    from agents import generalist as G
    G._INTERRUPTED.clear()
    G.request_interrupt("specific_run")
    assert G._INTERRUPTED.get("specific_run") is True
    G._INTERRUPTED.clear()


# ── F2: JSONL log file path is platform-portable ──────────────────────────


def test_jsonl_log_dir_is_writable():
    """The cache dir generalist will use for session logs must be writable."""
    import platform
    sysname = platform.system()
    if sysname == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA",
                                   Path.home() / "AppData" / "Local"))
        d = base / "aim" / "sessions"
    elif sysname == "Darwin":
        d = Path.home() / "Library" / "Caches" / "aim" / "sessions"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME",
                                str(Path.home() / ".cache"))) / "aim" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    test_file = d / "test_writable.tmp"
    test_file.write_text("ok", encoding="utf-8")
    assert test_file.read_text(encoding="utf-8") == "ok"
    test_file.unlink()
