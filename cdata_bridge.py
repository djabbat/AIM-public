"""
CDATA Bridge — AIM integration module.

Calls the cdata_patient_sim binary (CDATA Digital Twin) via subprocess,
returns structured aging predictions for use in AIM patient analysis.

Usage:
    from cdata_bridge import run_cdata_sim, aging_summary_text

    result = run_cdata_sim(age=45, tissue="Blood", damage_scale=1.0)
    print(aging_summary_text(result))
"""

import subprocess
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

# Path to compiled binary
_BINARY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "Desktop", "CDATA", "target", "debug", "cdata_patient_sim"
)

# Map damage_scale descriptors to float multipliers
DAMAGE_PRESETS = {
    "normal":       1.0,
    "accelerated":  1.5,   # smoker / chronic disease
    "progeria":     5.0,
    "longevity":    0.6,   # blue zone lifestyle
}

# Map common diagnoses / risk factors to tissue and damage_scale hints
_TISSUE_HINTS = {
    "leukemia":           "Blood",
    "anemia":             "Blood",
    "myeloma":            "Blood",
    "alzheimer":          "Neural",
    "parkinson":          "Neural",
    "dementia":           "Neural",
    "myopathy":           "Muscle",
    "muscular dystrophy": "Muscle",
    "cirrhosis":          "Liver",
    "hepatitis":          "Liver",
    "melanoma":           "Skin",
    "psoriasis":          "Skin",
    "renal":              "Kidney",
    "kidney":             "Kidney",
    "pulmonary":          "Lung",
    "copd":               "Lung",
    "cardiac":            "Heart",
    "heart failure":      "Heart",
}


@dataclass
class CdataResult:
    lifespan_estimate:          float = 0.0
    healthspan_estimate:        float = 0.0
    death_cause:                str   = ""
    damage_at_60:               float = 0.0
    damage_at_70:               float = 0.0
    damage_at_80:               float = 0.0
    myeloid_bias_at_70:         float = 0.0
    spindle_fidelity_at_70:     float = 0.0
    ciliary_function_at_70:     float = 0.0
    stem_pool_at_70:            float = 0.0
    methylation_age_at_70:      float = 0.0
    interventions_recommended:  List[str] = field(default_factory=list)
    ok:    bool          = False
    error: Optional[str] = None


def run_cdata_sim(
    age:          float  = 45.0,
    tissue:       str    = "Blood",
    damage_scale: float  = 1.0,
    steps:        int    = 36500,
    seed:         int    = 42,
) -> CdataResult:
    """
    Run CDATA patient simulation.

    Args:
        age:          Patient age (informational; future warm-start).
        tissue:       "Blood" | "Neural" | "Muscle" | "Skin" | "Liver" |
                      "Kidney" | "Lung" | "Heart"
        damage_scale: 1.0 = normal, >1.0 = accelerated, <1.0 = longevity.
        steps:        Simulation steps (days). 36500 = 100 years.
        seed:         RNG seed for reproducibility.

    Returns:
        CdataResult dataclass with lifespan, damage, and intervention data.
    """
    binary = _BINARY_PATH
    if not os.path.isfile(binary):
        return CdataResult(
            ok=False,
            error=f"cdata_patient_sim binary not found at {binary}. "
                  f"Run: cd ~/Desktop/CDATA && cargo build --bin cdata_patient_sim"
        )

    payload = json.dumps({
        "age":          age,
        "tissue":       tissue,
        "damage_scale": damage_scale,
        "steps":        steps,
        "seed":         seed,
    })

    try:
        proc = subprocess.run(
            [binary],
            input=payload,
            capture_output=True,
            text=True,
            timeout=300,
        )
        raw = proc.stdout.strip()
        if not raw:
            return CdataResult(ok=False, error=proc.stderr or "Empty output from binary")

        data = json.loads(raw)
        return CdataResult(**data)

    except subprocess.TimeoutExpired:
        return CdataResult(ok=False, error="Simulation timed out after 300 s")
    except json.JSONDecodeError as e:
        return CdataResult(ok=False, error=f"JSON parse error: {e}")
    except Exception as e:
        return CdataResult(ok=False, error=str(e))


def tissue_from_diagnoses(diagnoses: List[str]) -> str:
    """Guess most relevant tissue type from diagnosis keywords."""
    for dx in diagnoses:
        dx_lower = dx.lower()
        for keyword, tissue in _TISSUE_HINTS.items():
            if keyword in dx_lower:
                return tissue
    return "Blood"


def damage_scale_from_risk(risk_factors: List[str]) -> float:
    """Estimate damage_scale from risk factor keywords."""
    scale = 1.0
    for r in risk_factors:
        r = r.lower()
        if any(k in r for k in ("smok", "alcohol", "obesity", "diabete", "hypertens")):
            scale += 0.15
        if any(k in r for k in ("progeria", "werner", "hutchinson")):
            scale = max(scale, 5.0)
        if "exercise" in r or "diet" in r or "mediterran" in r:
            scale -= 0.10
    return max(0.3, min(scale, 5.0))


def aging_summary_text(result: CdataResult, lang: str = "ru") -> str:
    """
    Format CdataResult as a human-readable summary for AIM reports.

    Args:
        result: CdataResult from run_cdata_sim().
        lang:   "ru" | "en" | "ka"

    Returns:
        Formatted multi-line string.
    """
    if not result.ok:
        if lang == "ru":
            return f"[CDATA] Ошибка симуляции: {result.error}"
        return f"[CDATA] Simulation error: {result.error}"

    cause_map = {
        "frailty":          {"ru": "общая немощность", "en": "frailty",         "ka": "სიმოხუცე"},
        "neurodegeneration":{"ru": "нейродегенерация", "en": "neurodegeneration","ka": "ნეიროდეგენერაცია"},
        "pancytopenia":     {"ru": "панцитопения",      "en": "pancytopenia",    "ka": "პანციტოპენია"},
        "max_age":          {"ru": "максимальный возраст","en": "max age reached","ka": "მაქსიმალური ასაკი"},
    }
    cause_key = result.death_cause if result.death_cause else "max_age"
    cause_str = cause_map.get(cause_key, {}).get(lang, cause_key)

    interventions = ", ".join(result.interventions_recommended) if result.interventions_recommended else "—"

    if lang == "ru":
        lines = [
            "═══ CDATA Digital Twin — Прогноз старения ═══",
            f"  Ожидаемая продолжительность жизни : {result.lifespan_estimate:.1f} лет",
            f"  Период активного здоровья          : {result.healthspan_estimate:.1f} лет",
            f"  Прогнозируемая причина смерти      : {cause_str}",
            "",
            "  Накопление повреждений (центриолярный ущерб):",
            f"    в 60 лет : {result.damage_at_60:.2f}",
            f"    в 70 лет : {result.damage_at_70:.2f}",
            f"    в 80 лет : {result.damage_at_80:.2f}",
            "",
            "  Биомаркеры к 70 годам:",
            f"    Миелоидный сдвиг    : {result.myeloid_bias_at_70:.2f}",
            f"    Веретено (точность) : {result.spindle_fidelity_at_70:.2f}",
            f"    Цилии (функция)     : {result.ciliary_function_at_70:.2f}",
            f"    Пул стволовых клеток: {result.stem_pool_at_70:.2f}",
            f"    Метилационный возраст: {result.methylation_age_at_70:.1f} лет",
            "",
            f"  Рекомендуемые интервенции: {interventions}",
            "═" * 44,
        ]
    elif lang == "ka":
        lines = [
            "═══ CDATA Digital Twin — დაბერების პროგნოზი ═══",
            f"  სავარაუდო სიცოცხლის ხანგრძლივობა : {result.lifespan_estimate:.1f} წელი",
            f"  ჯანმრთელობის პერიოდი             : {result.healthspan_estimate:.1f} წელი",
            f"  სავარაუდო გარდაცვალების მიზეზი   : {cause_str}",
            "",
            f"  რეკომენდებული ინტერვენციები: {interventions}",
            "═" * 44,
        ]
    else:  # en
        lines = [
            "═══ CDATA Digital Twin — Aging Forecast ═══",
            f"  Lifespan estimate    : {result.lifespan_estimate:.1f} years",
            f"  Healthspan estimate  : {result.healthspan_estimate:.1f} years",
            f"  Predicted death cause: {cause_str}",
            "",
            "  Damage accumulation (centriolar):",
            f"    at 60y: {result.damage_at_60:.2f}  at 70y: {result.damage_at_70:.2f}  at 80y: {result.damage_at_80:.2f}",
            "",
            "  Biomarkers at age 70:",
            f"    Myeloid bias: {result.myeloid_bias_at_70:.2f}  "
            f"Spindle: {result.spindle_fidelity_at_70:.2f}  "
            f"Cilia: {result.ciliary_function_at_70:.2f}",
            f"    Stem pool: {result.stem_pool_at_70:.2f}  "
            f"Methylation age: {result.methylation_age_at_70:.1f}y",
            "",
            f"  Recommended interventions: {interventions}",
            "═" * 44,
        ]

    return "\n".join(lines)


def analyze_patient_aging(
    patient_age:    float,
    diagnoses:      List[str],
    risk_factors:   List[str],
    lang:           str = "ru",
) -> str:
    """
    High-level AIM integration call.

    Infers tissue and damage_scale from diagnoses/risk factors,
    runs simulation, returns formatted summary.

    Called from patient_analysis.py or medical_system.py.
    """
    tissue  = tissue_from_diagnoses(diagnoses)
    scale   = damage_scale_from_risk(risk_factors)
    result  = run_cdata_sim(age=patient_age, tissue=tissue, damage_scale=scale)
    return aging_summary_text(result, lang=lang)


# ── CLI self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    age   = float(sys.argv[1]) if len(sys.argv) > 1 else 55.0
    tiss  = sys.argv[2] if len(sys.argv) > 2 else "Blood"
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print(f"Running CDATA sim: age={age}, tissue={tiss}, damage_scale={scale}")
    res = run_cdata_sim(age=age, tissue=tiss, damage_scale=scale, steps=36500)
    print(aging_summary_text(res, lang="ru"))
