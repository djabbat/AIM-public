"""tests/test_kernel_parity.py — side-by-side validator (HW1, 2026-05-07).

Calls BOTH Python `agents.kernel_legacy` (frozen authoritative reference)
AND Rust `aim_kernel` (PyO3) on the same fixtures, asserting equality.
Run any time post-port to catch regression in Rust impl that Python
would still reject correctly (or vice versa).

Usage:
    pytest tests/test_kernel_parity.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force-import legacy explicitly (bypassing shim's env-gated path):
import importlib
legacy = importlib.import_module("agents.kernel_legacy")
import aim_kernel as rust


# ── helpers ────────────────────────────────────────────────────────────────


def _decision_legacy(id, action_type, payload=None, description=""):
    """Create a Python kernel_legacy.Decision."""
    return legacy.Decision(
        id=id,
        description=description,
        action_type=action_type,
        payload=payload or {},
    )


def _decision_rust(id, action_type, payload=None, description=""):
    """Create a Rust aim_kernel.Decision."""
    return rust.Decision(
        id=id,
        description=description,
        action_type=action_type,
        payload=payload or {},
    )


# ── L0 parity ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action_type,payload,description",
    [
        ("dx", {"text": "common cold"}, "diagnose flu"),
        ("treatment", {"drug": "amoxicillin", "indication": "strep throat"}, ""),
        # Dangerous — both must reject
        ("dx", {}, "weapon design plan"),
        # Broad ABx for viral — both must reject
        ("treatment", {"drug": "vancomycin", "indication": "viral URI"}, ""),
        # Edge: forge_documents in payload
        ("dx", {"task": "forge_documents"}, ""),
    ],
)
def test_l0_parity(action_type, payload, description):
    legacy_d = _decision_legacy("d1", action_type, payload, description)
    rust_d = _decision_rust("d1", action_type, payload, description)
    py_ok, _ = legacy.evaluate_l0(legacy_d, {}, {})
    rs_ok, _ = rust.evaluate_l0(rust_d, {}, {})
    assert py_ok == rs_ok, (
        f"L0 divergence on {action_type=} {payload=}: py={py_ok} vs rust={rs_ok}"
    )


# ── L1 parity (allergy + interaction blocks) ───────────────────────────────


@pytest.mark.parametrize(
    "allergies,drug,interactions",
    [
        ([], "amoxicillin", []),
        (["penicillin"], "amoxicillin", []),  # both block
        (["sulfa rash"], "amoxicillin", []),
        ([], "warfarin", [{"severity": "major", "summary": "x+y"}]),  # interaction blocks
        ([], "warfarin", [{"severity": "minor", "summary": "x+y"}]),
    ],
)
def test_l1_allergy_and_interaction_parity(allergies, drug, interactions):
    payload = {"drug": drug, "interactions": interactions}
    legacy_d = _decision_legacy("d1", "treatment", payload)
    rust_d = _decision_rust("d1", "treatment", payload)
    patient = {"allergies": allergies}
    py_ok, _ = legacy.evaluate_l1(legacy_d, patient, {})
    rs_ok, _ = rust.evaluate_l1(rust_d, patient, {})
    assert py_ok == rs_ok, (
        f"L1 divergence on {allergies=} {drug=} {interactions=}: "
        f"py={py_ok} vs rust={rs_ok}"
    )


# ── evaluate_laws aggregate ─────────────────────────────────────────────────


def test_evaluate_laws_passing_decision():
    payload = {"drug": "amoxicillin", "indication": "strep throat"}
    legacy_d = _decision_legacy("d1", "treatment", payload)
    rust_d = _decision_rust("d1", "treatment", payload)
    py = legacy.evaluate_laws(legacy_d, {}, {})
    rs = rust.evaluate_laws(rust_d, {}, {})
    assert py.passed == rs.passed
    assert py.L0 == rs.L0
    assert py.L1 == rs.L1
    assert py.L2 == rs.L2
    assert py.L3 == rs.L3


def test_evaluate_laws_blocked_decision():
    legacy_d = _decision_legacy("d1", "dx", {"task": "weapon_design"})
    rust_d = _decision_rust("d1", "dx", {"task": "weapon_design"})
    py = legacy.evaluate_laws(legacy_d, {}, {})
    rs = rust.evaluate_laws(rust_d, {}, {})
    assert py.passed == rs.passed == False
    assert py.L0 == rs.L0 == False


# ── score_decision parity (utility numerical) ──────────────────────────────


@pytest.mark.parametrize(
    "action_type,payload",
    [
        ("dx", {}),
        ("treatment", {"drug": "amoxicillin"}),
        ("test", {"tests": ["cbc", "bmp"]}),
        ("referral", {}),
        ("wait", {}),
    ],
)
def test_score_decision_utility_parity(action_type, payload):
    legacy_d = _decision_legacy("d1", action_type, payload, f"{action_type} action")
    rust_d = _decision_rust("d1", action_type, payload, f"{action_type} action")
    patient = {}
    py = legacy.score_decision(legacy_d, patient, {})
    rs = rust.score_decision(rust_d, patient, {})
    # Tolerance accounts for the LLM-judge baseline divergence:
    # Python `impedance_llm_delta` falls back to `ask_fast` even when no
    # caller is given (~0.05-0.1 noise contribution). Rust returns 0
    # when no LlmCaller is bound. Until `tools.literature` is ported and
    # we wire a unified LLM bridge, allow ±0.05 utility drift.
    assert abs(py.utility - rs.utility) < 0.05, (
        f"utility divergence on {action_type=}: py={py.utility} vs rust={rs.utility}"
    )


# ── decide() parity — same patient + alts → same chosen ─────────────────────


def test_decide_picks_same_alternative():
    payload_a = {"drug": "amoxicillin"}
    payload_b = {"drug": "ibuprofen"}
    py_alts = [
        _decision_legacy("a", "treatment", payload_a, "amox"),
        _decision_legacy("b", "treatment", payload_b, "ibu"),
    ]
    rs_alts = [
        _decision_rust("a", "treatment", payload_a, "amox"),
        _decision_rust("b", "treatment", payload_b, "ibu"),
    ]
    py_chosen = legacy.decide(py_alts, {}, {})
    rs_chosen = rust.decide(rs_alts, {}, {})
    assert py_chosen.decision.id == rs_chosen.decision.id


def test_decide_raises_on_all_violate():
    py_alts = [_decision_legacy("a", "treatment", {"drug": "amoxicillin"})]
    rs_alts = [_decision_rust("a", "treatment", {"drug": "amoxicillin"})]
    patient = {"allergies": ["penicillin"]}
    with pytest.raises(legacy.KernelViolation):
        legacy.decide(py_alts, patient, {})
    with pytest.raises(rust.KernelViolation):
        rust.decide(rs_alts, patient, {})


# ── needs_clarification parity ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "patient",
    [
        {},
        {"missing_labs_count": 5},
        {"missing_labs_count": 5, "history_contradictions": 3,
         "unexplained_symptoms_count": 4, "dx_without_evidence": True},
    ],
)
def test_needs_clarification_parity(patient):
    py = legacy.needs_clarification(patient, {})
    rs = rust.needs_clarification(patient, {})
    assert py == rs, f"needs_clarification divergence on {patient=}: py={py} rs={rs}"
