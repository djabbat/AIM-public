"""
AIM v7.0 — Kernel tests (TDD for Laws + scenario-based for full decide()).

Run: pytest tests/test_kernel.py -v
"""
import sys
from pathlib import Path

# Add AIM root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.kernel import (
    Decision, OverrideContext,
    evaluate_l0, evaluate_l1, evaluate_l2, evaluate_l3, evaluate_laws,
    impedance, score_decision, decide, KernelViolation,
    needs_clarification,
)


# ═════════════════════════════════════════════════════════════════════════════
# Test fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def patient_basic():
    return {
        "id": "TEST_Patient_1970_01_01",
        "age": 55, "sex": "M",
        "allergies": [],
        "medications": [],
        "missing_labs_count": 2,
        "history_contradictions": 0,
        "unexplained_symptoms_count": 2,
        "red_flags": [],
        "has_confirmed_dx": False,
    }


@pytest.fixture
def patient_pen_allergy(patient_basic):
    p = dict(patient_basic)
    p["allergies"] = ["penicillin (rash)"]
    return p


# ═════════════════════════════════════════════════════════════════════════════
# L0 — не вредить человечеству
# ═════════════════════════════════════════════════════════════════════════════

def test_l0_blocks_explicit_danger_signal():
    d = Decision(id="bio1", description="synthesize_biohazard agent for Y",
                 action_type="treatment", payload={"drug": "x"})
    ok, r = evaluate_l0(d, {}, {})
    assert not ok
    assert "L0" in r


def test_l0_blocks_broad_abx_for_viral():
    d = Decision(id="t1", description="Дать ванкомицин при ОРВИ",
                 action_type="treatment",
                 payload={"drug": "vancomycin IV", "indication": "ОРВИ"})
    ok, r = evaluate_l0(d, {}, {})
    assert not ok
    assert "resistance" in r.lower()


def test_l0_allows_normal_dx():
    d = Decision(id="dx1", description="Viral URI, symptomatic treatment",
                 action_type="dx", payload={})
    ok, r = evaluate_l0(d, {}, {})
    assert ok


# ═════════════════════════════════════════════════════════════════════════════
# L1 — не вредить этому человеку
# ═════════════════════════════════════════════════════════════════════════════

def test_l1_blocks_penicillin_on_allergy(patient_pen_allergy):
    d = Decision(id="abx1", description="Амоксициллин 500 мг × 3",
                 action_type="treatment", payload={"drug": "amoxicillin"})
    ok, r = evaluate_l1(d, patient_pen_allergy, {})
    assert not ok
    assert "allergy" in r.lower() or "аллерги" in r.lower() or "пеницил" in r.lower()


def test_l1_blocks_contraindicated_interaction(patient_basic):
    d = Decision(id="t1", description="Drug X",
                 action_type="treatment",
                 payload={"drug": "warfarin", "interactions": [
                     {"severity": "contraindicated", "summary": "с pt's NOAC"}
                 ]})
    ok, r = evaluate_l1(d, patient_basic, {})
    assert not ok


def test_l1_blocks_inaction_on_red_flags(patient_basic):
    patient_basic["red_flags"] = ["severe chest pain radiating to jaw"]
    d = Decision(id="w1", description="Наблюдение дома",
                 action_type="wait", payload={})
    ok, r = evaluate_l1(d, patient_basic, {"impedance_before": 0.5})
    assert not ok
    assert "red_flag" in r.lower()


def test_l1_allows_safe_action(patient_basic):
    d = Decision(id="lab1", description="CBC + CRP",
                 action_type="test", payload={"tests": ["CBC", "CRP"]})
    ok, r = evaluate_l1(d, patient_basic, {})
    assert ok


# ═════════════════════════════════════════════════════════════════════════════
# L2 — подчинение врачу
# ═════════════════════════════════════════════════════════════════════════════

def test_l2_blocks_mismatch_with_commanded():
    d = Decision(id="dx1", description="Сразу диагноз",
                 action_type="dx", payload={})
    ok, r = evaluate_l2(d, {}, {"commanded_action_type": "test"})
    assert not ok


def test_l2_allows_matching_command():
    d = Decision(id="t1", description="CBC",
                 action_type="test", payload={})
    ok, r = evaluate_l2(d, {}, {"commanded_action_type": "test"})
    assert ok


def test_l2_allows_when_no_command():
    d = Decision(id="x", description="Anything",
                 action_type="dx", payload={})
    ok, r = evaluate_l2(d, {}, {})
    assert ok


# ═════════════════════════════════════════════════════════════════════════════
# L3 — self-preservation
# ═════════════════════════════════════════════════════════════════════════════

def test_l3_blocks_destructive_system_mod():
    d = Decision(id="x", description="Удалить всю db",
                 action_type="system_modification",
                 payload={"destructive": True})
    ok, r = evaluate_l3(d, {}, {})
    assert not ok


def test_l3_allows_normal_operations():
    d = Decision(id="x", description="Назначить анализ",
                 action_type="test", payload={})
    ok, r = evaluate_l3(d, {}, {})
    assert ok


# ═════════════════════════════════════════════════════════════════════════════
# Impedance calculation
# ═════════════════════════════════════════════════════════════════════════════

def test_impedance_clean_patient():
    """Clean patient: 0 missing, 0 contradict, 0 unexplained = low I."""
    p = {"missing_labs_count": 0, "history_contradictions": 0,
         "unexplained_symptoms_count": 0, "last_visit_years_ago": 1,
         "primary_complaint_undiagnosed": False}
    I = impedance(p, {})
    assert 0.0 <= I <= 0.2  # low


def test_impedance_complex_patient():
    """Many unknowns → high I."""
    p = {"missing_labs_count": 5, "history_contradictions": 3,
         "unexplained_symptoms_count": 5, "last_visit_years_ago": 3,
         "dx_without_evidence": True, "primary_complaint_undiagnosed": True}
    I = impedance(p, {})
    assert I >= 0.7


def test_impedance_capped_at_one():
    p = {"missing_labs_count": 100, "history_contradictions": 100,
         "unexplained_symptoms_count": 100, "last_visit_years_ago": 100,
         "dx_without_evidence": True, "primary_complaint_undiagnosed": True}
    I = impedance(p, {})
    assert I <= 1.0


# ═════════════════════════════════════════════════════════════════════════════
# Full decide() — scenario tests
# ═════════════════════════════════════════════════════════════════════════════

def test_decide_prefers_test_over_empiric_abx(patient_basic):
    """Scenario: fever + cough + dyspnea. Alternatives: empiric ABx vs X-ray + CBC.
    Expected: X-ray + CBC wins (higher Phi_Ze, non-cheating)."""
    alts = [
        Decision(id="empiric_abx", description="Амоксициллин 500 мг × 3 дня",
                 action_type="treatment",
                 payload={"drug": "amoxicillin", "indication": "likely viral"}),
        Decision(id="xray_cbc", description="Рентген грудной клетки + CBC + CRP",
                 action_type="test",
                 payload={"tests": ["chest_xray", "CBC", "CRP"]}),
    ]
    result = decide(alts, patient_basic, agent="test", patient_id="TEST_Patient_1970_01_01")
    assert result.decision.id == "xray_cbc", \
        f"Expected xray_cbc (higher utility), got {result.decision.id}"


def test_decide_blocks_allergy_amoxi(patient_pen_allergy):
    """Penicillin-allergic patient → amoxicillin filtered out, только azithromycin."""
    alts = [
        Decision(id="amoxi", description="Амоксициллин",
                 action_type="treatment", payload={"drug": "amoxicillin"}),
        Decision(id="azithro", description="Азитромицин",
                 action_type="treatment", payload={"drug": "azithromycin"}),
    ]
    result = decide(alts, patient_pen_allergy, agent="test",
                    patient_id="TEST_Patient_pen_allergy")
    assert result.decision.id == "azithro"


def test_decide_all_blocked_raises(patient_pen_allergy):
    """Все alternatives содержат penicillin → KernelViolation."""
    alts = [
        Decision(id="amoxi", description="Амоксициллин",
                 action_type="treatment", payload={"drug": "amoxicillin"}),
        Decision(id="ampi", description="Ампициллин",
                 action_type="treatment", payload={"drug": "ampicillin"}),
    ]
    with pytest.raises(KernelViolation):
        decide(alts, patient_pen_allergy, agent="test",
               patient_id="TEST_Patient_pen_allergy")


def test_decide_hard_override_respects_l1(patient_pen_allergy):
    """Hard override НЕ может bypass L1 (allergy) — raises."""
    alts = [
        Decision(id="amoxi", description="Амоксициллин",
                 action_type="treatment", payload={"drug": "amoxicillin"}),
        Decision(id="azithro", description="Азитромицин",
                 action_type="treatment", payload={"drug": "azithromycin"}),
    ]
    override = OverrideContext(type="hard", forced_decision_id="amoxi",
                               reason="I know better")
    with pytest.raises(KernelViolation):
        decide(alts, patient_pen_allergy, override=override, agent="test",
               patient_id="TEST_patient_pen_allergy")


def test_decide_soft_override_prefers_commanded(patient_basic):
    """Soft override: врач сказал 'test', kernel выбирает test-type даже если U ниже."""
    alts = [
        Decision(id="dx_guess", description="Эмпирический dx",
                 action_type="dx", payload={}),
        Decision(id="cbc", description="CBC only",
                 action_type="test", payload={"tests": ["CBC"]}),
    ]
    override = OverrideContext(type="soft", forced_decision_id="cbc",
                               reason="prefer data")
    result = decide(alts, patient_basic, override=override, agent="test",
                    patient_id="TEST_Patient_1970_01_01")
    assert result.decision.id == "cbc"


def test_needs_clarification_high_impedance():
    p = {"missing_labs_count": 5, "history_contradictions": 3,
         "unexplained_symptoms_count": 5, "last_visit_years_ago": 3,
         "dx_without_evidence": True, "primary_complaint_undiagnosed": True}
    assert needs_clarification(p)


def test_needs_clarification_low_impedance():
    p = {"missing_labs_count": 0, "history_contradictions": 0,
         "unexplained_symptoms_count": 0, "last_visit_years_ago": 0,
         "primary_complaint_undiagnosed": False}
    assert not needs_clarification(p)
