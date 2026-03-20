#!/usr/bin/env python3
"""
regenesis_protocol.py — Протокол Regenesis: растительные экстракты для продления жизни.

Проект Regenesis — создание биологически активных продуктов из растений:
  биодобавки, мыло, свечи, эфирные масла, кремы и т.п.
  для улучшения качества жизни и продления жизни.

Модуль содержит:
  1. Базу данных растительных экстрактов (PLANT_EXTRACTS)
  2. Базу готовых протоколов продуктов (PRODUCT_PROTOCOLS)
  3. Функцию поиска по показанию / свойству
  4. Функцию генерации рецептуры через DeepSeek
  5. Импорт всей базы в AIM Knowledge Graph

Запуск:
  cd ~/AIM && source venv/bin/activate
  python3 regenesis_protocol.py                        # показать все протоколы
  python3 regenesis_protocol.py --search антиоксидант  # поиск по свойству
  python3 regenesis_protocol.py --import-kg            # импорт в AIM KG
  python3 regenesis_protocol.py --generate "крем от морщин"  # генерация рецептуры через AI
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

# ---------------------------------------------------------------------------
# База растительных экстрактов
# ---------------------------------------------------------------------------

PLANT_EXTRACTS = [
    {
        "id":         "rosehip",
        "name_ru":    "Шиповник (Rosa canina)",
        "name_ka":    "ხამვეული",
        "active":     ["Витамин C (3000 мг/100г)", "Флавоноиды", "Каротиноиды", "Дубильные вещества"],
        "properties": ["антиоксидант", "иммуностимулятор", "противовоспалительное", "ранозаживляющее"],
        "products":   ["чай", "сироп", "крем", "масло", "биодобавка"],
        "cdata_link": "снижает ROS → замедляет Трек E (митохондрии) и Трек A (цилии)",
        "notes":      "Самый богатый природный источник витамина C. В кремах — антиэйджинг.",
    },
    {
        "id":         "lavender",
        "name_ru":    "Лаванда (Lavandula angustifolia)",
        "name_ka":    "ლავანდა",
        "active":     ["Линалоол", "Линалилацетат", "Камфора", "1,8-цинеол"],
        "properties": ["успокаивающее", "антисептик", "антиоксидант", "снижает кортизол",
                       "улучшает сон"],
        "products":   ["эфирное масло", "свеча", "крем", "мыло", "диффузор"],
        "cdata_link": "снижение кортизола → меньше ROS → замедление накопления PTM-повреждений",
        "notes":      "Основа аромотерапии. Лавандовые свечи — самый популярный Regenesis-продукт.",
    },
    {
        "id":         "frankincense",
        "name_ru":    "Ладан (Boswellia sacra)",
        "name_ka":    "საკმეველი",
        "active":     ["Босвелиевые кислоты (AKBA)", "α-пинен", "β-пинен", "Лимонен"],
        "properties": ["мощное противовоспалительное (ингибитор 5-LOX)", "антиоксидант",
                       "нейропротектор", "улучшает когнитивные функции"],
        "products":   ["эфирное масло", "смола (курение)", "свеча", "биодобавка", "крем"],
        "cdata_link": "AKBA ингибирует NF-κB → снижает inflammaging (Трек миелоидного сдвига)",
        "notes":      "Традиционный грузинский и ближневосточный sacral plant. "
                      "AKBA = один из сильнейших природных ингибиторов воспаления.",
    },
    {
        "id":         "st_johns_wort",
        "name_ru":    "Зверобой (Hypericum perforatum)",
        "name_ka":    "ნემსიყლაპია",
        "active":     ["Гиперицин", "Гиперфорин", "Флавоноиды", "Эфирные масла"],
        "properties": ["антидепрессант", "противовоспалительное", "ранозаживляющее",
                       "антиоксидант", "антивирусное"],
        "products":   ["масло зверобоя (для кожи)", "биодобавка", "чай", "мыло"],
        "cdata_link": "антиоксидантный эффект защищает митохондриальный щит",
        "notes":      "Масло зверобоя (красное масло) — незаменимо для восстановления кожи. "
                      "Внимание: взаимодействует с некоторыми лекарствами.",
    },
    {
        "id":         "sea_buckthorn",
        "name_ru":    "Облепиха (Hippophae rhamnoides)",
        "name_ka":    "ჩიჩხვი",
        "active":     ["Омега-7 (пальмитолеиновая кислота)", "Витамин E", "β-каротин",
                       "Витамин C", "Флавоноиды"],
        "properties": ["регенерация кожи", "антиоксидант", "противовоспалительное",
                       "заживление слизистых", "антиэйджинг"],
        "products":   ["масло (для кожи и приёма внутрь)", "крем", "мыло", "биодобавка"],
        "cdata_link": "Омега-7 → восстановление клеточных мембран → защита митохондрий",
        "notes":      "Облепиховое масло — один из лучших природных регенерантов. "
                      "Уникальный источник омега-7.",
    },
    {
        "id":         "calendula",
        "name_ru":    "Календула (Calendula officinalis)",
        "name_ka":    "ხახვისფოთოლა",
        "active":     ["Тритерпеноиды (олеаноловая кислота)", "Флавоноиды (кверцетин)",
                       "Каротиноиды", "Эфирное масло"],
        "properties": ["ранозаживляющее", "противовоспалительное", "антибактериальное",
                       "смягчающее кожу", "антигрибковое"],
        "products":   ["крем", "мыло", "масло-инфуз", "свеча"],
        "cdata_link": "снижает воспалительный ответ, защищает стволовые клетки кожи",
        "notes":      "Основа любого «нежного» крема. Идеально для детей, чувствительной кожи.",
    },
    {
        "id":         "turmeric",
        "name_ru":    "Куркума (Curcuma longa)",
        "name_ka":    "კვერცხისფოთოლა (კურკუმა)",
        "active":     ["Куркумин", "Бисдеметоксикуркумин", "Турмерон"],
        "properties": ["мощное противовоспалительное", "антиоксидант", "нейропротектор",
                       "противоопухолевое", "улучшает желчеотделение"],
        "products":   ["биодобавка (с пиперином для биодоступности)", "чай", "мыло",
                       "крем (от пигментации)"],
        "cdata_link": "Куркумин ингибирует NF-κB и mTOR → прямой эффект на Трек D (эпигенетика) "
                      "и Трек G (воспаление при менопаузе)",
        "notes":      "Биодоступность куркумина низкая без пиперина (чёрного перца). "
                      "Пиперин увеличивает усвоение на 2000%.",
    },
    {
        "id":         "rosemary",
        "name_ru":    "Розмарин (Salvia rosmarinus)",
        "name_ka":    "ბოლოქი",
        "active":     ["Розмариновая кислота", "Карнозиновая кислота", "1,8-цинеол",
                       "Камфора", "Борнеол"],
        "properties": ["антиоксидант", "улучшает память и концентрацию", "противовоспалительное",
                       "стимулирует кровообращение", "антибактериальное"],
        "products":   ["эфирное масло (диффузор, массаж)", "крем для волос", "мыло", "свеча"],
        "cdata_link": "карнозиновая кислота → активация Nrf2 → защита митохондрий (Трек E)",
        "notes":      "Аромат розмарина улучшает когнитивные функции на 15% (исследования). "
                      "Масло для волос — стимулирует фолликулы.",
    },
    {
        "id":         "beeswax",
        "name_ru":    "Пчелиный воск",
        "name_ka":    "ფუტკრის ცვილი",
        "active":     ["Мирицилпальмитат", "Церотиновая кислота", "Пропилис (трейс)"],
        "properties": ["базовый компонент свечей и кремов", "защитная плёнка",
                       "смягчение кожи", "антибактериальное"],
        "products":   ["свечи", "крем-мазь", "помада для губ", "бальзам"],
        "cdata_link": "носитель для экстрактов; восковые свечи при горении выделяют отрицательные ионы",
        "notes":      "Основа всех натуральных свечей Regenesis. "
                      "Точка плавления: 62–65°C.",
    },
    {
        "id":         "saffron",
        "name_ru":    "Шафран (Crocus sativus)",
        "name_ka":    "ზაფრანა",
        "active":     ["Кроцин", "Кроцетин", "Сафранал", "Пикрокроцин"],
        "properties": ["антидепрессант (кроцин = SSRI-подобное)", "антиоксидант",
                       "нейропротектор", "улучшает память", "противовоспалительное",
                       "афродизиак"],
        "products":   ["биодобавка (30 мг/день)", "чай (1-2 нити)", "тинктура"],
        "cdata_link": "кроцетин защищает ДНК от повреждений → Трек C (теломеры) и Трек D",
        "notes":      "Самая дорогая специя мира. Клинические исследования подтверждают "
                      "антидепрессивный эффект (сопоставим с флуоксетином при лёгкой депрессии). "
                      "Используется в протоколе Джабы (9:00 настой).",
    },
]

# ---------------------------------------------------------------------------
# Протоколы продуктов
# ---------------------------------------------------------------------------

PRODUCT_PROTOCOLS = [
    {
        "id":           "regenesis:candle_relaxation",
        "category":     "candles",
        "name":         "Свеча «Ночной покой» (лаванда + ладан)",
        "purpose":      "Снижение кортизола, улучшение сна, аромотерапия",
        "ingredients":  [
            "Пчелиный воск — 200 г",
            "Кокосовое масло — 20 г (для мягкости)",
            "Эфирное масло лаванды — 15 кап (3%)",
            "Эфирное масло ладана — 10 кап (2%)",
        ],
        "method":       (
            "1. Расплавить воск + кокосовое масло на водяной бане (65°C). "
            "2. Остудить до 55°C, добавить эфирные масла, перемешать. "
            "3. Залить в форму с фитилем. Остывание 24ч. "
            "4. Жечь не более 3 ч подряд."
        ),
        "shelf_life":   "12 месяцев",
        "cdata_benefit":"снижение кортизола → замедление накопления PTM-повреждений",
    },
    {
        "id":           "regenesis:cream_antiaging",
        "category":     "creams",
        "name":         "Крем «Долголетие» (облепиха + шиповник + куркума)",
        "purpose":      "Антиэйджинг, регенерация кожи, защита от ROS",
        "ingredients":  [
            "Основа (BTMS-50 эмульгатор) — 5 г",
            "Масло облепихи — 10 г",
            "Масло шиповника — 10 г",
            "Дистиллированная вода — 70 г",
            "Куркуминоиды (порошок) — 0.5 г",
            "Витамин E (токоферол) — 1 г",
            "Консервант (Geogard ECT) — 1 г",
            "Эфирное масло розмарина — 5 кап",
        ],
        "method":       (
            "1. Фаза масел: расплавить BTMS-50 + масла при 70°C. "
            "2. Фаза воды: нагреть воду до 70°C. "
            "3. Влить воду в масляную фазу, перемешать миксером до однородности. "
            "4. Остудить до 40°C, добавить куркумин, витамин E, консервант, эфирные масла. "
            "5. pH: 5.0–5.5. Хранить в холодильнике."
        ),
        "shelf_life":   "6 месяцев (с консервантом)",
        "cdata_benefit":"омега-7 + антиоксиданты → защита митохондриального щита (Трек E)",
    },
    {
        "id":           "regenesis:soap_detox",
        "category":     "soap",
        "name":         "Мыло «Детокс» (зверобой + лаванда + активированный уголь)",
        "purpose":      "Глубокое очищение, детоксикация кожи, антибактериальный эффект",
        "ingredients":  [
            "Кокосовое масло — 300 г",
            "Масло пальмы (RSPO) — 200 г",
            "Масло оливы — 200 г",
            "Масло зверобоя (настоянное) — 50 г",
            "NaOH — 97 г",
            "Вода — 220 г",
            "Активированный уголь — 5 г",
            "Эфирное масло лаванды — 20 г",
        ],
        "method":       (
            "Холодный метод мылoварения. "
            "1. Приготовить щёлок: медленно добавить NaOH в воду (не наоборот!), остудить. "
            "2. Расплавить масла (40°C), влить щёлок, перемешать до trace. "
            "3. Добавить уголь, масло зверобоя, ЭМ лаванды. "
            "4. Залить в форму. Выдержка 4–6 недель (cure time). "
            "Техника безопасности: работать в перчатках, очках, вентиляция."
        ),
        "shelf_life":   "12–18 месяцев",
        "cdata_benefit":"зверобой — антиоксидантная защита кожных стволовых клеток",
    },
    {
        "id":           "regenesis:supplement_longevity",
        "category":     "supplements",
        "name":         "Биодобавка «Regenesis Core» (сафран + куркумин + шиповник)",
        "purpose":      "Антиоксидантная защита, нейропротекция, замедление старения",
        "ingredients":  [
            "Экстракт шафрана (2% кроцина) — 30 мг/капсула",
            "Куркумин с пиперином (95% куркуминоидов) — 500 мг",
            "Витамин C (аскорбат кальция) — 500 мг",
            "Витамин E (смешанные токоферолы) — 200 МЕ",
            "Экстракт розмарина (карнозиновая кислота 10%) — 150 мг",
            "Цинк пиколинат — 15 мг",
            "Наполнитель: целлюлоза (HPMC капсула)",
        ],
        "dosage":       "1 капсула 2 раза/день с едой (утро + вечер)",
        "shelf_life":   "24 месяца в тёмном сухом месте",
        "cdata_benefit":"комплексное снижение ROS → защита всех 7 треков CDATA одновременно",
        "contraindications": "беременность, лактация, приём антикоагулянтов (консультация врача)",
    },
    {
        "id":           "regenesis:essential_oil_focus",
        "category":     "essential_oils",
        "name":         "Смесь «Ясный ум» (розмарин + ладан + лимон)",
        "purpose":      "Улучшение концентрации, памяти, когнитивных функций",
        "ingredients":  [
            "Эфирное масло розмарина (1,8-цинеол хемотип) — 40%",
            "Эфирное масло ладана — 30%",
            "Эфирное масло лимона — 20%",
            "Эфирное масло мяты перечной — 10%",
        ],
        "method":       (
            "Диффузор: 5–7 кап смеси на 200 мл воды, 30–60 мин утром или перед работой. "
            "Ингаляция: 2–3 кап на ладони, вдыхать 3–5 раз. "
            "Массаж висков: 1 кап + 5 кап базового масла (миндаль, жожоба)."
        ),
        "shelf_life":   "24 месяца в тёмном прохладном месте",
        "cdata_benefit":"активация Nrf2 (розмарин) → защита нейронных стволовых клеток",
    },
]

# ---------------------------------------------------------------------------
# Функции поиска
# ---------------------------------------------------------------------------

def search_extracts(query: str) -> list:
    """Поиск экстрактов по свойству/показанию."""
    q = query.lower()
    results = []
    for ext in PLANT_EXTRACTS:
        text = " ".join([
            ext["name_ru"].lower(),
            " ".join(ext["properties"]).lower(),
            " ".join(ext["active"]).lower(),
            ext.get("cdata_link", "").lower(),
            ext.get("notes", "").lower(),
        ])
        if q in text:
            results.append(ext)
    return results


def search_products(query: str) -> list:
    """Поиск продуктов по категории/цели."""
    q = query.lower()
    results = []
    for p in PRODUCT_PROTOCOLS:
        text = " ".join([
            p["name"].lower(),
            p["purpose"].lower(),
            p["category"].lower(),
            p.get("cdata_benefit", "").lower(),
        ])
        if q in text:
            results.append(p)
    return results


def generate_recipe(request: str) -> str:
    """Генерирует рецептуру через DeepSeek AI."""
    try:
        from llm import ask
    except ImportError:
        return "[Ошибка: llm.py недоступен. Убедитесь что DEEPSEEK_API_KEY установлен.]"

    plant_list = "\n".join(
        f"- {e['name_ru']}: {', '.join(e['properties'][:3])}"
        for e in PLANT_EXTRACTS
    )

    prompt = f"""Ты — эксперт по натуральной косметике и биодобавкам проекта Regenesis (доктор Джаба Ткемаладзе).
Твоя задача — разработать рецептуру для: {request}

Доступные растительные экстракты:
{plant_list}

Требования:
1. Выбери 3–5 подходящих компонентов из базы
2. Укажи точные количества (проценты или граммы)
3. Опиши метод приготовления по шагам
4. Укажи срок хранения
5. Объясни связь с теорией CDATA (какие треки старения защищает)

Формат ответа: JSON с полями name, purpose, ingredients (list), method (str), shelf_life, cdata_benefit.
"""
    try:
        response = ask(prompt, system="Ты эксперт по натуральной косметике и геронтологии.")
        return response
    except Exception as e:
        return f"[Ошибка генерации: {e}]"


# ---------------------------------------------------------------------------
# Импорт в AIM Knowledge Graph
# ---------------------------------------------------------------------------

def import_to_kg(verbose: bool = True) -> dict:
    """Импортирует базу Regenesis в AIM Knowledge Graph."""
    try:
        from db import init_db, kg_register_project, kg_add_node, kg_add_edge, kg_stats
    except ImportError as e:
        print(f"[regenesis] db.py недоступен: {e}")
        return {}

    init_db()
    stats = {"nodes": 0, "edges": 0, "errors": 0}

    kg_register_project(
        project_id="regenesis",
        name="Regenesis — Растительные протоколы продления жизни",
        path="/home/oem/AIM",
        description=(
            "Проект Regenesis: создание биологически активных продуктов "
            "(биодобавки, кремы, мыло, свечи, эфирные масла) из растительных экстрактов. "
            "Цель: улучшение качества жизни и продление жизни через CDATA-механизмы."
        ),
    )

    # Экстракты → узлы KG
    for ext in PLANT_EXTRACTS:
        uid = f"regenesis:extract:{ext['id']}"
        body = (
            f"Активные компоненты: {', '.join(ext['active'])}. "
            f"Свойства: {', '.join(ext['properties'])}. "
            f"Продукты: {', '.join(ext['products'])}. "
            f"CDATA: {ext['cdata_link']}. "
            f"{ext.get('notes', '')}"
        )
        try:
            kg_add_node(
                uid=uid,
                domain="protocol",
                type_="plant_extract",
                title=ext["name_ru"],
                body=body,
                lang="ru",
                project="regenesis",
                tags=ext["properties"][:4],
                confidence=1.0,
            )
            stats["nodes"] += 1
            if verbose:
                print(f"  ✓ [{uid}] {ext['name_ru']}")
        except Exception as e:
            if verbose:
                print(f"  ✗ {uid}: {e}")
            stats["errors"] += 1

    # Продукты → узлы KG
    for prod in PRODUCT_PROTOCOLS:
        body = (
            f"Назначение: {prod['purpose']}. "
            f"Ингредиенты: {'; '.join(prod['ingredients'][:3])}... "
            f"Срок хранения: {prod['shelf_life']}. "
            f"CDATA: {prod.get('cdata_benefit', '')}."
        )
        tags = [prod["category"]] + prod["purpose"].split(",")[:2]
        try:
            kg_add_node(
                uid=prod["id"],
                domain="protocol",
                type_="product_formula",
                title=prod["name"],
                body=body,
                lang="ru",
                project="regenesis",
                tags=[t.strip() for t in tags],
                confidence=1.0,
            )
            stats["nodes"] += 1
            if verbose:
                print(f"  ✓ [{prod['id']}] {prod['name']}")
        except Exception as e:
            if verbose:
                print(f"  ✗ {prod['id']}: {e}")
            stats["errors"] += 1

    # Рёбра: продукт → экстракты (на основе ингредиентов)
    extract_map = {e["name_ru"].lower().split("(")[0].strip(): f"regenesis:extract:{e['id']}"
                   for e in PLANT_EXTRACTS}
    for prod in PRODUCT_PROTOCOLS:
        for ing in prod["ingredients"]:
            for name, uid in extract_map.items():
                if name.split()[0].lower() in ing.lower():
                    try:
                        kg_add_edge(prod["id"], uid, "contains",
                                    project="regenesis", weight=1.0)
                        stats["edges"] += 1
                    except Exception:
                        pass

    # Связь Regenesis → CDATA (через aging-треки)
    aging_links = [
        ("regenesis:extract:turmeric",      "aging:track_d", "protects_via",  0.8),
        ("regenesis:extract:rosehip",       "aging:track_e", "reduces_ros",   0.9),
        ("regenesis:extract:sea_buckthorn", "aging:track_e", "shields_mito",  0.8),
        ("regenesis:extract:saffron",       "aging:track_c", "protects_dna",  0.7),
        ("regenesis:extract:frankincense",  "aging:inflammaging", "inhibits", 0.9),
        ("regenesis:supplement_longevity",  "nutrition:protocol:jaba", "extends", 0.9),
    ]
    for from_uid, to_uid, rel, weight in aging_links:
        try:
            kg_add_edge(from_uid, to_uid, rel,
                        project="regenesis", weight=weight)
            stats["edges"] += 1
        except Exception:
            pass

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_all():
    """Вывод всех протоколов и экстрактов."""
    print("\n=== РАСТИТЕЛЬНЫЕ ЭКСТРАКТЫ REGENESIS ===\n")
    for ext in PLANT_EXTRACTS:
        print(f"🌿 {ext['name_ru']}")
        print(f"   Свойства: {', '.join(ext['properties'][:3])}")
        print(f"   Продукты: {', '.join(ext['products'])}")
        print(f"   CDATA:    {ext['cdata_link']}")
        print()

    print("\n=== ПРОТОКОЛЫ ПРОДУКТОВ ===\n")
    for prod in PRODUCT_PROTOCOLS:
        cat_icon = {"candles": "🕯️", "creams": "🧴", "soap": "🧼",
                    "supplements": "💊", "essential_oils": "💧"}.get(prod["category"], "📦")
        print(f"{cat_icon} {prod['name']}")
        print(f"   Цель:   {prod['purpose']}")
        print(f"   CDATA:  {prod.get('cdata_benefit', '-')}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Regenesis Protocol — растительные экстракты для продления жизни"
    )
    parser.add_argument("--search",    metavar="QUERY", help="Поиск по свойству/показанию")
    parser.add_argument("--import-kg", action="store_true", help="Импортировать в AIM KG")
    parser.add_argument("--generate",  metavar="REQUEST", help="Сгенерировать рецептуру через AI")
    parser.add_argument("--quiet",     action="store_true", help="Минимальный вывод")
    args = parser.parse_args()

    if args.search:
        results = search_extracts(args.search) + search_products(args.search)
        if not results:
            print(f"Ничего не найдено по запросу «{args.search}»")
        for r in results:
            name = r.get("name_ru") or r.get("name", "?")
            print(f"  → {name}")
            if "properties" in r:
                print(f"     {', '.join(r['properties'][:3])}")
            if "purpose" in r:
                print(f"     {r['purpose']}")
        return

    if args.generate:
        print(f"\nГенерирую рецептуру для: {args.generate}\n")
        result = generate_recipe(args.generate)
        print(result)
        return

    if args.import_kg:
        print("=== Импорт Regenesis → AIM Knowledge Graph ===\n")
        stats = import_to_kg(verbose=not args.quiet)
        print(f"\n✅ Импорт: {stats.get('nodes',0)} узлов, "
              f"{stats.get('edges',0)} рёбер, "
              f"{stats.get('errors',0)} ошибок")
        return

    print_all()


if __name__ == "__main__":
    main()
