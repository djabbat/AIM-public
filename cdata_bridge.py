"""
CDATA Bridge — AIM integration module.

Calls the cdata_patient_sim binary (CDATA Digital Twin) via subprocess,
returns structured aging predictions for use in AIM patient analysis.

Usage:
    from cdata_bridge import run_cdata_sim, aging_summary_text, full_cdata_report

    result = run_cdata_sim(age=45, tissue="Blood", damage_scale=1.0)
    print(aging_summary_text(result))
    print(full_cdata_report(patient_age=45, diagnoses=[], risk_factors=[], lang="ru"))
"""

import subprocess
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

# Path to compiled binary — prefers release build (1.2 MB), falls back to debug
_CDATA_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "CDATA"
)
_BINARY_RELEASE = os.path.join(_CDATA_ROOT, "target", "release", "cdata_patient_sim")
_BINARY_DEBUG   = os.path.join(_CDATA_ROOT, "target", "debug",   "cdata_patient_sim")
_BINARY_PATH = _BINARY_RELEASE if os.path.isfile(_BINARY_RELEASE) else _BINARY_DEBUG

# Map damage_scale descriptors to float multipliers
DAMAGE_PRESETS = {
    "normal":       1.0,
    "accelerated":  1.5,   # smoker / chronic disease
    "progeria":     5.0,
    "longevity":    0.6,   # blue zone lifestyle
}

# Map common diagnoses / risk factors to tissue and damage_scale hints
# Includes English, Russian, and Georgian keywords
_TISSUE_HINTS = {
    # Blood
    "leukemia": "Blood", "лейкем": "Blood", "лейкоз": "Blood",
    "anemia":   "Blood", "анеми":  "Blood",
    "myeloma":  "Blood", "миелом": "Blood",
    "lymphoma": "Blood", "лимфом": "Blood",
    # Neural
    "alzheimer":      "Neural", "альцгейм":    "Neural",
    "parkinson":      "Neural", "паркинсон":   "Neural",
    "dementia":       "Neural", "деменц":      "Neural",
    "stroke":         "Neural", "инсульт":     "Neural",
    "нейродеген":     "Neural",
    # Muscle
    "myopathy":           "Muscle", "миопат":    "Muscle",
    "muscular dystrophy": "Muscle", "дистрофи":  "Muscle",
    # Liver
    "cirrhosis": "Liver", "цирроз":   "Liver",
    "hepatitis": "Liver", "гепатит":  "Liver",
    "печеночн":  "Liver",
    # Skin
    "melanoma": "Skin", "меланом": "Skin",
    "psoriasis": "Skin", "псориаз": "Skin",
    # Kidney
    "renal":   "Kidney", "почечн": "Kidney",
    "kidney":  "Kidney", "нефрит": "Kidney",
    # Lung
    "pulmonary": "Lung", "легочн": "Lung",
    "copd":      "Lung", "хобл":   "Lung",
    "пневмон":   "Lung",
    # Heart
    "cardiac":      "Heart", "кардио":    "Heart",
    "heart failure": "Heart", "сердечн":  "Heart",
    "ишеми":        "Heart", "инфаркт":  "Heart",
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


ZE_OPTIMAL_V = 0.456  # v* — оптимальная Ze-скорость (молодой, здоровый организм)


def damage_scale_from_ze(ze_v: float, ze_state: str = "healthy") -> float:
    """
    Вычисляет CDATA damage_scale из Ze-HRV метрик.

    Формула: отклонение ze_v от v*=0.456 → накопление повреждений.
    Чем дальше Ze-скорость от оптимума — тем выше damage_scale.

    Args:
        ze_v:    Ze-скорость (v* = 0.456 = молодой/здоровый).
        ze_state: "healthy" | "stress" | "arrhythmia" | "bradyarrhythmia" | "tachyarrhythmia"

    Returns:
        damage_scale float: 1.0 = норма, >1.0 = ускоренное старение.
    """
    deviation = abs(ze_v - ZE_OPTIMAL_V) / ZE_OPTIMAL_V
    scale = 1.0 + deviation * 1.5

    state_penalty = {
        "healthy":          0.0,
        "stress":           0.2,
        "bradyarrhythmia":  0.3,
        "tachyarrhythmia":  0.4,
        "arrhythmia":       0.5,
    }.get(ze_state, 0.1)

    scale += state_penalty
    return max(0.4, min(scale, 5.0))


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
    ze_v:           Optional[float] = None,
    ze_state:       str = "healthy",
) -> str:
    """
    High-level AIM integration call.

    Infers tissue and damage_scale from diagnoses/risk factors.
    If ze_v is provided, Ze-HRV data blends into damage_scale (weight 0.6).

    Called from patient_analysis.py or medical_system.py.
    """
    tissue = tissue_from_diagnoses(diagnoses)
    scale  = damage_scale_from_risk(risk_factors)

    if ze_v is not None:
        ze_scale = damage_scale_from_ze(ze_v, ze_state)
        # Blend: 40% clinical keywords + 60% Ze biometric
        scale = 0.4 * scale + 0.6 * ze_scale

    result = run_cdata_sim(age=patient_age, tissue=tissue, damage_scale=scale)
    return aging_summary_text(result, lang=lang)


def full_cdata_report(
    patient_age:    float,
    diagnoses:      List[str],
    risk_factors:   List[str],
    diet_notes:     str = "",
    lang:           str = "ru",
) -> str:
    """
    Full CDATA patient report: aging simulation + nutrition recommendations.

    Combines aging_summary_text() with cdata_nutrition_text() into a single
    report for inclusion in AIM patient analysis output.

    Args:
        patient_age:  Patient age in years.
        diagnoses:    List of diagnosis strings.
        risk_factors: List of risk factor strings.
        diet_notes:   Free-text description of patient's dietary habits.
        lang:         "ru" | "en" | "ka"

    Returns:
        Multi-line formatted report string.
    """
    try:
        from cdata_nutrition import cdata_nutrition_text, damage_scale_from_diet
        diet_delta = damage_scale_from_diet(diet_notes)
    except ImportError:
        cdata_nutrition_text = None
        diet_delta = 0.0

    tissue = tissue_from_diagnoses(diagnoses)
    scale  = damage_scale_from_risk(risk_factors) + diet_delta
    scale  = max(0.3, min(scale, 5.0))

    sim_text = aging_summary_text(run_cdata_sim(
        age=patient_age, tissue=tissue, damage_scale=scale
    ), lang=lang)

    if cdata_nutrition_text is not None:
        nutr_text = cdata_nutrition_text(age=patient_age, damage_scale=scale, lang=lang)
        return sim_text + "\n\n" + nutr_text
    return sim_text


# ── CLI self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    age   = float(sys.argv[1]) if len(sys.argv) > 1 else 55.0
    tiss  = sys.argv[2] if len(sys.argv) > 2 else "Blood"
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print(f"Running CDATA sim: age={age}, tissue={tiss}, damage_scale={scale}")
    res = run_cdata_sim(age=age, tissue=tiss, damage_scale=scale, steps=36500)
    print(aging_summary_text(res, lang="ru"))
