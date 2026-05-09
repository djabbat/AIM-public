"""tests/test_phase8_shims.py — parity gates for the Python shims that
went through Rust binaries in Phase 8 (2026-05-07).

Per `PHASE_8_ROADMAP.md` test strategy: each shim must produce the
same outputs as the original Python implementation across N≥20 cases.
The original Python impls are gone (replaced by shims), so these tests
serve as **regression** gates instead — locking in the contract the
Rust binaries must respect.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── smart_routing shim ────────────────────────────────────────────────────


def test_smart_routing_classify_simple_question():
    from agents import smart_routing
    info = smart_routing.classify("что такое CRISPR?")
    assert info["tier"] == "fast"
    assert info["model"] == "llama-3.1-8b-instant"


def test_smart_routing_classify_reasoning_marker():
    from agents import smart_routing
    info = smart_routing.classify("проанализируй и сравни эти два подхода")
    assert info["tier"] == "reasoning"
    assert info["model"] == "deepseek-reasoner"


def test_smart_routing_classify_long_default():
    from agents import smart_routing
    long_prompt = "x" * 600  # >200 chars, no markers
    info = smart_routing.classify(long_prompt)
    assert info["tier"] == "standard"
    assert info["model"] == "deepseek-chat"


def test_smart_routing_classify_force_model_overrides():
    from agents import smart_routing
    info = smart_routing.classify("что такое CRISPR?", force_model="deepseek-reasoner")
    assert info["tier"] == "forced"
    assert info["model"] == "deepseek-reasoner"


def test_smart_routing_estimate_cost_known_model():
    from agents import smart_routing
    cost = smart_routing.estimate_cost("deepseek-v4-flash", 1000, 500)
    # 1000 * 0.14 + 500 * 0.28 = 280 → /1M = 0.00028
    assert abs(cost - 0.00028) < 1e-9


def test_smart_routing_estimate_cost_unknown_model_fallback():
    from agents import smart_routing
    # Unknown model → fallback ($1/M input, $2/M output)
    cost = smart_routing.estimate_cost("nonexistent-model-xyz", 1_000_000, 500_000)
    # 1M * 1 + 0.5M * 2 = 2_000_000 → /1M = 2.0
    assert abs(cost - 2.0) < 1e-3


def test_smart_routing_route_returns_cost():
    from agents import smart_routing
    info = smart_routing.route("что такое CRISPR?")
    assert "est_cost" in info
    assert info["est_cost"] >= 0


def test_smart_routing_stats_handles_missing_db(tmp_path, monkeypatch):
    from agents import smart_routing
    monkeypatch.setattr(smart_routing, "DB_PATH", tmp_path / "missing.db")
    s = smart_routing.stats()
    assert s["rows"] == 0


# ─── reflexion shim ─────────────────────────────────────────────────────────


def test_reflexion_classify_buckets():
    from agents import reflexion
    assert reflexion.classify("исправь bug в коде") == "code_edit"
    assert reflexion.classify("find papers about CDATA") == "research"
    assert reflexion.classify("напиши peer review") == "writing"
    assert reflexion.classify("diagnose patient with chest pain") == "diagnosis"
    assert reflexion.classify("git push") == "ops"
    assert reflexion.classify("send email to professor") == "email"
    assert reflexion.classify("hello world") == "general"


def test_reflexion_save_then_recent_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from agents import reflexion
    reflexion.save_reflection("peer review article", "verify all PMIDs first")
    reflexion.save_reflection("peer review article", "shorter introduction")
    out = reflexion.recent_reflections("peer review", n=5)
    assert len(out) == 2
    assert "verify all PMIDs first" in out
    assert "shorter introduction" in out


def test_reflexion_recent_empty_when_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from agents import reflexion
    out = reflexion.recent_reflections("nonexistent task class")
    assert out == []


def test_reflexion_recent_respects_n_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from agents import reflexion
    for i in range(5):
        reflexion.save_reflection("peer review", f"reflection {i}")
    out = reflexion.recent_reflections("peer review", n=2)
    assert len(out) == 2
    # Most recent should come last (Rust impl preserves chronological order)
    assert "reflection 4" in out
    assert "reflection 3" in out


def test_reflexion_save_handles_missing_binary_gracefully(tmp_path, monkeypatch):
    """save_reflection swallows binary errors per the original API contract."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from agents import reflexion
    # Simulate missing binary by overriding _binary_path
    monkeypatch.setattr(reflexion, "_binary_path",
                        lambda: Path("/nonexistent/aim-reflexion"))
    # save_reflection logs and returns; does not raise
    reflexion.save_reflection("task", "summary")
    # recent_reflections returns [] on error
    assert reflexion.recent_reflections("task") == []
