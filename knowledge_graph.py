#!/usr/bin/env python3
"""
knowledge_graph.py — AIM Unified Knowledge Graph
=================================================
AIM как центральное хранилище знаний для всех проектов.

Граф хранится в aim.db (таблицы kg_projects, kg_nodes, kg_edges).

Домены:
  nutrition  — протоколы питания (Dietebi, space_nutrition.py, Певзнер)
  medicine   — медицина (patients, diagnoses, lab_reference)
  aging      — CDATA-теория старения (DrJaba / DrJaba.com)
  mythology  — грузинская мифология (Georgians / Хвамли)
  language   — лингвистика (kSystem, ScheckerGe)
  protocol   — лечебные протоколы (Regenesis, Pevzner tables)

Использование:
  python3 knowledge_graph.py --sync        # синхронизировать все проекты
  python3 knowledge_graph.py --stats       # статистика графа
  python3 knowledge_graph.py --search TEXT # поиск по графу
  python3 knowledge_graph.py --export DOMAIN  # экспорт домена в JSON
"""

import json
import sys
from pathlib import Path

AIM_DIR = Path(__file__).parent
sys.path.insert(0, str(AIM_DIR))

import db

# ── Реестр проектов ────────────────────────────────────────────────────────

PROJECTS = [
    {
        "id": "aim",
        "name": "AIM — Ассистент интегративной медицины",
        "path": str(AIM_DIR),
        "description": "Ядро системы. Медицинский AI доктора Джабы. Содержит лаб. данные, диагнозы, протоколы лечения.",
    },
    {
        "id": "drjaba",
        "name": "DrJaba.com",
        "path": str(Path.home() / "Desktop/DrJaba"),
        "description": "Веб-сайт доктора Джабы. CDATA-теория старения, лечебные протоколы, питание. Phoenix LiveView.",
    },
    {
        "id": "dietebi",
        "name": "Dietebi — Протоколы питания",
        "path": str(Path.home() / "Desktop/Dietebi"),
        "description": "Статьи и меню доктора Джабы о правильном питании. Основа nutrition-домена.",
    },
    {
        "id": "georgians",
        "name": "Georgians — Тайна Хвамли",
        "path": str(Path.home() / "Desktop/Georgians"),
        "description": "Книга о горе Хвамли как протоцивилизационном узле. Мифология Кавказа, ТХТ-теория.",
    },
    {
        "id": "cdata",
        "name": "CDATA — Теория накопления повреждений центриолей",
        "path": str(Path.home() / "Desktop/CDATA"),
        "description": "Научная теория старения. Mol Biol Rep 2023, ARS 2025. Основа aging-домена.",
    },
    {
        "id": "ksystem",
        "name": "kSystem — 7 Библий",
        "path": str(Path.home() / "Desktop/kSystem"),
        "description": "Сравнительный анализ 7 переводов Библии. Лингвистика, семантика, грузинский язык.",
    },
    {
        "id": "scheckerge",
        "name": "ScheckerGe — Грузинский спелл-чекер",
        "path": str(Path.home() / "Desktop/ScheckerGe"),
        "description": "Орфографический корректор для грузинского языка. Поддержка AIM при обработке грузинских текстов.",
    },
]


# ── Синхронизаторы доменов ─────────────────────────────────────────────────

def _sync_nutrition():
    """Импортирует данные питания из space_nutrition.py в граф."""
    try:
        from space_nutrition import FORBIDDEN_FOODS, ALLOWED_FOODS, EATING_PROTOCOL
    except ImportError:
        print("  ⚠️  space_nutrition not available")
        return 0

    count = 0
    for item in FORBIDDEN_FOODS:
        uid = f"nutrition:forbidden:{item['name'].lower().replace(' ', '_')[:40]}"
        db.kg_add_node(
            uid=uid, domain="nutrition", type_="rule",
            title=f"ЗАПРЕЩЕНО: {item['name']}",
            body=json.dumps({
                "category": item.get("category", ""),
                "reason":   item.get("reason", ""),
                "effect":   item.get("effect", ""),
                "aliases":  item.get("aliases", []),
            }, ensure_ascii=False),
            lang="ru", project="aim",
            tags=["forbidden", item.get("category", "").lower()],
        )
        # ребро: nutrition:protocol → запрещённый продукт
        db.kg_add_edge("nutrition:protocol:jaba", uid, "forbids", "aim")
        count += 1

    for item in ALLOWED_FOODS:
        uid = f"nutrition:allowed:{item['name'].lower().replace(' ', '_')[:40]}"
        db.kg_add_node(
            uid=uid, domain="nutrition", type_="rule",
            title=f"РАЗРЕШЕНО: {item['name']}",
            body=json.dumps({
                "category": item.get("category", ""),
                "benefit":  item.get("benefit", ""),
                "aliases":  item.get("aliases", []),
            }, ensure_ascii=False),
            lang="ru", project="aim",
            tags=["allowed", item.get("category", "").lower()],
        )
        db.kg_add_edge("nutrition:protocol:jaba", uid, "allows", "aim")
        count += 1

    # Протокол как корневой узел
    db.kg_add_node(
        uid="nutrition:protocol:jaba",
        domain="nutrition", type_="protocol",
        title="Протокол питания доктора Джабы Ткемаладзе",
        body=json.dumps({
            "meals_per_day": 5,
            "meal_times": ["9:00", "12:00", "15:00", "18:00", "21:00"],
            "water_before_meal_min": 30,
            "rules": EATING_PROTOCOL if isinstance(EATING_PROTOCOL, list) else [],
        }, ensure_ascii=False),
        lang="ru", project="aim",
        tags=["protocol", "nutrition", "jaba"],
    )
    return count


def _sync_lab_reference():
    """Импортирует лабораторные параметры из lab_reference.py."""
    try:
        from lab_reference import REFERENCE_DB, ALIASES
    except ImportError:
        print("  ⚠️  lab_reference not available")
        return 0

    count = 0
    seen = set()
    for (param_id, sex, age_group), ref in REFERENCE_DB.items():
        if param_id in seen:
            continue
        seen.add(param_id)
        uid = f"medicine:lab:{param_id.lower()}"
        db.kg_add_node(
            uid=uid, domain="medicine", type_="concept",
            title=f"Лаб. параметр: {param_id}",
            body=json.dumps({
                "param_id": param_id,
                "unit":     getattr(ref, "unit", ""),
                "aliases":  ALIASES.get(param_id, []),
            }, ensure_ascii=False),
            lang="multi", project="aim",
            tags=["lab", "biomarker"],
        )
        count += 1
    return count


def _sync_mythology():
    """Импортирует материалы мифологии из папки Georgians."""
    georgians_dir = Path.home() / "Desktop/Georgians/Materials"
    if not georgians_dir.exists():
        return 0

    count = 0
    for md_file in georgians_dir.glob("*.md"):
        uid = f"mythology:source:{md_file.stem}"
        content = md_file.read_text(encoding="utf-8")[:2000]  # первые 2000 символов
        db.kg_add_node(
            uid=uid, domain="mythology", type_="source",
            title=md_file.stem.replace("_", " ").title(),
            body=content,
            lang="ru", project="georgians",
            tags=["khvamli", "georgia", "mythology"],
        )
        count += 1

    # Ключевые концепты
    concepts = [
        ("mythology:concept:amiran",     "Амиран — грузинский Прометей",          ["amiran", "prometheus", "caucasus"]),
        ("mythology:concept:dali",       "Дали — богиня охоты Сванети",           ["dali", "svaneti", "hunting"]),
        ("mythology:concept:khvamli",    "Хвамли — гора-святилище Колхиды",       ["khvamli", "colchis", "sacred_mountain"]),
        ("mythology:concept:ktt",        "ТХТ — Теория Хвамлийского Трансфера",   ["ktt", "sumer", "egypt", "canaan"]),
        ("mythology:concept:golden_fleece", "Золотое руно как технология омоложения", ["golden_fleece", "medea", "rejuvenation"]),
    ]
    for uid, title, tags in concepts:
        db.kg_add_node(
            uid=uid, domain="mythology", type_="concept",
            title=title, lang="ru", project="georgians", tags=tags,
        )

    # Золотое руно → связь с CDATA (омоложение)
    db.kg_add_edge(
        "mythology:concept:golden_fleece",
        "aging:concept:rejuvenation",
        "related_to", "georgians",
        notes="Золотое руно как древний символ технологии омоложения (Медея pharmakís)"
    )
    count += len(concepts)
    return count


def _sync_cdata():
    """Импортирует концепты CDATA-теории старения."""
    cdata_dir = Path.home() / "Desktop/CDATA"

    # Ключевые концепты теории
    concepts = [
        ("aging:concept:cdata",         "CDATA — Теория накопления повреждений центриолей",
         "Стволовые клетки при асимметричном делении удерживают старый материнский центриоль. "
         "Центриоли лишены репарации → необратимо накапливают повреждения → нарушают первичную ресничку → истощение пула СК → системное старение.",
         ["cdata", "centriole", "aging", "stem_cell"]),
        ("aging:concept:rejuvenation",  "Протокол омоложения — 4 терапевтических пути",
         "1. Центриольная замена. 2. Протеостатическая очистка. 3. Стимуляция цилиогенеза. 4. Нишевая терапия.",
         ["rejuvenation", "centriole", "protocol"]),
        ("aging:concept:pnie",          "PNIE — Психо-Нейро-Иммуно-Эндокринология",
         "Нервная, иммунная и эндокринная системы — единый молекулярный диалог. Нет органной медицины.",
         ["pnie", "integrative", "medicine"]),
        ("aging:concept:disease_as_protection", "Болезнь как защита",
         "Болезнь — не поломка, а защитная реакция. Тело разворачивает хроническое заболевание когда движение к цели угрожает гибелью.",
         ["disease", "protection", "psychosomatics"]),
    ]

    count = 0
    for uid, title, body, tags in concepts:
        db.kg_add_node(
            uid=uid, domain="aging", type_="concept",
            title=title, body=body, lang="ru",
            project="cdata", tags=tags,
        )
        count += 1

    # Связи: CDATA → медицина → питание
    db.kg_add_edge("aging:concept:cdata",     "medicine:concept:stem_cell",        "related_to", "cdata")
    db.kg_add_edge("aging:concept:pnie",      "nutrition:protocol:jaba",           "source_of",  "cdata",
                   notes="PNIE-ось объясняет почему питание влияет на иммунитет, гормоны и НС")
    db.kg_add_edge("aging:concept:rejuvenation", "nutrition:protocol:jaba",        "related_to", "cdata",
                   notes="Протокол питания — часть протокола омоложения")

    # Stem cell как связующий узел
    db.kg_add_node(
        uid="medicine:concept:stem_cell", domain="medicine", type_="concept",
        title="Стволовые клетки и регенерация",
        body="Пул стволовых клеток определяет регенеративный потенциал организма.",
        lang="ru", project="cdata", tags=["stem_cell", "regeneration"],
    )
    count += 1
    return count


def _sync_pevzner():
    """Импортирует таблицы Певзнера (если есть pevzner_tables.json)."""
    pf = Path.home() / "Desktop/Dietebi/pevzner_tables.json"
    if not pf.exists():
        return 0

    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️  pevzner_tables.json parse error: {e}")
        return 0

    count = 0
    for tbl in data.get("tables", []):
        uid = f"protocol:pevzner:{tbl['number']}"
        db.kg_add_node(
            uid=uid, domain="protocol", type_="protocol",
            title=f"Стол №{tbl['number']} — {tbl.get('name', '')}",
            body=json.dumps(tbl, ensure_ascii=False),
            lang="ru", project="dietebi",
            tags=["pevzner", f"table_{tbl['number']}"] + tbl.get("diagnoses", [])[:5],
        )
        # Связь стола с протоколом Джабы
        db.kg_add_edge(uid, "nutrition:protocol:jaba", "related_to", "dietebi",
                       notes="Стол Певзнера адаптирован в протоколе Джабы")
        count += 1

    # Карта диагнозов
    for diagnosis, table_num in data.get("diagnosis_map", {}).items():
        diag_uid = f"medicine:diagnosis:{diagnosis.lower().replace(' ', '_')[:50]}"
        table_uid = f"protocol:pevzner:{table_num}"
        db.kg_add_node(
            uid=diag_uid, domain="medicine", type_="entity",
            title=diagnosis, lang="ru", project="dietebi",
            tags=["diagnosis"],
        )
        db.kg_add_edge(diag_uid, table_uid, "treats", "dietebi")
        db.kg_add_edge(diag_uid, "nutrition:protocol:jaba", "treats", "dietebi")
        count += 1

    return count


def _sync_ksystem():
    """Импортирует данные из kSystem (7 Библий) если папка существует."""
    ks_dir = Path.home() / "Desktop/kSystem"
    if not ks_dir.exists():
        return 0

    db.kg_add_node(
        uid="language:project:ksystem",
        domain="language", type_="source",
        title="kSystem — Сравнительный анализ 7 переводов Библии",
        body="Анализ семантических и лингвистических параллелей в 7 переводах. Связь с грузинским языком.",
        lang="ru", project="ksystem",
        tags=["bible", "georgian", "linguistics", "comparative"],
    )
    # Связь с мифологией через грузинский язык
    db.kg_add_edge(
        "language:project:ksystem",
        "mythology:concept:khvamli",
        "related_to", "ksystem",
        notes="Грузинский библейский язык — культурный контекст мифологии Хвамли"
    )
    return 1


def _sync_scheckerge():
    """Импортирует данные ScheckerGe."""
    sg_dir = Path.home() / "Desktop/ScheckerGe"
    if not sg_dir.exists():
        return 0

    db.kg_add_node(
        uid="language:tool:scheckerge",
        domain="language", type_="concept",
        title="ScheckerGe — Грузинский орфографический корректор",
        body="Инструмент для AIM: обработка грузинскоязычных текстов пациентов, документов, источников.",
        lang="ru", project="scheckerge",
        tags=["georgian", "nlp", "spellcheck"],
    )
    db.kg_add_edge("language:tool:scheckerge", "medicine:concept:patient_records",
                   "source_of", "scheckerge",
                   notes="ScheckerGe улучшает качество OCR/обработки грузинских медицинских документов")
    db.kg_add_node(
        uid="medicine:concept:patient_records",
        domain="medicine", type_="concept",
        title="Записи пациентов на грузинском языке",
        lang="ka", project="aim", tags=["patient", "georgian", "records"],
    )
    return 1


# ── Главная точка входа ────────────────────────────────────────────────────

def sync_all(verbose: bool = True) -> dict:
    """
    Синхронизирует все проекты с графом знаний.
    Возвращает статистику по доменам.
    """
    def log(msg):
        if verbose: print(msg)

    db.init_db()
    log("🔗 AIM Knowledge Graph — синхронизация всех проектов\n")

    # Регистрируем проекты
    for p in PROJECTS:
        db.kg_register_project(p["id"], p["name"], p["path"], p["description"])

    stats = {}

    syncers = [
        ("nutrition (space_nutrition.py)", _sync_nutrition),
        ("medicine (lab_reference.py)",    _sync_lab_reference),
        ("mythology (Georgians/)",         _sync_mythology),
        ("aging (CDATA)",                  _sync_cdata),
        ("protocol (Певзнер)",             _sync_pevzner),
        ("language (kSystem)",             _sync_ksystem),
        ("language (ScheckerGe)",          _sync_scheckerge),
    ]

    for label, fn in syncers:
        try:
            n = fn()
            stats[label] = n
            log(f"  ✅ {label}: {n} узлов")
        except Exception as e:
            stats[label] = 0
            log(f"  ❌ {label}: {e}")

    total = db.kg_stats()
    log(f"\n📊 Граф знаний AIM:")
    log(f"   Узлов: {total['nodes']} | Рёбер: {total['edges']} | Проектов: {total['projects']}")
    log(f"   По доменам: {total['by_domain']}")
    return stats


def search(query: str, limit: int = 10) -> list:
    """Полнотекстовый поиск по графу."""
    db.init_db()
    return db.kg_query(text=query, limit=limit)


def export_domain(domain: str, output: str = None) -> list:
    """Экспорт домена в JSON файл или возврат списка."""
    db.init_db()
    nodes = db.kg_export_domain(domain)
    if output:
        Path(output).write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Экспортировано {len(nodes)} узлов → {output}")
    return nodes


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        db.init_db()
        s = db.kg_stats()
        print(f"Граф знаний AIM:")
        print(f"  Узлов: {s['nodes']} | Рёбер: {s['edges']} | Проектов: {s['projects']}")
        print(f"  По доменам: {json.dumps(s['by_domain'], ensure_ascii=False, indent=2)}")
        sys.exit(0)

    if "--search" in args:
        idx = args.index("--search")
        q = args[idx + 1] if idx + 1 < len(args) else ""
        results = search(q)
        for r in results:
            print(f"  [{r['domain']}] {r['uid']}: {r['title']}")
        sys.exit(0)

    if "--export" in args:
        idx = args.index("--export")
        domain = args[idx + 1] if idx + 1 < len(args) else "nutrition"
        out = args[idx + 2] if idx + 2 < len(args) else None
        export_domain(domain, out)
        sys.exit(0)

    # default: --sync
    sync_all(verbose=True)
