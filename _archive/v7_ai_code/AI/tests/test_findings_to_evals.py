"""AI/tests/test_findings_to_evals.py — FE1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    import importlib, sys
    if "AI.ai.findings_to_evals" in sys.modules:
        importlib.reload(sys.modules["AI.ai.findings_to_evals"])
    return tmp_path


# ── case_from_finding ───────────────────────────────────────────


def test_case_from_finding_with_line():
    from AI.ai.findings_to_evals import case_from_finding
    spec = case_from_finding("AI/ai/distillation_tracker.py:42")
    assert spec is not None
    assert spec.id == "regr-ai-ai-distillation-tracker-py-l42"
    assert "AI/ai/distillation_tracker.py" in spec.task
    assert "line 42" in spec.task
    assert "AI/ai/distillation_tracker.py" in spec.rubrics["contains_all"]
    assert "42" in spec.rubrics["contains_all"]
    assert "regression" in spec.tags
    assert "ai-subproject" in spec.tags


def test_case_from_finding_no_line():
    from AI.ai.findings_to_evals import case_from_finding
    spec = case_from_finding("agents/x.py")
    assert spec is not None
    assert spec.id == "regr-agents-x-py"
    assert "line" not in spec.task   # no "at line N"
    assert "agents-runtime" in spec.tags


def test_case_from_finding_test_path():
    from AI.ai.findings_to_evals import case_from_finding
    spec = case_from_finding("tests/test_x.py:10")
    assert "test-gap" in spec.tags


def test_case_from_finding_invalid_ref():
    from AI.ai.findings_to_evals import case_from_finding
    assert case_from_finding("not-a-path") is None
    assert case_from_finding("https://example.com/x") is None
    assert case_from_finding("") is None


def test_case_from_finding_strips_dot_slash():
    from AI.ai.findings_to_evals import case_from_finding
    spec = case_from_finding("./agents/x.py:5")
    assert spec is not None
    assert spec.id.startswith("regr-agents-x-py")


def test_case_rubrics_have_minlen_and_forbids():
    from AI.ai.findings_to_evals import case_from_finding
    spec = case_from_finding("agents/x.py:1")
    assert spec.rubrics["min_length"] == 200
    assert "probably" in spec.rubrics["forbid_any"]


# ── generate_cases ──────────────────────────────────────────────


def test_generate_cases_skips_invalid():
    from AI.ai.findings_to_evals import generate_cases
    out = generate_cases([
        "agents/x.py:1",
        "not-a-path",
        "AI/ai/y.py:2",
    ])
    assert len(out) == 2
    ids = {s.id for s in out}
    assert "regr-agents-x-py-l1" in ids
    assert "regr-ai-ai-y-py-l2" in ids


def test_generate_cases_dedupes():
    from AI.ai.findings_to_evals import generate_cases
    out = generate_cases([
        "agents/x.py:1",
        "agents/x.py:1",        # exact duplicate
        "./agents/x.py:1",      # same after strip
    ])
    assert len(out) == 1


# ── write_cases ─────────────────────────────────────────────────


def test_write_cases_creates_yaml(isolated, tmp_path):
    from AI.ai.findings_to_evals import write_cases
    written = write_cases(["agents/x.py:1", "AI/ai/y.py:2"])
    assert len(written) == 2
    contents = "\n".join(p.read_text() for p in written)
    assert "id: regr-" in contents
    assert "task: |" in contents
    assert "rubrics:" in contents
    assert "tags:" in contents


def test_write_cases_skips_existing(isolated):
    from AI.ai.findings_to_evals import write_cases
    written1 = write_cases(["agents/x.py:1"])
    assert len(written1) == 1
    # second call same ref → no writes (idempotent)
    written2 = write_cases(["agents/x.py:1"])
    assert written2 == []


def test_write_cases_overwrite_flag(isolated):
    from AI.ai.findings_to_evals import write_cases
    write_cases(["agents/x.py:1"])
    written = write_cases(["agents/x.py:1"], overwrite=True)
    assert len(written) == 1


def test_write_cases_explicit_dest(tmp_path):
    from AI.ai.findings_to_evals import write_cases
    dest = tmp_path / "custom"
    written = write_cases(["agents/x.py:1"], dest=dest)
    assert len(written) == 1
    assert written[0].parent == dest


def test_write_cases_skips_invalid_refs(isolated):
    from AI.ai.findings_to_evals import write_cases
    written = write_cases(["bogus", "agents/y.py:9", "https://x"])
    assert len(written) == 1


def test_yaml_round_trip_compatible_with_evals_loader(isolated):
    """The emitted yaml must be loadable by the same path that
    `agents/evals.py` uses (PyYAML safe_load)."""
    import yaml
    from AI.ai.findings_to_evals import write_cases
    written = write_cases(["agents/foo.py:7"])
    assert written
    doc = yaml.safe_load(written[0].read_text())
    assert doc["id"] == "regr-agents-foo-py-l7"
    assert "agents/foo.py" in doc["task"]
    assert doc["rubrics"]["min_length"] == 200
    assert "regression" in doc["tags"]


# ── summary ─────────────────────────────────────────────────────


def test_summary_empty(isolated):
    from AI.ai.findings_to_evals import summary
    assert "no eval cases" in summary([])


def test_summary_renders(isolated):
    from AI.ai.findings_to_evals import summary
    s = summary(["agents/x.py:1", "AI/ai/y.py:2"])
    assert "Generated 2" in s


def test_summary_truncates_when_many(isolated):
    from AI.ai.findings_to_evals import summary
    refs = [f"agents/m{i}.py:{i}" for i in range(20)]
    s = summary(refs)
    assert "+5 more" in s or "(+5" in s
