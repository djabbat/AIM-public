"""AI/tests/test_self_modify.py — S6 framework (2026-05-04)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.delenv("AI_SELF_MODIFY_DISABLED", raising=False)
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.self_modify"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── can_self_modify ─────────────────────────────────────────────


def test_gate_closed_on_empty_ledger(isolated):
    from AI.ai.self_modify import can_self_modify
    v = can_self_modify()
    assert v.allowed is False
    assert any("baseline runs" in r for r in v.reasons)


def test_gate_closed_when_too_few_runs(isolated):
    from AI.ai.diagnostic_ledger import record
    long_ago = (dt.datetime.now() - dt.timedelta(days=60)).isoformat()
    record(model="m", grade="B", n_refs=1, n_with_line=1, ts=long_ago)
    from AI.ai.self_modify import can_self_modify
    v = can_self_modify()
    assert v.allowed is False
    assert any("baseline runs" in r for r in v.reasons)


def test_gate_closed_when_too_young(isolated):
    """Lots of runs but all from today → still too young."""
    from AI.ai.diagnostic_ledger import record
    for i in range(40):
        record(model="m", grade="B", n_refs=1, n_with_line=1,
               ts=f"2026-05-04T10:{(i%60):02d}:{(i%60):02d}.{i:06d}")
    from AI.ai.self_modify import can_self_modify
    v = can_self_modify()
    assert v.allowed is False
    assert any("baseline age" in r for r in v.reasons)


def test_gate_open_when_baseline_mature(isolated):
    from AI.ai.diagnostic_ledger import record
    base = dt.datetime.now() - dt.timedelta(days=35)
    for i in range(35):
        ts = (base + dt.timedelta(days=i)).isoformat()
        record(model="m", grade="B", n_refs=1, n_with_line=1, ts=ts)
    from AI.ai.self_modify import can_self_modify
    v = can_self_modify()
    assert v.allowed is True
    assert v.reasons == []


def test_killswitch_env_blocks_open_gate(isolated, monkeypatch):
    """Even when baseline is mature, AI_SELF_MODIFY_DISABLED locks down."""
    from AI.ai.diagnostic_ledger import record
    base = dt.datetime.now() - dt.timedelta(days=35)
    for i in range(35):
        ts = (base + dt.timedelta(days=i)).isoformat()
        record(model="m", grade="B", n_refs=1, n_with_line=1, ts=ts)
    monkeypatch.setenv("AI_SELF_MODIFY_DISABLED", "1")
    from AI.ai.self_modify import can_self_modify
    v = can_self_modify()
    assert v.allowed is False
    assert any("DISABLED" in r for r in v.reasons)


# ── propose / apply ─────────────────────────────────────────────


def test_propose_returns_struct(isolated):
    from AI.ai.self_modify import propose
    p = propose("agents/x.py:42")
    assert p.finding_ref == "agents/x.py:42"
    assert str(p.target_path) == "agents/x.py"
    assert p.patch_unified == ""


def test_apply_refuses_when_gate_closed(isolated):
    from AI.ai.self_modify import propose, apply
    p = propose("agents/x.py:42")
    res = apply(p, dry_run=True)
    assert res.applied is False
    assert any("denied" in n for n in res.notes)


def test_apply_dry_run_when_gate_open(isolated):
    """Even with mature baseline, framework refuses live mutation
    until L_CONSENT integration lands. dry_run is forced."""
    from AI.ai.diagnostic_ledger import record
    base = dt.datetime.now() - dt.timedelta(days=35)
    for i in range(35):
        ts = (base + dt.timedelta(days=i)).isoformat()
        record(model="m", grade="B", n_refs=1, n_with_line=1, ts=ts)
    from AI.ai.self_modify import propose, apply
    p = propose("agents/x.py:42")
    res = apply(p, dry_run=False)
    assert res.applied is False
    assert any("not yet enabled" in n for n in res.notes)


# ── summary ─────────────────────────────────────────────────────


def test_summary_closed_gate(isolated):
    from AI.ai.self_modify import summary
    s = summary()
    assert "CLOSED" in s
    assert "runs=" in s


def test_summary_open_gate(isolated):
    from AI.ai.diagnostic_ledger import record
    base = dt.datetime.now() - dt.timedelta(days=35)
    for i in range(35):
        ts = (base + dt.timedelta(days=i)).isoformat()
        record(model="m", grade="B", n_refs=1, n_with_line=1, ts=ts)
    from AI.ai.self_modify import summary
    s = summary()
    assert "OPEN" in s
