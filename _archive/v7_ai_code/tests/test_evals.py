"""tests/test_evals.py — S1 eval harness (2026-05-02)."""
from __future__ import annotations

import json
import textwrap

import pytest

from agents import evals as ev


@pytest.fixture
def isolated_eval_env(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "eval.db"))
    return tmp_path


def write_case(setup, name, body):
    (setup / "cases" / f"{name}.yaml").write_text(textwrap.dedent(body),
                                                   encoding="utf-8")


# ── individual rubric scoring ────────────────────────────────────────


def test_score_regex_match_and_miss():
    s, _ = ev.score_case("answer is 42",
                          {"regex": r"\bis 42\b"})
    assert s == 1.0
    s, _ = ev.score_case("answer is 41",
                          {"regex": r"\bis 42\b"})
    assert s == 0.0


def test_score_contains_all():
    s, per = ev.score_case("Inferior STEMI, route to PCI immediately.",
                            {"contains_all": ["STEMI", "PCI"]})
    assert s == 1.0
    assert per["contains_all"] == 1.0


def test_score_contains_all_partial():
    s, _ = ev.score_case("STEMI confirmed.",
                          {"contains_all": ["STEMI", "PCI"]})
    assert s == 0.5


def test_score_forbids():
    s, _ = ev.score_case("As an AI I cannot help",
                          {"forbids": ["as an AI"]})
    assert s == 0.0
    s, _ = ev.score_case("Sure, here's the diagnosis.",
                          {"forbids": ["as an AI"]})
    assert s == 1.0


def test_score_json_keys():
    s, _ = ev.score_case('{"name": "Alice", "age": 30}',
                          {"json_keys": ["name", "age"]})
    assert s == 1.0
    s, _ = ev.score_case('{"name": "Alice"}',
                          {"json_keys": ["name", "age"]})
    assert s == 0.5
    s, _ = ev.score_case('not json',
                          {"json_keys": ["name"]})
    assert s == 0.0


def test_score_json_keys_dot_path():
    s, _ = ev.score_case('{"a": {"b": {"c": 1}}}',
                          {"json_keys": ["a.b.c"]})
    assert s == 1.0


def test_score_min_max_length():
    s, _ = ev.score_case("hi", {"min_length": 10})
    assert s == 0.0
    s, _ = ev.score_case("hi" * 20, {"min_length": 10})
    assert s == 1.0
    s, _ = ev.score_case("x" * 100, {"max_length": 50})
    assert s == 0.0


def test_score_combines_rubrics_average():
    # 2/2 contains_all (1.0) + forbids passes (1.0) → 1.0
    s, per = ev.score_case("STEMI inferior PCI now",
                            {"contains_all": ["STEMI", "PCI"],
                             "forbids": ["AI"]})
    assert s == 1.0
    # 1/2 contains_all (0.5) + forbids passes (1.0) → 0.75
    s, _ = ev.score_case("STEMI",
                          {"contains_all": ["STEMI", "PCI"],
                           "forbids": ["AI"]})
    assert s == pytest.approx(0.75)


def test_score_unknown_rubric_ignored():
    s, _ = ev.score_case("anything", {"made_up_rubric": True})
    assert s == 1.0  # no rubrics applied → perfect by default


# ── case loading ────────────────────────────────────────────────────


def test_load_cases_skips_invalid(isolated_eval_env):
    write_case(isolated_eval_env, "good", """
        id: good
        task: do thing
        rubrics:
          min_length: 1
    """)
    write_case(isolated_eval_env, "bad", "- not a mapping\n")
    cases = ev.load_cases()
    ids = {c.id for c in cases}
    assert ids == {"good"}


def test_load_cases_returns_canonical_fields(isolated_eval_env):
    write_case(isolated_eval_env, "x", """
        id: x
        task: foo
        tags: [a, b]
        weight: 1.5
        rubrics:
          contains_any: ["foo"]
    """)
    [c] = ev.load_cases()
    assert c.id == "x"
    assert c.task == "foo"
    assert c.tags == ["a", "b"]
    assert c.weight == 1.5


# ── runner & DB ─────────────────────────────────────────────────────


def test_run_case_records_latency_and_score(isolated_eval_env):
    case = ev.EvalCase(id="t", task="hello",
                       rubrics={"contains_any": ["hi", "hello"]})
    r = ev.run_case(case, lambda task: f"hello, {task}")
    assert r.score == 1.0
    assert r.latency_ms >= 0
    assert r.error is None


def test_run_case_captures_exception(isolated_eval_env):
    case = ev.EvalCase(id="t", task="hi", rubrics={"min_length": 1})

    def boom(_t):
        raise RuntimeError("nope")

    r = ev.run_case(case, boom)
    assert r.score == 0.0
    assert "RuntimeError" in (r.error or "")


def test_run_all_persists_to_db(isolated_eval_env):
    write_case(isolated_eval_env, "c1", """
        id: c1
        task: greet
        rubrics:
          contains_any: ["hi", "hello"]
    """)
    write_case(isolated_eval_env, "c2", """
        id: c2
        task: numbers
        rubrics:
          regex: "\\\\d+"
    """)
    run = ev.run_all(lambda t: "hello, " + t + " 42",
                     version="v0", persist_results=True)
    assert run.aggregate_score == 1.0
    score = ev.latest_score("v0")
    assert score == pytest.approx(1.0)


def test_compare_versions(isolated_eval_env):
    write_case(isolated_eval_env, "c", """
        id: c
        task: greet
        rubrics:
          contains_any: ["hi", "hello"]
    """)
    ev.run_all(lambda t: "hello", version="v0", persist_results=True)
    ev.run_all(lambda t: "what?", version="v1", persist_results=True)
    cmp = ev.compare("v0", "v1")
    assert cmp["a"] == 1.0
    assert cmp["b"] == 0.0
    assert cmp["delta"] < 0
    assert cmp["verdict"] == "regressed"


def test_compare_neutral_when_close(isolated_eval_env):
    write_case(isolated_eval_env, "c", "id: c\ntask: greet\nrubrics: {min_length: 1}\n")
    ev.run_all(lambda t: "x", version="v0", persist_results=True)
    ev.run_all(lambda t: "x", version="v1", persist_results=True)
    cmp = ev.compare("v0", "v1")
    assert cmp["verdict"] == "neutral"


def test_run_all_filter_by_tag(isolated_eval_env):
    write_case(isolated_eval_env, "tagged", """
        id: tagged
        task: x
        tags: [keep]
        rubrics: {min_length: 0}
    """)
    write_case(isolated_eval_env, "untagged", """
        id: untagged
        task: x
        rubrics: {min_length: 0}
    """)
    run = ev.run_all(lambda _: "anything", version="v",
                     tag_filter="keep", persist_results=False)
    ids = {c.case_id for c in run.cases}
    assert ids == {"tagged"}


def test_latest_score_unknown_version_is_none(isolated_eval_env):
    assert ev.latest_score("never-ran") is None


# ── shipped builtin cases load cleanly ─────────────────────────────


def test_shipped_cases_parse(monkeypatch, tmp_path):
    """Spot-check that the YAMLs in tests/evals/cases/ load without errors.
    Doesn't run them — just validates the fixture set is well-formed."""
    monkeypatch.delenv("AIM_EVAL_CASES_DIR", raising=False)
    cases = ev.load_cases()
    assert len(cases) >= 1
    for c in cases:
        assert c.id and c.task
        # rubrics dict is optional; if present, must have known keys.
        for rubric in c.rubrics:
            assert rubric in ev._RUBRIC_FNS, f"unknown rubric in {c.id}: {rubric}"
