"""tests/test_patient_as_project_phase7.py
End-to-end test for Phase 7 (Patient-as-Project cornerstone, 2026-05-07):

    pam_tracker  ↔  L_AGENCY  ↔  codesign_log  ↔  automation_bias_detector

The test simulates one full clinical loop:
1. Patient is administered PAM-13 (level 4 — highly activated)
2. Agent proposes a treatment → L_AGENCY blocks (no co-design)
3. Patient agrees via codesign_log → L_AGENCY passes
4. Disagreement classifier returns the right zone for AI/clinician confidence
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def setup_patients_dir(tmp_path, monkeypatch):
    pdir = tmp_path / "Patients"
    pdir.mkdir()
    monkeypatch.setenv("AIM_PATIENTS_DIR", str(pdir))
    return pdir


def test_full_codesign_flow(tmp_path, monkeypatch):
    pdir = setup_patients_dir(tmp_path, monkeypatch)

    pid = "TEST_FlowPatient_2000_01_01"
    (pdir / pid).mkdir()

    from agents import pam_tracker, codesign_log
    from agents.kernel import Decision, evaluate_l_agency

    # 1. Highly activated patient (raw 50 → 94.9 → level 4).
    s = pam_tracker.record_administration(pid, [4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 3, 3, 4])
    assert s.level == 4
    assert pam_tracker.current_activation_level(pid) == 4

    # 2. Treatment without co-design → L_AGENCY blocks.
    d = Decision(
        id="rx-001",
        action_type="treatment",
        payload={"drug": "lisinopril 5mg"},
        description="start ACEi",
    )
    patient_dict = {"activation_level": pam_tracker.current_activation_level(pid)}
    ok, reason = evaluate_l_agency(d, patient_dict, {})
    assert not ok
    assert "co-design" in reason

    # 3. Patient agrees → log + retry. L_AGENCY now passes.
    codesign_log.record(pid, "agreed", "ACEi for HTN", decision_id="rx-001")
    assert codesign_log.mark_codesigned(pid, "rx-001")
    context = {"patient_codesigned": codesign_log.mark_codesigned(pid, "rx-001")}
    ok2, reason2 = evaluate_l_agency(d, patient_dict, context)
    assert ok2
    assert "co-designed" in reason2


def test_pam_delta_classification(tmp_path, monkeypatch):
    pdir = setup_patients_dir(tmp_path, monkeypatch)
    pid = "TEST_Delta_2000_01_01"
    (pdir / pid).mkdir()

    from agents import pam_tracker

    # First administration: raw 28 → 38.5 → level 1.
    pam_tracker.record_administration(pid, [2, 2, 2, 2, 2, 2, 3, 3, 3, 2, 2, 2, 1])
    # Six months later: raw 33 → 51.3 → level 2 (Δ ≈ 12.8 → individually significant).
    pam_tracker.record_administration(pid, [3, 3, 3, 2, 3, 3, 3, 2, 2, 3, 3, 2, 1])

    delta, label = pam_tracker.latest_delta(pid)
    assert delta is not None and delta > 0
    assert label == "individually_significant"


def test_disagreement_classification_zones():
    from agents.automation_bias_detector import classify

    aligned = classify(0.95, 0.90, agree=True)
    assert aligned.zone == "aligned"
    assert aligned.ui_action == "auto_execute"

    conflict = classify(0.95, 0.90, agree=False)
    assert conflict.zone == "conflict_high_stakes"
    assert conflict.ui_action == "force_mdt_review"

    ai_leads = classify(0.95, 0.40, agree=True)
    assert ai_leads.zone == "ai_leads"
    assert ai_leads.ui_action == "show_evidence_confirm"

    clin_leads = classify(0.30, 0.90, agree=False)
    assert clin_leads.zone == "clinician_leads"

    escalate = classify(0.40, 0.50, agree=False)
    assert escalate.zone == "escalate"


def test_disagreement_rejects_out_of_range():
    import pytest
    from agents.automation_bias_detector import classify

    with pytest.raises(ValueError):
        classify(1.5, 0.5, agree=True)
    with pytest.raises(ValueError):
        classify(0.5, -0.1, agree=True)


def test_pam_tracker_parity_with_rust_binary(tmp_path, monkeypatch):
    """Score via Python and via the aim-pam Rust binary; compare."""
    setup_patients_dir(tmp_path, monkeypatch)
    from agents import pam_tracker

    bin_path = ROOT / "rust-core" / "target" / "release" / "aim-pam"
    if not bin_path.exists():
        # binary not built; skip rather than fail (CI may not build Rust)
        import pytest
        pytest.skip("aim-pam binary not built")

    responses = [3, 4, 3, 2, 3, 4, 3, 3, 2, 3, 3, 4, 3]
    py = pam_tracker.score_responses(responses)
    rs = pam_tracker.via_rust_binary(responses)
    assert py.raw_sum == rs.raw_sum
    assert py.level == rs.level
    # Rust binary prints score with 1-decimal precision; allow rounding.
    assert abs(py.score - rs.score) < 0.1


def test_codesign_log_filters_and_kinds(tmp_path, monkeypatch):
    pdir = setup_patients_dir(tmp_path, monkeypatch)
    pid = "TEST_Filter_2000_01_01"
    (pdir / pid).mkdir()

    from agents import codesign_log

    codesign_log.record(pid, "consulted", "annual review", decision_id="d1")
    codesign_log.record(pid, "modified", "halve dose", decision_id="d1")
    codesign_log.record(pid, "refused", "second-line drug", decision_id="d2")

    # mark_codesigned only true for agreed/modified
    assert codesign_log.mark_codesigned(pid, "d1")  # modified counts
    assert not codesign_log.mark_codesigned(pid, "d2")  # refused does not

    refused = codesign_log.filter_by_kind(pid, ["refused"])
    assert len(refused) == 1
    assert refused[0]["topic"] == "second-line drug"


def test_codesign_log_rejects_unknown_kind(tmp_path, monkeypatch):
    pdir = setup_patients_dir(tmp_path, monkeypatch)
    pid = "TEST_BadKind_2000_01_01"
    (pdir / pid).mkdir()

    import pytest
    from agents import codesign_log

    with pytest.raises(ValueError):
        codesign_log.record(pid, "ignored", "topic")
