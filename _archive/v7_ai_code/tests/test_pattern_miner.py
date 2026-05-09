"""tests/test_pattern_miner.py — S4 (2026-05-02)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from agents import pattern_miner as pm


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path))
    return tmp_path


def write_session(setup, name: str, events: list[dict]) -> None:
    p = setup / f"{name}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ── iter_events ───────────────────────────────────────────────────


def test_iter_skips_malformed_lines(sessions):
    p = sessions / "bad.jsonl"
    p.write_text('{"type":"tool_call"}\nnot-json\n{"type":"final"}\n')
    out = list(pm.iter_events())
    assert len(out) == 2


def test_window_days_filter(sessions):
    now = dt.datetime.now()
    write_session(sessions, "old", [
        {"type": "tool_result", "tool": "x", "ts":
         (now - dt.timedelta(days=30)).isoformat()},
    ])
    write_session(sessions, "new", [
        {"type": "tool_result", "tool": "x", "ts": now.isoformat()},
    ])
    out = list(pm.iter_events(window_days=7))
    assert len(out) == 1


# ── tool_failure_rate ─────────────────────────────────────────────


def test_failure_rate_finding(sessions):
    events = []
    for i in range(10):
        events.append({"type": "tool_result", "tool": "shaky",
                        "result": "ERROR:NETWORK:timeout" if i < 5 else "OK"})
    f = pm._mine_tool_failure_rate(events)
    assert len(f) == 1
    assert f[0].kind == "tool_failure_rate"
    assert "50%" in f[0].summary
    assert f[0].support == 5


def test_failure_rate_skips_low_volume():
    events = [{"type": "tool_result", "tool": "rare",
               "result": "ERROR:X:y"}] * 3
    assert pm._mine_tool_failure_rate(events, min_calls=5) == []


def test_failure_rate_threshold():
    events = ([{"type": "tool_result", "tool": "stable",
                "result": "ERROR:X:y"}] * 1
              + [{"type": "tool_result", "tool": "stable",
                  "result": "OK"}] * 9)
    assert pm._mine_tool_failure_rate(events, failure_threshold=0.50) == []


# ── slow_tool ────────────────────────────────────────────────────


def test_slow_tool_p95():
    events = [
        {"type": "tool_result", "tool": "fat", "duration_ms": d}
        for d in [100, 200, 300, 400, 500, 5000]
    ]
    f = pm._mine_slow_tool(events, slow_ms=2000)
    assert len(f) == 1
    assert "fat" in f[0].summary
    assert "p95=" in f[0].summary


def test_fast_tool_no_finding():
    events = [{"type": "tool_result", "tool": "snappy", "duration_ms": d}
              for d in [50] * 10]
    assert pm._mine_slow_tool(events) == []


# ── redundant memory queries ──────────────────────────────────────


def test_redundant_memory_query():
    events = [{"type": "tool_call", "tool": "memory_recall",
               "args": {"q": "FCLC deadline"}}] * 4
    f = pm._mine_redundant_memory_queries(events, min_repeats=3)
    assert len(f) == 1
    assert f[0].support == 4


def test_distinct_memory_queries_not_flagged():
    events = [{"type": "tool_call", "tool": "memory_recall",
               "args": {"q": f"q{i}"}} for i in range(5)]
    assert pm._mine_redundant_memory_queries(events) == []


# ── sequential pairs ─────────────────────────────────────────────


def test_sequential_pair_detected():
    events = []
    for sid in range(4):
        events.append({"type": "tool_call", "tool": "read_file",
                        "session_id": sid, "args": {}})
        events.append({"type": "tool_call", "tool": "edit_file",
                        "session_id": sid, "args": {}})
    f = pm._mine_sequential_pairs(events, min_pairs=3)
    assert any("read_file" in x.summary and "edit_file" in x.summary
               for x in f)


def test_sequential_pair_self_loop_ignored():
    events = [{"type": "tool_call", "tool": "x",
               "session_id": 1, "args": {}}] * 5
    assert pm._mine_sequential_pairs(events) == []


# ── error_type_frequency ─────────────────────────────────────────


def test_error_type_frequency():
    events = [{"type": "tool_result", "tool": "x",
               "result": "ERROR:PERMISSION:bash blocked"}] * 4
    f = pm._mine_error_type_frequency(events)
    assert len(f) == 1
    assert "ERROR:PERMISSION" in f[0].summary


# ── orchestration ────────────────────────────────────────────────


def test_mine_aggregates_findings(sessions):
    write_session(sessions, "s1", [
        {"type": "tool_result", "tool": "shaky", "result": "ERROR:X:y"} for _ in range(5)
    ] + [
        {"type": "tool_result", "tool": "shaky", "result": "OK"} for _ in range(5)
    ])
    findings = pm.mine(window_days=999)
    kinds = {f.kind for f in findings}
    assert "tool_failure_rate" in kinds


def test_summary_when_no_logs(sessions):
    s = pm.summary(window_days=7)
    assert "no actionable patterns" in s


def test_summary_renders_findings(sessions):
    write_session(sessions, "s", [
        {"type": "tool_result", "tool": "fat", "duration_ms": 9999}
        for _ in range(10)
    ])
    s = pm.summary(window_days=999)
    assert "slow_tool" in s
    assert "fat" in s
