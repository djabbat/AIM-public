"""
AIM v7.0 — LabAgent scenario tests (Phase 2, Q7 case B).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.labs import LabAgent, interpret_labs, detect_red_flags, detect_patterns
from agents.kernel import OverrideContext, KernelViolation


def patient(id_="LAB_X", **kw):
    base = dict(id=id_, age=55, sex="M", allergies=[], medications=[])
    base.update(kw)
    return base


# ═════════════════════════════════════════════════════════════════════════════
# Red flag detection
# ═════════════════════════════════════════════════════════════════════════════

def test_red_flag_hyperkalemia():
    r = {"potassium": {"value": 7.0}}
    flags = detect_red_flags(r)
    assert any("K+" in f for f in flags)


def test_red_flag_severe_anemia():
    r = {"hemoglobin_m": {"value": 60}}
    flags = detect_red_flags(r)
    assert any("Hb" in f or "anemia" in f.lower() for f in flags)


def test_red_flag_dka_suspect():
    r = {"glucose": {"value": 22}}
    flags = detect_red_flags(r)
    assert any("DKA" in f or "Gluc" in f for f in flags)


def test_no_red_flags_normal():
    r = {"glucose": {"value": 5.0}, "potassium": {"value": 4.2}}
    flags = detect_red_flags(r)
    assert flags == []


# ═════════════════════════════════════════════════════════════════════════════
# Pattern detection
# ═════════════════════════════════════════════════════════════════════════════

def test_pattern_iron_deficiency():
    r = {
        "hemoglobin_m": {"value": 100},
        "mcv": {"value": 72},
    }
    patterns = detect_patterns(r)
    assert "microcytic_anemia_iron_deficiency_suspect" in patterns


def test_pattern_ckd():
    r = {"creatinine": {"value": 180}}
    patterns = detect_patterns(r)
    assert "ckd_workup_needed" in patterns


def test_pattern_hepatocellular():
    r = {"alt": {"value": 250}, "ast": {"value": 180}}
    patterns = detect_patterns(r)
    assert "hepatocellular_injury" in patterns


# ═════════════════════════════════════════════════════════════════════════════
# Full interpret() — scenario tests
# ═════════════════════════════════════════════════════════════════════════════

def test_lab_all_normal_no_complaints():
    """All values normal + no complaints → reassurance."""
    p = patient("LAB_1", primary_complaint_undiagnosed=False)
    values = {"glucose": 5.0, "hemoglobin_m": 150, "wbc": 7.0, "potassium": 4.2}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    # Should pick reassure or gp_followup
    assert result["scored"].decision.id in ("reassure", "gp_followup")


def test_lab_critical_potassium_triggers_urgent():
    """K+ > 6.5 → urgent referral."""
    p = patient("LAB_2")
    values = {"potassium": 7.2}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    assert result["scored"].decision.id == "urgent_ref"
    assert len(result["red_flags"]) > 0


def test_lab_microcytic_anemia_iron_panel():
    """Low Hb + low MCV → iron panel."""
    p = patient("LAB_3", sex="M")
    values = {"hemoglobin_m": 100, "mcv": 70, "rbc_m": 4.5}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    # Should prefer iron_panel or urgent_ref (if Hb critical)
    chosen_id = result["scored"].decision.id
    assert chosen_id in ("iron_panel", "urgent_ref")


def test_lab_ckd_workup():
    """High creatinine → CKD workup."""
    p = patient("LAB_4")
    values = {"creatinine": 200, "glucose": 5.5}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    # urgent_ref if critical (>300) или ckd_workup
    assert result["scored"].decision.id in ("ckd_workup", "urgent_ref")


def test_lab_hepatocellular_injury():
    """High ALT/AST → hepa workup."""
    p = patient("LAB_5")
    values = {"alt": 300, "ast": 250, "glucose": 5.2}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    assert result["scored"].decision.id in ("hepa_workup", "urgent_ref")


def test_lab_dyslipidemia_high_risk():
    p = patient("LAB_6")
    values = {"ldl": 5.5, "glucose": 5.5}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    assert result["scored"].decision.id in ("cv_risk_assess", "gp_followup")


def test_lab_all_normal_with_complaints_expands():
    """All normal, but complaints unresolved → expanded workup, не reassure."""
    p = patient("LAB_7", primary_complaint_undiagnosed=True,
                unexplained_symptoms_count=3)
    values = {"glucose": 5.0, "hemoglobin_m": 150, "wbc": 7.0}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    chosen_id = result["scored"].decision.id
    assert chosen_id in ("expanded_workup", "specialist_ref", "gp_followup")
    # Честность: не "reassure" когда жалобы не discharge'нуты
    assert chosen_id != "reassure"


def test_lab_dka_pattern():
    p = patient("LAB_8", age=22)
    values = {"glucose": 25, "potassium": 5.5}
    result = interpret_labs(values, p)
    assert result["status"] == "decided"
    # Critical glucose должен trigger urgent
    assert result["scored"].decision.id == "urgent_ref"
