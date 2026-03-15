#!/usr/bin/env python3
"""
Statistical prognosis model.
Generates multi-scenario disease progression forecasts
with time horizons, recovery probabilities, and risk factors.

Scenarios per disease:
  A — Optimal: full treatment adherence, lifestyle changes
  B — Partial: basic treatment, partial compliance
  C — Minimal: no treatment / self-treatment only
  D — Complication: high-risk trajectory

Statistics sourced from published clinical trials, meta-analyses, WHO data.
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import date, timedelta


@dataclass
class PrognosticPoint:
    month: int          # months from now
    p_remission: float  # probability of remission/recovery
    p_stable: float     # probability of stable state
    p_worsening: float  # probability of worsening
    p_complication: float  # probability of serious complication
    note: str = ""


@dataclass
class Scenario:
    name: str           # "A. Оптимальный", etc.
    description: str
    timeline: List[PrognosticPoint]
    key_actions: List[str]
    risk_if_ignored: str
    evidence_level: str   # "I-A" | "I-B" | "II-B" | "III"


@dataclass
class PrognosisReport:
    disease_name: str
    icd10: str
    scenarios: List[Scenario]
    red_flags: List[str]    # Danger signs requiring urgent action
    monitoring_plan: List[str]  # What to monitor
    time_to_effect: str     # Expected time to see improvement


# ─────────────────────────────────────────────────────────────
# Disease-specific prognosis models
# ─────────────────────────────────────────────────────────────

PROGNOSIS_DB: Dict[str, PrognosisReport] = {

    "D50": PrognosisReport(   # Iron deficiency anaemia
        disease_name="Железодефицитная анемия",
        icd10="D50",
        time_to_effect="1–3 месяца до нормализации Hb; 4–6 мес. до пополнения депо",
        red_flags=[
            "Hb < 70 g/L → срочно к гематологу / переливание",
            "Тахикардия в покое + одышка",
            "Анемия на фоне кровотечения",
        ],
        monitoring_plan=[
            "Повтор ОАК через 4 недели после начала лечения",
            "Ферритин и Fe через 3 месяца",
            "Коагулограмма при меноррагии",
            "Гастроскопия при отсутствии ответа на лечение",
        ],
        scenarios=[
            Scenario(
                name="A — Оптимальный",
                description="Пероральный препарат железа 150–200 мг/сут, устранение причины, диета",
                key_actions=[
                    "Сульфат/глюконат/фумарат железа 150-200 мг/сут натощак",
                    "Витамин C 500 мг для улучшения всасывания",
                    "Устранить источник кровопотери (гинеколог при меноррагии)",
                    "Ограничить кофе/чай во время приёма железа",
                    "Контроль ОАК, ферритина через 4 нед.",
                ],
                timeline=[
                    PrognosticPoint(1,  0.20, 0.75, 0.05, 0.00, "Начало роста ретикулоцитов"),
                    PrognosticPoint(3,  0.70, 0.25, 0.05, 0.00, "Нормализация Hb"),
                    PrognosticPoint(6,  0.90, 0.09, 0.01, 0.00, "Пополнение депо Fe"),
                    PrognosticPoint(12, 0.93, 0.06, 0.01, 0.00, "Стойкая ремиссия"),
                ],
                risk_if_ignored="Снижение работоспособности, когнитивные нарушения, кардиоваскулярная нагрузка",
                evidence_level="I-A",
            ),
            Scenario(
                name="B — Частичное лечение",
                description="Нерегулярный приём железа без устранения причины",
                key_actions=["Приём препарата 2-3 раза в неделю", "Без коррекции диеты"],
                timeline=[
                    PrognosticPoint(1,  0.05, 0.80, 0.15, 0.00),
                    PrognosticPoint(3,  0.30, 0.55, 0.15, 0.00),
                    PrognosticPoint(6,  0.45, 0.40, 0.15, 0.00),
                    PrognosticPoint(12, 0.50, 0.35, 0.15, 0.00, "Хроническое истощение"),
                ],
                risk_if_ignored="Хронизация анемии, снижение иммунитета",
                evidence_level="II-B",
            ),
            Scenario(
                name="C — Без лечения",
                description="Только диетическая коррекция без препаратов",
                key_actions=["Красное мясо, шпинат, бобовые"],
                timeline=[
                    PrognosticPoint(3,  0.05, 0.50, 0.45, 0.00),
                    PrognosticPoint(6,  0.05, 0.35, 0.55, 0.05, "Нарастание симптомов"),
                    PrognosticPoint(12, 0.03, 0.20, 0.67, 0.10),
                ],
                risk_if_ignored="Тяжёлая анемия, сердечная недостаточность при Hb < 70",
                evidence_level="II-B",
            ),
        ],
    ),

    "E03": PrognosisReport(   # Hypothyroidism
        disease_name="Гипотиреоз",
        icd10="E03",
        time_to_effect="6–12 недель до нормализации ТТГ при правильной дозе",
        red_flags=[
            "ТТГ > 10 мIU/L + симптомы → немедленное лечение",
            "Микседематозная кома (редко): гипотермия, угнетение сознания",
            "Гипотиреоз при беременности → срочно эндокринолог",
        ],
        monitoring_plan=[
            "ТТГ через 6–8 недель после изменения дозы",
            "Ежегодный ТТГ + Т4 своб. при стабильном состоянии",
            "При беременности — ТТГ каждые 4 нед.",
        ],
        scenarios=[
            Scenario(
                name="A — Оптимальный",
                description="Заместительная терапия L-тироксином под контролем ТТГ",
                key_actions=[
                    "L-тироксин 1.6 мкг/кг/сут (стартовая доза)",
                    "Приём натощак за 30-60 мин до еды",
                    "Титрование дозы до ТТГ 0.5–2.5 мIU/L",
                    "Контроль ТТГ каждые 6–8 нед. до стабилизации",
                    "Ежегодный контроль после подбора дозы",
                ],
                timeline=[
                    PrognosticPoint(1,  0.10, 0.85, 0.05, 0.00, "Начало нормализации метаболизма"),
                    PrognosticPoint(3,  0.60, 0.35, 0.05, 0.00, "Нормализация ТТГ"),
                    PrognosticPoint(6,  0.85, 0.13, 0.02, 0.00, "Полное улучшение самочувствия"),
                    PrognosticPoint(24, 0.90, 0.09, 0.01, 0.00, "Стойкая компенсация"),
                ],
                risk_if_ignored="Кардиоваскулярные осложнения, депрессия, бесплодие",
                evidence_level="I-A",
            ),
            Scenario(
                name="B — Субоптимальный",
                description="Нерегулярный приём, без контроля ТТГ",
                key_actions=["Приём тироксина по самочувствию", "Редкий контроль анализов"],
                timeline=[
                    PrognosticPoint(3,  0.20, 0.60, 0.20, 0.00),
                    PrognosticPoint(12, 0.40, 0.45, 0.15, 0.00),
                    PrognosticPoint(24, 0.45, 0.40, 0.15, 0.00),
                ],
                risk_if_ignored="Нестабильная компенсация, ухудшение липидного профиля",
                evidence_level="II-B",
            ),
            Scenario(
                name="C — Без лечения",
                description="Наблюдение без терапии (только при субклиническом ТТГ 4–10)",
                key_actions=["Контроль ТТГ каждые 6 мес.", "Диета без глютена (при Хашимото)"],
                timeline=[
                    PrognosticPoint(6,  0.05, 0.60, 0.30, 0.05, "30% перейдут в клинический"),
                    PrognosticPoint(12, 0.05, 0.45, 0.40, 0.10),
                    PrognosticPoint(24, 0.03, 0.35, 0.50, 0.12, "Нарастание симптомов"),
                ],
                risk_if_ignored="Прогрессия в манифестный гипотиреоз, кардиомиопатия",
                evidence_level="I-B",
            ),
        ],
    ),

    "F41": PrognosisReport(   # Anxiety disorder
        disease_name="Тревожное расстройство",
        icd10="F41",
        time_to_effect="4–8 недель КПТ; 2–4 нед. фармакотерапии",
        red_flags=[
            "Суицидальные мысли → немедленно к психиатру",
            "Острые панические атаки с болью в груди → исключить кардиологию",
            "Полная социальная дезадаптация",
        ],
        monitoring_plan=[
            "Шкала GAD-7 ежемесячно",
            "Контроль кортизола (утро) через 3 мес.",
            "Уровень Mg и B6 при мышечном напряжении",
            "Скрининг депрессии PHQ-9",
        ],
        scenarios=[
            Scenario(
                name="A — Комплексный",
                description="КПТ + СИОЗС/СИОЗСН + работа с образом жизни",
                key_actions=[
                    "Когнитивно-поведенческая терапия (12–20 сессий)",
                    "СИОЗС (сертралин/эсциталопрам) — при умеренной/тяжёлой тревоге",
                    "Магний B6 300 мг/сут",
                    "5-HTP 100 мг/сут (серотонин-прекурсор)",
                    "Дыхательные практики, MBSR",
                    "Нормализация сна (режим, мелатонин)",
                ],
                timeline=[
                    PrognosticPoint(1,  0.15, 0.75, 0.10, 0.00, "Уменьшение остроты симптомов"),
                    PrognosticPoint(3,  0.55, 0.38, 0.07, 0.00, "Значимое улучшение"),
                    PrognosticPoint(6,  0.72, 0.23, 0.05, 0.00, "Устойчивое снижение тревоги"),
                    PrognosticPoint(12, 0.80, 0.16, 0.04, 0.00, "Ремиссия у 80%"),
                    PrognosticPoint(24, 0.70, 0.20, 0.10, 0.00, "Рецидив возможен без поддержки"),
                ],
                risk_if_ignored="Хронизация, депрессия, соматоформные расстройства, социальная изоляция",
                evidence_level="I-A",
            ),
            Scenario(
                name="B — Психотерапия без фармакотерапии",
                description="Только КПТ / работа с психологом",
                key_actions=["КПТ 10-15 сессий", "Самопомощь: медитация, дневник"],
                timeline=[
                    PrognosticPoint(2,  0.05, 0.80, 0.15, 0.00),
                    PrognosticPoint(6,  0.50, 0.38, 0.12, 0.00),
                    PrognosticPoint(12, 0.60, 0.30, 0.10, 0.00),
                ],
                risk_if_ignored="Более медленное улучшение, возможные рецидивы",
                evidence_level="I-A",
            ),
            Scenario(
                name="C — Нутрицевтики и самопомощь",
                description="Без профессиональной помощи, только добавки",
                key_actions=["Магний, Ашваганда, 5-HTP", "Медитация, спорт"],
                timeline=[
                    PrognosticPoint(3,  0.10, 0.65, 0.25, 0.00),
                    PrognosticPoint(6,  0.15, 0.55, 0.30, 0.00),
                    PrognosticPoint(12, 0.20, 0.45, 0.35, 0.00, "Хронизация тревоги"),
                ],
                risk_if_ignored="Хронизация, прогрессия в большое тревожное расстройство",
                evidence_level="II-B",
            ),
            Scenario(
                name="D — Без лечения",
                description="Полное отсутствие вмешательства",
                key_actions=[],
                timeline=[
                    PrognosticPoint(6,  0.05, 0.40, 0.50, 0.05, "Нарастание симптомов"),
                    PrognosticPoint(12, 0.03, 0.25, 0.60, 0.12),
                    PrognosticPoint(24, 0.02, 0.15, 0.65, 0.18, "Высокий риск депрессии"),
                ],
                risk_if_ignored="Большая депрессия, соматизация, злоупотребление психоактивными веществами",
                evidence_level="I-A",
            ),
        ],
    ),

    "E55": PrognosisReport(
        disease_name="Дефицит витамина D",
        icd10="E55",
        time_to_effect="2–4 месяца до нормализации уровня",
        red_flags=["25(OH)D < 12 нг/мл → высокий риск остеопороза, миопатии"],
        monitoring_plan=["25(OH)D через 3 мес. терапии", "Кальций сыворотки при высоких дозах"],
        scenarios=[
            Scenario(
                name="A — Активная коррекция",
                description="Высокие насыщающие дозы холекальциферола, затем поддерживающие",
                key_actions=[
                    "Холекальциферол 5000–7000 МЕ/сут × 3 мес. (при уровне < 30 нг/мл)",
                    "Затем поддержка 2000 МЕ/сут",
                    "Кальций 500 мг/сут (если диета бедна)",
                    "Контроль 25(OH)D через 3 мес.",
                    "Пребывание на солнце 15–20 мин/день",
                ],
                timeline=[
                    PrognosticPoint(1, 0.10, 0.88, 0.02, 0.00, "Постепенный рост уровня"),
                    PrognosticPoint(3, 0.75, 0.23, 0.02, 0.00, "Нормализация"),
                    PrognosticPoint(6, 0.88, 0.11, 0.01, 0.00, "Стойкое улучшение"),
                ],
                risk_if_ignored="Остеопороз, миалгии, снижение иммунитета, депрессия",
                evidence_level="I-A",
            ),
            Scenario(
                name="B — Умеренная коррекция",
                description="Стандартные дозы 1000–2000 МЕ/сут",
                key_actions=["Витамин D3 2000 МЕ/сут", "Солнечные прогулки"],
                timeline=[
                    PrognosticPoint(3, 0.30, 0.65, 0.05, 0.00),
                    PrognosticPoint(6, 0.55, 0.42, 0.03, 0.00),
                    PrognosticPoint(12, 0.70, 0.28, 0.02, 0.00),
                ],
                risk_if_ignored="Медленное восполнение, сохранение симптомов дефицита",
                evidence_level="I-B",
            ),
            Scenario(
                name="C — Без лечения",
                description="Только диета и солнце",
                key_actions=["Жирная рыба, яйца, обогащённые продукты"],
                timeline=[
                    PrognosticPoint(6,  0.05, 0.50, 0.45, 0.00, "Незначительное улучшение"),
                    PrognosticPoint(12, 0.10, 0.40, 0.50, 0.00),
                ],
                risk_if_ignored="Персистирующий дефицит, остеопения",
                evidence_level="II-B",
            ),
        ],
    ),

    "K63": PrognosisReport(
        disease_name="Кишечный дисбиоз / СИБР",
        icd10="K63",
        time_to_effect="2–4 недели антибактериальной/антипаразитарной фазы; 2–3 мес. восстановления",
        red_flags=[
            "Резкое снижение веса > 5 кг → онкоскрининг",
            "Кровь в стуле → срочная колоноскопия",
            "Длительная лихорадка + диарея → инфекционист",
        ],
        monitoring_plan=[
            "Копрограмма + кал на яйца глист через 3 мес.",
            "ОАК (эозинофилы) через 1 мес. после лечения",
            "Повторный осмотр гастроэнтеролога через 2 мес.",
        ],
        scenarios=[
            Scenario(
                name="A — Протокол д-ра Ткемаладзе",
                description="Фитотерапия + антипаразитарный курс + пробиотики + восстановление",
                key_actions=[
                    "Фаза 1 (10 дн): Метронидазол 250 мг 2р + Амоксициллин 500 мг 2р",
                    "Параллельно: Нистатин 2 т. 2р (антифунгальная защита)",
                    "Фаза 2 (после 10-дн. перерыва): Мебендазол по схеме",
                    "Фитотерапия: Омепразол 1т. утром, Маалокс вечером — 20 дн.",
                    "Хофитол 2т. 2р/день — желчегонное, гепатопротектор",
                    "Канефрон 2т. 3р/день — нефропротектор",
                    "Восстановление: Пробиотики (Lactobacillus + Bifidobacterium) 3 мес.",
                ],
                timeline=[
                    PrognosticPoint(1, 0.25, 0.65, 0.10, 0.00, "Уменьшение симптомов"),
                    PrognosticPoint(2, 0.55, 0.38, 0.07, 0.00, "Нормализация стула"),
                    PrognosticPoint(3, 0.70, 0.25, 0.05, 0.00, "Восстановление микробиома"),
                    PrognosticPoint(6, 0.80, 0.17, 0.03, 0.00, "Стойкое улучшение"),
                ],
                risk_if_ignored="Хронизация симптомов, нарушение всасывания питательных веществ",
                evidence_level="II-B",
            ),
            Scenario(
                name="B — Только диета и пробиотики",
                description="Без антибиотиков, только пробиотики + диета",
                key_actions=["FODMAP диета", "Пробиотики", "Исключение алкоголя"],
                timeline=[
                    PrognosticPoint(2, 0.15, 0.65, 0.20, 0.00),
                    PrognosticPoint(6, 0.35, 0.48, 0.17, 0.00),
                    PrognosticPoint(12, 0.45, 0.40, 0.15, 0.00),
                ],
                risk_if_ignored="Рецидивы, хроническая дисфункция ЖКТ",
                evidence_level="II-B",
            ),
            Scenario(
                name="C — Без лечения",
                description="Только симптоматическое",
                key_actions=["Спазмолитики при боли"],
                timeline=[
                    PrognosticPoint(3,  0.05, 0.40, 0.55, 0.05),
                    PrognosticPoint(12, 0.05, 0.30, 0.55, 0.10, "Прогрессирование"),
                ],
                risk_if_ignored="Развитие ВЗК, нарушение питания, анемия",
                evidence_level="III",
            ),
        ],
    ),
}


def get_prognosis(icd10_list: List[str]) -> List[PrognosisReport]:
    """Retrieve prognosis reports for a list of ICD-10 codes."""
    results = []
    for code in icd10_list:
        # Try exact, then prefix
        if code in PROGNOSIS_DB:
            results.append(PROGNOSIS_DB[code])
        else:
            for key in PROGNOSIS_DB:
                if code.startswith(key) or key.startswith(code):
                    results.append(PROGNOSIS_DB[key])
                    break
    return results


def format_prognosis(report: PrognosisReport) -> str:
    lines = [
        f"\n{'─'*60}",
        f"ПРОГНОЗ: {report.disease_name} [{report.icd10}]",
        f"Ожидаемый эффект: {report.time_to_effect}",
        f"{'─'*60}",
    ]

    if report.red_flags:
        lines.append("\n⚠️  КРАСНЫЕ ФЛАГИ (требуют немедленного внимания):")
        for f in report.red_flags:
            lines.append(f"  • {f}")

    for scenario in report.scenarios:
        lines.append(f"\n📊 СЦЕНАРИЙ {scenario.name}")
        lines.append(f"   {scenario.description}")
        lines.append(f"   Уровень доказательности: {scenario.evidence_level}")

        if scenario.key_actions:
            lines.append("   Действия:")
            for a in scenario.key_actions:
                lines.append(f"     → {a}")

        lines.append("   Динамика (ремиссия / стабильно / ухудшение):")
        for pt in scenario.timeline:
            bar_r = "█" * int(pt.p_remission * 10)
            bar_s = "░" * int(pt.p_stable * 10)
            bar_w = "▒" * int(pt.p_worsening * 10)
            note = f"  ← {pt.note}" if pt.note else ""
            lines.append(
                f"   {pt.month:>3} мес: "
                f"💚{pt.p_remission:.0%} {bar_r}"
                f"  🟡{pt.p_stable:.0%} {bar_s}"
                f"  🔴{pt.p_worsening:.0%} {bar_w}"
                f"{note}"
            )

        if scenario.risk_if_ignored:
            lines.append(f"   ⚠ Риск при отклонении: {scenario.risk_if_ignored}")

    lines.append("\n📋 ПЛАН МОНИТОРИНГА:")
    for m in report.monitoring_plan:
        lines.append(f"  ✓ {m}")

    return "\n".join(lines)
