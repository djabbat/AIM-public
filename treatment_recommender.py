#!/usr/bin/env python3
"""
Evidence-based treatment recommender.
Generates treatment protocols per diagnosis with:
  - First-line, second-line treatments
  - Doses, routes, duration
  - Drug interactions
  - Contraindications
  - Lifestyle recommendations
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Drug:
    name: str
    dose: str
    route: str       # "per os" | "в/м" | "в/в" | "местно"
    frequency: str
    duration: str
    notes: str = ""
    contraindications: List[str] = field(default_factory=list)
    interactions: List[str] = field(default_factory=list)


@dataclass
class TreatmentProtocol:
    disease_name: str
    icd10: str
    line: str              # "Первая линия" | "Вторая линия" | "Адъювантная"
    drugs: List[Drug]
    lifestyle: List[str]
    follow_up: str
    notes: str = ""
    evidence_level: str = "II-B"


TREATMENT_DB: Dict[str, List[TreatmentProtocol]] = {

    "D50": [
        TreatmentProtocol(
            disease_name="Железодефицитная анемия",
            icd10="D50",
            line="Первая линия",
            evidence_level="I-A",
            drugs=[
                Drug("Сульфат железа (Сорбифер Дурулес)", "100 мг Fe²⁺",
                     "per os", "2 р/сут", "3–6 мес.",
                     "За 30 мин до еды, запивать водой с C-витамином",
                     contraindications=["ЯБЖ в стадии обострения", "гемохроматоз"],
                     interactions=["тетрациклины", "антациды (разделить на 2 ч)"]),
                Drug("Аскорбиновая кислота", "500 мг", "per os",
                     "вместе с железом", "весь курс",
                     "Улучшает всасывание Fe²⁺ в 2–3 раза"),
            ],
            lifestyle=[
                "Красное мясо, субпродукты (печень), шпинат — ежедневно",
                "Исключить кофе/чай за 1 час до и после приёма железа",
                "Готовить в чугунной посуде",
                "При меноррагии → гинеколог обязательно",
            ],
            follow_up="ОАК + ферритин через 4 недели, затем через 3 и 6 месяцев",
        ),
        TreatmentProtocol(
            disease_name="Железодефицитная анемия — IV форма",
            icd10="D50",
            line="При непереносимости пероральных форм",
            evidence_level="I-A",
            drugs=[
                Drug("Феринжект (сахарозный комплекс железа)", "500–1000 мг",
                     "в/в капельно", "1–3 введения", "по схеме",
                     "Под наблюдением врача, реакции гиперчувствительности редки",
                     contraindications=["первый триместр беременности"]),
            ],
            lifestyle=["Те же, что при пероральной терапии"],
            follow_up="ОАК + ферритин через 4 нед.",
        ),
    ],

    "E03": [
        TreatmentProtocol(
            disease_name="Гипотиреоз",
            icd10="E03",
            line="Первая линия",
            evidence_level="I-A",
            drugs=[
                Drug("Левотироксин натрий (Эутирокс)", "1.6–1.8 мкг/кг/сут",
                     "per os", "1 р/сут (утром, натощак)", "пожизненно",
                     "За 30–60 мин до завтрака; отдельно от Са, Fe, антацидов",
                     contraindications=["тиреотоксикоз", "острый инфаркт"],
                     interactions=["варфарин (+LR доза)", "метформин", "антациды"]),
            ],
            lifestyle=[
                "Исключить избыток сои и сырых крестоцветных",
                "Нормализовать сон (8 ч)",
                "Физическая активность умеренная",
                "Контроль ТТГ каждые 6–8 нед. при подборе дозы",
                "При Хашимото: безглютеновая диета (обсуждается, уровень II-B)",
            ],
            follow_up="ТТГ + Т4 своб. через 6–8 нед.; затем ежегодно при стабильном ТТГ",
        ),
        TreatmentProtocol(
            disease_name="Гипотиреоз — субклинический",
            icd10="E03",
            line="При ТТГ 4–10 мIU/L без симптомов",
            evidence_level="II-B",
            drugs=[
                Drug("Наблюдение / L-тироксин при симптомах", "25–50 мкг/сут",
                     "per os", "1 р/сут", "По решению эндокринолога",
                     "ТТГ > 10 → лечение обязательно"),
            ],
            lifestyle=["Достаточный йод (150–250 мкг/сут)", "Контроль ТТГ каждые 6 мес."],
            follow_up="ТТГ каждые 6 мес.",
        ),
    ],

    "F41": [
        TreatmentProtocol(
            disease_name="Тревожное расстройство",
            icd10="F41",
            line="Первая линия",
            evidence_level="I-A",
            drugs=[
                Drug("Эсциталопрам (СИОЗС)", "10 мг → 20 мг",
                     "per os", "1 р/сут (утром)", "минимум 6–12 мес.",
                     "Первые 2 нед. возможно усиление тревоги — нормально",
                     contraindications=["MAO ингибиторы"],
                     interactions=["трамадол", "триптаны", "варфарин"]),
                Drug("Феназепам (только краткосрочно!)", "0.25–0.5 мг",
                     "per os", "при острой панике", "до 2–4 нед.",
                     "Риск зависимости — не более 2 нед.",
                     contraindications=["глаукома", "беременность"]),
            ],
            lifestyle=[
                "Когнитивно-поведенческая терапия (КПТ) — 12–20 сессий (стандарт)",
                "Аэробные нагрузки 30 мин/день × 3–5 р/нед.",
                "Медитация осознанности (MBSR) — снижает кортизол на 25–30%",
                "Диафрагмальное дыхание (4-7-8) при приступах",
                "Исключить кофеин > 2 чашек/день",
                "Режим сна: ложиться и вставать в одно время",
            ],
            follow_up="GAD-7 шкала ежемесячно; визит психиатра через 4 нед.",
        ),
        TreatmentProtocol(
            disease_name="Тревожное расстройство — нутрицевтики",
            icd10="F41",
            line="Адъювантная",
            evidence_level="II-B",
            drugs=[
                Drug("5-HTP (5-гидрокситриптофан)", "100 мг",
                     "per os", "2 р/сут (с едой)", "3–6 мес.",
                     "Прекурсор серотонина. Не сочетать с СИОЗС!",
                     interactions=["СИОЗС (синдром серотонина)", "MAO ингибиторы"]),
                Drug("Фенибут", "250 мг",
                     "per os", "1 р/сут вечером", "не более 4 нед.",
                     "Анксиолитик. Риск зависимости при длительном приёме",
                     contraindications=["беременность", "тяжёлая печёночная нед."]),
                Drug("Магний B6 (Магне B6)", "300–400 мг Mg",
                     "per os", "2 р/сут", "3 мес.",
                     "Снижает возбудимость нервной системы, улучшает сон"),
            ],
            lifestyle=[
                "Ашваганда (Withania somnifera) — снижает кортизол (уровень I-B)",
                "Валериана 600 мг/сут при нарушениях сна",
            ],
            follow_up="Повторная оценка симптомов через 4 нед.",
        ),
    ],

    "E55": [
        TreatmentProtocol(
            disease_name="Дефицит витамина D",
            icd10="E55",
            line="Первая линия",
            evidence_level="I-A",
            drugs=[
                Drug("Холекальциферол (D3)", "5000–7000 МЕ/сут",
                     "per os", "1 р/сут", "3 мес., затем 2000 МЕ/сут поддержка",
                     "Принимать с жирной едой для всасывания",
                     contraindications=["гиперкальциемия", "саркоидоз"]),
                Drug("Кальций карбонат (при необходимости)", "500–1000 мг",
                     "per os", "с едой, делить дозу", "постоянно при дефиците",
                     "Не сочетать с железом (разделить на 2–3 ч)",
                     interactions=["железо", "тетрациклины", "левотироксин"]),
            ],
            lifestyle=[
                "Жирная рыба (лосось, сардины) 2–3 р/нед.",
                "Пребывание на солнце 15–20 мин (руки + лицо) в полдень",
                "Яйца, обогащённые молочные продукты",
            ],
            follow_up="25(OH)D через 3 мес., затем ежегодно",
        ),
    ],

    "K63": [
        TreatmentProtocol(
            disease_name="Кишечный дисбиоз / Паразитарная инвазия",
            icd10="K63",
            line="Протокол курсовой терапии",
            evidence_level="II-B",
            drugs=[
                Drug("Метронидазол 250 мг", "250 мг",
                     "per os", "2 р/сут после еды", "10 дн.",
                     "Против простейших, анаэробов, H.pylori"),
                Drug("Амоксициллин 500 мг", "500 мг",
                     "per os", "2 р/сут после еды", "10 дн.",
                     "Широкий спектр; пробиотик обязателен параллельно",
                     contraindications=["аллергия на пенициллины"]),
                Drug("Нистатин", "500 000 МЕ (2 таб)",
                     "per os", "2 р/сут после еды", "10 дн. + 10 дн. перерыв, повтор",
                     "Профилактика кандидоза на фоне АБ"),
                Drug("Мебендазол (Вермокс)", "100–200 мг",
                     "per os", "по схеме (3 дня)", "повторить через 2 нед.",
                     "Широкий антигельминтный спектр"),
                Drug("Омепразол 20 мг", "20 мг",
                     "per os", "1 р/сут за 30 мин до завтрака", "10 дн.",
                     "Защита слизистой ЖКТ"),
                Drug("Хофитол", "2 таб",
                     "per os", "2 р/сут (до еды)", "20 дн.",
                     "Желчегонный, гепатопротекторный"),
                Drug("Канефрон", "2 таб",
                     "per os", "3 р/сут после еды", "1 мес.",
                     "Нефропротекция при антибиотиках"),
                Drug("Пробиотик (Lactobacillus rhamnosus GG)", "10⁹ КОЕ",
                     "per os", "2 р/сут", "3 мес. после курса АБ",
                     "Начать на 3-й день АБ, продолжать 3 мес."),
            ],
            lifestyle=[
                "Исключить сахар, алкоголь, дрожжевые продукты на время лечения",
                "FODMAP диета при СРК",
                "Обработка воды (кипячение или фильтрация)",
                "Гигиена рук после туалета, контакта с животными",
            ],
            follow_up="Кал на яйца глист, ОАК (эозинофилы) через 1 мес.",
        ),
    ],

    "D51": [
        TreatmentProtocol(
            disease_name="Дефицит витамина B12",
            icd10="D51",
            line="Первая линия",
            evidence_level="I-A",
            drugs=[
                Drug("Цианокобаламин (в/м)", "1000 мкг",
                     "в/м", "1 р/сут", "7–10 дн., затем 1 р/мес.",
                     "При тяжёлом дефиците или мальабсорбции — в/м"),
                Drug("Метилкобаламин (per os)", "1000–2000 мкг",
                     "per os", "1 р/сут", "3–6 мес.",
                     "При нетяжёлом дефиците без неврологии; активная форма"),
                Drug("Фолиевая кислота (при дефиците фолатов)", "1–5 мг",
                     "per os", "1 р/сут", "3 мес.",
                     "Только после исключения/коррекции дефицита B12!"),
            ],
            lifestyle=[
                "Мясо, рыба, молочные, яйца — основные источники B12",
                "Вегетарианцы/веганы: B12 необходим постоянно",
                "При гастрите с АТ к внутреннему фактору — только парентеральный путь",
            ],
            follow_up="B12, ОАК через 3 мес.",
        ),
    ],

    "N18": [
        TreatmentProtocol(
            disease_name="Хроническая болезнь почек (ранняя стадия)",
            icd10="N18",
            line="Нефропротективная терапия",
            evidence_level="I-A",
            drugs=[
                Drug("Рамиприл (иАПФ)", "2.5–10 мг",
                     "per os", "1 р/сут", "постоянно",
                     "Снижает протеинурию, замедляет прогрессию ХБП",
                     contraindications=["беременность", "гиперкалиемия > 5.5"],
                     interactions=["НПВС", "калийсберегающие диуретики"]),
            ],
            lifestyle=[
                "Ограничение белка 0.6–0.8 г/кг/сут",
                "Контроль АД < 130/80 мм рт.ст.",
                "Отказ от НПВС (ибупрофен, диклофенак)",
                "Адекватная гидратация 1.5–2 л/сут",
                "Контроль гликемии при СД",
            ],
            follow_up="Креатинин + СКФ каждые 3 мес.; нефролог",
        ),
    ],
}


# ─────────────────────────────────────────────────────────────
# Drug interaction checker (simplified)
# ─────────────────────────────────────────────────────────────

KNOWN_INTERACTIONS = {
    frozenset(["5-HTP", "эсциталопрам"]): "⚠️ СЕРОТОНИНОВЫЙ СИНДРОМ — не сочетать!",
    frozenset(["5-HTP", "СИОЗС"]):         "⚠️ СЕРОТОНИНОВЫЙ СИНДРОМ — не сочетать!",
    frozenset(["метронидазол", "алкоголь"]): "❌ Реакция Антабуса — строго исключить алкоголь",
    frozenset(["левотироксин", "кальций"]):  "🟡 Разделить на 2–3 ч (снижение всасывания тироксина)",
    frozenset(["левотироксин", "железо"]):   "🟡 Разделить на 2–3 ч",
    frozenset(["варфарин", "аспирин"]):      "⚠️ Высокий риск кровотечения",
    frozenset(["нистатин", "амфотерицин"]): "🟡 Возможно снижение эффекта нистатина",
}


def check_interactions(drug_names: List[str]) -> List[str]:
    warnings = []
    names_lower = [n.lower() for n in drug_names]
    for pair, warning in KNOWN_INTERACTIONS.items():
        pair_lower = {p.lower() for p in pair}
        if pair_lower.issubset(set(names_lower)):
            warnings.append(warning)
    return warnings


def get_protocols(icd10_list: List[str]) -> List[TreatmentProtocol]:
    protocols = []
    for code in icd10_list:
        for key in TREATMENT_DB:
            if code == key or code.startswith(key) or key.startswith(code.split(".")[0]):
                protocols.extend(TREATMENT_DB[key])
    return protocols


def format_treatment(protocols: List[TreatmentProtocol],
                     existing_drugs: List[str] = None) -> str:
    if not protocols:
        return "  Протоколы лечения не найдены для данных диагнозов"

    lines = ["\n=== РЕКОМЕНДАЦИИ ПО ЛЕЧЕНИЮ ===\n"]

    # Check interactions across all protocols
    all_drugs = [d.name for p in protocols for d in p.drugs]
    if existing_drugs:
        all_drugs += existing_drugs
    interactions = check_interactions(all_drugs)
    if interactions:
        lines.append("⚠️  ВАЖНО — ЛЕКАРСТВЕННЫЕ ВЗАИМОДЕЙСТВИЯ:")
        for w in interactions:
            lines.append(f"  {w}")
        lines.append("")

    for proto in protocols:
        lines.append(f"{'─'*60}")
        lines.append(f"📋 {proto.disease_name} [{proto.icd10}]")
        lines.append(f"   {proto.line}  |  Уровень доказательности: {proto.evidence_level}")
        lines.append("")
        lines.append("   Медикаментозное лечение:")
        for drug in proto.drugs:
            lines.append(f"   • {drug.name}")
            lines.append(f"     Доза: {drug.dose}  |  {drug.route}  |  {drug.frequency}  |  {drug.duration}")
            if drug.notes:
                lines.append(f"     ℹ {drug.notes}")
            if drug.contraindications:
                lines.append(f"     ⛔ Противопоказания: {', '.join(drug.contraindications)}")
            if drug.interactions:
                lines.append(f"     ↔ Взаимодействия: {', '.join(drug.interactions)}")

        if proto.lifestyle:
            lines.append("\n   Немедикаментозные рекомендации:")
            for rec in proto.lifestyle:
                lines.append(f"   ✓ {rec}")

        lines.append(f"\n   📅 Контроль: {proto.follow_up}")
        lines.append("")

    return "\n".join(lines)
