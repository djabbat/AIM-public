"""tests/test_permission_broker.py — G3 interactive permission (2026-05-02).

Covers agents.permission.request + the AIM_INTERACTIVE_CONSENT integration
in agents.kernel.evaluate_l_consent. We don't drive a real TTY; instead
we monkeypatch the TUI prompt and verify cache, env overrides, and audit
log behaviour.
"""
from __future__ import annotations

import os
import time

import pytest

from agents import permission as perm
from agents.kernel import Decision as KDecision, evaluate_l_consent


@pytest.fixture(autouse=True)
def _clean_cache_and_env(monkeypatch):
    perm.clear_cache()
    for k in ("AIM_AUTO_CONSENT", "AIM_NONINTERACTIVE",
              "AIM_INTERACTIVE_CONSENT", "AIM_PERMISSION_CHANNEL"):
        monkeypatch.delenv(k, raising=False)
    yield
    perm.clear_cache()


# ── env overrides ─────────────────────────────────────────────────────


def test_auto_consent_grants(monkeypatch):
    monkeypatch.setenv("AIM_AUTO_CONSENT", "1")
    d = perm.request("email_send", "x@example.com")
    assert d.granted is True
    assert d.via == "auto_consent"


def test_noninteractive_denies(monkeypatch):
    monkeypatch.setenv("AIM_NONINTERACTIVE", "1")
    d = perm.request("email_send", "x@example.com")
    assert d.granted is False
    assert d.via == "noninteractive_deny"


# ── cache behaviour ───────────────────────────────────────────────────


def test_cache_grants_persist_within_ttl(monkeypatch):
    monkeypatch.setattr(perm, "_prompt_tui",
                        lambda *_args, **_kw: (True, "tui allow"))
    d1 = perm.request("email_send", "alice@example.com")
    d2 = perm.request("email_send", "alice@example.com")
    assert d1.granted and d2.granted
    assert d1.via == "tui"
    assert d2.via == "cache"


def test_cache_denials_are_not_cached(monkeypatch):
    calls = {"n": 0}
    def fake(*_a, **_k):
        calls["n"] += 1
        return False, "tui deny"
    monkeypatch.setattr(perm, "_prompt_tui", fake)
    d1 = perm.request("email_send", "spam@example.com")
    d2 = perm.request("email_send", "spam@example.com")
    assert not d1.granted and not d2.granted
    # Both decisions should have hit the prompt — denies are NOT cached.
    assert calls["n"] == 2


def test_always_deny_is_cached(monkeypatch):
    monkeypatch.setattr(perm, "_prompt_tui",
                        lambda *_a, **_k: (False, "tui always-deny (15m)"))
    d1 = perm.request("git_push_public", "djabbat/repo")
    d2 = perm.request("git_push_public", "djabbat/repo")
    assert not d1.granted and not d2.granted
    assert d1.via == "tui"
    assert d2.via == "cache"


def test_clear_cache_resets():
    perm._cache_put("x", "y", True, ttl_s=600)
    assert perm._cache_get("x", "y") is True
    perm.clear_cache()
    assert perm._cache_get("x", "y") is None


def test_expired_cache_entry_is_dropped():
    perm._cache_put("x", "y", True, ttl_s=0.01)
    time.sleep(0.05)
    assert perm._cache_get("x", "y") is None


# ── tui prompt parsing ───────────────────────────────────────────────


@pytest.mark.parametrize("answer,expected,reason_substr", [
    ("a",  True,  "allow"),
    ("A",  True,  "always-allow"),
    ("d",  False, "deny"),
    ("D",  False, "always-deny"),
    ("",   False, "invalid"),
    ("y",  False, "invalid"),
])
def test_tui_answer_parsing(monkeypatch, answer, expected, reason_substr):
    monkeypatch.setattr(perm, "_read_stdin_with_timeout",
                        lambda *_a, **_k: answer)
    granted, reason = perm._prompt_tui("email_send", "x", "preview", "ext")
    assert granted is expected
    assert reason_substr in reason


def test_tui_timeout_denies(monkeypatch):
    monkeypatch.setattr(perm, "_read_stdin_with_timeout",
                        lambda *_a, **_k: None)
    granted, reason = perm._prompt_tui("email_send", "x", "preview", "ext")
    assert granted is False
    assert "timeout" in reason


# ── kernel integration ──────────────────────────────────────────────


def _decision(action_type="email_send", **payload) -> KDecision:
    return KDecision(id="t", description="test action",
                     action_type=action_type, payload=payload, meta={})


def test_kernel_consent_blocks_without_user_confirmed():
    # Default behaviour (no AIM_INTERACTIVE_CONSENT): block.
    ok, reason = evaluate_l_consent(_decision(), {}, {})
    assert ok is False
    assert "user_confirmed" in reason or "user confirmation" in reason


def test_kernel_consent_passes_with_user_confirmed_flag():
    ok, reason = evaluate_l_consent(_decision(), {}, {"user_confirmed": True})
    assert ok is True


def test_kernel_consent_uses_broker_when_interactive(monkeypatch):
    monkeypatch.setenv("AIM_INTERACTIVE_CONSENT", "1")
    monkeypatch.setattr(perm, "_prompt_tui",
                        lambda *_a, **_k: (True, "tui allow"))
    ok, reason = evaluate_l_consent(
        _decision(scope="alice@example.com"), {}, {})
    assert ok is True
    assert "granted" in reason


def test_kernel_consent_broker_denial_is_propagated(monkeypatch):
    monkeypatch.setenv("AIM_INTERACTIVE_CONSENT", "1")
    monkeypatch.setattr(perm, "_prompt_tui",
                        lambda *_a, **_k: (False, "tui deny"))
    ok, reason = evaluate_l_consent(
        _decision(scope="bob@example.com"), {}, {})
    assert ok is False
    assert "denied" in reason


def test_kernel_consent_skips_broker_for_non_public_action():
    # `read_file` etc are not in public_actions → broker never queried.
    ok, reason = evaluate_l_consent(
        _decision(action_type="read_only"), {}, {})
    assert ok is True
    assert "n/a" in reason


# ── audit log ────────────────────────────────────────────────────────


def test_audit_log_records_each_request(monkeypatch, tmp_path):
    monkeypatch.setattr(perm, "_AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setenv("AIM_AUTO_CONSENT", "1")
    perm.request("email_send", "x@example.com")
    perm.request("git_push_public", "djabbat/repo")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    import json as _json
    rows = [_json.loads(l) for l in lines]
    assert rows[0]["action_type"] == "email_send"
    assert rows[1]["action_type"] == "git_push_public"
    assert all(r["granted"] for r in rows)
