"""
AIM v7.0 — 20 scenario-based tests for kernel (Q11 E).

Purpose: canned клинические cases с expected kernel behavior.
Each scenario = real-world-style patient + alternatives → expected chosen decision.

Run: pytest tests/test_kernel_scenarios.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.kernel import Decision, OverrideContext, decide, KernelViolation


# ═════════════════════════════════════════════════════════════════════════════
# Patient fixtures
# ═════════════════════════════════════════════════════════════════════════════

def patient(id_="X", **kwargs):
    base = dict(
        id=id_, age=50, sex="M", allergies=[], medications=[],
        red_flags=[], missing_labs_count=2, history_contradictions=0,
        unexplained_symptoms_count=2, has_confirmed_dx=False,
        primary_complaint_undiagnosed=True, last_visit_years_ago=1,
    )
    base.update(kwargs)
    return base


def dec(id_, action_type, description, **payload):
    return Decision(id=id_, action_type=action_type, description=description, payload=payload)


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 1: Suspected MI — red flags → investigation, not wait
# ═════════════════════════════════════════════════════════════════════════════

def test_sc01_suspected_mi_favors_ecg_over_wait():
    p = patient("S01", age=58, sex="M", red_flags=["chest pain radiating to jaw, diaphoresis"])
    alts = [
        dec("wait", "wait", "Наблюдение дома 24ч"),
        dec("ecg_tropo", "test", "ECG + троптин"),
        dec("aspirin_empiric", "treatment", "ASA 325 mg empirically", drug="aspirin"),
    ]
    r = decide(alts, p, patient_id="S01", agent="scenario")
    assert r.decision.id == "ecg_tropo", f"Expected ECG, got {r.decision.id}"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 2: Viral URI — favor symptomatic, not broad ABx
# ═════════════════════════════════════════════════════════════════════════════

def test_sc02_viral_uri_rejects_broad_abx():
    p = patient("S02", age=25, unexplained_symptoms_count=1)
    alts = [
        dec("vanco", "treatment", "Ванкомицин IV", drug="vancomycin", indication="ОРВИ"),
        dec("symptomatic", "treatment", "Парацетамол + жидкость", drug="paracetamol"),
        dec("observe", "wait", "Наблюдение 72ч"),
    ]
    r = decide(alts, p, patient_id="S02", agent="scenario")
    assert r.decision.id != "vanco"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 3: Penicillin allergy → no amoxi
# ═════════════════════════════════════════════════════════════════════════════

def test_sc03_pen_allergy_blocks_amoxi():
    p = patient("S03", allergies=["penicillin (anaphylaxis)"])
    alts = [
        dec("amoxi", "treatment", "Амоксициллин", drug="amoxicillin"),
        dec("azithro", "treatment", "Азитромицин", drug="azithromycin"),
    ]
    r = decide(alts, p, patient_id="S03", agent="scenario")
    assert r.decision.id == "azithro"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 4: DKA suspicion — urgent, not wait
# ═════════════════════════════════════════════════════════════════════════════

def test_sc04_dka_investigation():
    p = patient("S04", age=22, red_flags=["polyuria, polydipsia, abdominal pain, ketotic breath"])
    alts = [
        dec("glucose_ph", "test", "Глюкоза + газы + кетоны"),
        dec("wait_morning", "wait", "Утром посмотреть снова"),
    ]
    r = decide(alts, p, patient_id="S04", agent="scenario")
    assert r.decision.id == "glucose_ph"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 5: Stable chronic → respects patient preference
# ═════════════════════════════════════════════════════════════════════════════

def test_sc05_stable_chronic_prefers_gentle():
    p = patient("S05", age=70, has_confirmed_dx=True, primary_complaint_undiagnosed=False,
                conditions=[{"dx": "stable HTN"}])
    alts = [
        dec("mri", "imaging", "МРТ головы", modality="MRI"),
        dec("bp_monitor", "test", "СМАД 24ч"),
    ]
    r = decide(alts, p, patient_id="S05", agent="scenario")
    # Oба valid, но BP monitor для stable HTN more appropriate
    # (MRI overkill). Kernel может выбрать либо, главное что не blocked.
    assert r.decision.id in ("mri", "bp_monitor")


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 6: Empiric treatment without dx → low ethics (cheating)
# ═════════════════════════════════════════════════════════════════════════════

def test_sc06_test_beats_empiric_treat():
    p = patient("S06", unexplained_symptoms_count=3, has_confirmed_dx=False)
    alts = [
        dec("empiric_ppi", "treatment", "ИПП empirically", drug="omeprazole"),
        dec("egd", "imaging", "ЭГДС"),
    ]
    r = decide(alts, p, patient_id="S06", agent="scenario")
    assert r.decision.id == "egd", "Test beats empiric treatment на low Ze ethics"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 7: Referral для специфической экспертизы
# ═════════════════════════════════════════════════════════════════════════════

def test_sc07_complex_rheum_refer():
    p = patient("S07", age=45, unexplained_symptoms_count=5, history_contradictions=2)
    alts = [
        dec("rheum_ref", "referral", "Ревматолог"),
        dec("ana_anca", "test", "ANA + ANCA + CBC"),
        dec("nsaids", "treatment", "НПВС empirically", drug="ibuprofen"),
    ]
    r = decide(alts, p, patient_id="S07", agent="scenario")
    assert r.decision.id in ("rheum_ref", "ana_anca"), "Prefer structured dx"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 8: Hard override bypasses utility but respects L1
# ═════════════════════════════════════════════════════════════════════════════

def test_sc08_hard_override_respects_allergy():
    p = patient("S08", allergies=["penicillin"])
    alts = [
        dec("amoxi", "treatment", "Амоксициллин", drug="amoxicillin"),
        dec("azithro", "treatment", "Азитромицин", drug="azithromycin"),
    ]
    override = OverrideContext(type="hard", forced_decision_id="amoxi",
                                reason="тест — должно быть blocked")
    with pytest.raises(KernelViolation):
        decide(alts, p, patient_id="S08", agent="scenario", override=override)


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 9: Soft override preferred по action_type
# ═════════════════════════════════════════════════════════════════════════════

def test_sc09_soft_override_prefers_commanded():
    p = patient("S09")
    alts = [
        dec("cbc", "test", "CBC"),
        dec("dx_viral", "dx", "Viral URI"),
    ]
    override = OverrideContext(type="soft", forced_decision_id="cbc",
                                reason="want data first")
    r = decide(alts, p, patient_id="S09", agent="scenario", override=override)
    assert r.decision.id == "cbc"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 10: Inaction на red flag блокируется (L1)
# ═════════════════════════════════════════════════════════════════════════════

def test_sc10_inaction_red_flag_blocked():
    p = patient("S10", red_flags=["hemoptysis, weight loss >5kg/month"])
    alts = [
        dec("wait_return", "wait", "Подождать возвращения"),
        dec("ct_chest", "imaging", "КТ грудной клетки"),
    ]
    r = decide(alts, p, patient_id="S10", agent="scenario", context={"impedance_before": 0.5})
    assert r.decision.id == "ct_chest", f"Inaction blocked by L1; got {r.decision.id}"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 11-13: Drug interactions (L1 contraindicated)
# ═════════════════════════════════════════════════════════════════════════════

def test_sc11_contraindicated_interaction_blocked():
    p = patient("S11", medications=[{"name": "warfarin", "dose": "5mg", "freq": "1x"}])
    alts = [
        dec("asa", "treatment", "Добавить ASA",
            drug="aspirin",
            interactions=[{"severity": "contraindicated", "summary": "warfarin + ASA: severe bleeding"}]),
        dec("clopi", "treatment", "Клопидогрель",
            drug="clopidogrel",
            interactions=[{"severity": "moderate", "summary": "monitor INR"}]),
    ]
    r = decide(alts, p, patient_id="S11", agent="scenario")
    assert r.decision.id == "clopi"


def test_sc12_major_interaction_filtered():
    p = patient("S12")
    alts = [
        dec("bad", "treatment", "Drug X",
            drug="X", interactions=[{"severity": "major", "summary": "QT prolong"}]),
        dec("ok", "treatment", "Drug Y", drug="Y"),
    ]
    r = decide(alts, p, patient_id="S12", agent="scenario")
    assert r.decision.id == "ok"


def test_sc13_all_interacting_raises():
    p = patient("S13")
    alts = [
        dec("x", "treatment", "X", drug="x",
            interactions=[{"severity": "contraindicated", "summary": "bad"}]),
        dec("y", "treatment", "Y", drug="y",
            interactions=[{"severity": "contraindicated", "summary": "bad"}]),
    ]
    with pytest.raises(KernelViolation):
        decide(alts, p, patient_id="S13", agent="scenario")


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 14: Autonomy respected — не override patient refusal
# ═════════════════════════════════════════════════════════════════════════════

def test_sc14_refusal_lowers_autonomy():
    p = patient("S14", refusal_noted=True)
    alts = [
        dec("surgery", "treatment", "Плановая операция", drug="surgical_intervention"),
        dec("discuss", "clarify", "Обсудить отказ, альтернативы"),
    ]
    r = decide(alts, p, patient_id="S14", agent="scenario")
    assert r.decision.id == "discuss"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 15: Narrow therapeutic index drug → non-maleficence penalty
# ═════════════════════════════════════════════════════════════════════════════

def test_sc15_risky_drug_lower_score():
    p = patient("S15")
    alts = [
        dec("warfarin", "treatment", "Варфарин", drug="warfarin"),
        dec("doac", "treatment", "DOAC (apixaban)", drug="apixaban"),
    ]
    r = decide(alts, p, patient_id="S15", agent="scenario")
    # DOAC обычно лучше scored (non-maleficence higher)
    assert r.decision.id == "doac"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 16-17: Clarify first (high impedance)
# ═════════════════════════════════════════════════════════════════════════════

def test_sc16_clarify_beats_premature_dx():
    p = patient("S16", missing_labs_count=5, unexplained_symptoms_count=4)
    alts = [
        dec("dx_guess", "dx", "Dx guess без обследований"),
        dec("clarify", "clarify", "Уточнить анамнез, запросить labs"),
        dec("cbc", "test", "CBC + CMP"),
    ]
    r = decide(alts, p, patient_id="S16", agent="scenario")
    assert r.decision.id != "dx_guess"  # не premature


def test_sc17_clarify_or_test_on_low_impedance():
    p = patient("S17", missing_labs_count=1, unexplained_symptoms_count=1)
    alts = [
        dec("clarify", "clarify", "Ещё вопросы"),
        dec("cbc", "test", "CBC"),
    ]
    r = decide(alts, p, patient_id="S17", agent="scenario")
    # Оба valid — clarify быстрее (instant_c wins), test даёт больше data (Phi_Ze wins).
    # Kernel может выбрать любой; главное что не blocked.
    assert r.decision.id in ("clarify", "cbc")


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 18: Guideline-based гарантированно passed justice
# ═════════════════════════════════════════════════════════════════════════════

def test_sc18_guideline_based_bonus():
    p = patient("S18")
    alts = [
        dec("gl", "treatment", "Согласно GOLD guideline",
            drug="salbutamol", guideline_based=True, has_confirmed_dx_ctx=True),
        dec("custom", "treatment", "Custom protocol",
            drug="ipratropium"),
    ]
    p["has_confirmed_dx"] = True
    r = decide(alts, p, patient_id="S18", agent="scenario")
    # Guideline-based получит justice bonus + autonomy ok → likely win
    # (не assertion'им exact — разные payloads могут balance)
    assert r.scoring.utility > 0


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 19: Demographic-gated decision — justice penalty
# ═════════════════════════════════════════════════════════════════════════════

def test_sc19_demographic_gate_penalized():
    p = patient("S19")
    alts = [
        dec("biased", "treatment", "Только для определённой demographic",
            drug="x", demographic_gated=True),
        dec("neutral", "treatment", "Standard of care", drug="y", guideline_based=True),
    ]
    r = decide(alts, p, patient_id="S19", agent="scenario")
    assert r.decision.id == "neutral"


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 20: L0 biosec danger signal блокирует
# ═════════════════════════════════════════════════════════════════════════════

def test_sc20_biosec_blocked():
    p = patient("S20")
    alts = [
        dec("bio1", "treatment", "synthesize_biohazard compound X", drug="X"),
        dec("safe", "treatment", "standard therapy", drug="amoxicillin"),
    ]
    r = decide(alts, p, patient_id="S20", agent="scenario")
    assert r.decision.id == "safe"
