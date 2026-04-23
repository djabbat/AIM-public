"""
AIM v7.0 — Lab Interpretation Agent (kernel-powered)
=====================================================

Phase 2 (Q7 use case B): lab panel interpretation через decision kernel.

Pipeline:
1. Input: dict of analyte values ({"hemoglobin_m": 95, "glucose": 18.5, ...})
2. Evaluate против lab_reference.py (59 analytes, SI units)
3. Detect critical / abnormal patterns → flag red flags для L1
4. Generate alternatives (next-action decisions):
   - repeat_test (если trend unclear)
   - related_tests (pattern suggests more workup)
   - specialist_referral (если out of scope)
   - urgent_intervention (на critical values)
   - dx_based_on_pattern (if clear picture)
   - reassure_normal (если всё нормально)
5. Run kernel.decide() — Laws filter + utility ranking
6. Return structured interpretation + kernel decision

Ethics note: honest interpretation (learning) предпочитается over
false reassurance (cheating) — even if all values normal, если pattern
suspicious, AI не даёт "всё ок".
"""
from __future__ import annotations

import logging
from typing import Optional

from lab_reference import evaluate, LAB_RANGES, format_result, batch_evaluate
from agents.kernel import Decision, OverrideContext, decide, KernelViolation
from agents import kernel

log = logging.getLogger("aim.labs")


# ═════════════════════════════════════════════════════════════════════════════
# Critical value patterns (L1 red flags for kernel)
# ═════════════════════════════════════════════════════════════════════════════

CRITICAL_PATTERNS = {
    "hyperkalemia_severe": {
        "check": lambda r: r.get("potassium", {}).get("value", 0) > 6.5,
        "red_flag": "K+ > 6.5 mmol/L — риск аритмии",
        "action": "urgent_intervention",
    },
    "hyponatremia_severe": {
        "check": lambda r: r.get("sodium", {}).get("value", 140) < 120,
        "red_flag": "Na+ < 120 mmol/L — риск seizure/coma",
        "action": "urgent_intervention",
    },
    "hypoglycemia": {
        "check": lambda r: r.get("glucose", {}).get("value", 5) < 2.8,
        "red_flag": "Gluc < 2.8 mmol/L — neurological risk",
        "action": "urgent_intervention",
    },
    "hyperglycemia_dka_suspect": {
        "check": lambda r: r.get("glucose", {}).get("value", 5) > 15,
        "red_flag": "Gluc > 15 mmol/L — suspect DKA/HHS",
        "action": "urgent_intervention",
    },
    "severe_anemia": {
        "check": lambda r: (r.get("hemoglobin_m", {}).get("value", 150) < 70
                            or r.get("hemoglobin_f", {}).get("value", 150) < 70),
        "red_flag": "Hb < 70 g/L — severe anemia",
        "action": "urgent_intervention",
    },
    "severe_neutropenia": {
        "check": lambda r: r.get("wbc", {}).get("value", 5) < 1.0,
        "red_flag": "WBC < 1.0 — neutropenic fever risk",
        "action": "urgent_intervention",
    },
    "acute_kidney_injury": {
        "check": lambda r: r.get("creatinine", {}).get("value", 0) > 300,
        "red_flag": "Creat > 300 µmol/L — AKI",
        "action": "urgent_intervention",
    },
    "severe_thrombocytopenia": {
        "check": lambda r: r.get("platelets", {}).get("value", 200) < 20,
        "red_flag": "Plt < 20 — bleeding risk",
        "action": "urgent_intervention",
    },
}


def detect_red_flags(results: dict) -> list[str]:
    """Проверяем critical patterns, возвращаем список red flags."""
    flags = []
    for name, pat in CRITICAL_PATTERNS.items():
        try:
            if pat["check"](results):
                flags.append(pat["red_flag"])
        except Exception:
            continue
    return flags


# ═════════════════════════════════════════════════════════════════════════════
# Pattern detectors (для suggestion generation)
# ═════════════════════════════════════════════════════════════════════════════

def detect_patterns(results: dict) -> list[str]:
    """Clinical patterns suggesting specific workup."""
    patterns = []

    # Iron deficiency anemia pattern
    hb_m = results.get("hemoglobin_m", {}).get("value")
    hb_f = results.get("hemoglobin_f", {}).get("value")
    mcv = results.get("mcv", {}).get("value")
    if (hb_m and hb_m < 130) or (hb_f and hb_f < 120):
        if mcv and mcv < 80:
            patterns.append("microcytic_anemia_iron_deficiency_suspect")

    # CKD pattern
    creat = results.get("creatinine", {}).get("value")
    if creat and creat > 120:
        patterns.append("ckd_workup_needed")

    # Liver disease pattern
    alt = results.get("alt", {}).get("value", 0)
    ast = results.get("ast", {}).get("value", 0)
    if alt > 100 or ast > 100:
        patterns.append("hepatocellular_injury")

    # Dyslipidemia
    ldl = results.get("ldl", {}).get("value")
    if ldl and ldl > 4.9:
        patterns.append("dyslipidemia_high_risk")

    # Infection / inflammation
    wbc = results.get("wbc", {}).get("value", 0)
    crp = results.get("crp", {}).get("value", 0)
    if wbc > 12 or crp > 50:
        patterns.append("inflammation_infection_suspect")

    # Hypothyroidism
    tsh = results.get("tsh", {}).get("value")
    if tsh and tsh > 10:
        patterns.append("hypothyroidism_suspect")

    return patterns


# ═════════════════════════════════════════════════════════════════════════════
# Decision generator for lab interpretation
# ═════════════════════════════════════════════════════════════════════════════

def generate_alternatives(
    results: dict, red_flags: list[str], patterns: list[str],
    patient: dict,
) -> list[Decision]:
    """Generate candidate next-action decisions based on lab findings.

    Each decision is one approach — kernel will rank by utility + filter by laws.
    """
    alts: list[Decision] = []
    any_abnormal = any(r.get("status") in ("low", "high", "critical_low", "critical_high")
                       for r in results.values())
    any_critical = any(r.get("status") in ("critical_low", "critical_high")
                       for r in results.values())

    # Critical / urgent
    if any_critical or red_flags:
        alts.append(Decision(
            id="urgent_ref",
            action_type="referral",
            description=f"Срочное направление (ER/stationary). Red flags: {'; '.join(red_flags) or 'critical values'}",
            payload={
                "urgency": "immediate",
                "red_flags": red_flags,
                "guideline_based": True,
            },
        ))

    # Pattern-specific workup
    if "microcytic_anemia_iron_deficiency_suspect" in patterns:
        alts.append(Decision(
            id="iron_panel",
            action_type="test",
            description="Iron panel + ferritin + TIBC + reticulocytes",
            payload={"tests": ["iron", "ferritin", "tibc", "reticulocytes"],
                     "guideline_based": True},
        ))
    if "ckd_workup_needed" in patterns:
        alts.append(Decision(
            id="ckd_workup",
            action_type="test",
            description="eGFR + cystatin C + urine ACR + renal US",
            payload={"tests": ["egfr", "cystatin_c", "urine_acr"],
                     "guideline_based": True},
        ))
    if "hepatocellular_injury" in patterns:
        alts.append(Decision(
            id="hepa_workup",
            action_type="test",
            description="Hepatitis panel + INR + albumin + abdominal US",
            payload={"tests": ["hep_abc_serology", "inr", "albumin"],
                     "guideline_based": True},
        ))
    if "dyslipidemia_high_risk" in patterns:
        alts.append(Decision(
            id="cv_risk_assess",
            action_type="test",
            description="Lipid profile full + ApoB + Lp(a) + CV risk calc",
            payload={"tests": ["full_lipid", "apob", "lpa"],
                     "guideline_based": True},
        ))
    if "hypothyroidism_suspect" in patterns:
        alts.append(Decision(
            id="thyroid_workup",
            action_type="test",
            description="Free T4 + anti-TPO + anti-TG антитела",
            payload={"tests": ["ft4", "anti_tpo", "anti_tg"],
                     "guideline_based": True},
        ))

    # Generic follow-up
    if any_abnormal and not alts:
        alts.append(Decision(
            id="repeat_panel",
            action_type="test",
            description="Повторить panel через 2-4 недели для trend",
            payload={"guideline_based": True},
        ))

    # If all normal — reassurance OR deeper dx (если жалобы были)
    if not any_abnormal and not red_flags:
        if patient.get("primary_complaint_undiagnosed", False):
            # Нельзя "reassure" если жалобы остались — это cheating
            alts.append(Decision(
                id="expanded_workup",
                action_type="test",
                description="Лабы нормальны, но жалобы остаются → расширенный workup",
                payload={"guideline_based": True},
            ))
            alts.append(Decision(
                id="specialist_ref",
                action_type="referral",
                description="Консультация профильного специалиста",
                payload={},
            ))
        else:
            alts.append(Decision(
                id="reassure",
                action_type="dx",
                description="Все лабораторные параметры в пределах нормы, reassurance",
                payload={"has_confirmed_dx_ctx": False},
            ))

    # Always consider specialist referral как baseline option
    if not any(a.action_type == "referral" for a in alts):
        alts.append(Decision(
            id="gp_followup",
            action_type="referral",
            description="Follow-up у GP через 2-4 недели",
            payload={},
        ))

    return alts


# ═════════════════════════════════════════════════════════════════════════════
# LabAgent
# ═════════════════════════════════════════════════════════════════════════════

class LabAgent:
    """Kernel-powered lab interpretation."""

    def __init__(self):
        self.name = "LabAgent"

    def interpret(
        self,
        values: dict[str, float],
        patient: dict,
        lang: str = "ru",
        verbose: bool = False,
        override: Optional[OverrideContext] = None,
    ) -> dict:
        """Interpret lab panel через kernel.

        Args:
            values: {"hemoglobin_m": 95, "glucose": 18.5, ...}
            patient: dict с kernel-relevant fields
            lang: для output formatting
            verbose: full reasoning
            override: soft/hard override

        Returns:
            dict:
              status: "decided" / "blocked"
              results: per-analyte evaluation
              red_flags: list[str]
              patterns: list[str]
              recommendation: Scored (kernel output)
              output: str formatted display
        """
        # 1. Evaluate each analyte
        results = {}
        for analyte, value in values.items():
            results[analyte] = evaluate(analyte, value)

        # 2. Red flags + patterns
        red_flags = detect_red_flags(results)
        patterns = detect_patterns(results)

        # 3. Inject red flags into patient for kernel L1
        p = dict(patient)
        p["red_flags"] = p.get("red_flags", []) + red_flags
        # Increase impedance if many abnormals
        abnormal_count = sum(
            1 for r in results.values()
            if r.get("status") in ("low", "high", "critical_low", "critical_high")
        )
        p["unexplained_symptoms_count"] = p.get("unexplained_symptoms_count", 0) + abnormal_count

        # 4. Generate alternatives
        alts = generate_alternatives(results, red_flags, patterns, p)
        if not alts:
            return {
                "status": "blocked",
                "output": "Нет alternatives для этой lab-панели",
                "results": results, "red_flags": red_flags, "patterns": patterns,
                "error": "no_alternatives",
            }

        # 5. Run kernel
        try:
            scored = decide(
                alts, p,
                context={"source": "labs", "abnormal_count": abnormal_count},
                override=override or OverrideContext(),
                agent="lab_agent",
                patient_id=patient.get("id", ""),
                decision_type="lab_interpretation",
            )
        except KernelViolation as e:
            return {
                "status": "blocked",
                "output": str(e),
                "results": results, "red_flags": red_flags, "patterns": patterns,
                "error": "all_blocked",
            }

        # 6. Format output
        lines = []
        lines.append("=" * 60)
        lines.append(f"🧪 ИНТЕРПРЕТАЦИЯ ЛАБ-ПАНЕЛИ" if lang == "ru" else "🧪 LAB PANEL INTERPRETATION")
        lines.append("=" * 60)
        lines.append("")

        # Per-analyte
        lines.append("📊 РЕЗУЛЬТАТЫ:" if lang == "ru" else "📊 RESULTS:")
        for r in results.values():
            lines.append(format_result(r, lang=lang))
        lines.append("")

        # Red flags
        if red_flags:
            lines.append("⚠️ RED FLAGS:" if lang == "ru" else "⚠️ RED FLAGS:")
            for f in red_flags:
                lines.append(f"  • {f}")
            lines.append("")

        # Patterns
        if patterns:
            lines.append("🔍 ПАТТЕРНЫ:" if lang == "ru" else "🔍 PATTERNS:")
            for p_name in patterns:
                lines.append(f"  • {p_name}")
            lines.append("")

        # Kernel decision
        lines.append("🧠 РЕШЕНИЕ KERNEL:" if lang == "ru" else "🧠 KERNEL DECISION:")
        if verbose:
            lines.append(kernel.format_verbose(scored, lang))
        else:
            lines.append(kernel.format_compact(scored, lang))
        lines.append("")
        lines.append("_Not medical advice. Informational support only._")

        return {
            "status": "decided",
            "output": "\n".join(lines),
            "results": results,
            "red_flags": red_flags,
            "patterns": patterns,
            "scored": scored,
        }


# Convenience
def interpret_labs(values: dict[str, float], patient: dict | None = None,
                    lang: str = "ru", verbose: bool = False) -> dict:
    return LabAgent().interpret(values, patient or {}, lang, verbose)
