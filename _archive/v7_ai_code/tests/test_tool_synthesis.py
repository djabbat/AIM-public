"""tests/test_tool_synthesis.py — S2 (2026-05-02)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SYNTH_TOOLS_DIR", str(tmp_path / "synth"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib
    import agents.tool_synthesis as ts
    importlib.reload(ts)
    return ts


# ── name sanitisation ────────────────────────────────────────────


def test_safe_name_basic(isolated):
    assert isolated._safe_name("read_file", "edit_file") == "read_file_then_edit_file"


def test_safe_name_strips_specials(isolated):
    assert isolated._safe_name("foo-bar!", "baz/qux") == "foo_bar_then_baz_qux"


def test_safe_name_empty(isolated):
    assert isolated._safe_name("", "x") == ""
    assert isolated._safe_name("x", "") == ""


# ── candidate generation via pattern_miner ───────────────────────


def test_candidates_filters_min_support(isolated, monkeypatch):
    from agents import pattern_miner as pm
    fake = [
        pm.Finding(kind="sequential_pair",
                   summary="ok",
                   support=10,
                   sample={"a": "read_file", "b": "edit_file"}),
        pm.Finding(kind="sequential_pair",
                   summary="too rare",
                   support=2,
                   sample={"a": "x", "b": "y"}),
        pm.Finding(kind="slow_tool",
                   summary="not a pair",
                   support=99,
                   sample={"name": "fat"}),
    ]
    monkeypatch.setattr(pm, "mine", lambda window_days=14: fake)
    cands = isolated.candidates(min_support=3)
    assert [c.name for c in cands] == ["read_file_then_edit_file"]


def test_candidates_skips_invalid_names(isolated, monkeypatch):
    from agents import pattern_miner as pm
    fake = [pm.Finding(kind="sequential_pair", summary="weird",
                       support=5, sample={"a": "", "b": ""})]
    monkeypatch.setattr(pm, "mine", lambda window_days=14: fake)
    assert isolated.candidates() == []


# ── code rendering ────────────────────────────────────────────────


def test_render_code_contains_tool_names(isolated):
    cand = isolated.SynthesisCandidate(
        name="read_then_edit", tool_a="read_file", tool_b="edit_file",
        support=4, description="…",
    )
    code = isolated.render_code(cand)
    assert "def read_then_edit" in code
    assert "'read_file'" in code
    assert "'edit_file'" in code
    # Must compile cleanly.
    compile(code, "<test>", "exec")


def test_render_code_executable_with_stub(isolated):
    cand = isolated.SynthesisCandidate(
        name="a_then_b", tool_a="A", tool_b="B", support=3,
    )
    code = isolated.render_code(cand)
    ns: dict = {}
    exec(code, ns)
    fn = ns["a_then_b"]

    class Stub:
        def call(self, name, args):
            return f"OK_{name}"
    out = fn({}, {}, registry=Stub())
    assert out == {"a": "OK_A", "b": "OK_B", "ok": True}


def test_render_code_detects_failure_in_inner_call(isolated):
    cand = isolated.SynthesisCandidate(
        name="fail_then_ok", tool_a="X", tool_b="Y", support=3,
    )
    code = isolated.render_code(cand)
    ns: dict = {}
    exec(code, ns)

    class Stub:
        def call(self, name, args):
            return "ERROR:NETWORK:timeout" if name == "X" else "OK"

    out = ns["fail_then_ok"]({}, {}, registry=Stub())
    assert out["ok"] is False


# ── propose / register lifecycle ─────────────────────────────────


def test_propose_default_fixture_passes(isolated):
    cand = isolated.SynthesisCandidate(
        name="r_then_e", tool_a="read_file", tool_b="edit_file", support=4,
    )
    res = isolated.propose(cand, repeats=5)
    assert res.passed is True
    assert len(res.fixture_results) == 5
    assert all(r["ok"] for r in res.fixture_results)


def test_propose_custom_fixture(isolated):
    cand = isolated.SynthesisCandidate(name="x", tool_a="A", tool_b="B", support=3)

    def fixture():
        return ({"p": 1}, {"p": 2},
                {"A": "OK_A", "B": "ERROR:X:nope"})

    res = isolated.propose(cand, fixture=fixture, repeats=3)
    assert res.passed is False
    assert res.error == "fixture not all-pass"


def test_register_writes_file(isolated):
    cand = isolated.SynthesisCandidate(name="r", tool_a="a", tool_b="b", support=4)
    res = isolated.propose(cand, repeats=3)
    assert res.passed
    path = isolated.register(res)
    assert path.exists()
    assert "def r" in path.read_text()


def test_register_refuses_failing(isolated):
    cand = isolated.SynthesisCandidate(name="r", tool_a="a", tool_b="b", support=4)
    res = isolated.SynthesisResult(candidate=cand, code="", passed=False,
                                    fixture_results=[], error="bad")
    with pytest.raises(ValueError):
        isolated.register(res)


def test_list_registered_and_remove(isolated):
    cand = isolated.SynthesisCandidate(name="t1", tool_a="a", tool_b="b", support=4)
    isolated.register(isolated.propose(cand, repeats=2))
    assert "t1" in isolated.list_registered()
    assert isolated.remove("t1") is True
    assert "t1" not in isolated.list_registered()


def test_audit_records_register_and_unregister(isolated):
    cand = isolated.SynthesisCandidate(name="t2", tool_a="a", tool_b="b", support=4)
    isolated.register(isolated.propose(cand, repeats=2))
    isolated.remove("t2")
    h = isolated.history()
    events = [r["event"] for r in h]
    assert "register" in events
    assert "unregister" in events
