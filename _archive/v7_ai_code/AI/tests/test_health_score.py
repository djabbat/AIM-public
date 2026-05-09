"""AI/tests/test_health_score.py — HS1 (2026-05-04)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1 prompt\n", encoding="utf-8")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in (
        "AI.ai.diagnostic_ledger",
        "AI.ai.regression_detector",
        "AI.ai.prompt_versions",
        "AI.ai.case_validator",
        "AI.ai.doctor",
        "AI.ai.health_score",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── Score grade thresholds ──────────────────────────────────────


def test_grade_thresholds():
    from AI.ai.health_score import Score
    assert Score(total=95, components={}, notes=[]).grade == "A"
    assert Score(total=80, components={}, notes=[]).grade == "B"
    assert Score(total=65, components={}, notes=[]).grade == "C"
    assert Score(total=45, components={}, notes=[]).grade == "D"
    assert Score(total=20, components={}, notes=[]).grade == "F"


def test_total_is_sum_of_components():
    from AI.ai.health_score import Score
    s = Score(total=42, components={"a": 30, "b": 12}, notes=[])
    assert s.components["a"] + s.components["b"] == s.total


# ── individual components ───────────────────────────────────────


def test_wiring_full_when_doctor_clean(isolated):
    from AI.ai.health_score import _wiring_component, _W_WIRING
    pts, _ = _wiring_component()
    # On real repo all crit-probes should be clean → at minimum we
    # shouldn't be at zero.
    assert pts >= _W_WIRING - 5  # at most 1 warn (api_key) deducts 5


def test_compliance_no_runs(isolated):
    from AI.ai.health_score import _compliance_component, _W_COMPLIANCE
    pts, notes = _compliance_component()
    assert pts == _W_COMPLIANCE // 2
    assert any("no diagnostic runs" in n for n in notes)


def test_compliance_high(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=10, n_with_line=10, crit=0)
    from AI.ai.health_score import _compliance_component, _W_COMPLIANCE
    pts, _ = _compliance_component()
    assert pts == _W_COMPLIANCE


def test_compliance_low(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="D", n_refs=10, n_with_line=4, crit=2)  # 40%
    from AI.ai.health_score import _compliance_component
    pts, notes = _compliance_component()
    assert pts > 0
    assert any("avg compliance" in n for n in notes)


def test_compliance_zero_when_critical_low(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="F", n_refs=10, n_with_line=0, crit=5)
    from AI.ai.health_score import _compliance_component
    pts, notes = _compliance_component()
    assert pts == 0


def test_regression_no_baseline_half(isolated):
    from AI.ai.health_score import _regression_component, _W_REGRESSION
    pts, _ = _regression_component()
    assert pts == _W_REGRESSION // 2


def test_regression_zero_when_regressed(isolated, tmp_path):
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1` and `agents/new.py:42`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="C", n_refs=2, n_with_line=2, crit=1,
           report_path=str(p2), ts="2026-05-04T10:00:00")
    from AI.ai.health_score import _regression_component
    pts, notes = _regression_component()
    assert pts == 0
    assert any("REGRESSED" in n for n in notes)


def test_cases_full_when_no_cases(isolated):
    from AI.ai.health_score import _cases_component, _W_CASES
    pts, _ = _cases_component()
    assert pts == _W_CASES


def test_cases_partial_when_some_invalid(isolated, tmp_path):
    cases = tmp_path / "cases"
    (cases / "good.yaml").write_text(
        "id: c\ntask: x\nrubrics:\n  min_length: 1\n")
    (cases / "bad.yaml").write_text("id: c\n")  # missing task + rubrics
    from AI.ai.health_score import _cases_component, _W_CASES
    pts, notes = _cases_component()
    assert 0 < pts < _W_CASES
    assert any("invalid" in n for n in notes)


def test_prompt_drift_no_history(isolated):
    from AI.ai.health_score import _prompt_drift_component, _W_PROMPT_DRIFT
    pts, notes = _prompt_drift_component()
    assert pts == _W_PROMPT_DRIFT // 2
    assert any("never fingerprinted" in n for n in notes)


def test_prompt_drift_changed_after_record(isolated, tmp_path):
    from AI.ai.prompt_versions import record_current
    record_current(ts="2026-05-04T10:00:00")
    # Modify the prompt
    (tmp_path / "PROMPT.md").write_text("v2 totally different",
                                          encoding="utf-8")
    from AI.ai.health_score import _prompt_drift_component, _W_PROMPT_DRIFT
    pts, notes = _prompt_drift_component()
    assert pts == _W_PROMPT_DRIFT // 2
    assert any("drifted" in n for n in notes)


def test_prompt_drift_unchanged_full(isolated):
    from AI.ai.prompt_versions import record_current
    record_current()
    from AI.ai.health_score import _prompt_drift_component, _W_PROMPT_DRIFT
    pts, _ = _prompt_drift_component()
    assert pts == _W_PROMPT_DRIFT


# ── score() composition ─────────────────────────────────────────


def test_score_total_in_range(isolated):
    from AI.ai.health_score import score
    s = score()
    assert 0 <= s.total <= 100
    assert s.components   # dict non-empty


def test_score_components_match_keys(isolated):
    from AI.ai.health_score import score
    s = score()
    for key in ("wiring", "regression", "compliance", "cases",
                "prompt_drift"):
        assert key in s.components


def test_score_components_sum_to_total(isolated):
    from AI.ai.health_score import score
    s = score()
    assert sum(s.components.values()) == s.total


# ── summary ─────────────────────────────────────────────────────


def test_summary_includes_grade(isolated):
    from AI.ai.health_score import summary
    s = summary()
    assert "AIM/AI health" in s
    assert "/100" in s
    assert "grade" in s


def test_summary_lists_components(isolated):
    from AI.ai.health_score import summary
    s = summary()
    assert "wiring" in s
    assert "compliance" in s
    assert "regression" in s
    assert "cases" in s
    assert "prompt_drift" in s


# ── persistence ─────────────────────────────────────────────────


def test_record_persists(isolated):
    from AI.ai.health_score import record, history
    s = record(ts="2026-05-04T10:00:00")
    h = history()
    assert len(h) == 1
    assert h[0]["ts"] == "2026-05-04T10:00:00"
    assert h[0]["total"] == s.total
    assert h[0]["grade"] == s.grade


def test_history_returns_oldest_first(isolated):
    from AI.ai.health_score import record, history
    record(ts="2026-05-04T10:00:00")
    record(ts="2026-05-04T11:00:00")
    record(ts="2026-05-04T12:00:00")
    h = history(limit=10)
    timestamps = [r["ts"] for r in h]
    assert timestamps == sorted(timestamps)


def test_history_respects_limit(isolated):
    from AI.ai.health_score import record, history
    for i in range(15):
        record(ts=f"2026-05-04T{i:02d}:00:00")
    h = history(limit=5)
    assert len(h) == 5


def test_trend_empty(isolated):
    from AI.ai.health_score import trend
    assert trend() == {"n": 0}


def test_trend_calculates_delta(isolated):
    from AI.ai.health_score import record, trend
    record(ts="2026-05-04T10:00:00")
    record(ts="2026-05-04T11:00:00")
    t = trend()
    assert t["n"] == 2
    assert "delta" in t
    assert t["min"] <= t["max"]


def test_trend_handles_single_row(isolated):
    from AI.ai.health_score import record, trend
    record(ts="2026-05-04T10:00:00")
    t = trend()
    assert t["n"] == 1
    assert t["delta"] == 0   # first == last
    assert t["first_ts"] == t["last_ts"]


# ── info_line ───────────────────────────────────────────────────


def test_info_line_format(isolated):
    from AI.ai.health_score import info_line
    line = info_line()
    assert line.startswith("AIM/AI: ")
    assert "/100" in line
    assert "wir=" in line
    assert "reg=" in line
    assert "comp=" in line
    assert "cases=" in line
    assert "pd=" in line
    # exactly one line
    assert "\n" not in line


def test_info_line_components_match_score(isolated):
    from AI.ai.health_score import info_line, score
    s = score()
    line = info_line()
    assert f"{s.total}/100" in line
    assert f"wir={s.components['wiring']}" in line
