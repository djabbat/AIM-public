"""tests/test_prompt_evolver.py — S3 (2026-05-02)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROMPTS_DIR", str(tmp_path / "prompts"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    import agents.prompt_evolver as pe
    importlib.reload(pe)
    return pe


# ── filesystem helpers ────────────────────────────────────────────


def test_current_version_zero_for_unknown_key(isolated):
    assert isolated.current_version("doctor") == 0


def test_persist_patch_increments(isolated):
    n1 = isolated._persist_patch("doctor", "v1 text")
    n2 = isolated._persist_patch("doctor", "v2 text")
    assert n1 == 1 and n2 == 2
    assert isolated.current_version("doctor") == 2
    assert isolated.load_baseline("doctor") == "v2 text"


def test_revert_drops_latest(isolated):
    isolated._persist_patch("doctor", "v1")
    isolated._persist_patch("doctor", "v2")
    v = isolated.revert("doctor")
    assert v == 2
    assert isolated.current_version("doctor") == 1
    assert isolated.load_baseline("doctor") == "v1"


def test_revert_when_nothing(isolated):
    assert isolated.revert("ghost") is None


# ── propose() flow ────────────────────────────────────────────────


def test_propose_refuses_with_few_reflections(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_gather_reflections",
                        lambda key, n=8: ["only one"])
    runner = lambda p: (0.5, 0.001)
    res = isolated.propose("doctor", runner=runner, min_reflections=3)
    assert res.verdict == "insufficient_reflections"
    assert res.new_version is None


def test_propose_no_candidates(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_gather_reflections",
                        lambda key, n=8: ["a", "b", "c"])
    runner = lambda p: (0.5, 0.001)
    res = isolated.propose("doctor", runner=runner,
                            mutate_fn=lambda *a: [])
    assert res.verdict == "no_change"
    assert res.new_version is None


def test_propose_promotes_clear_winner(isolated, monkeypatch):
    """Baseline scores 0.5±ε, candidate scores 0.9±ε → must promote."""
    monkeypatch.setattr(isolated, "_gather_reflections",
                        lambda key, n=8: ["fix it", "cite better", "be terse"])
    isolated._persist_patch("doctor", "BASELINE")

    def runner(prompt: str) -> tuple[float, float]:
        if prompt == "BASELINE":
            return 0.5, 0.001
        # Candidate "WINNER" scores high, others moderate.
        if prompt == "WINNER":
            return 0.9, 0.001
        return 0.6, 0.001

    candidates = ["LOSER", "WINNER", "MEH"]
    res = isolated.propose("doctor", runner=runner,
                            repeats=8,
                            mutate_fn=lambda *a: candidates)
    assert res.verdict == "promoted", res.note
    assert res.new_version == 2
    assert isolated.load_baseline("doctor") == "WINNER"


def test_propose_rejects_no_improvement(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_gather_reflections",
                        lambda key, n=8: ["a", "b", "c"])
    isolated._persist_patch("doctor", "BASELINE")
    # All variants score the same.
    runner = lambda p: (0.5, 0.001)
    res = isolated.propose("doctor", runner=runner, repeats=4,
                            mutate_fn=lambda *a: ["X", "Y"])
    assert res.verdict in {"rejected", "no_change"}
    assert isolated.load_baseline("doctor") == "BASELINE"
    assert isolated.current_version("doctor") == 1


def test_propose_history_records_decision(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "_gather_reflections",
                        lambda key, n=8: ["x"])
    isolated.propose("doctor", runner=lambda p: (0.5, 0),
                      min_reflections=3)
    h = isolated.history("doctor")
    assert h and h[-1]["verdict"] == "insufficient_reflections"


# ── mutation helper ──────────────────────────────────────────────


def test_mutate_candidates_empty_when_optimizer_missing(isolated, monkeypatch):
    # Force ImportError on the optimizer.
    import sys
    monkeypatch.setitem(sys.modules, "agents.prompt_optimizer",
                        type(sys)("agents.prompt_optimizer"))
    out = isolated._mutate_candidates("base", ["r1"], 4)
    assert out == []


def test_baseline_path_versioned(isolated):
    p = isolated.baseline_path("doctor", version=3)
    assert p.name == "v3.md"


def test_load_baseline_when_none(isolated):
    assert isolated.load_baseline("brand-new") == ""
