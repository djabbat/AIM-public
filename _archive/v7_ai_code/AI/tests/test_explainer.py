"""AI/tests/test_explainer.py — EX1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1\n", encoding="utf-8")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in (
        "AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
        "AI.ai.prompt_versions", "AI.ai.case_validator",
        "AI.ai.doctor", "AI.ai.health_score",
        "AI.ai.explainer",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── explain() basics ────────────────────────────────────────────


def test_explain_returns_recoveries(isolated):
    from AI.ai.explainer import explain
    e = explain()
    # Total/grade come straight from health_score
    assert isinstance(e.total, int)
    assert e.grade in {"A", "B", "C", "D", "F"}
    assert isinstance(e.recoveries, list)


def test_explain_lists_largest_loss_first(isolated):
    from AI.ai.explainer import explain
    e = explain()
    if len(e.recoveries) >= 2:
        assert e.recoveries[0].pts_lost >= e.recoveries[1].pts_lost


def test_explain_no_recoveries_when_perfect_score(isolated, monkeypatch):
    """If every component is at full, recoveries == []."""
    from AI.ai import health_score
    monkeypatch.setattr(health_score, "_wiring_component",
                         lambda: (health_score._W_WIRING, []))
    monkeypatch.setattr(health_score, "_regression_component",
                         lambda: (health_score._W_REGRESSION, []))
    monkeypatch.setattr(health_score, "_compliance_component",
                         lambda: (health_score._W_COMPLIANCE, []))
    monkeypatch.setattr(health_score, "_cases_component",
                         lambda: (health_score._W_CASES, []))
    monkeypatch.setattr(health_score, "_prompt_drift_component",
                         lambda: (health_score._W_PROMPT_DRIFT, []))
    from AI.ai.explainer import explain
    e = explain()
    assert e.total == 100
    assert e.recoveries == []


# ── _diagnose() per component ──────────────────────────────────


def test_diagnose_compliance_no_runs(isolated):
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("compliance", 10, 20)
    # default branch when no runs
    assert "no diagnostic runs" in why or "compliance" in why.lower()


def test_diagnose_compliance_low(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="D", n_refs=10, n_with_line=2)  # 20% comp
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("compliance", 0, 20)
    assert "20%" in why or "ignores" in why
    assert "tighten" in action.lower() or "stricter" in action.lower()


def test_diagnose_cases_invalid(isolated, tmp_path):
    cases = tmp_path / "cases"
    (cases / "broken.yaml").write_text("id: x\ntask: y\n")  # no rubrics
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.case_validator"])
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("cases", 0, 15)
    assert "invalid" in why
    assert "validate-cases" in action


def test_diagnose_regression_no_baseline(isolated):
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("regression", 12, 25)
    assert "baseline" in why.lower() or "regression" in why.lower()


def test_diagnose_prompt_no_fingerprint(isolated):
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("prompt_drift", 5, 10)
    # default = no history → "never fingerprinted"
    assert "fingerprint" in why.lower() or "drift" in why.lower()


def test_diagnose_unknown_component():
    from AI.ai.explainer import _diagnose
    why, action = _diagnose("nonsense_component", 0, 10)
    assert "unrecognised" in why.lower() or "unrecognized" in why.lower()


# ── summary ────────────────────────────────────────────────────


def test_summary_includes_total_and_grade(isolated):
    from AI.ai.explainer import summary
    s = summary()
    assert "/100" in s
    assert "grade" in s


def test_summary_calm_at_full_score(isolated, monkeypatch):
    from AI.ai import health_score
    monkeypatch.setattr(health_score, "_wiring_component",
                         lambda: (health_score._W_WIRING, []))
    monkeypatch.setattr(health_score, "_regression_component",
                         lambda: (health_score._W_REGRESSION, []))
    monkeypatch.setattr(health_score, "_compliance_component",
                         lambda: (health_score._W_COMPLIANCE, []))
    monkeypatch.setattr(health_score, "_cases_component",
                         lambda: (health_score._W_CASES, []))
    monkeypatch.setattr(health_score, "_prompt_drift_component",
                         lambda: (health_score._W_PROMPT_DRIFT, []))
    from AI.ai.explainer import summary
    s = summary()
    assert "nothing to fix" in s


def test_summary_lists_actions(isolated):
    """When score is sub-100, summary should include `action:` lines."""
    from AI.ai.explainer import summary
    s = summary()
    if "/100" in s and "100/100" not in s:
        assert "action:" in s.lower() or "nothing to fix" in s
