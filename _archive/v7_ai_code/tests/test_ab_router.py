"""tests/test_ab_router.py — S5 A/B routing automation (2026-05-02)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_AB_ROUTER_DB", str(tmp_path / "ab.db"))
    import importlib
    import agents.ab_router as ar
    importlib.reload(ar)
    return ar


# ── stats ─────────────────────────────────────────────────────────


def test_welch_t_p_handles_small_samples(isolated):
    assert isolated.welch_t_p([1.0], [1.0]) is None
    assert isolated.welch_t_p([], [1.0, 2.0]) is None


def test_welch_t_p_zero_variance_equal(isolated):
    p = isolated.welch_t_p([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
    assert p == 1.0


def test_welch_t_p_zero_variance_different(isolated):
    p = isolated.welch_t_p([0.5, 0.5, 0.5], [0.9, 0.9, 0.9])
    assert p == 0.0


def test_welch_t_p_significant_diff(isolated):
    """Big effect, low variance → p should be small."""
    a = [0.50, 0.51, 0.49, 0.50, 0.51, 0.49] * 3
    b = [0.80, 0.81, 0.79, 0.80, 0.81, 0.79] * 3
    p = isolated.welch_t_p(a, b)
    assert p is not None
    assert p < 0.001


def test_welch_t_p_no_diff_high_p(isolated):
    a = [0.5, 0.6, 0.4, 0.5, 0.6, 0.4]
    b = [0.5, 0.6, 0.4, 0.5, 0.6, 0.4]
    p = isolated.welch_t_p(a, b)
    assert p is not None
    assert p > 0.5


# ── round lifecycle ───────────────────────────────────────────────


def test_round_id_increments(isolated):
    r1 = isolated.start_round("v2", baseline="v1")
    r2 = isolated.start_round("v3", baseline="v2")
    assert r2 > r1


def test_record_run_persists(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    isolated.record_run(rid, "v1", score=0.6, cost_usd=0.01, n_cases=10)
    isolated.record_run(rid, "v2", score=0.8, cost_usd=0.012, n_cases=10)
    runs_v1 = isolated._runs_for(rid, "v1")
    runs_v2 = isolated._runs_for(rid, "v2")
    assert len(runs_v1) == 1 and runs_v1[0]["score"] == 0.6
    assert len(runs_v2) == 1


# ── decide() ──────────────────────────────────────────────────────


def test_decide_insufficient(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    res = isolated.decide(rid)
    assert res["verdict"] == "insufficient"


def test_decide_promotes_challenger_on_clear_win(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.50, 0.51, 0.49, 0.50, 0.51, 0.49] * 2:
        isolated.record_run(rid, "v1", score=s, cost_usd=0.01, n_cases=20)
    for s in [0.80, 0.81, 0.79, 0.80, 0.81, 0.79] * 2:
        isolated.record_run(rid, "v2", score=s, cost_usd=0.011, n_cases=20)
    res = isolated.decide(rid)
    assert res["verdict"] == "promote_challenger"
    assert res["winner"] == "v2"
    assert res["p_value"] is not None and res["p_value"] < 0.001


def test_decide_keeps_baseline_when_challenger_worse(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.80, 0.81, 0.79, 0.82, 0.78, 0.80]:
        isolated.record_run(rid, "v1", score=s)
    for s in [0.50, 0.51, 0.49, 0.52, 0.48, 0.50]:
        isolated.record_run(rid, "v2", score=s)
    res = isolated.decide(rid)
    assert res["verdict"] == "keep_baseline"
    assert res["winner"] == "v1"


def test_decide_neutral_when_close(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.6, 0.61, 0.59, 0.6, 0.61, 0.59]:
        isolated.record_run(rid, "v1", score=s)
    for s in [0.605, 0.6, 0.61, 0.598, 0.601, 0.602]:
        isolated.record_run(rid, "v2", score=s)
    res = isolated.decide(rid)
    assert res["verdict"] in {"neutral", "keep_baseline"}


def test_decide_cost_guard_blocks_promotion(isolated):
    """Score wins, but challenger costs 5× baseline — fail cost guard."""
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.50, 0.51, 0.49, 0.50, 0.51, 0.49] * 2:
        isolated.record_run(rid, "v1", score=s, cost_usd=0.001)
    for s in [0.80, 0.81, 0.79, 0.80, 0.81, 0.79] * 2:
        isolated.record_run(rid, "v2", score=s, cost_usd=0.005)
    res = isolated.decide(rid, cost_tolerance=0.20)
    assert res["verdict"] == "keep_baseline"
    assert "cost guard" in res["note"]


def test_decide_persists_into_history(isolated):
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.5] * 4:
        isolated.record_run(rid, "v1", score=s)
        isolated.record_run(rid, "v2", score=s)
    isolated.decide(rid)
    h = isolated.history()
    assert len(h) == 1
    assert h[0]["round_id"] == rid


def test_current_baseline_after_decisions(isolated):
    # Initially nothing.
    assert isolated.current_baseline() is None
    rid = isolated.start_round("v2", baseline="v1")
    for s in [0.50, 0.51, 0.49, 0.50] * 2:
        isolated.record_run(rid, "v1", score=s)
    for s in [0.80, 0.81, 0.79, 0.80] * 2:
        isolated.record_run(rid, "v2", score=s)
    isolated.decide(rid)
    assert isolated.current_baseline() == "v2"


# ── input validation ─────────────────────────────────────────────


def test_start_round_requires_challenger(isolated):
    with pytest.raises(ValueError):
        isolated.start_round("")


def test_round_unknown_id_raises(isolated):
    with pytest.raises(ValueError):
        isolated.decide(9999)
