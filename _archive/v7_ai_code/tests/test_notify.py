"""tests/test_notify.py — N1 notification multiplexer (2026-05-03)."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    import agents.notify as n
    importlib.reload(n)
    return n


# ── channel routing ──────────────────────────────────────────────


def test_stdout_always_succeeds(isolated, capsys):
    r = isolated.notify("hello", channels=("stdout",), subject="T")
    out = capsys.readouterr().out
    assert r.delivered_via == "stdout"
    assert "hello" in out
    assert "T" in out


def test_log_channel_succeeds(isolated):
    r = isolated.notify("hi", channels=("log",))
    assert r.delivered_via == "log"


def test_falls_back_when_first_fails(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_send_telegram",
                        lambda text, subject: False)
    r = isolated.notify("text", channels=("telegram", "log"))
    assert r.delivered_via == "log"
    assert r.attempted == ["telegram", "log"]
    assert "telegram" in r.failures


def test_records_full_failure(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_send_telegram",
                        lambda text, subject: False)
    monkeypatch.setattr(isolated, "_send_log",
                        lambda text, subject: False)
    r = isolated.notify("text", channels=("telegram", "log"))
    assert r.delivered_via is None
    assert r.failures == {"telegram": "send returned False",
                          "log": "send returned False"}


def test_unknown_channel_recorded(isolated):
    r = isolated.notify("text", channels=("ghost", "log"))
    assert r.delivered_via == "log"
    assert r.failures.get("ghost") == "unknown channel"


def test_telegram_channel_unavailable_propagates(isolated, monkeypatch):
    """If scripts.daily_brief import fails, telegram should report False (not crash)."""
    # Force the inner send_telegram to raise.
    def boom(*_args, **_kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(isolated, "_send_telegram",
                        lambda text, subject: False)
    r = isolated.notify("hi", channels=("telegram", "log"))
    assert r.delivered_via == "log"


# ── dedup ────────────────────────────────────────────────────────


def test_dedup_suppresses_repeat(isolated):
    r1 = isolated.notify("alert", channels=("log",),
                          dedup_key="x", dedup_window_minutes=60)
    r2 = isolated.notify("alert", channels=("log",),
                          dedup_key="x", dedup_window_minutes=60)
    assert r1.delivered_via == "log"
    assert r2.delivered_via is None
    assert r2.suppressed is True


def test_dedup_window_zero_lets_through(isolated):
    isolated.notify("alert", channels=("log",), dedup_key="y",
                     dedup_window_minutes=0)
    r2 = isolated.notify("alert", channels=("log",), dedup_key="y",
                         dedup_window_minutes=0)
    assert r2.delivered_via == "log"
    assert not r2.suppressed


def test_dedup_distinct_keys_are_independent(isolated):
    isolated.notify("alert", channels=("log",), dedup_key="a")
    r = isolated.notify("alert", channels=("log",), dedup_key="b")
    assert not r.suppressed


def test_dedup_skipped_when_no_key(isolated):
    isolated.notify("alert", channels=("log",))
    r = isolated.notify("alert", channels=("log",))
    assert r.delivered_via == "log"   # both delivered


def test_failed_send_does_not_block_dedup(isolated, monkeypatch):
    """If the first attempt failed (delivered_via=None), the second should
    still try — i.e. dedup only triggers on past SUCCESS, not past attempts."""
    monkeypatch.setattr(isolated, "_send_log",
                        lambda text, subject: False)
    isolated.notify("a", channels=("log",), dedup_key="k")
    monkeypatch.setattr(isolated, "_send_log",
                        lambda text, subject: True)
    r2 = isolated.notify("a", channels=("log",), dedup_key="k")
    assert r2.delivered_via == "log"
    assert not r2.suppressed


# ── audit log ────────────────────────────────────────────────────


def test_audit_records_delivery(isolated):
    isolated.notify("x", channels=("log",), source="brief")
    h = isolated.history(source="brief")
    assert h
    assert h[-1]["delivered_via"] == "log"
    assert h[-1]["source"] == "brief"


def test_audit_filters_by_source(isolated):
    isolated.notify("x", channels=("log",), source="A")
    isolated.notify("y", channels=("log",), source="B")
    a = isolated.history(source="A")
    b = isolated.history(source="B")
    assert len(a) == 1 and a[0]["source"] == "A"
    assert len(b) == 1 and b[0]["source"] == "B"


def test_audit_includes_failures(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_send_telegram",
                        lambda t, s: False)
    isolated.notify("x", channels=("telegram", "log"))
    h = isolated.history()
    assert "telegram" in h[-1]["failures"]


# ── N2 rate limiter ──────────────────────────────────────────────


def test_rate_limit_blocks_excess(isolated, monkeypatch):
    monkeypatch.setenv("AIM_NOTIFY_RATE_MAX", "3")
    monkeypatch.setenv("AIM_NOTIFY_RATE_WINDOW_MIN", "60")
    for i in range(3):
        r = isolated.notify(f"msg {i}", channels=("log",))
        assert r.delivered_via == "log"
    # 4th gets dropped.
    r = isolated.notify("blocked", channels=("log",))
    assert r.suppressed is True
    assert "rate_limit" in r.failures


def test_rate_limit_high_level_bypasses(isolated, monkeypatch):
    monkeypatch.setenv("AIM_NOTIFY_RATE_MAX", "1")
    isolated.notify("ok", channels=("log",))
    r = isolated.notify("urgent", channels=("log",), level="high")
    assert r.delivered_via == "log"
    assert not r.suppressed


def test_rate_limit_zero_disables(isolated, monkeypatch):
    monkeypatch.setenv("AIM_NOTIFY_RATE_MAX", "0")
    for _ in range(50):
        r = isolated.notify("x", channels=("log",))
        assert not r.suppressed


def test_rate_limit_invalid_falls_back(isolated, monkeypatch):
    monkeypatch.setenv("AIM_NOTIFY_RATE_MAX", "not-int")
    monkeypatch.setenv("AIM_NOTIFY_RATE_WINDOW_MIN", "also-not")
    # Default is 20/60min — still works.
    for _ in range(5):
        r = isolated.notify("x", channels=("log",))
        assert r.delivered_via == "log"


# ── email channel ────────────────────────────────────────────────


def test_email_skipped_without_address(isolated, monkeypatch):
    monkeypatch.delenv("AIM_NOTIFY_EMAIL_TO", raising=False)
    assert isolated._send_email("body", "subject") is False


def test_email_attempts_when_address_set(isolated, monkeypatch):
    monkeypatch.setenv("AIM_NOTIFY_EMAIL_TO", "user@example.com")
    sent = {}
    class FakeAgent:
        @staticmethod
        def send(**kwargs):
            sent.update(kwargs)
            return True
    # `from agents import email_agent` resolves via the `agents` package
    # attribute first, falling back to sys.modules — patch BOTH so the
    # stub wins regardless of whether the real module was already
    # imported by an earlier test.
    import sys, agents as _agents_pkg
    monkeypatch.setitem(sys.modules, "agents.email_agent", FakeAgent)
    monkeypatch.setattr(_agents_pkg, "email_agent", FakeAgent,
                         raising=False)
    ok = isolated._send_email("hello body", "Daily")
    assert ok is True
    assert sent["to"] == "user@example.com"
    assert sent["subject"] == "Daily"
    assert sent["user_confirmed"] is True
