#!/usr/bin/env python3
"""
Differential diagnosis engine.
Uses Bayesian inference: P(disease | symptoms + labs) ∝ P(labs | disease) × P(disease | symptoms)

Evidence base: curated symptom-lab-disease probability tables
based on clinical epidemiology.
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from lab_reference import LabResult


# ─────────────────────────────────────────────────────────────
# Disease probability table
# P(lab_pattern | disease) and P(symptom | disease)
# ─────────────────────────────────────────────────────────────

@dataclass
class DiseasePrior:
    name_ru: str
    icd10: str
    base_prevalence: float           # population prevalence
    # Lab markers: {param_id: (status_pattern, likelihood_ratio)}
    lab_markers: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    # Symptom keywords (Russian/Georgian) → LR
    symptom_markers: Dict[str, float] = field(default_factory=dict)
    # Protective factors: negative markers reduce probability
    negative_markers: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    description: str = ""
    specialist: str = ""


# ─────────────────────────────────────────────────────────────
# Clinical knowledge base (evidence-based)
# Likelihood Ratios from meta-analyses and clinical guidelines
# ─────────────────────────────────────────────────────────────
DISEASE_KB: List[DiseasePrior] = [

    DiseasePrior(
        name_ru="Железодефицитная анемия",
        icd10="D50",
        base_prevalence=0.12,
        lab_markers={
            "HGB":   ("low",  8.0),   # LR+ for iron deficiency
            "MCV":   ("low",  6.5),
            "FERR":  ("low",  15.0),  # LR+ 15 for ferritin < 15
            "FE":    ("low",  3.5),
            "TIBC":  ("high", 3.0),
        },
        symptom_markers={
            "усталость": 2.5, "слабость": 2.0, "бледность": 3.0,
            "хрупкость ногтей": 4.0, "выпадение волос": 2.5,
            "головокружение": 2.0, "тахикардия": 1.8,
            "დაღლილობა": 2.5,  # Georgian
        },
        negative_markers={
            "FERR": ("normal", 0.2),
            "HGB":  ("normal", 0.1),
        },
        description="Дефицит железа — наиболее частая анемия у женщин репродуктивного возраста",
        specialist="Терапевт / Гематолог",
    ),

    DiseasePrior(
        name_ru="Субклинический/клинический гипотиреоз",
        icd10="E03",
        base_prevalence=0.08,
        lab_markers={
            "TSH":  ("high", 12.0),
            "T4F":  ("low",  8.0),
            "TPO":  ("high", 4.5),
        },
        symptom_markers={
            "усталость": 2.0, "сухость кожи": 3.0, "запор": 2.5,
            "прибавка веса": 2.5, "зябкость": 4.0, "брадикардия": 3.0,
            "депрессия": 2.0, "выпадение волос": 3.0, "нарушение менструаций": 2.5,
            "ჰიპოთირეოზი": 5.0, "ფარისებრი": 3.0,
        },
        negative_markers={
            "TSH": ("normal", 0.05),
            "T4F": ("normal", 0.3),
        },
        description="Снижение функции щитовидной железы. Субклинический: ТТГ↑, Т4 норма",
        specialist="Эндокринолог",
    ),

    DiseasePrior(
        name_ru="Аутоиммунный тиреоидит (Хашимото)",
        icd10="E06.3",
        base_prevalence=0.05,
        lab_markers={
            "TSH":  ("high", 6.0),
            "TPO":  ("high", 10.0),
            "T4F":  ("low",  5.0),
        },
        symptom_markers={
            "усталость": 2.0, "зябкость": 3.0, "выпадение волос": 3.0,
            "нарушение менструаций": 2.5, "тревожность": 2.0,
            "ფარისებრი ჯირკვლის": 3.0,
        },
        description="Аутоиммунное воспаление щитовидной железы, антитела к ТПО резко повышены",
        specialist="Эндокринолог",
    ),

    DiseasePrior(
        name_ru="Дисфункция кишечника / СИБР / Дисбиоз",
        icd10="K63 / K92",
        base_prevalence=0.25,
        lab_markers={
            "CRP":  ("high", 1.5),
            "EOS%": ("high", 2.0),
        },
        symptom_markers={
            "метеоризм": 5.0, "вздутие": 5.0, "запор": 2.5, "диарея": 2.0,
            "боль в животе": 2.5, "изжога": 2.0, "тошнота": 1.8,
            "усталость после еды": 3.0,
            "მუცლის შებერილობა": 5.0,  # Georgian
            "ჭამის შემდეგ": 2.0,
        },
        description="Синдром избыточного бактериального роста, кишечный дисбиоз",
        specialist="Гастроэнтеролог",
    ),

    DiseasePrior(
        name_ru="Хроническое воспаление / Скрытая инфекция",
        icd10="R50 / B99",
        base_prevalence=0.15,
        lab_markers={
            "CRP":   ("high", 5.0),
            "ESR":   ("high", 3.0),
            "PCT":   ("high", 8.0),
            "WBC":   ("high", 3.0),
            "NEUT%": ("high", 2.5),
        },
        symptom_markers={
            "субфебрилитет": 4.0, "температура": 3.0, "слабость": 2.0,
            "ночная потливость": 3.0, "лимфаденопатия": 3.5,
            "ტემპ": 3.0, "ინფ": 3.0,
        },
        description="Системное воспаление, скрытая инфекция (паразитарная, вирусная, бактериальная)",
        specialist="Инфекционист / Терапевт",
    ),

    DiseasePrior(
        name_ru="Дефицит витамина D",
        icd10="E55",
        base_prevalence=0.40,
        lab_markers={
            "VD25": ("low", 8.0),
            "CA":   ("low", 2.0),
        },
        symptom_markers={
            "усталость": 1.5, "боли в костях": 4.0, "мышечная слабость": 3.0,
            "депрессия": 2.0, "частые ОРВИ": 3.0, "тревожность": 1.8,
            "ვიტ": 2.0, "ოსტეო": 3.0,
        },
        description="Широко распространённый дефицит, нарушает иммунитет, нейромышечную передачу",
        specialist="Терапевт / Эндокринолог",
    ),

    DiseasePrior(
        name_ru="Преддиабет / Нарушение толерантности к глюкозе",
        icd10="R73",
        base_prevalence=0.10,
        lab_markers={
            "GLU":   ("high", 6.0),
            "HBA1C": ("high", 5.5),
            "INS":   ("high", 3.0),
            "HOMA":  ("high", 5.0),
            "TG":    ("high", 2.0),
        },
        symptom_markers={
            "жажда": 4.0, "полиурия": 4.0, "усталость": 1.5,
            "ожирение": 3.0, "тяга к сладкому": 2.5,
        },
        negative_markers={
            "GLU":   ("normal", 0.15),
            "HBA1C": ("normal", 0.1),
        },
        description="Инсулинорезистентность и ранние нарушения гликемии",
        specialist="Эндокринолог",
    ),

    DiseasePrior(
        name_ru="Дислипидемия / Атерогенный профиль",
        icd10="E78",
        base_prevalence=0.30,
        lab_markers={
            "CHOL": ("high", 5.0),
            "LDL":  ("high", 8.0),
            "TG":   ("high", 3.0),
            "HDL":  ("low",  4.0),
        },
        symptom_markers={
            "ожирение": 2.0, "гипертензия": 2.5,
        },
        description="Нарушение липидного профиля, риск кардиоваскулярных событий",
        specialist="Кардиолог / Терапевт",
    ),

    DiseasePrior(
        name_ru="Хроническая болезнь почек (ранняя стадия)",
        icd10="N18",
        base_prevalence=0.08,
        lab_markers={
            "CREA": ("high", 6.0),
            "UREA": ("high", 4.0),
            "UA":   ("high", 2.5),
        },
        symptom_markers={
            "отёки": 3.0, "гипертензия": 2.5, "никтурия": 3.0,
            "усталость": 1.5, "снижение аппетита": 2.0,
        },
        description="Нарушение функции почек — раннее выявление важно для замедления прогрессии",
        specialist="Нефролог",
    ),

    DiseasePrior(
        name_ru="Дефицит B12 / Фолатов",
        icd10="D51 / D52",
        base_prevalence=0.06,
        lab_markers={
            "VB12":  ("low", 10.0),
            "FOLAT": ("low", 8.0),
            "MCV":   ("high", 5.0),
            "HGB":   ("low",  3.0),
        },
        symptom_markers={
            "онемение": 4.0, "покалывание": 4.0, "слабость": 2.5,
            "депрессия": 2.5, "ухудшение памяти": 3.0, "глоссит": 5.0,
        },
        description="Мегалобластная анемия и неврологические нарушения при дефиците B12/фолатов",
        specialist="Терапевт / Невролог",
    ),

    DiseasePrior(
        name_ru="Тревожное расстройство / Хронический стресс",
        icd10="F41",
        base_prevalence=0.15,
        lab_markers={
            "CORT": ("high", 3.0),
            "MG":   ("low",  2.0),
            "VD25": ("low",  1.5),
        },
        symptom_markers={
            "тревога": 8.0, "тревожность": 8.0, "паника": 7.0,
            "бессонница": 4.0, "сердцебиение": 3.0,
            "раздражительность": 3.0, "нарушение сна": 4.0,
            "შფოთ": 8.0, "ანქსი": 8.0, "panic": 7.0,
            "დერეალ": 5.0, "derealization": 5.0,
        },
        description="Хроническая активация стресс-системы, нарушение регуляции HPA-оси",
        specialist="Психиатр / Психотерапевт",
    ),

    DiseasePrior(
        name_ru="Паразитарная инвазия / Глистная инвазия",
        icd10="B82",
        base_prevalence=0.20,
        lab_markers={
            "EOS%": ("high", 6.0),
            "EOS":  ("high", 6.0),
            "IgE":  ("high", 4.0),
            "HGB":  ("low",  2.0),
        },
        symptom_markers={
            "зуд": 3.0, "кожные высыпания": 2.5, "боль в животе": 2.0,
            "усталость": 1.5, "аллергия": 2.5, "скрежет зубов": 3.5,
            "ალერგ": 2.5, "კბენ": 3.0, "პარაზ": 5.0,
        },
        description="Гельминтозы и протозоозы — часто недооцениваются, дают полисимптоматику",
        specialist="Инфекционист / Паразитолог",
    ),

    DiseasePrior(
        name_ru="Синдром раздражённого кишечника / Функциональная диспепсия",
        icd10="K58 / K30",
        base_prevalence=0.20,
        lab_markers={},   # labs usually normal in IBS
        symptom_markers={
            "боль в животе": 4.0, "вздутие": 5.0, "чередование запор/диарея": 6.0,
            "связь с едой": 4.0, "стресс": 3.0, "усиление при стрессе": 4.0,
            "მუცლის ტკივილი": 4.0, "შებერ": 5.0,
        },
        description="Функциональные ЖКТ-расстройства без органической патологии",
        specialist="Гастроэнтеролог",
    ),

    DiseasePrior(
        name_ru="Нарушение гормонального фона (женский цикл)",
        icd10="N91 / N94",
        base_prevalence=0.18,
        lab_markers={
            "E2":   ("low",  4.0),
            "PROG": ("low",  4.0),
            "FSH":  ("high", 3.0),
            "LH":   ("high", 3.0),
        },
        symptom_markers={
            "нарушение менструаций": 8.0, "болезненные месячные": 6.0,
            "предменструальный синдром": 6.0, "нарушение цикла": 8.0,
            "приливы": 5.0, "потливость": 3.0,
            "მენსტ": 8.0, "ციკლ": 6.0, "ტემპ": 2.5,
        },
        description="Дисбаланс половых гормонов — эстрогена, прогестерона, ЛГ/ФСГ",
        specialist="Гинеколог / Эндокринолог",
    ),

    DiseasePrior(
        name_ru="Надпочечниковая дисфункция / HPA-ось",
        icd10="E27.4",
        base_prevalence=0.10,
        lab_markers={
            "CORT": ("low",  5.0),    # low cortisol (hypo-adrenal)
            "DHEA": ("low",  4.0),
            "MG":   ("low",  2.5),
            "NA":   ("low",  2.0),    # hyponatremia in adrenal insufficiency
            "K":    ("high", 2.0),    # hyperkalemia
        },
        symptom_markers={
            "хроническая усталость": 4.0, "усталость с утра": 5.0,
            "трудно вставать": 4.0, "тяга к соли": 5.0,
            "снижение давления": 3.0, "гипотония": 3.5,
            "нарушение сна": 3.0, "выпадение волос": 2.5,
            "усиление усталости при стрессе": 5.0, "непереносимость стресса": 5.0,
            "ნადოფართ": 5.0, "სტრ": 3.0,
        },
        negative_markers={
            "CORT": ("normal", 0.2),
        },
        description="Нарушение HPA-оси: субклиническая надпочечниковая недостаточность, дефицит ДГЭА",
        specialist="Эндокринолог / Интегративный врач",
    ),

    DiseasePrior(
        name_ru="Синдром хронической усталости (МЭ/СХУ)",
        icd10="G93.3",
        base_prevalence=0.02,
        lab_markers={
            "VD25": ("low",  2.0),
            "VB12": ("low",  2.0),
            "FERR": ("low",  2.0),
            "TSH":  ("high", 1.5),
            "CRP":  ("high", 1.5),
        },
        symptom_markers={
            "хроническая усталость": 6.0, "усталость более 6 месяцев": 8.0,
            "усталость после нагрузки": 7.0, "постнагрузочное недомогание": 8.0,
            "нарушение сна": 4.0, "когнитивные нарушения": 5.0,
            "туман в голове": 6.0, "brain fog": 6.0,
            "ортостатическая гипотензия": 4.0, "боли в мышцах": 3.0,
            "ქრონ": 5.0, "დაღლ": 5.0,
        },
        description="МЭ/СХУ — многосистемное нейроиммунное заболевание, постнагрузочное недомогание — ключевой критерий",
        specialist="Невролог / Иммунолог / Интегративный врач",
    ),

    DiseasePrior(
        name_ru="Инсулинорезистентность (без явного диабета)",
        icd10="E11.9",
        base_prevalence=0.25,
        lab_markers={
            "INS":   ("high", 6.0),
            "HOMA":  ("high", 8.0),
            "TG":    ("high", 3.0),
            "HDL":   ("low",  3.0),
            "GLU":   ("high", 2.5),
            "UA":    ("high", 2.0),   # uric acid elevated in metabolic syndrome
        },
        symptom_markers={
            "тяга к сладкому": 4.0, "голод через час после еды": 5.0,
            "усталость после углеводов": 5.0, "ожирение по животу": 5.0,
            "абдоминальное ожирение": 5.0, "акантоз": 6.0,
            "тёмные складки кожи": 6.0, "ПКЯ": 4.0, "СПКЯ": 4.0,
            "ინსულინ": 6.0, "მეტ": 3.0,
        },
        negative_markers={
            "INS":  ("normal", 0.2),
            "HOMA": ("normal", 0.15),
        },
        description="Нарушение чувствительности к инсулину без явной гипергликемии — предшественник метаболического синдрома",
        specialist="Эндокринолог / Диетолог",
    ),
]


# ─────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────

@dataclass
class DiagnosisResult:
    disease: DiseasePrior
    posterior: float       # 0..1
    log_odds: float
    supporting: List[str]  # evidence that supports
    opposing: List[str]    # evidence against
    confidence: str        # "высокая" | "умеренная" | "низкая"


def bayesian_differential(
    lab_results: List[LabResult],
    symptom_text: str = "",
    sex: str = "*",
) -> List[DiagnosisResult]:
    """
    Compute posterior P(disease | evidence) using log-odds Bayesian update.
    Returns sorted list of diagnoses (most probable first).
    """
    symptom_lower = symptom_text.lower()
    lab_map: Dict[str, LabResult] = {r.param_id: r for r in lab_results}

    diagnosis_list: List[DiagnosisResult] = []

    for disease in DISEASE_KB:
        # Start with log-prior
        p0 = max(disease.base_prevalence, 1e-6)
        log_odds = math.log(p0 / (1 - p0))

        supporting = []
        opposing = []

        # Update on lab evidence
        for param_id, (expected_status, lr) in disease.lab_markers.items():
            if param_id in lab_map:
                obs = lab_map[param_id]
                if obs.status == expected_status or (
                    expected_status in ("low", "critical_low") and obs.status in ("low", "critical_low")
                ) or (
                    expected_status in ("high", "critical_high") and obs.status in ("high", "critical_high")
                ):
                    log_odds += math.log(lr)
                    supporting.append(f"{obs.name} {obs.status} (LR={lr:.1f})")
                else:
                    # Observed normal when abnormal expected → mild negative evidence
                    log_odds += math.log(0.6)

        # Update on negative markers
        for param_id, (expected_status, lr_neg) in disease.negative_markers.items():
            if param_id in lab_map:
                obs = lab_map[param_id]
                if obs.status == expected_status:
                    log_odds += math.log(lr_neg)
                    opposing.append(f"{obs.name} в норме")

        # Update on symptom evidence
        for keyword, lr in disease.symptom_markers.items():
            if keyword.lower() in symptom_lower:
                log_odds += math.log(lr)
                supporting.append(f"симптом: {keyword} (LR={lr:.1f})")

        # Convert log-odds back to probability
        posterior = 1 / (1 + math.exp(-log_odds))
        posterior = max(0.001, min(0.999, posterior))

        if posterior > 0.04:  # Only show diseases with >4% probability
            if posterior > 0.5:
                confidence = "высокая"
            elif posterior > 0.2:
                confidence = "умеренная"
            else:
                confidence = "низкая"

            diagnosis_list.append(DiagnosisResult(
                disease=disease,
                posterior=posterior,
                log_odds=log_odds,
                supporting=supporting,
                opposing=opposing,
                confidence=confidence,
            ))

    # Sort by posterior descending
    diagnosis_list.sort(key=lambda x: -x.posterior)
    return diagnosis_list[:8]   # Return top-8


def format_differential(diagnoses: List[DiagnosisResult]) -> str:
    lines = ["\n=== ДИФФЕРЕНЦИАЛЬНАЯ ДИАГНОСТИКА ===\n"]
    for i, d in enumerate(diagnoses, 1):
        p_pct = d.posterior * 100
        bar = "█" * int(p_pct / 5) + "░" * (20 - int(p_pct / 5))
        lines.append(
            f"{i}. {d.disease.name_ru} [{d.disease.icd10}]"
        )
        lines.append(f"   Вероятность: {p_pct:.1f}%  {bar}  ({d.confidence})")
        lines.append(f"   Специалист: {d.disease.specialist}")
        if d.supporting:
            lines.append(f"   ▲ Подтверждает: {', '.join(d.supporting[:3])}")
        if d.opposing:
            lines.append(f"   ▼ Против: {', '.join(d.opposing[:2])}")
        lines.append(f"   ℹ {d.disease.description}")
        lines.append("")
    return "\n".join(lines)


def run_diagnosis_ai(lab_results: List[LabResult],
                     symptom_text: str = "",
                     patient_name: str = "") -> str:
    """
    Two-stage diagnosis:
    1. Bayesian differential (fast, local)
    2. DeepSeek-R1 validation + clinical reasoning (deep)

    Returns formatted string with combined results.
    """
    # Stage 1 — Bayesian
    bayes = bayesian_differential(lab_results, symptom_text)
    bayes_text = format_differential(bayes)

    if not bayes:
        return "Недостаточно данных для дифференциальной диагностики."

    # Stage 2 — R1 reasoning (expensive: only when Bayesian result is uncertain)
    # Skip R1 if top diagnosis has high posterior AND clear gap from #2
    top_posterior = bayes[0].posterior if bayes else 0.0
    second_posterior = bayes[1].posterior if len(bayes) > 1 else 0.0
    confidence_gap = top_posterior - second_posterior
    skip_r1 = (top_posterior >= 0.60 and confidence_gap >= 0.20)

    if skip_r1:
        return bayes_text + "\n\n_(DeepSeek R1 пропущен — байесовская уверенность достаточна)_"

    try:
        from llm import ask_deep

        lab_summary = "\n".join(
            f"  {r.param_id}: {r.value} {r.unit} [{r.status}]"
            for r in lab_results if r.status != "normal"
        ) or "  Все показатели в норме"

        top_bayes = "\n".join(
            f"  {i+1}. {d.disease.name_ru} [{d.disease.icd10}] "
            f"— вероятность {d.posterior:.0%} ({d.confidence})"
            for i, d in enumerate(bayes[:5])
        )

        prompt = f"""Пациент: {patient_name or 'не указан'}

ОТКЛОНЕНИЯ В АНАЛИЗАХ:
{lab_summary}

ЖАЛОБЫ/СИМПТОМЫ:
{symptom_text[:500] or 'не указаны'}

БАЙЕСОВСКИЙ РАСЧЁТ (предварительно):
{top_bayes}

Задача: проверь байесовский расчёт, скорректируй если нужно, и дай клиническое заключение.
Ответь строго в формате:

## ДИФФЕРЕНЦИАЛЬНЫЙ ДИАГНОЗ
1. [Диагноз] — [вероятность%] — [ключевое обоснование]
2. ...

## КЛИНИЧЕСКОЕ ЗАКЛЮЧЕНИЕ
[2-3 предложения — что наиболее вероятно и почему]

## СЛЕДУЮЩИЕ ШАГИ
- [что проверить дополнительно]
- [к какому специалисту направить]"""

        ai_reasoning = ask_deep(prompt, max_tokens=1500)
        return bayes_text + "\n\n" + "=" * 60 + "\nDEEPSEEK R1 — КЛИНИЧЕСКОЕ ЗАКЛЮЧЕНИЕ\n" + "=" * 60 + "\n" + ai_reasoning

    except Exception as e:
        # Fallback: just return Bayesian results
        return bayes_text
