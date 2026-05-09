"""tests/test_recall_perf.py — SL1 (2026-05-03)."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path))
    monkeypatch.setenv("AIM_RECALL_SLOW_MS", "100")
    monkeypatch.setenv("AIM_RECALL_CACHE_TTL", "60")
    monkeypatch.setenv("AIM_RECALL_CACHE_MAX", "4")
    import importlib, sys
    if "agents.recall_perf" in sys.modules:
        importlib.reload(sys.modules["agents.recall_perf"])
    import agents.recall_perf as rp
    rp.reset_state_for_tests()
    yield rp
    rp.uninstall()
    rp.reset_state_for_tests()


def _fast_retrieve(query, k=12, max_chars_per_file=4000):
    return [{"file": f"x.md", "text": query, "_distance": 0.1}]


def _slow_retrieve(query, k=12, max_chars_per_file=4000):
    time.sleep(0.15)
    return [{"file": "slow.md", "text": query, "_distance": 0.2}]


# ── wrapper basics ───────────────────────────────────────────────


def test_make_wrapper_calls_original(isolated):
    calls = []
    def orig(q, k=12, max_chars_per_file=4000):
        calls.append(q)
        return [{"file": "x.md", "text": q, "_distance": 0.1}]
    wrap = isolated.make_wrapper(orig)
    out = wrap("hello", k=3)
    assert calls == ["hello"]
    assert out[0]["text"] == "hello"


def test_cache_hit_avoids_second_call(isolated):
    calls = []
    def orig(q, k=12, max_chars_per_file=4000):
        calls.append(q)
        return [{"file": "x", "text": q, "_distance": 0.0}]
    wrap = isolated.make_wrapper(orig)
    wrap("foo", k=3)
    wrap("foo", k=3)
    assert calls == ["foo"]
    s = isolated.stats()
    assert s["n_calls"] == 2
    assert s["n_cache_hits"] == 1


def test_cache_keys_distinguish_k(isolated):
    calls = []
    def orig(q, k=12, max_chars_per_file=4000):
        calls.append((q, k))
        return [{"file": "x", "text": q, "_distance": 0.0}]
    wrap = isolated.make_wrapper(orig)
    wrap("foo", k=3)
    wrap("foo", k=5)
    assert len(calls) == 2


def test_cache_eviction(isolated):
    """With AIM_RECALL_CACHE_MAX=4, the oldest entry drops at 5."""
    calls = []
    def orig(q, k=12, max_chars_per_file=4000):
        calls.append(q)
        return []
    wrap = isolated.make_wrapper(orig)
    for n in range(5):
        wrap(f"q{n}", k=1)
    # Now ask for the oldest again — should hit `orig` (cache evicted).
    wrap("q0", k=1)
    assert calls.count("q0") == 2


def test_cache_ttl_expiry(isolated, monkeypatch):
    monkeypatch.setenv("AIM_RECALL_CACHE_TTL", "0.05")
    import importlib, agents.recall_perf as rp
    importlib.reload(rp)
    rp.reset_state_for_tests()
    calls = []
    def orig(q, k=12, max_chars_per_file=4000):
        calls.append(q); return []
    wrap = rp.make_wrapper(orig)
    wrap("ttl", k=1)
    time.sleep(0.1)
    wrap("ttl", k=1)
    assert calls == ["ttl", "ttl"]   # second call missed cache


# ── slow-query detection ────────────────────────────────────────


def test_slow_query_recorded(isolated):
    wrap = isolated.make_wrapper(_slow_retrieve)
    wrap("slow query", k=2)
    s = isolated.stats()
    assert s["n_slow"] == 1
    assert s["top_slow"][0][0] == "slow query"
    h = isolated.history()
    assert h and h[-1]["query"] == "slow query"


def test_fast_query_not_recorded(isolated):
    wrap = isolated.make_wrapper(_fast_retrieve)
    wrap("fast", k=2)
    s = isolated.stats()
    assert s["n_slow"] == 0


def test_top_slow_capped(isolated):
    """The slow_queries buffer caps at 20."""
    wrap = isolated.make_wrapper(_slow_retrieve)
    for n in range(25):
        wrap(f"q{n}", k=1)
    assert len(isolated.stats()["top_slow"]) == 20


# ── install / uninstall lifecycle ───────────────────────────────


def test_install_replaces_retrieve(isolated):
    import agents.memory_index as mi
    original = mi.retrieve
    assert isolated.install() is True
    assert mi.retrieve is not original
    isolated.uninstall()
    assert mi.retrieve is original


def test_install_idempotent(isolated):
    isolated.install()
    isolated.install()   # second call should be no-op
    isolated.uninstall()


def test_uninstall_when_not_installed_returns_false(isolated):
    assert isolated.uninstall() is False


def test_install_then_recall_uses_wrapper(isolated, monkeypatch):
    """End-to-end: install, call recall, see stats updated."""
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x", "text": q, "_distance": 0.1}])
    isolated.install()
    out = mi.retrieve("hello", k=3)
    assert out[0]["text"] == "hello"
    assert isolated.stats()["n_calls"] == 1


# ── stats shape ─────────────────────────────────────────────────


def test_stats_has_expected_fields(isolated):
    s = isolated.stats()
    for key in ("n_calls", "n_cache_hits", "n_slow",
                "cache_size", "top_slow"):
        assert key in s
