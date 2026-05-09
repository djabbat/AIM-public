"""tests/test_delegate_parallel.py — G6 regression tests (2026-05-02).

The G6 audit row claimed `delegate_parallel` was a stub. Reading the
code at agents/generalist.py:1236 shows it's a full implementation:
ThreadPoolExecutor with bounded workers, error per sub-task is captured,
synthesis routes through ask_critical with ask_deep fallback, and the
whole call is wrapped in the orchestrator (Asimov + Ze-verify).

This file just locks in that behaviour so a future refactor can't
silently degrade it into the stub the audit feared.
"""
from __future__ import annotations

import json
import re

import pytest


def _strip_ze_header(text: str) -> str:
    """Orchestrator prepends a `[Ze] …\\n\\n` header. Strip it for parsing."""
    return re.sub(r"^\[Ze\][^\n]*\n+", "", text, count=1)


@pytest.fixture
def isolated_run(monkeypatch):
    """Replace `generalist.run` with a deterministic stub so the test
    doesn't actually hit any LLM."""
    import agents.generalist as g

    def fake_run(task: str, *, max_iters: int = 6, **_kw):
        # Each task echoes its name + the iter cap so we can verify
        # propagation through the parallel dispatcher.
        return {"answer": f"answered:{task}:{max_iters}"}

    monkeypatch.setattr(g, "run", fake_run)
    return g


@pytest.fixture
def isolated_synthesis(monkeypatch):
    """Replace ask_critical so the synthesis step is hermetic."""
    import llm
    monkeypatch.setattr(llm, "ask_critical",
                        lambda prompt, **kw: f"SYNTHESIZED:{len(prompt)}",
                        raising=False)
    return llm


# ── happy path ────────────────────────────────────────────────────


def test_returns_synthesised_text(isolated_run, isolated_synthesis):
    out = isolated_run._t_delegate_parallel(
        tasks=["one", "two", "three"], max_iters=4, synthesise=True)
    assert isinstance(out, str)
    assert "SYNTHESIZED:" in out


def test_returns_json_when_synthesise_false(isolated_run, isolated_synthesis):
    out = isolated_run._t_delegate_parallel(
        tasks=["a", "b"], max_iters=3, synthesise=False)
    rows = json.loads(_strip_ze_header(out))
    assert {r["task"] for r in rows} == {"a", "b"}
    assert all(r["answer"].startswith("answered:") for r in rows)


def test_propagates_max_iters_to_subruns(isolated_run, isolated_synthesis):
    out = isolated_run._t_delegate_parallel(
        tasks=["solo"], max_iters=11, synthesise=False)
    rows = json.loads(_strip_ze_header(out))
    assert rows[0]["answer"].endswith(":11")


# ── input validation ─────────────────────────────────────────────


def test_rejects_empty_list(isolated_run, isolated_synthesis):
    out = isolated_run._t_delegate_parallel(tasks=[])
    assert out.startswith("ERROR:INVALID_INPUT")


def test_rejects_non_list(isolated_run, isolated_synthesis):
    out = isolated_run._t_delegate_parallel(tasks="just one task")
    assert out.startswith("ERROR:INVALID_INPUT")


# ── error isolation ──────────────────────────────────────────────


def test_one_subtask_failure_does_not_kill_others(isolated_synthesis,
                                                  monkeypatch):
    """Only the failing sub-task gets a `[sub-task failed: …]` placeholder;
    the other answers still come through."""
    import agents.generalist as g

    def flaky(task: str, **_kw):
        if task == "boom":
            raise RuntimeError("nope")
        return {"answer": f"answered:{task}"}

    monkeypatch.setattr(g, "run", flaky)
    out = g._t_delegate_parallel(
        tasks=["boom", "ok"], max_iters=2, synthesise=False)
    rows = json.loads(_strip_ze_header(out))
    by_task = {r["task"]: r["answer"] for r in rows}
    assert "sub-task failed" in by_task["boom"]
    assert by_task["ok"] == "answered:ok"
