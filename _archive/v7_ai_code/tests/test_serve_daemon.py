"""tests/test_serve_daemon.py — G10 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import json
import socket
import threading
import time

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path))
    import importlib, sys
    if "agents.serve_daemon" in sys.modules:
        importlib.reload(sys.modules["agents.serve_daemon"])
    return tmp_path


# ── schedule parsing ─────────────────────────────────────────────


def test_parse_schedule_daily(isolated):
    from agents.serve_daemon import _parse_schedule
    s = _parse_schedule("daily@09:00")
    assert s == {"kind": "daily", "h": 9, "m": 0}


def test_parse_schedule_weekly(isolated):
    from agents.serve_daemon import _parse_schedule
    s = _parse_schedule("weekly@sun@09:00")
    assert s["kind"] == "weekly"
    assert s["dow"] == 6
    assert s["h"] == 9


def test_parse_schedule_every(isolated):
    from agents.serve_daemon import _parse_schedule
    assert _parse_schedule("every@30m") == {"kind": "every", "minutes": 30}


def test_parse_schedule_invalid(isolated):
    from agents.serve_daemon import _parse_schedule
    with pytest.raises(ValueError):
        _parse_schedule("garbage")


# ── _due ─────────────────────────────────────────────────────────


def test_due_every_first_run(isolated):
    from agents.serve_daemon import _due
    spec = {"kind": "every", "minutes": 5}
    assert _due(spec, last_run=None, now=dt.datetime(2026, 5, 3, 12, 0)) is True


def test_due_every_within_window(isolated):
    from agents.serve_daemon import _due
    spec = {"kind": "every", "minutes": 5}
    last = dt.datetime(2026, 5, 3, 12, 0)
    assert _due(spec, last_run=last,
                now=dt.datetime(2026, 5, 3, 12, 3)) is False
    assert _due(spec, last_run=last,
                now=dt.datetime(2026, 5, 3, 12, 6)) is True


def test_due_daily(isolated):
    from agents.serve_daemon import _due
    spec = {"kind": "daily", "h": 9, "m": 0}
    # Before the time → False
    assert _due(spec, last_run=None,
                now=dt.datetime(2026, 5, 3, 8, 0)) is False
    # After the time, no last run → True
    assert _due(spec, last_run=None,
                now=dt.datetime(2026, 5, 3, 9, 30)) is True
    # Already ran today → False
    last = dt.datetime(2026, 5, 3, 9, 5)
    assert _due(spec, last_run=last,
                now=dt.datetime(2026, 5, 3, 10, 0)) is False
    # Tomorrow it fires again.
    assert _due(spec, last_run=last,
                now=dt.datetime(2026, 5, 4, 9, 5)) is True


def test_due_weekly(isolated):
    from agents.serve_daemon import _due
    # Sunday at 09:00
    spec = {"kind": "weekly", "dow": 6, "h": 9, "m": 0}
    saturday = dt.datetime(2026, 5, 2, 9, 30)   # Sat
    sunday   = dt.datetime(2026, 5, 3, 9, 30)   # Sun
    assert _due(spec, last_run=None, now=saturday) is False
    assert _due(spec, last_run=None, now=sunday)   is True


# ── tick() ───────────────────────────────────────────────────────


def test_tick_runs_due_jobs(isolated):
    from agents.serve_daemon import Job, tick
    fired = []
    job = Job(name="test_job", fn=lambda: fired.append("ran"),
               schedule="every@1m")
    out = tick([job], now=dt.datetime(2026, 5, 3, 12, 0))
    assert out == ["test_job"]
    assert fired == ["ran"]


def test_tick_skips_not_due(isolated):
    from agents.serve_daemon import Job, tick
    fired = []
    job = Job(name="not_yet", fn=lambda: fired.append("ran"),
               schedule="daily@09:00")
    # Run at 03:00 — too early.
    out = tick([job], now=dt.datetime(2026, 5, 3, 3, 0))
    assert out == []
    assert fired == []


def test_tick_does_not_double_fire(isolated):
    from agents.serve_daemon import Job, tick
    fired = []
    job = Job(name="once", fn=lambda: fired.append("ran"),
               schedule="every@5m")
    now = dt.datetime(2026, 5, 3, 12, 0)
    tick([job], now=now)
    tick([job], now=now)        # same second → not due again
    assert len(fired) == 1


def test_tick_swallows_job_exceptions(isolated):
    from agents.serve_daemon import Job, tick

    def boom():
        raise RuntimeError("nope")

    out = tick([Job("flaky", boom, "every@1m")],
               now=dt.datetime(2026, 5, 3, 12, 0))
    # Failed jobs aren't reported as fired (see implementation: only
    # successful runs append to `fired`).
    assert out == []


# ── socket server ────────────────────────────────────────────────


def test_socket_handles_ping(isolated):
    """Stand the socket server up briefly, send 'ping', expect pong."""
    from agents.serve_daemon import serve_socket, socket_path
    stop = threading.Event()
    th = threading.Thread(target=serve_socket, args=(stop, []),
                           daemon=True)
    th.start()
    # Wait for socket to be live.
    sp = socket_path()
    for _ in range(40):
        if sp.exists():
            break
        time.sleep(0.05)
    assert sp.exists()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(sp))
    s.sendall(json.dumps({"cmd": "ping"}).encode("utf-8"))
    resp = s.recv(8192).decode("utf-8")
    s.close()
    stop.set()
    th.join(timeout=1.0)
    assert json.loads(resp.strip())["pong"] is True


def test_socket_handle_request_unknown(isolated):
    from agents.serve_daemon import _handle_socket_request
    out = json.loads(_handle_socket_request('{"cmd":"unknown"}'))
    assert "unknown" in out["error"]


def test_socket_handle_invalid_json(isolated):
    from agents.serve_daemon import _handle_socket_request
    out = json.loads(_handle_socket_request('not-json'))
    assert "invalid JSON" in out["error"]


def test_socket_do_dispatches(isolated, monkeypatch):
    from agents.serve_daemon import _handle_socket_request
    from agents import quick_action as qa
    monkeypatch.setattr(qa, "handle", lambda q: {"action": "fake", "echo": q})
    out = json.loads(_handle_socket_request(
        '{"cmd":"do","args":["hello","world"]}'))
    assert out["action"] == "fake"
    assert out["echo"] == "hello world"


# ── run_once ────────────────────────────────────────────────────


def test_run_once_returns_list(isolated, monkeypatch):
    """run_once should return a list (possibly empty) without crashing."""
    from agents import serve_daemon as sd
    monkeypatch.setattr(sd, "default_jobs", lambda: [])
    fired = sd.run_once()
    assert fired == []
