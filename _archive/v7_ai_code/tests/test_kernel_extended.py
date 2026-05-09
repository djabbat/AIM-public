"""tests/test_kernel_extended.py — L_PRIVACY / L_CONSENT / L_VERIFIABILITY."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.kernel import (  # noqa: E402
    Decision, evaluate_extended, evaluate_l_agency, AGENCY_ACTIONS,
)


def _d(action_type: str, payload: dict | None = None) -> Decision:
    return Decision(id="t", description="test", action_type=action_type,
                    payload=payload or {})


def test_privacy_blocks_patient_path_in_email():
    d = _d("email_send", {"body": "see /home/oem/Desktop/AIM/Patients/X/AI_LOG.md"})
    res = evaluate_extended(d)
    assert not res.privacy
    assert not res.passed


def test_privacy_blocks_phone_in_external_call():
    d = _d("external_api_call_with_data", {"data": "patient phone +995 555 185 161"})
    res = evaluate_extended(d)
    assert not res.privacy


def test_privacy_passes_with_consent_flag():
    d = _d("email_send", {"body": "see /home/oem/Desktop/AIM/Patients/X/AI_LOG.md"})
    res = evaluate_extended(d, context={"privacy_consent": True})
    assert res.privacy


def test_consent_blocks_unconfirmed_email():
    d = _d("email_send", {"body": "Hello world"})
    res = evaluate_extended(d)
    assert not res.consent


def test_consent_passes_when_confirmed():
    d = _d("email_send", {"body": "Hello world"})
    res = evaluate_extended(d, context={"user_confirmed": True})
    assert res.consent


def test_consent_blocks_git_push_public_unconfirmed():
    d = _d("git_push_public", {"branch": "main"})
    res = evaluate_extended(d)
    assert not res.consent


def test_consent_no_op_for_non_public_actions():
    d = _d("read_file", {"path": "/tmp/x"})
    res = evaluate_extended(d)
    assert res.consent  # n/a


@pytest.mark.network
def test_verifiability_passes_with_real_pmid():
    d = _d("emit_text", {"text": "See PMID: 28425478."})
    res = evaluate_extended(d)
    assert res.verifiability


@pytest.mark.network
def test_verifiability_fails_with_fake_pmid():
    d = _d("emit_text", {"text": "See fabricated work PMID: 999999999."})
    res = evaluate_extended(d)
    assert not res.verifiability


def test_verifiability_no_op_when_no_citations():
    d = _d("emit_text", {"text": "A plain sentence with no PMID or DOI."})
    res = evaluate_extended(d)
    assert res.verifiability


# ── L_AGENCY (Patient as a Project, 2026-05-07) ────────────────────────────

def test_agency_na_for_non_agency_actions():
    d = _d("dx", {})
    ok, r = evaluate_l_agency(d, {"activation_level": 3}, {})
    assert ok and "n/a" in r


def test_agency_passes_when_codesigned():
    d = _d("treatment", {"drug": "lisinopril"})
    ok, r = evaluate_l_agency(d, {"activation_level": 3}, {"patient_codesigned": True})
    assert ok and "co-designed" in r


def test_agency_blocks_activated_patient_without_codesign():
    d = _d("lifestyle_directive", {"text": "walk 30 min"})
    ok, r = evaluate_l_agency(d, {"activation_level": 3}, {})
    assert not ok and "co-design" in r


def test_agency_passes_with_flag_for_disengaged_patient():
    d = _d("treatment", {})
    ok, r = evaluate_l_agency(d, {"activation_level": 1}, {})
    assert ok and "capacity-building" in r


def test_agency_passes_with_flag_for_unknown_activation():
    d = _d("regimen_change", {})
    ok, r = evaluate_l_agency(d, {}, {})
    assert ok and "capacity-building" in r


def test_agency_blocks_at_level_2_threshold():
    d = _d("behavior_change", {})
    ok, _ = evaluate_l_agency(d, {"activation_level": 2}, {})
    assert not ok


def test_extended_includes_agency_failure():
    d = _d("treatment", {"drug": "lisinopril"})
    res = evaluate_extended(d, patient={"activation_level": 4}, context={})
    assert not res.agency
    assert not res.passed
    assert len(res.reasons) == 4


def test_extended_passes_when_agency_codesigned():
    d = _d("treatment", {"drug": "lisinopril"})
    res = evaluate_extended(
        d,
        patient={"activation_level": 4},
        context={"patient_codesigned": True},
    )
    assert res.agency
    assert res.passed


def test_agency_actions_includes_expected_set():
    expected = {"treatment", "lifestyle_directive", "behavior_change",
                "regimen_change", "auto_action"}
    assert expected.issubset(AGENCY_ACTIONS)


# ── Fix #1 (2026-05-07): L_AGENCY must fire from decide(), not be dead ─────

def test_decide_blocks_treatment_for_activated_patient_without_codesign():
    """Regression for the audit gap that L_AGENCY was dead in production.
    decide() now calls evaluate_extended for every alternative; if a
    treatment is the only candidate and it fails L_AGENCY, decide() must
    raise KernelViolation rather than recommend it."""
    from agents.kernel import decide, KernelViolation

    treatment = Decision(id="rx-only", description="start ACEi",
                         action_type="treatment",
                         payload={"drug": "lisinopril 5mg"})

    patient = {
        "activation_level": 4,  # highly activated → L_AGENCY requires co-design
        "allergies": [],
        "medications": [],
        "red_flags": [],
        "primary_complaint_undiagnosed": False,
        "has_confirmed_dx": True,
    }
    import pytest
    with pytest.raises(KernelViolation) as exc:
        decide([treatment], patient, agent="test", patient_id="P_TEST")
    assert "L_AGENCY" in str(exc.value) or "agency" in str(exc.value).lower()


def test_decide_picks_alternative_when_one_fails_agency():
    """Treatment fails L_AGENCY → decide() falls back to the non-agency
    alternative (a `test` action that bypasses L_AGENCY)."""
    from agents.kernel import decide

    treatment = Decision(id="rx", description="treat",
                         action_type="treatment",
                         payload={"drug": "lisinopril 5mg"})
    test_action = Decision(id="tst", description="bp holter",
                           action_type="test",
                           payload={"name": "BP Holter"})

    patient = {
        "activation_level": 3,
        "allergies": [],
        "medications": [],
        "red_flags": [],
        "primary_complaint_undiagnosed": False,
        "has_confirmed_dx": True,
    }
    chosen = decide([treatment, test_action], patient, agent="test", patient_id="P_TEST")
    assert chosen.decision.id == "tst", f"Expected non-treatment, got {chosen.decision.id}"


def test_decide_passes_treatment_when_codesigned():
    """With patient_codesigned=True, L_AGENCY passes and decide() can
    select the treatment normally."""
    from agents.kernel import decide

    treatment = Decision(id="rx-only", description="treat",
                         action_type="treatment",
                         payload={"drug": "lisinopril 5mg"})

    patient = {
        "activation_level": 3,
        "allergies": [],
        "medications": [],
        "red_flags": [],
        "primary_complaint_undiagnosed": False,
        "has_confirmed_dx": True,
    }
    chosen = decide(
        [treatment], patient,
        context={"patient_codesigned": True},
        agent="test", patient_id="P_TEST",
    )
    assert chosen.decision.id == "rx-only"


def test_decide_passes_treatment_for_disengaged_patient():
    """Activation level 1 (disengaged) → L_AGENCY pass-with-flag → decide()
    can still recommend the treatment."""
    from agents.kernel import decide

    treatment = Decision(id="rx-low-activation", description="treat",
                         action_type="treatment",
                         payload={"drug": "lisinopril"})

    patient = {
        "activation_level": 1,
        "allergies": [],
        "medications": [],
        "red_flags": [],
        "primary_complaint_undiagnosed": False,
        "has_confirmed_dx": True,
    }
    chosen = decide(
        [treatment], patient,
        agent="test", patient_id="P_TEST",
    )
    assert chosen.decision.id == "rx-low-activation"


def test_scored_carries_extended_field():
    """After Fix #1, every Scored returned from decide() must carry the
    extended laws result for downstream auditing."""
    from agents.kernel import decide

    test_action = Decision(id="ecg", description="ECG",
                           action_type="test", payload={"name": "ECG"})
    patient = {
        "activation_level": 4,
        "allergies": [],
        "medications": [],
        "red_flags": [],
        "primary_complaint_undiagnosed": False,
        "has_confirmed_dx": True,
    }
    chosen = decide([test_action], patient, agent="test", patient_id="P_TEST")
    # Scored.extended exists and tracks all 4 extended laws.
    assert hasattr(chosen, "extended")
    assert chosen.extended is not None
    assert chosen.extended.passed
    assert chosen.extended.agency  # n/a → True for non-agency action
