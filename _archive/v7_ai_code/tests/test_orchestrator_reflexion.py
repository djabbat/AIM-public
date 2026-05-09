"""tests/test_orchestrator_reflexion.py — F1 reflexion auto-pull (2026-05-03)."""
from __future__ import annotations

import pytest

from agents import orchestrator as orch
from agents.kernel import Decision


def _decision(action_type="emit_text", **payload):
    return Decision(
        id="t", description="some descr",
        action_type=action_type, payload=payload, meta={},
    )


# ── enable flag ───────────────────────────────────────────────────


def test_reflexion_auto_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AIM_REFLEXION_AUTO", raising=False)
    assert orch._reflexion_auto_enabled() is False


def test_reflexion_auto_enabled_via_env(monkeypatch):
    monkeypatch.setenv("AIM_REFLEXION_AUTO", "1")
    assert orch._reflexion_auto_enabled() is True


# ── hint injection ────────────────────────────────────────────────


def test_orchestrate_injects_hints_when_enabled(monkeypatch):
    monkeypatch.setenv("AIM_REFLEXION_AUTO", "1")
    monkeypatch.setattr(orch, "_gather_reflexion_hints",
                        lambda d: ["watch out for bad PMIDs",
                                    "user prefers ≤120 words"])
    captured = {}

    def service(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    out = orch.orchestrate(
        _decision(action_type="emit_text", text="ok-without-citations"),
        service,
    )
    assert "ok" in out
    assert captured.get("_aim_reflexion_hints") == [
        "watch out for bad PMIDs", "user prefers ≤120 words",
    ]


def test_orchestrate_no_hints_when_disabled(monkeypatch):
    monkeypatch.delenv("AIM_REFLEXION_AUTO", raising=False)
    monkeypatch.setattr(orch, "_gather_reflexion_hints",
                        lambda d: ["never injected"])
    captured = {}

    def service(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    orch.orchestrate(_decision(text="ok-text"), service)
    assert "_aim_reflexion_hints" not in captured


def test_orchestrate_no_hints_when_empty(monkeypatch):
    monkeypatch.setenv("AIM_REFLEXION_AUTO", "1")
    monkeypatch.setattr(orch, "_gather_reflexion_hints", lambda d: [])
    captured = {}

    def service(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    orch.orchestrate(_decision(text="x"), service)
    assert "_aim_reflexion_hints" not in captured


# ── compatibility with services that don't accept the kwarg ──────


def test_orchestrate_drops_hint_on_typeerror(monkeypatch):
    monkeypatch.setenv("AIM_REFLEXION_AUTO", "1")
    monkeypatch.setattr(orch, "_gather_reflexion_hints",
                        lambda d: ["hint-1"])

    calls = []

    def picky_service(*args, **kwargs):
        calls.append(kwargs)
        if "_aim_reflexion_hints" in kwargs:
            raise TypeError("got an unexpected keyword '_aim_reflexion_hints'")
        return "ok"

    out = orch.orchestrate(_decision(text="x"), picky_service)
    assert "ok" in out
    assert len(calls) == 2
    assert "_aim_reflexion_hints" in calls[0]
    assert "_aim_reflexion_hints" not in calls[1]


def test_orchestrate_propagates_real_typeerror(monkeypatch):
    """If service fails with an unrelated TypeError, we don't silently retry."""
    monkeypatch.setenv("AIM_REFLEXION_AUTO", "1")
    monkeypatch.setattr(orch, "_gather_reflexion_hints", lambda d: ["x"])

    def buggy_service(*args, **kwargs):
        raise TypeError("something else broke")

    out = orch.orchestrate(_decision(text="x"), buggy_service)
    assert out.startswith("ERROR:INTERNAL")


# ── _gather_reflexion_hints ──────────────────────────────────────


def _patch_reflexion(monkeypatch, fake):
    """`from agents import reflexion` resolves via the `agents` package
    attribute first, falling back to sys.modules — patch BOTH so the
    stub wins regardless of whether the real module was already
    imported by an earlier test."""
    import sys, agents as _agents_pkg
    monkeypatch.setitem(sys.modules, "agents.reflexion", fake)
    monkeypatch.setattr(_agents_pkg, "reflexion", fake, raising=False)


def test_gather_handles_reflexion_unavailable(monkeypatch):
    """If agents.reflexion can't be imported, return [] silently."""
    import sys
    _patch_reflexion(monkeypatch, type(sys)("agents.reflexion"))
    out = orch._gather_reflexion_hints(_decision())
    assert out == []


def test_gather_uses_action_type_as_bucket(monkeypatch):
    """The bucket key should be the action_type."""
    received = {}

    class FakeRfx:
        @staticmethod
        def classify(t): return "fallback"
        @staticmethod
        def recent_reflections(task, n=3, bucket=None, max_age_days=60):
            received["bucket"] = bucket
            return ["from-bucket"]

    _patch_reflexion(monkeypatch, FakeRfx)
    out = orch._gather_reflexion_hints(_decision(action_type="email_send"))
    assert out == ["from-bucket"]
    assert received["bucket"] == "email_send"
