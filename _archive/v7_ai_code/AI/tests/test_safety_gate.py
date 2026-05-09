"""AI/tests/test_safety_gate.py — SG1 (2026-05-04)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.delenv("AI_DIAG_COOLDOWN_HOURS", raising=False)
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.safety_gate"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _stub_budget(monkeypatch, *, cost: float = 0.0, budget: float = 5.0):
    """Pretend agents.cost_ledger reports these values."""
    import sys, agents as _agents_pkg
    fake = type(sys)("agents.cost_ledger")
    fake.daily_cost = lambda: cost
    fake.daily_budget = lambda: budget
    monkeypatch.setitem(sys.modules, "agents.cost_ledger", fake)
    monkeypatch.setattr(_agents_pkg, "cost_ledger", fake, raising=False)


# ── cooldown gate ───────────────────────────────────────────────


def test_no_history_allows_run(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.allowed is True
    assert v.cooldown_ok is True
    assert v.last_run_age_h is None


def test_recent_run_blocks(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    from AI.ai.diagnostic_ledger import record
    fresh = (dt.datetime.now() - dt.timedelta(hours=2)).isoformat()
    record(model="m", grade="B", n_refs=1, n_with_line=1, ts=fresh)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.cooldown_ok is False
    assert v.allowed is False
    assert v.last_run_age_h is not None
    assert any("cooldown" in r for r in v.reasons)


def test_old_run_allows(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    from AI.ai.diagnostic_ledger import record
    old = (dt.datetime.now() - dt.timedelta(days=2)).isoformat()
    record(model="m", grade="B", n_refs=1, n_with_line=1, ts=old)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.cooldown_ok is True
    assert v.allowed is True


def test_custom_cooldown_via_env(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    monkeypatch.setenv("AI_DIAG_COOLDOWN_HOURS", "0.5")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.safety_gate"])
    from AI.ai.diagnostic_ledger import record
    last = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat()
    record(model="m", grade="B", n_refs=1, n_with_line=1, ts=last)
    from AI.ai.safety_gate import can_run
    v = can_run()
    # 1h elapsed, cooldown 0.5h → allowed
    assert v.cooldown_ok is True


def test_invalid_cooldown_env_falls_back(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    monkeypatch.setenv("AI_DIAG_COOLDOWN_HOURS", "not-a-number")
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.safety_gate"])
    from AI.ai.safety_gate import _min_cooldown_hours
    assert _min_cooldown_hours() == 23.0


# ── budget gate ─────────────────────────────────────────────────


def test_budget_under_cap_allows(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=2.0, budget=5.0)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.budget_ok is True


def test_budget_over_cap_blocks(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=6.0, budget=5.0)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.budget_ok is False
    assert v.allowed is False
    assert any("budget" in r for r in v.reasons)


def test_zero_budget_means_unlimited(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=100.0, budget=0.0)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.budget_ok is True
    assert v.allowed is True


def test_budget_module_missing_does_not_block(isolated, monkeypatch):
    """When agents.cost_ledger isn't importable, gate must NOT block."""
    import sys, agents as _agents_pkg
    monkeypatch.delitem(sys.modules, "agents.cost_ledger", raising=False)
    if hasattr(_agents_pkg, "cost_ledger"):
        delattr(_agents_pkg, "cost_ledger")
    # Force ImportError by stubbing a module that raises on attr access
    fake = type(sys)("agents.cost_ledger")
    def boom(): raise RuntimeError("boom")
    fake.daily_cost = boom
    fake.daily_budget = boom
    monkeypatch.setitem(sys.modules, "agents.cost_ledger", fake)
    monkeypatch.setattr(_agents_pkg, "cost_ledger", fake, raising=False)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.budget_ok is True   # don't block on accounting failure


# ── combined verdict ────────────────────────────────────────────


def test_both_gates_failing(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=10.0, budget=5.0)
    from AI.ai.diagnostic_ledger import record
    fresh = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat()
    record(model="m", grade="B", n_refs=1, n_with_line=1, ts=fresh)
    from AI.ai.safety_gate import can_run
    v = can_run()
    assert v.allowed is False
    assert v.cooldown_ok is False
    assert v.budget_ok is False
    assert len(v.reasons) >= 2


# ── summary ─────────────────────────────────────────────────────


def test_summary_allowed_label(isolated, monkeypatch):
    _stub_budget(monkeypatch)
    from AI.ai.safety_gate import summary
    s = summary()
    assert "OK to run" in s


def test_summary_blocked_label(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=10.0, budget=5.0)
    from AI.ai.safety_gate import summary
    s = summary()
    assert "BLOCKED" in s
    assert "budget" in s


def test_summary_includes_cost_pair(isolated, monkeypatch):
    _stub_budget(monkeypatch, cost=2.5, budget=10.0)
    from AI.ai.safety_gate import summary
    s = summary()
    assert "$2.50" in s and "$10.00" in s
