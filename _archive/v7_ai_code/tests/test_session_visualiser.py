"""tests/test_session_visualiser.py — SE1 (2026-05-03)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path))
    sid = "abc123"
    p = tmp_path / f"{sid}.jsonl"
    events = [
        {"type": "start",        "ts": "2026-05-03T10:00:00", "task": "do x"},
        {"type": "tool_call",    "ts": "2026-05-03T10:00:01",
         "tool": "read_file",    "args": {"path": "x.md"}},
        {"type": "tool_result",  "ts": "2026-05-03T10:00:01.500000",
         "tool": "read_file",    "result": "OK"},
        {"type": "tool_call",    "ts": "2026-05-03T10:00:02",
         "tool": "bash",         "args": {"command": "ls"}},
        {"type": "tool_error",   "ts": "2026-05-03T10:00:02.300000",
         "tool": "bash",         "error": "ERROR:PERMISSION"},
        {"type": "self_critique_issue_found", "ts": "2026-05-03T10:00:03",
         "issue": "fabricated PMID"},
        {"type": "final",        "ts": "2026-05-03T10:00:04",
         "answer": "all done"},
    ]
    with p.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    import importlib, sys
    if "agents.session_visualiser" in sys.modules:
        importlib.reload(sys.modules["agents.session_visualiser"])
    return sid, p


# ── resolve ──────────────────────────────────────────────────────


def test_resolve_by_id(session_file):
    from agents.session_visualiser import _resolve
    sid, path = session_file
    assert _resolve(sid) == path


def test_resolve_by_path(session_file):
    from agents.session_visualiser import _resolve
    sid, path = session_file
    assert _resolve(str(path)) == path


def test_resolve_missing_raises(session_file):
    from agents.session_visualiser import _resolve
    with pytest.raises(FileNotFoundError):
        _resolve("ghost-session")


# ── timeline ─────────────────────────────────────────────────────


def test_timeline_starts_with_header(session_file):
    sid, _ = session_file
    from agents.session_visualiser import timeline
    out = timeline(sid)
    assert out.startswith("# Session timeline")


def test_timeline_includes_all_events(session_file):
    sid, _ = session_file
    from agents.session_visualiser import timeline
    out = timeline(sid)
    for kind in ("start", "tool_call", "tool_result", "tool_error",
                 "self_critique_issue_found", "final"):
        assert kind in out


def test_timeline_marks_errors(session_file):
    sid, _ = session_file
    from agents.session_visualiser import timeline
    out = timeline(sid)
    assert "🛑" in out


def test_timeline_marks_final(session_file):
    sid, _ = session_file
    from agents.session_visualiser import timeline
    out = timeline(sid)
    assert "✅" in out


def test_timeline_empty_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path))
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    import importlib, agents.session_visualiser as sv
    importlib.reload(sv)
    assert "empty session" in sv.timeline("empty")


def test_timeline_skips_malformed_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path))
    p = tmp_path / "x.jsonl"
    p.write_text('{"type":"final","answer":"ok","ts":"2026-05-03T10:00:00"}\n'
                  "garbage line\n"
                  '{"type":"start","ts":"2026-05-03T09:59:00"}\n')
    import importlib, agents.session_visualiser as sv
    importlib.reload(sv)
    out = sv.timeline("x")
    assert "final" in out
    assert "start" in out


# ── stats ────────────────────────────────────────────────────────


def test_stats_counts_per_tool(session_file):
    sid, _ = session_file
    from agents.session_visualiser import stats
    s = stats(sid)
    assert s["n_events"] == 7
    assert s["tools"]["read_file"]["calls"] == 1
    assert s["tools"]["read_file"]["errors"] == 0
    assert s["tools"]["bash"]["calls"] == 1
    assert s["tools"]["bash"]["errors"] == 1


def test_stats_records_durations(session_file):
    sid, _ = session_file
    from agents.session_visualiser import stats
    s = stats(sid)
    assert s["tools"]["read_file"]["p50_ms"] >= 400


def test_stats_lists_interesting(session_file):
    sid, _ = session_file
    from agents.session_visualiser import stats
    s = stats(sid)
    kinds = {ev["type"] for ev in s["interesting"]}
    assert "self_critique_issue_found" in kinds
    assert "tool_error" in kinds
    assert "final" in kinds


def test_summary_string_renders(session_file):
    sid, _ = session_file
    from agents.session_visualiser import summary_string
    s = summary_string(sid)
    assert "Session" in s
    assert "read_file" in s
    assert "bash" in s
