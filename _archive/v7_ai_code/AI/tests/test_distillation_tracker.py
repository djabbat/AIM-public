"""AI/tests/test_distillation_tracker.py — S9 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "eval.db"))
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    import importlib, sys
    for m in ["agents.evals", "AI.ai.distillation_tracker"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    # `agents.evals._ensure_cases_dir` may have written a builtin smoke
    # case during reload — clear so each test sees only its own fixtures.
    for f in cases.glob("*.yaml"):
        f.unlink()
    return tmp_path


def write_case(setup, name, body):
    (setup / "cases" / f"{name}.yaml").write_text(body, encoding="utf-8")


# ── record / query ───────────────────────────────────────────────


def test_record_persists(isolated):
    from AI.ai.distillation_tracker import record, latest_per_tier_per_case
    record("haiku", "case-a", 0.7, latency_ms=200, cost_usd=0.001)
    out = latest_per_tier_per_case()
    assert ("case-a", "haiku") in out
    assert out[("case-a", "haiku")]["score"] == 0.7


def test_latest_per_tier_returns_most_recent(isolated):
    from AI.ai.distillation_tracker import record, latest_per_tier_per_case
    record("opus", "case-x", 0.5)
    record("opus", "case-x", 0.9)
    out = latest_per_tier_per_case()
    assert out[("case-x", "opus")]["score"] == 0.9


def test_latest_per_tier_distinct_pairs(isolated):
    from AI.ai.distillation_tracker import record, latest_per_tier_per_case
    record("opus", "x", 0.9)
    record("haiku", "x", 0.6)
    record("opus", "y", 0.8)
    out = latest_per_tier_per_case()
    assert {(c, t) for c, t in out} == {("x", "opus"), ("x", "haiku"),
                                         ("y", "opus")}


# ── run_tier integration with evals ─────────────────────────────


def test_run_tier_persists_per_case(isolated):
    write_case(isolated, "c1", "id: c1\ntask: greet\n"
                                  "rubrics:\n  contains_any: [hi, hello]\n")
    write_case(isolated, "c2", "id: c2\ntask: hi\nrubrics:\n  min_length: 0\n")

    from AI.ai.distillation_tracker import Tier, run_tier, latest_per_tier_per_case
    out = run_tier(Tier(name="stub", runner=lambda t: "hello",
                          cost_per_call=0.001))
    assert out["score"] == 1.0
    assert out["n_cases"] == 2
    matrix = latest_per_tier_per_case()
    assert ("c1", "stub") in matrix
    assert ("c2", "stub") in matrix


def test_run_tier_dry_run(isolated):
    write_case(isolated, "c", "id: c\ntask: x\nrubrics:\n  min_length: 0\n")
    from AI.ai.distillation_tracker import Tier, run_tier, latest_per_tier_per_case
    run_tier(Tier(name="dry", runner=lambda t: "ok"), persist=False)
    assert latest_per_tier_per_case() == {}


def test_run_all_tiers_iterates(isolated):
    write_case(isolated, "c", "id: c\ntask: x\nrubrics:\n  min_length: 0\n")
    from AI.ai.distillation_tracker import Tier, run_all_tiers
    out = run_all_tiers([
        Tier(name="t1", runner=lambda _: "a"),
        Tier(name="t2", runner=lambda _: "b"),
    ])
    assert [o["tier"] for o in out] == ["t1", "t2"]


# ── compare_tiers / downgrade_candidates ────────────────────────


def test_compare_tiers_matrix(isolated):
    from AI.ai.distillation_tracker import record, compare_tiers
    record("opus", "x", 0.9, cost_usd=0.05)
    record("haiku", "x", 0.85, cost_usd=0.001)
    m = compare_tiers()
    assert m["x"] == {"opus": 0.9, "haiku": 0.85}


def test_downgrade_safe_when_close_score(isolated):
    from AI.ai.distillation_tracker import (
        record, downgrade_candidates,
    )
    record("opus", "x", 0.92, cost_usd=0.05)
    record("haiku", "x", 0.88, cost_usd=0.001)   # 88% / 92% = 0.957
    out = downgrade_candidates(premium_tier="opus",
                                budget_tiers=["haiku"],
                                min_safe_score=0.85,
                                ratio=0.95)
    assert len(out) == 1
    assert out[0].safe_tier == "haiku"
    assert out[0].premium_tier == "opus"
    assert out[0].cost_saved_per_call > 0


def test_downgrade_skipped_when_score_drops_too_far(isolated):
    from AI.ai.distillation_tracker import record, downgrade_candidates
    record("opus", "x", 0.9, cost_usd=0.05)
    record("haiku", "x", 0.6, cost_usd=0.001)   # well under threshold
    assert downgrade_candidates(premium_tier="opus",
                                 budget_tiers=["haiku"]) == []


def test_downgrade_skipped_when_premium_missing(isolated):
    from AI.ai.distillation_tracker import record, downgrade_candidates
    record("haiku", "x", 0.95, cost_usd=0.001)
    assert downgrade_candidates(premium_tier="opus",
                                 budget_tiers=["haiku"]) == []


def test_downgrade_picks_cheapest_safe_tier(isolated):
    from AI.ai.distillation_tracker import record, downgrade_candidates
    record("opus", "x", 0.9, cost_usd=0.05)
    record("sonnet", "x", 0.88, cost_usd=0.01)
    record("haiku", "x", 0.86, cost_usd=0.001)
    # budget_tiers ordered cheapest-first → expect haiku.
    out = downgrade_candidates(premium_tier="opus",
                                 budget_tiers=["haiku", "sonnet"],
                                 min_safe_score=0.85,
                                 ratio=0.95)
    assert len(out) == 1
    assert out[0].safe_tier == "haiku"


# ── summary string ──────────────────────────────────────────────


def test_summary_calm_when_empty(isolated):
    from AI.ai.distillation_tracker import summary
    assert "no distillation runs" in summary()


def test_summary_renders_matrix_and_recs(isolated):
    from AI.ai.distillation_tracker import record, summary
    record("opus", "x", 0.9, cost_usd=0.05)
    record("haiku", "x", 0.88, cost_usd=0.001)
    s = summary(premium_tier="opus", budget_tiers=["haiku"])
    assert "Distillation matrix" in s
    assert "x" in s
    assert "downgrade-safe" in s


# ── CRIT-2 fix: concurrency safety ──────────────────────────────


def test_concurrent_record_no_corruption(isolated):
    """20 threads × 50 record() calls each — no corruption / loss / dup."""
    import threading
    from AI.ai.distillation_tracker import record, latest_per_tier_per_case

    errors: list[str] = []
    err_lock = threading.Lock()

    def worker(thread_id):
        try:
            for i in range(50):
                record(f"tier{thread_id}", f"case{i}",
                       score=0.5 + (i % 50) / 100.0,
                       cost_usd=0.001)
        except Exception as e:
            with err_lock:
                errors.append(f"t{thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(t,))
               for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, f"concurrent record() failed: {errors}"
    matrix = latest_per_tier_per_case()
    # 20 tiers × 50 cases = 1000 distinct (tier, case_id) pairs.
    assert len(matrix) == 1000


def test_idempotent_record_with_same_ts(isolated, monkeypatch):
    """Two record() calls with same timestamp → REPLACE, no dup row."""
    import datetime as _dt
    from AI.ai.distillation_tracker import record, latest_per_tier_per_case

    fixed_iso = "2026-05-03T12:00:00.000000"

    class _FrozenDT:
        @staticmethod
        def now():
            class _N:
                @staticmethod
                def isoformat():
                    return fixed_iso
            return _N()

    monkeypatch.setattr("AI.ai.distillation_tracker.dt.datetime", _FrozenDT)
    record("opus", "x", 0.5, cost_usd=0.01)
    record("opus", "x", 0.7, cost_usd=0.02)  # same ts → REPLACE
    matrix = latest_per_tier_per_case()
    assert matrix[("x", "opus")]["score"] == 0.7
    # Exactly one row for (opus, x, ts).
    import contextlib
    from AI.ai.distillation_tracker import _connect
    with contextlib.closing(_connect()) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM tier_runs "
            "WHERE tier='opus' AND case_id='x'").fetchone()[0]
    assert n == 1


def test_no_connection_leak_after_record(isolated):
    """200 record() calls — no accumulated sqlite3.Connection objects."""
    import gc, sqlite3
    from AI.ai.distillation_tracker import record
    before = sum(1 for o in gc.get_objects()
                  if isinstance(o, sqlite3.Connection))
    for i in range(200):
        record("tier", f"c{i}", 0.5)
    gc.collect()
    after = sum(1 for o in gc.get_objects()
                 if isinstance(o, sqlite3.Connection))
    # Allow a small number of legitimate connections; what we want to
    # ensure is that we don't keep one per record() call.
    assert after - before < 5, f"connection leak: {after - before} new"
