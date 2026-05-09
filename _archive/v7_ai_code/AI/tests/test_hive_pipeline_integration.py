"""AI/tests/test_hive_pipeline_integration.py — HIVE end-to-end (2026-05-04).

End-to-end smoke of HV1 (worker telemetry) → HV2 (queen aggregator)
→ HV3 (worker consumer) → HV4 (skill standard adapter).

Walks the full federation cycle with stubbed transport (in-process).
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def hive(tmp_path, monkeypatch):
    """Set up paths for both 2 workers + 1 queen, all in tmp_path."""
    # Queen state
    monkeypatch.setenv("AIM_HIVE_QUEEN_DB", str(tmp_path / "queen.db"))
    # Worker A state (we'll switch envs as we simulate each worker)
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "wa_dl.db"))
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(tmp_path / "PROMPT.md"))
    (tmp_path / "PROMPT.md").write_text("v1 prompt\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("AIM_HIVE_STATE_DB",
                        str(tmp_path / "wa_hive_state.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "wa_cases"))
    (tmp_path / "wa_cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.prompt_versions",
              "AI.ai.reflexion_cluster", "AI.ai.finding_suppressions",
              "AI.ai.hive_telemetry", "AI.ai.hive_queen",
              "AI.ai.hive_consumer", "AI.ai.skill_standard"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── HV1 → HV2: worker contributes, queen accepts ───────────────


def test_full_federation_one_worker(hive):
    """Single worker contribution flows through queen with no
    candidates yet (need ≥2 workers for cross-pattern detection)."""
    from AI.ai.hive_telemetry import contribution
    from AI.ai.hive_queen import (
        accept_contribution, list_contributions, distill_candidates,
    )

    payload = contribution()
    cid = accept_contribution(payload)
    assert cid

    rows = list_contributions()
    assert len(rows) == 1
    # No cross-worker patterns yet
    assert distill_candidates() == []


def test_full_federation_consumer_installs_skill(hive):
    """Queen publishes a skill update → consumer-side apply() writes
    it to ~/.aim/skills/."""
    from AI.ai.hive_queen import Candidate, publish_update
    from AI.ai.hive_consumer import Update as ConsumerUpdate, apply
    qcand = Candidate(
        kind="skill",
        body={"skill_id": "auto-test-1", "theme": ["a", "b"],
              "rationale": "auto from 2 workers"},
        source_workers={"wa", "wb"},
        rationale="theme cluster",
    )
    qupd = publish_update(qcand, eval_pass=True, eval_delta=0.07)

    # Convert queen Update -> consumer Update (same fields)
    cupd = ConsumerUpdate(
        id=qupd.id, ts=qupd.ts, kind=qupd.kind, body=qupd.body,
        source_n=qupd.source_n, eval_delta=qupd.eval_delta,
        signature=qupd.signature,
    )
    res = apply(cupd)
    assert res.installed is True
    skill_path = hive / "home" / ".aim" / "skills" / "auto-test-1.json"
    assert skill_path.exists()


def test_full_federation_eval_case_distribution(hive):
    """Queen publishes an eval_case update → consumer writes yaml to
    AIM_EVAL_CASES_DIR."""
    from AI.ai.hive_queen import Candidate, publish_update
    from AI.ai.hive_consumer import Update, apply
    qupd = publish_update(
        Candidate(kind="eval_case",
                    body={"id": "regr-distilled-1",
                          "task": "verify thing",
                          "rubrics": {"min_length": 50}},
                    source_workers={"wa", "wb"},
                    rationale="test"),
        eval_pass=True, eval_delta=0.05,
    )
    cupd = Update(id=qupd.id, ts=qupd.ts, kind=qupd.kind,
                   body=qupd.body, source_n=qupd.source_n,
                   eval_delta=qupd.eval_delta, signature=qupd.signature)
    res = apply(cupd)
    assert res.installed is True
    yaml_path = hive / "wa_cases" / "regr-distilled-1.yaml"
    assert yaml_path.exists()


def test_full_federation_l_consent_blocks_install(hive):
    """User opts out of skill kind → apply rejects."""
    from AI.ai.hive_consumer import opt_out, apply, Update
    opt_out("skill")
    upd = Update(id="x", ts="2026-05-04", kind="skill",
                  body={"skill_id": "y"}, source_n=2,
                  eval_delta=0.1, signature="abcdef123456")
    res = apply(upd)
    assert res.installed is False
    assert "L_CONSENT" in res.skipped_reason


def test_full_federation_skill_standard_export_import_loop(hive, tmp_path):
    """A queen-distilled skill exported via HV4 to agentskills format
    can be re-imported back to AIM format losslessly."""
    from AI.ai.hive_queen import Candidate, publish_update
    from AI.ai.skill_standard import to_agentskills, from_agentskills
    qupd = publish_update(
        Candidate(kind="skill",
                    body={"skill_id": "rt-skill",
                          "theme": ["alpha", "beta"],
                          "rationale": "round trip test"},
                    source_workers={"wa", "wb"},
                    rationale="rt"),
        eval_pass=True, eval_delta=0.05,
    )
    ext = to_agentskills(qupd.body)
    re_aim = from_agentskills(ext)
    assert re_aim["skill_id"] == "rt-skill"
    assert re_aim["theme"] == ["alpha", "beta"]


