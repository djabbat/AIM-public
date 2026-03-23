"""
cdata_nutrition.py — CDATA-based nutritional recommendations for AIM.

Maps the 5 postulates and 6 aging tracks of CDATA theory to specific
dietary interventions from Dr. Tkemaladze's nutrition protocol
(nutrition_rules.json).

Core CDATA logic applied here:
  - ROS↑ → centrosomal O₂-exposure → M-IDI depletion → potency loss
  - Dysbiosis → LPS/SASP → systemic ROS boost (Vicious Cycle III)
  - Inflammaging (myeloid bias) → Cycle IV feedback → accelerated damage
  - Midlife multiplier ×1.6 (age 40+): antioxidant-rich diet lowers effective
    ROS coefficient → reduces damage_scale toward longevity preset (0.6)
  - Track A (cilia): CEP164 protection via Se/Zn/anti-inflammatory nutrients
  - Track B (spindle): tubulin stability via Mg, Omega-3, low ROS
  - Track G (hypothalamic GnRH axis): tanycyte cilia require ciliary function
    → same nutrients as Track A

Usage:
    from cdata_nutrition import cdata_nutrition_recommendations, CdataFoodScore

    recs = cdata_nutrition_recommendations(age=55, damage_scale=1.2, lang="ru")
    for r in recs:
        print(r)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class CdataFoodScore:
    """A food item scored by its CDATA-protective value."""
    name: str
    cdata_tracks: List[str]       # e.g. ["Track A", "Track B", "Cycle I"]
    mechanism: str                 # molecular explanation
    key_nutrients: List[str]       # e.g. ["Mg", "Omega-3", "Se"]
    priority: str                  # "critical" | "high" | "moderate"
    age_group: str                 # "all" | "40+" | "60+"
    damage_scale_threshold: float  # recommend if damage_scale >= this
    notes_ru: str = ""
    notes_en: str = ""


@dataclass
class NutritionRecommendation:
    category: str
    headline_ru: str
    headline_en: str
    items: List[str]
    cdata_rationale_ru: str
    cdata_rationale_en: str
    priority: str  # "critical" | "high" | "moderate"


# ─── CDATA food score database ────────────────────────────────────────────────

CDATA_FOOD_SCORES: List[CdataFoodScore] = [

    # ── Antioxidants / ROS reduction (Vicious Cycle I + Track E) ──────────────

    CdataFoodScore(
        name="Ежевика, смородина, вишня, кизил, клюква",
        cdata_tracks=["Cycle I", "Track E", "Track A", "Track B"],
        mechanism=(
            "Антоцианы и полифенолы снижают ros_level → ослабляют "
            "кислородный барьер, уменьшая O₂-доступность к центриолям → "
            "замедляют деплецию M-IDI. Снижают ROS-продукцию митохондриями "
            "(Track E), улучшают mito_shield."
        ),
        key_nutrients=["антоцианы", "витамин C", "полифенолы", "флавоноиды"],
        priority="critical",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="Только в первой половине дня. Лучший источник антиоксидантов в протоколе.",
        notes_en="Morning only. Best antioxidant source in protocol.",
    ),

    CdataFoodScore(
        name="Чёрный тмин (гицрули / нигелла)",
        cdata_tracks=["Cycle I", "Track A", "Track B"],
        mechanism=(
            "Тимохинон — мощный антиоксидант (витамины A, E, бета-каротин, биотин). "
            "Снижает carbonylation_level и ros_level. Защита почек и печени от "
            "окислительного повреждения → снижение системного SASP (Cycle III)."
        ),
        key_nutrients=["тимохинон", "витамины A/E/F/B1/B3/B6", "бета-каротин", "биотин"],
        priority="high",
        age_group="40+",
        damage_scale_threshold=1.0,
        notes_ru="Семена. Небольшие количества ежедневно.",
    ),

    CdataFoodScore(
        name="Базилик (рехан, особенно фиолетовый)",
        cdata_tracks=["Cycle I", "Track A"],
        mechanism=(
            "Ca, Fe, Mn, витамины A/K/C, фолиевая кислота, антиоксиданты. "
            "Фолат необходим для репарации ДНК (DDRState) и снижает methylation_age."
        ),
        key_nutrients=["Ca", "Fe", "Mn", "витамин C", "фолиевая кислота"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    CdataFoodScore(
        name="Шафран",
        cdata_tracks=["Cycle I", "Track D"],
        mechanism=(
            "Кроцин и кроцетин — антиоксиданты, ингибируют липидное перокисление. "
            "Снижают clock_acceleration (Track D — эпигенетические часы) "
            "при хроническом применении."
        ),
        key_nutrients=["кроцин", "кроцетин", "сафранал"],
        priority="moderate",
        age_group="40+",
        damage_scale_threshold=1.0,
    ),

    CdataFoodScore(
        name="Бархатец имеретинский (шафран имеретинский)",
        cdata_tracks=["Cycle I", "Track B"],
        mechanism=(
            "P, Se, Ca, Na, Mg, K, Fe, Zn, Mn; витамины A/P/C/B. "
            "Se — кофактор тиоредоксинредуктазы и глутатионпероксидазы → защита "
            "центриолей от окисления. Zn поддерживает структурную целостность "
            "CEP164 и других центриолярных белков (Track A)."
        ),
        key_nutrients=["Se", "Zn", "Mg", "P", "витамин C"],
        priority="high",
        age_group="40+",
        damage_scale_threshold=1.0,
    ),

    # ── Mg / Tubulin / Spindle (Track B) ──────────────────────────────────────

    CdataFoodScore(
        name="Ботва свёклы (пхали) — ОСНОВНОЙ источник Mg",
        cdata_tracks=["Track B", "Track A"],
        mechanism=(
            "Mg — главный кофактор полимеризации тубулина и стабилизации "
            "митотического веретена. Дефицит Mg → spindle_fidelity↓ → "
            "симметричные деления → истощение стволового пула (Track B). "
            "Хлорофилл → снижение ROS (Track E побочно)."
        ),
        key_nutrients=["Mg", "хлорофилл", "клетчатка"],
        priority="critical",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="ОСНОВНОЙ источник Mg по протоколу. Ежедневно.",
        notes_en="PRIMARY Mg source in protocol. Daily.",
    ),

    CdataFoodScore(
        name="Крапива",
        cdata_tracks=["Track B", "Cycle I"],
        mechanism=(
            "Железо, магний, хлорофилл. Mg поддерживает spindle_fidelity. "
            "Fe нужен для рибонуклеотидредуктазы (синтез ДНК при делениях)."
        ),
        key_nutrients=["Mg", "Fe", "хлорофилл"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    CdataFoodScore(
        name="Стручковая (зелёная) фасоль",
        cdata_tracks=["Track B"],
        mechanism="Ca, Mg — поддержка веретена и кариокинеза.",
        key_nutrients=["Ca", "Mg"],
        priority="moderate",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    # ── Se / Zn / CEP164 (Track A — Цилии) ────────────────────────────────────

    CdataFoodScore(
        name="Жирная рыба (скумбрия, сардины, лосось)",
        cdata_tracks=["Track A", "Track G", "Cycle IV"],
        mechanism=(
            "Omega-3 EPA+DHA → снижение inflammaging_index (Cycle IV) → "
            "уменьшение myeloid_bias → торможение vicious cycle IV. "
            "Se защищает CEP164 от карбонилирования → ciliary_function↑ (Track A). "
            "Йод необходим для функции гипоталамо-гипофизарной оси (Track G)."
        ),
        key_nutrients=["Omega-3 EPA/DHA", "Se", "йод", "витамин D"],
        priority="critical",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="Морская рыба предпочтительна. 2–3 раза в неделю.",
        notes_en="Marine fish preferred. 2-3 times/week.",
    ),

    CdataFoodScore(
        name="Грецкий орех (свежеколотый)",
        cdata_tracks=["Track A", "Track B", "Cycle I"],
        mechanism=(
            "Лучший растительный источник Omega-3 (АЛК) → противовоспалительное → "
            "Cycle IV торможение. Mg, Zn, Mn, B6, E, K. "
            "Zn критичен для структуры центриолярного цилиарного аппарата. "
            "ТОЛЬКО свежеколотый: АЛК быстро окисляется до провоспалительных метаболитов."
        ),
        key_nutrients=["Omega-3 АЛК", "Mg", "Zn", "Mn", "витамины B6/E"],
        priority="critical",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="ТОЛЬКО свежеколотый! Покупной пакетированный — запрещён.",
        notes_en="FRESHLY SHELLED only! Pre-packaged is oxidized.",
    ),

    CdataFoodScore(
        name="Миндаль (свежеколотый, необжаренный)",
        cdata_tracks=["Track A", "Track B"],
        mechanism=(
            "Mg, Zn, Ca, витамин D, E, Omega-3. "
            "Витамин D → рецептор VDR активирует гены репарации ДНК (DDRState) "
            "и снижает p21_level → меньше сенесцентных клеток. "
            "ТОЛЬКО свежеколотый."
        ),
        key_nutrients=["Mg", "витамин D", "Zn", "Ca", "витамин E"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="ТОЛЬКО свежеколотый, необжаренный.",
    ),

    # ── Anti-inflammaging (Cycle IV + Cycle III) ───────────────────────────────

    CdataFoodScore(
        name="Квашеные овощи (огурцы, патиссоны, брокколи, фасоль, джонджоли)",
        cdata_tracks=["Cycle III", "Cycle IV"],
        mechanism=(
            "Живые пробиотики восстанавливают микробиом → снижают кишечную "
            "проницаемость → снижают LPS-нагрузку → меньше системного SASP "
            "(Cycle III: senescent niche). Опосредованно снижают ros_boost "
            "и niche_impairment из InflammagingState."
        ),
        key_nutrients=["пробиотики", "лактат", "Ca"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru=(
            "Замена коммерческих дрожжей квашеными овощами — ключевой шаг. "
            "Коммерческие дрожжи крадут Zn → дефицит → центриолярная нестабильность."
        ),
    ),

    CdataFoodScore(
        name="Кинза (кориандр зелень)",
        cdata_tracks=["Cycle III", "Cycle IV"],
        mechanism=(
            "Мочегонное, дезинфицирующее, противогрибковое → подавляет Candida → "
            "снижает кишечный воспалительный фон → меньше SASP (Cycle III)."
        ),
        key_nutrients=["эфирные масла", "флавоноиды"],
        priority="moderate",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    CdataFoodScore(
        name="Чабер (кондари)",
        cdata_tracks=["Cycle III", "Track A"],
        mechanism=(
            "Очищает кровь, улучшает ЖКТ, убивает инфекции в лёгких и "
            "мочеполовых путях. Снижает микробную нагрузку → меньше системного SASP."
        ),
        key_nutrients=["карвакрол", "тимол"],
        priority="moderate",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    # ── Caloric restriction / IGF-1 axis (Track G + midlife ×1.6) ─────────────

    CdataFoodScore(
        name="Кислые минеральные воды",
        cdata_tracks=["Cycle I", "Track G"],
        mechanism=(
            "Поддерживают кислый pH желудка → оптимальный пепсин → полное "
            "переваривание белков → меньше AGEP (конечных продуктов гликирования) → "
            "меньше ROS (Cycle I). Обеспечивают гидратацию гипоталамуса "
            "(танициты требуют адекватной гидратации для GnRH-секреции, Track G)."
        ),
        key_nutrients=["минеральные соли", "кислый pH"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
    ),

    # ── Protein quality / B12 / Heme Fe (general stem cell support) ───────────

    CdataFoodScore(
        name="Яйца вкрутую (40–90 мин) куриные пастбищные",
        cdata_tracks=["Track B", "Track D"],
        mechanism=(
            "97–98% усвоение: все аминокислоты, Se, Zn, B12, холин. "
            "B12 — кофактор метилирования (снижает clock_acceleration, Track D). "
            "Se+Zn → центриолярная защита. Холин → синтез ацетилхолина "
            "(нейрональные стволовые клетки, Track G)."
        ),
        key_nutrients=["Se", "Zn", "B12", "холин", "все аминокислоты"],
        priority="critical",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="ТОЛЬКО вкрутую (40–90 мин). Сырые/всмятку — запрещены (раздражают желчный проток).",
    ),

    CdataFoodScore(
        name="Говядина пастбищная / баранина (обескровленная)",
        cdata_tracks=["Track B", "Track D"],
        mechanism=(
            "Гемовое Fe (биодоступность 15–35%) → нормальная митохондриальная "
            "цепь переноса электронов → меньше митохондриального ROS-слива (Track E). "
            "Zn, B12 → метилирование и центриолярная защита."
        ),
        key_nutrients=["гемовое Fe", "Zn", "B12", "Omega-6:Omega-3 = 3–4:1"],
        priority="high",
        age_group="all",
        damage_scale_threshold=0.8,
        notes_ru="Обескровленная. Без кожи. Омега-6:Omega-3 = 3–4:1 у пастбищного скота.",
    ),
]


# ─── Recommendation engine ────────────────────────────────────────────────────

# Foods to strictly AVOID — key CDATA rationale (excerpted from nutrition_rules.json)
CDATA_FORBIDDEN_RATIONALE = {
    "Коммерческие дрожжи (хлебопекарные, пивные)": (
        "Крадут Zn, Mg, Ca, B-витамины → дефицит Zn разрушает структуру центриолярных белков "
        "(CEP164, SAS-6) → ciliary_function↓ (Track A). 9 месяцев для очищения."
    ),
    "Промышленный хлеб на коммерческих дрожжах": (
        "Та же причина: дрожжевые колонии в кишечнике → Zn/Mg-кража → центриолярная нестабильность."
    ),
    "Мёд и свежевыжатые соки (свободная фруктоза)": (
        "Свободная фруктоза → печёночный de novo липогенез → оксидативный стресс → "
        "ros_level↑ → ускоренная деплеция M-IDI (Cycle I)."
    ),
    "Маргарин (трансжиры)": (
        "Трансжиры встраиваются в мембраны митохондрий → mito_shield↓ → "
        "O₂ проникает к центриолям → accelerated M-IDI depletion (Track E + Cycle I)."
    ),
    "Свинина (арахидоновая кислота)": (
        "AA → PGE2 → NF-κB → системное воспаление → inflammaging_index↑ → "
        "Vicious Cycle IV активация → ускоренный мyeloid сдвиг."
    ),
    "Сырая морковь и морковный сок": (
        "Раздражает желчный проток → холестаз → нарушение выведения "
        "желчных кислот → токсическая нагрузка на печень → SASP↑ (Cycle III)."
    ),
    "Помидоры (альфа-томатин / холестаз)": (
        "Сапонин альфа-томатин → холестаз → нарушение желчного оттока → "
        "системная воспалительная нагрузка → Cycle III."
    ),
    "Оливковое масло": (
        "Раздражает желчный проток при нагреве; нерафинированное окисляется → "
        "aldehydy → carbonylation_level↑ (PTM на центриолях)."
    ),
}


def cdata_nutrition_recommendations(
    age: float = 45.0,
    damage_scale: float = 1.0,
    lang: str = "ru",
    top_n: int = 8,
) -> List[NutritionRecommendation]:
    """
    Generate CDATA-based nutritional recommendations.

    Args:
        age:          Patient age in years.
        damage_scale: CDATA damage scale (1.0=normal, >1.0=accelerated).
        lang:         "ru" | "en" | "ka"
        top_n:        Maximum number of recommendation blocks to return.

    Returns:
        List of NutritionRecommendation (sorted critical → high → moderate).
    """
    age_group_ok = lambda fs: (
        fs.age_group == "all"
        or (fs.age_group == "40+" and age >= 40)
        or (fs.age_group == "60+" and age >= 60)
    )

    relevant = [
        fs for fs in CDATA_FOOD_SCORES
        if age_group_ok(fs) and damage_scale >= fs.damage_scale_threshold
    ]

    priority_order = {"critical": 0, "high": 1, "moderate": 2}
    relevant.sort(key=lambda fs: priority_order.get(fs.priority, 3))

    recs: List[NutritionRecommendation] = []

    # Build grouped recommendations
    seen = set()
    for fs in relevant:
        if fs.name in seen:
            continue
        seen.add(fs.name)

        tracks_str = ", ".join(fs.cdata_tracks)
        nutrients_str = ", ".join(fs.key_nutrients[:4])

        if lang == "ru":
            headline = f"[{fs.priority.upper()}] {fs.name}"
            rationale = (
                f"CDATA треки: {tracks_str}. "
                f"Ключевые нутриенты: {nutrients_str}. "
                f"{fs.mechanism}"
                + (f" {fs.notes_ru}" if fs.notes_ru else "")
            )
            items = [fs.name]
        else:
            headline = f"[{fs.priority.upper()}] {fs.name}"
            rationale = (
                f"CDATA tracks: {tracks_str}. "
                f"Key nutrients: {nutrients_str}. "
                f"{fs.mechanism}"
                + (f" {fs.notes_en}" if fs.notes_en else "")
            )
            items = [fs.name]

        recs.append(NutritionRecommendation(
            category=fs.cdata_tracks[0] if fs.cdata_tracks else "General",
            headline_ru=headline if lang == "ru" else fs.name,
            headline_en=headline if lang == "en" else fs.name,
            items=items,
            cdata_rationale_ru=rationale if lang == "ru" else fs.mechanism,
            cdata_rationale_en=rationale if lang == "en" else fs.mechanism,
            priority=fs.priority,
        ))

        if len(recs) >= top_n:
            break

    return recs


def cdata_nutrition_text(
    age: float = 45.0,
    damage_scale: float = 1.0,
    lang: str = "ru",
) -> str:
    """
    Format CDATA nutrition recommendations as a human-readable text block
    for inclusion in AIM patient reports.

    Args:
        age:          Patient age in years.
        damage_scale: CDATA damage_scale (from run_cdata_sim / damage_scale_from_risk).
        lang:         "ru" | "en" | "ka"

    Returns:
        Multi-line formatted string.
    """
    recs = cdata_nutrition_recommendations(age=age, damage_scale=damage_scale, lang=lang)

    if lang == "ru":
        midlife_note = (
            "\n  ⚠ После 40 лет CDATA-модель фиксирует ×1.6 ускорение накопления "
            "повреждений (антагонистическая плейотропия). Антиоксидантная диета "
            "снижает эффективный коэффициент damage_scale → longevity preset (0.6)."
            if age >= 40 else ""
        )
        header = (
            "═══ CDATA Нутрициологические рекомендации ═══\n"
            f"  (возраст: {age:.0f} лет, уровень повреждений: {damage_scale:.1f}×)"
            + midlife_note
        )
        forbidden_header = "\n  ─── Исключить (CDATA-обоснование) ───"
        separator = "═" * 44
    elif lang == "ka":
        header = (
            "═══ CDATA კვების რეკომენდაციები ═══\n"
            f"  (ასაკი: {age:.0f} წ., დაზიანების დონე: {damage_scale:.1f}×)"
        )
        forbidden_header = "\n  ─── გამორიცხვა (CDATA-საფუძველი) ───"
        separator = "═" * 44
    else:
        midlife_note = (
            "\n  ⚠ After age 40 CDATA documents ×1.6 damage acceleration "
            "(antagonistic pleiotropy). Antioxidant diet lowers effective "
            "damage_scale toward longevity preset (0.6)."
            if age >= 40 else ""
        )
        header = (
            "═══ CDATA Nutrition Recommendations ═══\n"
            f"  (age: {age:.0f}y, damage scale: {damage_scale:.1f}×)"
            + midlife_note
        )
        forbidden_header = "\n  ─── Eliminate (CDATA rationale) ───"
        separator = "═" * 44

    lines = [header, ""]

    for rec in recs:
        headline = rec.headline_ru if lang == "ru" else rec.headline_en
        rationale = rec.cdata_rationale_ru if lang == "ru" else rec.cdata_rationale_en
        lines.append(f"  • {headline}")
        # Wrap rationale to ~80 chars
        words = rationale.split()
        line = "    "
        for w in words:
            if len(line) + len(w) + 1 > 80:
                lines.append(line)
                line = "    " + w + " "
            else:
                line += w + " "
        if line.strip():
            lines.append(line)
        lines.append("")

    # Add forbidden section (top 4 most important)
    lines.append(forbidden_header)
    top_forbidden = list(CDATA_FORBIDDEN_RATIONALE.items())[:4]
    for food, rationale in top_forbidden:
        lines.append(f"  ✗ {food}")
        lines.append(f"    {rationale[:120]}...")
        lines.append("")

    lines.append(separator)
    return "\n".join(lines)


def damage_scale_from_diet(diet_notes: str) -> float:
    """
    Estimate CDATA damage_scale adjustment from dietary habits description.

    Positive adjustment (worse): dysbiosis-promoting foods
    Negative adjustment (better): CDATA-protective foods

    Returns delta to add to base damage_scale.
    """
    notes_lower = diet_notes.lower()
    delta = 0.0

    # Dysbiosis → increases effective ROS (Vicious Cycle III)
    if any(k in notes_lower for k in ("дрожж", "yeast", "пивн", "beer")):
        delta += 0.20
    if any(k in notes_lower for k in ("свинин", "pork", "сало")):
        delta += 0.15
    if any(k in notes_lower for k in ("маргарин", "margarin", "трансжир", "trans fat")):
        delta += 0.25

    # Anti-CDATA lifestyle
    if any(k in notes_lower for k in ("мёд", "honey", "свежевыжат", "fresh juice")):
        delta += 0.10
    if any(k in notes_lower for k in ("молоко", "milk", "кефир", "йогурт", "yogurt")):
        delta += 0.10

    # Protective
    if any(k in notes_lower for k in ("рыб", "fish", "скумбри", "сардин", "лосос", "salmon")):
        delta -= 0.10
    if any(k in notes_lower for k in ("грецк", "walnut", "миндал", "almond")):
        delta -= 0.08
    if any(k in notes_lower for k in ("ежевик", "blackberr", "смородин", "currant")):
        delta -= 0.08
    if any(k in notes_lower for k in ("квашен", "ferment", "пробиотик", "probiotic")):
        delta -= 0.08

    return round(max(-0.40, min(delta, 0.50)), 2)


# ─── CLI self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    age = float(sys.argv[1]) if len(sys.argv) > 1 else 55.0
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 1.2
    lang = sys.argv[3] if len(sys.argv) > 3 else "ru"
    print(cdata_nutrition_text(age=age, damage_scale=scale, lang=lang))
