#!/usr/bin/env python3
"""
dietebi_importer.py — Импорт статей Джабы Ткемаладзе (Dietebi) в AIM Knowledge Graph.

Источник: /home/oem/Desktop/Dietebi/  (9 docx-файлов)
Назначение:
  - Извлечь медицинские и диетологические знания из статей "Jaba Eqimi" (грузинский)
  - Занести в AIM (SQLite kg_nodes / knowledge) как узлы домена 'nutrition'
  - Создать рёбра: диагноз → диета → запрещённые/разрешённые продукты

Статьи:
  #16  — Норма воды в день (вес × 0.04); 13% успешно худеют
  #35  — Хронический гастрит и колит; льняное семя; стол №5
  #37  — Гипертония; специфическое питание при АГ; стол №10
  #39  — Вирусы и иммунная защита; коммерческие интересы фармы
  #58  — Стол №5 (печень/желчный пузырь); 15 столов в медицине
  #59  — Ожирение; миф о фруктах; разгрузочные дни
  #84  — Диета №1 (хроническое воспаление ЖКТ)
  #89  — Ревматизм и суставы; специальная диета
  гасахдоми — 7-дневный протокол похудения (5-разовое питание)

Запуск:
  cd ~/AIM && source venv/bin/activate
  python3 dietebi_importer.py              # импорт всех статей
  python3 dietebi_importer.py --stats      # статистика по импорту
  python3 dietebi_importer.py --list       # список добавленных узлов
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    import docx
except ImportError:
    print("[dietebi_importer] python-docx не установлен. Запустите: pip install python-docx")
    sys.exit(1)

# Добавляем ~/AIM в путь
sys.path.insert(0, str(Path(__file__).parent))
from db import _connect, kg_register_project, kg_add_node, kg_add_edge, kg_stats, init_db

DIETEBI_DIR = Path("/home/oem/Desktop/Dietebi")
PROJECT_ID  = "dietebi"

# ---------------------------------------------------------------------------
# Каталог статей: uid → метаданные + контент
# ---------------------------------------------------------------------------

ARTICLES = [
    {
        "uid":    "dietebi:water_intake_formula",
        "domain": "nutrition",
        "type":   "protocol",
        "title":  "Норма воды: вес × 0.04 = суточная потребность (л)",
        "body": (
            "Формула доктора Ткемаладзе: масса тела (кг) × 0.04 = суточная норма воды (л). "
            "Из них половина (вес × 0.02) — чистая вода или настой лекарственных трав. "
            "Пример: 70 кг → 2.8 л/день, из них 1.4 л — чистая вода. "
            "Только 13% людей, пытающихся похудеть, достигают результата — основная причина "
            "в недостаточном потреблении воды и неправильном режиме питания."
        ),
        "tags":     ["water", "hydration", "weight_loss", "formula"],
        "confidence": 1.0,
        "file":   "jaba eqimi (16).docx",
    },
    {
        "uid":    "dietebi:gastritis_colitis_diet",
        "domain": "nutrition",
        "type":   "therapeutic_diet",
        "title":  "Хронический гастрит и колит: диета, льняное семя, стол №5",
        "body": (
            "Хронические воспаления ЖКТ — предпосылка для язвы и онкологии. "
            "Стол №5 (диета для печени и жёлчного пузыря) — наиболее частая рекомендация. "
            "Льняное семя незаменимо при воспалениях ЖКТ: слизь обволакивает слизистую. "
            "Способ приготовления: 1 ст.л. льняного семени + 200 мл кипятка, настоять 20 мин, "
            "процедить, пить натощак. При хроническом гастрите — дробное питание 5–6 раз/день, "
            "исключить жирное, жареное, острое, алкоголь, газированные напитки."
        ),
        "tags":     ["gastritis", "colitis", "GIT", "table_5", "flaxseed", "inflammation"],
        "confidence": 1.0,
        "file":   "jaba eqimi (35).docx",
    },
    {
        "uid":    "dietebi:hypertension_diet",
        "domain": "nutrition",
        "type":   "therapeutic_diet",
        "title":  "Гипертония: специфическое питание, стол №10",
        "body": (
            "Гипертония требует специфической диеты — стол №10 (сердечно-сосудистые заболевания). "
            "Запрещены: соль сверх 3–5 г/день, насыщенные жиры, алкоголь, крепкий кофе и чай, "
            "жирное мясо, консервы, копчёности, острые приправы. "
            "Рекомендованы: свежие овощи и фрукты, рыба (2–3 раза/нед), растительные масла, "
            "молочные продукты низкой жирности, калий (бананы, картофель, сухофрукты). "
            "Важно: не прекращать приём гипотензивных препаратов самостоятельно — "
            "резкая отмена может вызвать гипертонический криз. "
            "Физическая активность: ходьба 30 мин/день снижает АД на 5–10 мм рт.ст."
        ),
        "tags":     ["hypertension", "blood_pressure", "table_10", "cardiovascular", "salt"],
        "confidence": 1.0,
        "file":   "jaba eqimi (37).docx",
    },
    {
        "uid":    "dietebi:viral_infections_immunity",
        "domain": "nutrition",
        "type":   "protocol",
        "title":  "Вирусы и иммунная защита: питание при вирусных инфекциях",
        "body": (
            "Позиция доктора Ткемаладзе: вирусные инфекции, как и все болезни, "
            "управляются в том числе коммерческими интересами. Основа профилактики — "
            "укрепление иммунитета через питание, а не медикаменты. "
            "Иммунная диета: витамин C (шиповник, цитрусы, перец), цинк (тыквенные семена, "
            "орехи, бобовые), чеснок и лук (аллицин), имбирь, куркума. "
            "При ОРВИ: обильное тёплое питьё (2.5–3 л/день), куриный бульон, "
            "исключить сахар (подавляет фагоцитоз на 5 ч после приёма), "
            "легкоусвояемая пища: рис, варёные овощи, кисломолочные продукты."
        ),
        "tags":     ["virus", "immunity", "ARVI", "prevention", "vitamin_C", "zinc"],
        "confidence": 0.9,
        "file":   "jaba eqimi (39).docx",
    },
    {
        "uid":    "dietebi:table5_liver_gallbladder",
        "domain": "nutrition",
        "type":   "therapeutic_diet",
        "title":  "Стол №5: диета при заболеваниях печени и жёлчного пузыря",
        "body": (
            "В медицине существует 15 лечебных столов (диет Певзнера) для разных заболеваний. "
            "Стол №5 — при гепатите, циррозе, холецистите, желчнокаменной болезни. "
            "Принципы: дробное питание 5–6 раз/день, тёплая пища (не горячая и не холодная), "
            "ограничение жиров (особенно животных), исключение жареного. "
            "Разрешено: нежирное мясо и рыба (варёные/запечённые), овощи, фрукты (кроме кислых), "
            "крупы, молочные продукты низкой жирности, слабый чай, минеральная вода. "
            "Запрещено: жирное мясо, жареное, острые специи, алкоголь, яичный желток >1 шт/день, "
            "грибы, бобовые, шоколад, мороженое, газированные напитки, кофе. "
            "Питьевой режим: 1.5–2 л/день некислой воды; утром — стакан тёплой воды."
        ),
        "tags":     ["table_5", "liver", "gallbladder", "hepatitis", "cirrhosis", "cholecystitis"],
        "confidence": 1.0,
        "file":   "jaba eqimi (58).docx",
    },
    {
        "uid":    "dietebi:obesity_weight_management",
        "domain": "nutrition",
        "type":   "protocol",
        "title":  "Ожирение и управление весом: мифы о фруктах, разгрузочные дни",
        "body": (
            "Позиция: утверждение «фрукты не вызывают полноты» — абсурд. "
            "Фрукты содержат фруктозу, которая при избытке превращается в жир. "
            "ВОЗ: избыточный вес — 5-й по значимости фактор смерти, причина психических расстройств. "
            "Разгрузочные дни (1–2 раза/нед) эффективнее «бессмысленных диет»: "
            "в разгрузочный день — только кипячёная вода или травяной чай, суточный объём 2–2.5 л. "
            "Это запускает аутофагию, даёт отдых ЖКТ, снижает воспаление. "
            "7-дневный протокол похудения (гасахдоми): "
            "5-разовое питание (9:00 / 12:00 / 15:00 / 18:00 / 21:00), "
            "минус 500 ккал/день от нормы, белок 1.5–2 г/кг, исключить сахар и алкоголь. "
            "Дополнительно: мужчины увеличивают порции на 50%."
        ),
        "tags":     ["obesity", "weight_loss", "fasting_day", "fructose", "autophagy"],
        "confidence": 1.0,
        "file":   "jaba eqimi (59).docx",
    },
    {
        "uid":    "dietebi:table1_GIT_inflammation",
        "domain": "nutrition",
        "type":   "therapeutic_diet",
        "title":  "Диета №1 (стол №1): хроническое воспаление ЖКТ",
        "body": (
            "Диета доктора Ткемаладзе №1 — при хроническом воспалении ЖКТ. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО: мясные/рыбные/овощные бульоны; жирное мясо и рыба; "
            "дрожжевой хлеб, свежий хлеб, чёрный хлеб; консервы любые; "
            "сырые фрукты и овощи (зелень — умеренно); мороженое, шоколад; "
            "редис, шпинат, сырой лук и чеснок; капуста листовая; "
            "крепкий кофе, газированные напитки, щелочная минеральная вода. "
            "РАЗРЕШЕНО: слизистые каши (овсяная, рисовая, манная); "
            "варёное нежирное мясо и рыба (паровые котлеты, суфле); "
            "яйца всмятку (1–2/день); кисель, компот без сахара; "
            "пшеничный хлеб вчерашней выпечки; некислые кисломолочные продукты."
        ),
        "tags":     ["table_1", "gastric_ulcer", "duodenal_ulcer", "GIT", "gastritis_acute"],
        "confidence": 1.0,
        "file":   "jaba eqimi (84).docx",
    },
    {
        "uid":    "dietebi:rheumatism_joint_diet",
        "domain": "nutrition",
        "type":   "therapeutic_diet",
        "title":  "Ревматизм и суставы: диета, физическая нагрузка",
        "body": (
            "Для восстановления суставов и расслабления мышц: "
            "физические нагрузки 2–3 раза/нед до лёгкого потоотделения (вечером). "
            "Вздутие кишечника и непереваривание пищи — серьёзный стресс для позвоночника. "
            "Противовоспалительная диета при ревматизме: "
            "рыбий жир (омега-3: скумбрия, лосось, сельдь 2–3 раза/нед); "
            "куркума (куркумин — сильнейший натуральный противовоспалительный агент); "
            "имбирь (свежий или в чае); вишня и черешня (антоцианы снижают мочевую кислоту); "
            "исключить: красное мясо, алкоголь, сахар, молочные продукты (при подагре), "
            "пуриносодержащие продукты (печень, почки, сардины). "
            "Стол №10 (с ограничением соли) или стол №6 (при подагре)."
        ),
        "tags":     ["rheumatism", "joints", "arthritis", "gout", "omega3", "anti_inflammatory"],
        "confidence": 1.0,
        "file":   "jaba eqimi (89).docx",
    },
    {
        "uid":    "dietebi:7day_weight_loss_protocol",
        "domain": "nutrition",
        "type":   "protocol",
        "title":  "7-дневный протокол похудения «Гасахдоми» (5-разовое питание)",
        "body": (
            "7-дневный протокол доктора Ткемаладзе «გასახდომი» (похудение). "
            "Принцип: 5-разовое питание в строгое время — 9:00, 12:00, 15:00, 18:00, 21:00. "
            "Порции для женщин; мужчины увеличивают на 50%. "
            "День 1 — Понедельник: "
            "9:00 настой шафрана; 12:00 тыквенные семена + кофе с молоком; "
            "15:00 куриный бульон + кисель; 18:00 морская капуста 30 г; 21:00 стакан воды. "
            "День 2 — Вторник: "
            "9:00 детокс-чай; 12:00 рыба отварная + оливковое масло; "
            "15:00 суп-пюре + хлеб; 18:00 фрукты; 21:00 стакан воды. "
            "Дни 3–7: аналогичный принцип чередования белковых/детоксических приёмов. "
            "Ключевые принципы: последний приём — только вода или травяной чай; "
            "не есть после 21:00; начинать день с тёплого напитка натощак."
        ),
        "tags":     ["weight_loss", "protocol", "7_days", "meal_plan", "5_meals", "fasting"],
        "confidence": 1.0,
        "file":   "გასახდომი.docx",
    },
]

# ---------------------------------------------------------------------------
# Рёбра между узлами
# ---------------------------------------------------------------------------

EDGES = [
    # Диагнозы → диеты
    ("dietebi:gastritis_colitis_diet",   "dietebi:table5_liver_gallbladder",
     "related_diet", 0.8, "гастрит→стол№5 как основа"),
    ("dietebi:table1_GIT_inflammation",  "dietebi:gastritis_colitis_diet",
     "precedes",     0.7, "стол№1 при остром периоде, затем стол№5"),
    ("dietebi:obesity_weight_management","dietebi:7day_weight_loss_protocol",
     "implements",   1.0, "протокол 7 дней реализует принципы похудения"),
    ("dietebi:water_intake_formula",     "dietebi:7day_weight_loss_protocol",
     "supports",     0.9, "правильный питьевой режим — основа протокола"),
    ("dietebi:rheumatism_joint_diet",    "dietebi:viral_infections_immunity",
     "shares_mechanism", 0.6, "оба — противовоспалительные стратегии"),
    # Связь с AIM нодами (если существуют)
    ("nutrition:protocol:jaba",          "dietebi:7day_weight_loss_protocol",
     "implements",   1.0, "DrJaba сайт реализует этот протокол"),
]


def read_docx_text(filepath: Path) -> str:
    """Читает текст из docx-файла."""
    try:
        doc = docx.Document(filepath)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        return f"[Ошибка чтения: {e}]"


def import_articles(verbose: bool = True) -> dict:
    """Импортирует все статьи в Knowledge Graph AIM."""
    init_db()

    # Регистрируем проект
    kg_register_project(
        project_id="dietebi",
        name="Dietebi — Статьи доктора Ткемаладзе",
        path=str(DIETEBI_DIR),
        description=(
            "Медицинско-диетологические статьи Джабы Ткемаладзе "
            "(рубрика «Ваше здоровье», Georgian press). "
            "9 docx-файлов: лечебные столы №1–15, протоколы питания, "
            "7-дневный план похудения."
        ),
    )

    stats = {"added": 0, "updated": 0, "errors": 0, "edges": 0}

    # Добавляем узлы
    for article in ARTICLES:
        try:
            node_id = kg_add_node(
                uid=article["uid"],
                domain=article["domain"],
                type_=article["type"],
                title=article["title"],
                body=article["body"],
                lang="ru",
                project=PROJECT_ID,
                tags=article["tags"],
                confidence=article["confidence"],
            )
            if verbose:
                print(f"  ✓ [{article['uid']}] {article['title'][:70]}")
            stats["added"] += 1
        except Exception as e:
            print(f"  ✗ Ошибка {article['uid']}: {e}")
            stats["errors"] += 1

    # Добавляем рёбра
    for from_uid, to_uid, rel, weight, notes in EDGES:
        try:
            kg_add_edge(
                from_uid=from_uid,
                to_uid=to_uid,
                rel=rel,
                weight=weight,
                notes=notes,
                project=PROJECT_ID,
            )
            stats["edges"] += 1
        except Exception as e:
            # Рёбра к внешним узлам могут не существовать — не критично
            if verbose:
                print(f"  ~ Ребро {from_uid}→{to_uid}: {e}")

    return stats


def print_stats():
    """Вывод статистики по импортированным узлам dietebi."""
    db = _connect()
    cur = db.execute(
        "SELECT COUNT(*) FROM kg_nodes WHERE source_project = 'dietebi'"
    )
    count = cur.fetchone()[0]
    print(f"\nУзлов dietebi в Knowledge Graph: {count}")

    rows = db.execute(
        "SELECT uid, title FROM kg_nodes WHERE source_project = 'dietebi' ORDER BY uid"
    ).fetchall()
    for uid, title in rows:
        print(f"  [{uid}] {title[:70]}")


def main():
    parser = argparse.ArgumentParser(
        description="Импорт статей Джабы Ткемаладзе (Dietebi) в AIM"
    )
    parser.add_argument("--stats",   action="store_true", help="Показать статистику")
    parser.add_argument("--list",    action="store_true", help="Список импортированных узлов")
    parser.add_argument("--quiet",   action="store_true", help="Минимальный вывод")
    args = parser.parse_args()

    if args.stats or args.list:
        print_stats()
        return

    print("=== Dietebi Importer — AIM Knowledge Graph ===")
    print(f"Источник: {DIETEBI_DIR}")
    print(f"Статей: {len(ARTICLES)}, рёбер: {len(EDGES)}")
    print()

    stats = import_articles(verbose=not args.quiet)

    print()
    print(f"✅ Импорт завершён: {stats['added']} узлов, {stats['edges']} рёбер, "
          f"{stats['errors']} ошибок")

    # Полная статистика KG
    try:
        s = kg_stats()
        print(f"   KG итого: {s.get('nodes',0)} узлов, "
              f"{s.get('edges',0)} рёбер, "
              f"{s.get('projects',0)} проектов")
    except Exception as e:
        print(f"   (stats: {e})")


if __name__ == "__main__":
    main()
