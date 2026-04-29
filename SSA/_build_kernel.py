#!/usr/bin/env python3
"""
SSA — оркестратор сборки ядра подпроекта Системного Синдромального Анализа CBC.

Идея: каждый параметр CBC дискретизируется на 5 зон:
    L2 = ниже нижнего критического  (life-threatening low)
    L1 = ниже оптимума               (subnormal)
    L0 = оптимум                     (target range)
    H1 = выше оптимума               (supranormal)
    H2 = выше верхнего критического  (life-threatening high)

Каждое наблюдение CBC → tuple зон → синдромальный паттерн.

Этапы:
  1. sources: per-parameter 5-зонные карты (24 параметра).
  2. patterns: парные и тройные паттерны (синдромы).
  3. meta:    методология, литература, валидация.
  4. core:    9 файлов ядра по схеме AIM.

Запуск:
  python3 _build_kernel.py [stage]    stage = sources|patterns|meta|core|all
"""

from __future__ import annotations
import os, sys, time, traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_AIM = Path.home() / "Desktop" / "AIM"
sys.path.insert(0, str(ROOT_AIM))
os.chdir(ROOT_AIM)
from llm import ask_deep  # noqa: E402

ROOT = Path.home() / "Desktop" / "AIM" / "SSA"
SRC = ROOT / "sources"
PAT = ROOT / "patterns"
LOG = ROOT / "_build.log"
SRC.mkdir(parents=True, exist_ok=True)
PAT.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


SYSTEM_RU = (
    "Ты — клинический гематолог-методолог. Пишешь академически точно, по-русски. "
    "Используешь markdown с таблицами, нумерованными списками, ссылками на классику "
    "(Hoffbrand, Williams Hematology, Wintrobe, Лука Б., Кассирский И.А., Файнштейн Ф.Э., "
    "WHO, BCSH, ICSH-стандарты). Без вступлений и общих фраз. Только клиническое содержание."
)


# ─────────────────────────── PARAMETERS ─────────────────────────────────────
# 24 параметра классического CBC + ключевые деривативы.
PARAMS = [
    ("01_WBC",    "Лейкоциты (WBC, абс. количество × 10⁹/л)"),
    ("02_RBC",    "Эритроциты (RBC, × 10¹²/л)"),
    ("03_HGB",    "Гемоглобин (HGB, г/л)"),
    ("04_HCT",    "Гематокрит (HCT, %)"),
    ("05_MCV",    "Средний объём эритроцита (MCV, fL)"),
    ("06_MCH",    "Среднее содержание Hb в эритроците (MCH, pg)"),
    ("07_MCHC",   "Средняя концентрация Hb в эритроците (MCHC, г/л)"),
    ("08_RDW",    "Распределение эритроцитов по объёму (RDW-CV, %)"),
    ("09_PLT",    "Тромбоциты (PLT, × 10⁹/л)"),
    ("10_MPV",    "Средний объём тромбоцита (MPV, fL)"),
    ("11_PDW",    "Распределение тромбоцитов по объёму (PDW)"),
    ("12_PCT",    "Тромбокрит (PCT, %)"),
    ("13_NEUT_abs","Нейтрофилы абсолютные (× 10⁹/л)"),
    ("14_NEUT_pct","Нейтрофилы %"),
    ("15_LYMPH_abs","Лимфоциты абсолютные (× 10⁹/л)"),
    ("16_LYMPH_pct","Лимфоциты %"),
    ("17_MONO_abs","Моноциты абсолютные (× 10⁹/л)"),
    ("18_MONO_pct","Моноциты %"),
    ("19_EOS_abs","Эозинофилы абсолютные (× 10⁹/л)"),
    ("20_EOS_pct","Эозинофилы %"),
    ("21_BASO_abs","Базофилы абсолютные (× 10⁹/л)"),
    ("22_BASO_pct","Базофилы %"),
    ("23_RETIC", "Ретикулоциты (RET %, RET-He)"),
    ("24_ESR",   "СОЭ (ESR, мм/ч) — формально не CBC, но всегда идёт пакетом"),
    ("25_NLR",   "Деривативы — NLR (neutrophil-to-lymphocyte ratio)"),
    ("26_PLR",   "Деривативы — PLR (platelet-to-lymphocyte ratio)"),
    ("27_SII",   "Деривативы — SII (systemic immune-inflammation index = NLR × PLT)"),
    ("28_RDW_PLT","Деривативы — RPR (RDW-to-platelet ratio)"),
]


def param_prompt(name: str, descr: str) -> str:
    return f"""
Параметр CBC: **{descr}**

Сформируй полный 5-зонный профиль этого параметра:

Зоны:
- **L2** — ниже нижнего критического (life-threatening low)
- **L1** — ниже оптимума, но выше критического
- **L0** — оптимум (target / референс)
- **H1** — выше оптимума, но ниже верхнего критического
- **H2** — выше верхнего критического (life-threatening high)

Для каждой зоны заполни шаблон:

### {{ZONE}} — {{короткое название}}
- **Числовые границы (взрослые):** мужчины / женщины / беременные. Указать единицы.
- **Числовые границы (педиатрия):** новорождённые / грудные / 1-12 лет / подростки.
- **Скорость наступления имеет значение?** (острое vs хроническое — разные интерпретации).
- **Что это значит физиологически:** механизм возникновения именно этой зоны.
- **Дифряд (топ-7 причин)** — таблица: причина / частота (common/uncommon/rare) / ключевые ассоциации.
- **Опасность сейчас:** что может случиться у пациента в ближайшие часы / сутки / недели именно при этом значении (например, для PLT < 10 — спонтанное ВЧК).
- **Минимальный набор подтверждающих тестов:** что заказать, чтобы сузить дифряд.
- **Подсказки на скрытое:** какие смежные CBC-параметры проверить (например, MCV при анемии, ретикулоциты при цитопении).
- **Pitfalls / artefacts:** холодовые агглютинины, EDTA-зависимая псевдотромбоцитопения, гемолиз при заборе, lipemia, leucocytosis-induced spuriously raised Hb и т.д.
- **Pearls:** 2-3 клинические жемчужины (правило Виноградова, Wintrobe, Hoffbrand).

В конце профиля — **сводная таблица «зона → синдромальный смысл»** в одну строку на зону.

Ссылки в скобках в стиле «Hoffbrand 2020», «WHO 2011», «ICSH 2014». Без преамбул.
""".strip()


# ─────────────────────────── PATTERNS ───────────────────────────────────────
# Парные паттерны = клинически значимые двойные комбинации зон по двум параметрам.
PAIR_PATTERNS = [
    ("HGB_x_MCV",     "HGB × MCV — анемии: микро/нормо/макроцитарные с разной тяжестью"),
    ("HGB_x_RDW",     "HGB × RDW — обогащённая классификация анемий (Бессман, Mayo)"),
    ("HGB_x_RETIC",   "HGB × ретикулоциты — гипо- vs гиперрегенераторные анемии"),
    ("WBC_x_NEUT",    "WBC × NEUT — лейкоцитоз/лейкопения с нейтрофильным профилем"),
    ("WBC_x_LYMPH",   "WBC × LYMPH — вирусная картина, лимфопролиферативные, иммунодефициты"),
    ("WBC_x_EOS",     "WBC × EOS — эозинофильные синдромы, паразиты, аллергии, HES, EGPA"),
    ("PLT_x_MPV",     "PLT × MPV — продукция vs деструкция тромбоцитов"),
    ("PLT_x_WBC",     "PLT × WBC — миелопролиферация, ИТП, ТТП, сепсис, ДВС"),
    ("NEUT_x_LYMPH",  "NEUT × LYMPH (NLR) — стресс, инфекция, COVID, прогноз онкологии"),
    ("MCV_x_MCHC",    "MCV × MCHC — микро-гипохром, нормо-нормо, макро-нормо, сфероцитоз"),
    ("MCV_x_RDW",     "MCV × RDW — Bessman classification (homo/hetero)"),
    ("HCT_x_HGB",     "HCT × HGB — нарушения соотношения (3:1 правило), микроцитоз"),
    ("RBC_x_HGB",     "RBC × HGB — талассемия (RBC↑ + HGB↓), полицитемия абсолютная vs относительная"),
    ("EOS_x_BASO",    "EOS × BASO — миелопролиферация, аллергический фон, миастения"),
    ("MONO_x_LYMPH",  "MONO × LYMPH — мононуклеоз, ХММЛ, туберкулёз, саркоидоз"),
]

TRIPLE_PATTERNS = [
    ("PANCYTOPENIA",         "Панцитопения = WBC↓ + HGB↓ + PLT↓ — апластическая, миелодиспластический синдром, миелофиброз, megaloblastoid, инфильтрация костного мозга, гиперспленизм, ПНГ"),
    ("BICYTOPENIA_HEM_PLT",  "Бицитопения HGB↓ + PLT↓ при сохранных WBC: ТТП/HUS, ДВС, гиперспленизм, B12-дефицит, MDS"),
    ("LEUKOERYTHROBLASTIC",  "Лейкоэритробластическая картина = NEUT↑ + nRBC + слёзовидные эритроциты — миелофиброз, метастазы в КМ, тяжёлый сепсис, кровотечение"),
    ("MYELOPROLIFERATIVE",   "WBC↑ + PLT↑ + HGB↑ (или RBC↑) — миелопролиферативные новообразования (PV, ET, PMF, CML)"),
    ("INFLAMMATION",         "WBC↑ + NEUT↑ + PLT↑ + ESR↑ — острофазное воспаление; различение септическое vs стерильное"),
    ("VIRAL_PATTERN",        "WBC ~normal/↓ + LYMPH↑ + atypical lymph — острые вирусные инфекции, IM, CMV, COVID-19"),
    ("EOS_HYPERSYNDROME",    "EOS↑↑ (>1.5×10⁹/л устойчиво) + органная дисфункция — HES, EGPA, паразитоз, лекарственная DRESS"),
    ("ANEMIA_MICROCYTIC_SET","HGB↓ + MCV↓ + MCH↓ + RDW↑ — ЖДА; HGB↓ + MCV↓ + RBC↑ + RDW нормальный — талассемия"),
    ("ANEMIA_MACROCYTIC_SET","HGB↓ + MCV↑ + RDW↑ + макроциты + гиперсегментация — мегалобластная (B12/фолат); или MDS"),
    ("HEMOLYSIS_PATTERN",    "HGB↓ + RETIC↑↑ + LDH↑ (внешний) + непрямой билирубин↑ + гаптоглобин↓ — гемолиз; CBC-часть: HGB↓ + MCV ~normal/↑"),
    ("THROMBOTIC_MICROANG",  "PLT↓↓ + HGB↓ + шистоциты + RETIC↑ — ТТП/HUS/ДВС"),
    ("SEPSIS_DECOMP",        "Шок-картина: WBC↓↓ или WBC↑↑ + бэндемия + PLT↓ + LYMPH↓↓ — септическая декомпенсация"),
    ("STRESS_CORTISOL",      "WBC↑ + NEUT↑ + LYMPH↓ + EOS↓ — стресс/кортикостероиды/острая хирургия"),
    ("BONE_MARROW_FAILURE",  "Все ростки↓ + ретикулоциты↓ — апластическая анемия / тяжёлая ЛТ"),
    ("PROLONGED_INFL_ANEMIA","HGB↓ + MCV нормальный/↓ + RDW нормальный + ESR↑ + PLT↑ — анемия хронического воспаления"),
]


def pair_prompt(name: str, scope: str) -> str:
    return f"""
Парный синдромальный паттерн CBC: **{scope}**

Каждый параметр в 5-зонной шкале (L2/L1/L0/H1/H2). Сформируй полную таблицу комбинаций.

Структура ответа:

## {name} — обзор

Краткое введение (1-2 строки) — что эта пара ловит.

### Таблица 5×5 комбинаций
| Param1 \\ Param2 | L2 | L1 | L0 | H1 | H2 |
|---|---|---|---|---|---|
| **L2** | ... | ... | ... | ... | ... |
| **L1** | ... | ... | ... | ... | ... |
| **L0** | ... | ... | ... | ... | ... |
| **H1** | ... | ... | ... | ... | ... |
| **H2** | ... | ... | ... | ... | ... |

В каждую ячейку — короткая формула: **синдром / 1-2 ключевые причины / срочность (red/amber/green)**.

### Ключевые ячейки — расшифровка
Для 5-7 наиболее клинически значимых ячеек дай **развёрнутый разбор**:
- что значит этот двойной паттерн физиологически
- топ-3 причины с частотой
- что заказать следующим шагом
- pitfalls

### Pearls
2-3 клинические жемчужины именно для этой пары.

Ссылки на классику в скобках. Без преамбул.
""".strip()


def triple_prompt(name: str, scope: str) -> str:
    return f"""
Тройной/синдромальный паттерн CBC: **{scope}**

Сформируй академический разбор:

## {name}

### Определение и порог
Какие именно зоны параметров образуют этот паттерн (формализм через 5-зонную шкалу
L2/L1/L0/H1/H2 для каждого участвующего параметра).

### Физиология/патогенез
Один абзац, что происходит на уровне костного мозга, периферии, потребления.

### Дифференциальный ряд
Таблица с колонками: Диагноз / Частота / Ключевые отличия / Подтверждающий тест.
10-15 строк.

### Алгоритм действий
Пошагово (нумерованно): что заказать первым, как ветвиться по результату.

### Скорость и срочность
Острое vs хроническое наступление; red flags для немедленной госпитализации.

### Pitfalls / artefacts
EDTA-агглютинация, аналитические артефакты, лекарственные эффекты.

### Pearls
3-4 жемчужины.

### Литература
2-5 ключевых ссылок в скобках в тексте (Hoffbrand, Williams, Hoffman/Benz, ASH-guideline).

Без преамбул.
""".strip()


# ─────────────────────────── META ───────────────────────────────────────────
META_SECTIONS = [
    ("01_zonal_methodology",
     "5-зонная методология (L2/L1/L0/H1/H2): историческая основа (Wintrobe ranges, "
     "ICSH 2014, BCSH guidelines), статистика на population reference (97.5/2.5 percentile + "
     "clinical critical thresholds), почему 5 зон точнее 3-х (low/normal/high)"),
    ("02_combinatorics",
     "Комбинаторика: 28 параметров × 5 зон = 5²⁸ ≈ 7.45×10¹⁹ возможных профилей. Как это "
     "сводится к ~50-200 клинически осмысленным паттернам через doминантные оси (anemia "
     "axis, infl axis, MPN axis, BM-failure axis, hemolysis axis, allergy/parasite axis, "
     "vire axis). Концепция syndrome-vector в multidim space."),
    ("03_population_refs",
     "Референсные интервалы и критические пороги: ICSH 2014, NHANES, GeKid, RU-стандарты. "
     "Различия по полу/возрасту/беременности/высокогорью. Когда лабораторная норма "
     "противоречит клинике (нижний лимит Hb по WHO vs ВОЗ vs национальные)."),
    ("04_evidence_for_combinations",
     "Доказательная база для комбинаций: Bessman 1983 (MCV/RDW), Mentzer index, "
     "England-Fraser index, Green-King, Sirdah, Ricerca; NLR (Zahorec 2001 → COVID-19, "
     "онко), PLR, SII (Hu 2014). Прогностические ML-модели на CBC: Razavian, Cabitza."),
    ("05_artefacts_pitfalls",
     "Лабораторные артефакты, фальшивые отклонения: EDTA-зависимая псевдотромбоцитопения, "
     "холодовые агглютинины (фальшиво высокий MCV), гипертриглицеридемия (фальшиво "
     "повышенный Hb), лейкоцитоз >100 (искажение Hb), хранение пробы, ICSH "
     "квалификационные требования к анализаторам."),
    ("06_validation_metrics",
     "Метрики качества SSA-движка: top-1 / top-3 синдромальный паттерн accuracy на gold "
     "set из ~200 CBC; calibration (ECE), red-flag-miss-rate (для panсytopenia, TMA, "
     "leukoerythroblastic — must-not-miss), time-to-pattern. Сравнение с человеком "
     "(Cabitza 2021, Goh 2024)."),
    ("07_synthesis_for_aim",
     "СИНТЕЗ для проекта SSA в составе AIM: вход = CBC values → digitize в 5-зонную "
     "шкалу → match по таблицам patterns/ → ranked syndrome list → flag for differential "
     "with DiffDiagnosis. Архитектура слоёв: data (referenсе ranges JSON) → engine "
     "(zonal mapper + pattern matcher) → API → UI. Связь с DiffDiagnosis: SSA отдаёт "
     "узкий список синдромов как вход в DiffDiagnosis."),
]


def meta_prompt(name: str, scope: str) -> str:
    return f"""
Раздел мета-аналитического обзора методологии SSA: **{scope}**

Глубокий академический стиль на русском. Каждое утверждение — со ссылкой на конкретный
источник (Hoffbrand, Williams, Hoffman/Benz, Wintrobe, ICSH, WHO, BCSH; первичные
исследования: Bessman 1983, Zahorec 2001, Hu 2014, Cabitza 2021, Goh 2024). Цитирование
в стиле «Автор Год» прямо в тексте.

Структура: ## заголовок → ### подразделы → таблицы → итоговые выводы.

Без воды, без преамбул, без вступлений. Если упёрся в лимит — `<!-- TBD -->`.
""".strip()


# ─────────────────────────── CORE ───────────────────────────────────────────
CORE_FILES = [
    "CONCEPT.md","README.md","CLAUDE.md","THEORY.md","DESIGN.md",
    "EVIDENCE.md","PARAMETERS.md","STATE.md","OPEN_PROBLEMS.md",
]


def _digest(label: str, max_chars: int) -> str:
    bucket = SRC if label != "pattern" else PAT
    head = []
    for p in sorted(bucket.glob("*.md")):
        if label in p.name or label == "any":
            text = p.read_text(encoding="utf-8")
            lines = [l for l in text.splitlines() if l.startswith("## ") or l.startswith("### ")]
            head.append(f"### {p.name}\n" + "\n".join(lines[:40]))
    return "\n\n".join(head)[:max_chars]


def core_prompt(filename: str) -> str:
    params_digest = _digest("", 5000) if False else "\n".join(f"- {n}: {d}" for n,d in PARAMS)
    pairs_digest = "\n".join(f"- {n}: {d}" for n,d in PAIR_PATTERNS)
    triples_digest = "\n".join(f"- {n}: {d}" for n,d in TRIPLE_PATTERNS)
    metas_digest = "\n".join(f"- {n}: {d}" for n,d in META_SECTIONS)

    common_ctx = f"""
КОНТЕКСТ — подпроект **AIM/SSA** = Системный Синдромальный Анализ полного клинического
анализа крови (CBC).

Принцип: каждый из 28 параметров CBC дискретизируется на 5 зон:
  L2 (≪ нижний критический) | L1 (ниже опт) | L0 (опт) | H1 (выше опт) | H2 (≫ верхний критический)
Любой результат CBC = вектор зон длиной 28.
Задача движка: вектор зон → ранжированный список синдромальных паттернов.

Параметры (28):
{params_digest}

Парные паттерны (15):
{pairs_digest}

Тройные/синдромальные паттерны (15):
{triples_digest}

Мета-аналитика (7 секций):
{metas_digest}

Подпроект живёт в `~/Desktop/AIM/SSA/`. Стек тот же, что у DiffDiagnosis: Rust backend
(axum) + Phoenix LiveView frontend; LLM только через `~/Desktop/AIM/llm.py`.
SSA связан с DiffDiagnosis: SSA → синдромы → DiffDiagnosis → нозологии.
""".strip()

    if filename == "CONCEPT.md":
        return common_ctx + "\n\n" + """
Сгенерируй CONCEPT.md по 9-файловой схеме AIM. Состав:

## 1. Vision
Что такое SSA, зачем, кто пользователь.

## 2. Scope
Что входит (CBC + ESR + 4 деривативы), что НЕ входит (биохимия, коагулограмма, иммунограмма — отдельные подпроекты).

## 3. Принцип 5-зонной дискретизации
Формальное определение L2/L1/L0/H1/H2; почему 5 зон, а не 3 (low/normal/high) и не 7.

## 4. Пайплайн
CBC raw → digitizer (5-zonal) → vector(28) → pattern matcher → ranked syndromes → output.
Связь с DiffDiagnosis (SSA → DiffDiagnosis).

## 5. Архитектура (high-level)
Слои: data (ranges + patterns JSON) / engine (Rust) / API (axum) / UI (Phoenix).

## 6. Файловая структура
~/Desktop/AIM/SSA/ дерево с пояснениями.

## 7. Источник истины
sources/parameter_*.md — per-parameter карты;
patterns/pair_*.md, patterns/triple_*.md — синдромальные таблицы;
ranges.json + patterns.json — машинно-читаемые формализации.

## 8. Связь с AIM
agents/doctor.py использует SSA как preprocessing-слой для дифдиагностики.
SSA НЕ дублирует DiffDiagnosis — это специализированный анализатор CBC.

## 9. Метрики качества
top-1 / top-3 паттерн accuracy ≥ 0.7 / 0.9; red-flag miss-rate ≤ 0.02.

Markdown, без воды.
""".strip()

    if filename == "README.md":
        return common_ctx + "\n\n" + """
Сгенерируй README.md — public-safe quickstart на русском.
# SSA · Syndromic Hematology Analyzer
Краткое описание + пример входа/выхода (CBC values → ranked syndromes).
## Запуск backend / frontend.
## API.
## Источники: Hoffbrand 2020, Williams Hematology 10th ed., ICSH 2014, BCSH guidelines.
## Лицензия: TBD.
Без секретов. Markdown.
""".strip()

    if filename == "CLAUDE.md":
        return common_ctx + "\n\n" + """
Сгенерируй CLAUDE.md — operating rules для Claude в этом подпроекте.
- Расположение: ~/Desktop/AIM/SSA/, монорепо AIM.
- Startup: прочитать CONCEPT, STATE, OPEN_PROBLEMS, проверить consistency 9 файлов.
- LLM: только через ~/Desktop/AIM/llm.py.
- Источник истины: sources/parameter_*.md → ranges.json; patterns/*.md → patterns.json.
- При изменении: сперва .md, потом .json, потом backend tests (cargo test).
- Не подменять референсные интервалы LLM-генерацией без записи в EVIDENCE.md.
- Тесты: cargo test, mix test.
Markdown.
""".strip()

    if filename == "THEORY.md":
        return common_ctx + "\n\n" + """
Сгенерируй THEORY.md — формальная модель SSA.

## 1. 5-зонная дискретизация
Формальное определение зон для параметра p:
   z(p, x) = L2 if x < c_low(p)
           = L1 if c_low(p) ≤ x < r_low(p)
           = L0 if r_low(p) ≤ x ≤ r_high(p)
           = H1 if r_high(p) < x ≤ c_high(p)
           = H2 if x > c_high(p)
где r_low/r_high — population reference (2.5/97.5 percentile), c_low/c_high — clinical
critical thresholds (ICSH 2014).

## 2. CBC vector
v ∈ {L2,L1,L0,H1,H2}^N, N=28. Пространство профилей |V|=5^N≈7.45×10¹⁹.

## 3. Синдромальное многообразие
Подмножество клинически осмысленных профилей S ⊂ V размером ~50-200. Каждый
синдромальный паттерн — это не одна точка в V, а **подмножество** (paттерн с условием
типа "HGB ∈ {L1,L2} и MCV ∈ {L1,L2}").

## 4. Pattern matching
Каждый паттерн p_i имеет функцию match: V → {0,1}. Несколько паттернов могут сработать
одновременно. Ранжирование по специфичности и тяжести.

## 5. Bayesian-overlay
P(syndrome | v) ∝ likelihood(v | syndrome) × prior(syndrome). Calibration на gold-set.

## 6. Связь с DiffDiagnosis
Для каждого синдрома SSA → набор кандидатов нозологий → DiffDiagnosis уточняет.

## 7. Open formal questions
См. OPEN_PROBLEMS.md.

С формулами через `\\(...\\)` или `$$...$$`. Markdown.
""".strip()

    if filename == "DESIGN.md":
        return common_ctx + "\n\n" + """
Сгенерируй DESIGN.md — план реализации.

## 1. Слои
data: ranges.json (28 параметров × {L2/L1/L0/H1/H2 numeric thresholds} × age/sex/preg)
+ patterns.json (paтерны с функциями match).
engine: Rust crate `ssa-engine` — digitizer + matcher.
api: Rust binary `ssa-api` (axum). REST.
ui: Phoenix LiveView.

## 2. REST API
POST /api/v1/cbc      → принимает CBC values + demography → возвращает digitized vector.
POST /api/v1/syndromes → принимает CBC values → возвращает ranked syndromes.
GET  /api/v1/parameter/:id → 5-зонная карта параметра.
GET  /api/v1/pattern/:id   → таблица паттерна.
GET  /api/v1/ranges?sex=&age=&preg= → референсы.

## 3. Схема ranges.json
Один параметр пример:
```json
{ "id":"HGB", "unit":"g/L",
  "ranges":[
    {"sex":"male","age":">=18",
     "L2_max":80,"L1_min":80,"L1_max":135,"L0_min":135,"L0_max":175,"H1_min":175,"H1_max":200,"H2_min":200},
    ... pediatric, female, pregnancy
  ]}
```

## 4. Схема patterns.json
```json
{ "id":"PANCYTOPENIA",
  "match":{
    "AND":[
      {"param":"WBC","zone":["L1","L2"]},
      {"param":"HGB","zone":["L1","L2"]},
      {"param":"PLT","zone":["L1","L2"]}
    ]
  },
  "severity":"red", "differentials":["aplastic","MDS","myelofibrosis","B12_def","gypersplenism","PNH"]
}
```

## 5. Engine pseudo-code
```rust
fn digitize(cbc: Cbc, refs: Ranges) -> Vector<Zone>
fn match_patterns(v: Vector<Zone>, patterns: &[Pattern]) -> Vec<MatchedPattern>
fn rank(matched: Vec<MatchedPattern>) -> RankedSyndromes
```

## 6. Phoenix UI
- /cbc form → /cbc/:id show с вектором зон + ranked syndromes.
- /parameters browse.
- /patterns browse.

## 7. Тесты
20 gold CBC примеров → ожидаемые синдромы. CI = cargo test + mix test.

## 8. Связь с DiffDiagnosis
HTTP-call SSA → DiffDiagnosis с пред-вектором differentials.

Markdown с диаграммой (mermaid или ASCII).
""".strip()

    if filename == "EVIDENCE.md":
        return common_ctx + "\n\n" + """
Сгенерируй EVIDENCE.md — внешние источники.

## 1. Ключевые руководства по гематологии
- Hoffbrand AV, Steensma DP. Hoffbrand's Essential Haematology, 8th ed. 2020.
- Williams Hematology, 10th ed. 2021.
- Hoffman R. et al. Hematology: Basic Principles and Practice, 8th ed. 2023.
- Wintrobe's Clinical Hematology, 14th ed.
- Кассирский И.А., Алексеев Г.А. Клиническая гематология.

## 2. Reference intervals
- ICSH 2014 recommendations for FBC reference intervals.
- BCSH 2016 guidelines.
- WHO definitions of anemia (Hb cutoffs, 2011).
- NHANES reference data.

## 3. Combination indices (peer-reviewed)
- Bessman JD, Gilmer PR, Gardner FH. Improved classification of anemias by MCV and RDW. Am J Clin Pathol 1983.
- Mentzer WC. Differentiation of iron deficiency from thalassemia trait. Lancet 1973.
- Zahorec R. Ratio of neutrophil to lymphocyte counts. Bratisl Lek Listy 2001.
- Hu B et al. Systemic immune-inflammation index. Clin Cancer Res 2014.
- Mentzer, England-Fraser, Green-King, Sirdah, Ricerca indices.

## 4. ML/CDSS на CBC
- Razavian N et al. Population-level prediction of type 2 diabetes from claims data and CBC. JAMIA Open 2016.
- Cabitza F et al. The need to separate the wheat from the chaff in medical informatics. PLOS ONE 2021.
- Goh E et al. Large language model influence on diagnostic reasoning. NEJM AI 2024.

## 5. Артефакты и pitfalls
- Lippi G et al. Pre-analytical variables in haematology testing.
- ICSH guidelines on EDTA-induced pseudothrombocytopenia.

## 6. Связанные проекты в экосистеме AIM
- ~/Desktop/AIM/DiffDiagnosis — потребляет SSA-output.
- BioSense / FCLC / CDATA — биомедицинский RAG, могут переиспользовать ranges.json.

## 7. URLs
ICSH (https://icsh.org), BCSH (https://b-s-h.org.uk), WHO Anemia (https://www.who.int).

С DOI/PMID где возможно. Markdown.
""".strip()

    if filename == "PARAMETERS.md":
        return common_ctx + "\n\n" + """
Сгенерируй PARAMETERS.md — численные/конфигурируемые значения.

## 1. Engine
- ZONE_BORDER_TOLERANCE_PCT = 2 (зона ± 2% — флаг "borderline")
- TOP_K_SYNDROMES = 10
- MIN_PATTERN_SPECIFICITY = 0.3
- ENGINE_TIMEOUT_MS = 1500

## 2. API
- API_PORT = 8766 (DiffDiagnosis занимает 8765)
- API_RATE_LIMIT_RPM = 60

## 3. UI
- PHOENIX_PORT = 4001 (DiffDiagnosis занимает 4000)

## 4. Reference set version
- ranges.json version = "ICSH-2014_v1"
- patterns.json version = "AIM-SSA_v0.1"

## 5. Метрики качества (target)
- top-1 syndrome accuracy ≥ 0.70 на gold-set (n=200 запланировано)
- top-3 ≥ 0.90
- red-flag-miss-rate ≤ 0.02 (panсytopenia / TMA / leukoerythroblastic — must-not-miss)

## 6. Версии стека
Rust ≥ 1.78, Elixir ≥ 1.17, Phoenix ≥ 1.7.

## 7. Дедлайны/гранты
TBD.

Markdown — таблицы.
""".strip()

    if filename == "STATE.md":
        return common_ctx + "\n\n" + """
Сгенерируй STATE.md — волатильное состояние.

## Status
- Phase: 0 (kernel bootstrap)
- Created: 2026-04-29
- Owner: Dr. Jaba Tkemaladze (CEO GLA)

## Active TODOs
- [ ] sources/: проверить полноту 28 параметров
- [ ] patterns/: проверить полноту 15 пар + 15 триплетов
- [ ] ranges.json: формализовать референсы (ICSH-2014)
- [ ] patterns.json: формализовать паттерны
- [ ] backend: cargo init, axum scaffold
- [ ] backend: digitize() + match_patterns() + 10 unit tests
- [ ] frontend: mix phx.new + LiveView /cbc
- [ ] gold-set: 200 CBC с экспертными метками синдромов
- [ ] integration: SSA → DiffDiagnosis (HTTP)

## Decision Log
- 2026-04-29: проект создан; 5-зонная дискретизация принята как канон.
- 2026-04-29: 28 параметров (24 CBC + ESR + 3 derivative).
- 2026-04-29: стек Rust+Phoenix (как у DiffDiagnosis).

## Что НЕ делать
- Не подменять ICSH-2014 референсы LLM-генерацией.
- Не дублировать функции DiffDiagnosis — SSA только пред-обработка CBC.
- Не упрощать 5 зон до 3 (low/normal/high) — это потеря клинической информации.

## Milestones (✅)
(пусто)

## Startup checklist
1. Прочитать CONCEPT, STATE, OPEN_PROBLEMS.
2. cargo check проходит.
3. mix compile проходит.
4. 9 core .md на месте.

Markdown.
""".strip()

    if filename == "OPEN_PROBLEMS.md":
        return common_ctx + "\n\n" + """
Сгенерируй OPEN_PROBLEMS.md.

## 1. Reference intervals
- ICSH 2014 — взрослые. Педиатрические референсы фрагментарны → требуется отдельная локализация.
- Беременные, высокогорье, расовые особенности (Duffy-null neutropenia) — отдельные ranges.

## 2. Полнота paтернов
- 15 пар × 25 ячеек = 375 комбинаций; не все клинически осмысленны.
- Тройные паттерны = заведомо неполный список (~15 из ∞).

## 3. 5-зонная гипотеза
- Граница L2/L1 и H1/H2 = clinical critical, не population. Где взять с доказательной базой? ICSH рекомендует, но не всегда даёт чисел для всех параметров.

## 4. Артефакты
- EDTA-агглютинация, холодовые агглютинины, lipemia, leucocytosis-induced pseudo-Hb.
- Mitigation: в API входе требовать pre-analytical flag (если есть).

## 5. Calibration
- LLM-rerank уровень не откалиброван. Нужна Platt/isotonic на gold-set.

## 6. Multi-label синдромы
- Один CBC может одновременно быть «панцитопения» и «гемолиз» (если идёт ТМА). Текущая схема ranking, не sets.

## 7. Связь с DiffDiagnosis
- Контракт SSA → DiffDiagnosis (формат: ранжированный список syndromes → preferred algorithms) — пока на уровне идеи.

## 8. Pediatric
- Острая необходимость в отдельной taxonomy для детей <2 лет.

## 9. Regulatory
- Clinical decision support → MDR/SaMD. На R&D стадии не критично.

## 10. Validation set
- 200 CBC — план; пока 0.

Markdown.
""".strip()

    return f"# {filename}\n\nTBD"


# ─────────────────────────── EXECUTOR ───────────────────────────────────────


def run_chunk(out_path: Path, prompt: str, label: str, system: str = SYSTEM_RU) -> str:
    if out_path.exists() and out_path.stat().st_size > 1000:
        log(f"SKIP   {label}  ({out_path.stat().st_size} B)")
        return f"skip:{label}"
    log(f"START  {label}")
    t0 = time.time()
    try:
        result = ask_deep(prompt, system=system)
    except Exception as e:
        log(f"ERROR  {label}: {e}")
        log(traceback.format_exc())
        return f"error:{label}"
    dt = time.time() - t0
    out_path.write_text(result, encoding="utf-8")
    log(f"DONE   {label}  in {dt:.0f}s, {len(result)} chars")
    return f"ok:{label}"


def run_parallel(jobs, workers=6):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_chunk, p, pr, lab): lab for (p,pr,lab) in jobs}
        for fut in as_completed(futures):
            fut.result()


def stage_sources():
    log("=== STAGE: sources (28 параметров) ===")
    jobs = []
    for name, descr in PARAMS:
        out = SRC / f"parameter_{name}.md"
        jobs.append((out, param_prompt(name, descr), f"param/{name}"))
    run_parallel(jobs, workers=6)
    log("=== STAGE sources: DONE ===")


def stage_patterns():
    log("=== STAGE: patterns (15 пар + 15 триплетов) ===")
    jobs = []
    for name, scope in PAIR_PATTERNS:
        out = PAT / f"pair_{name}.md"
        jobs.append((out, pair_prompt(name, scope), f"pair/{name}"))
    for name, scope in TRIPLE_PATTERNS:
        out = PAT / f"triple_{name}.md"
        jobs.append((out, triple_prompt(name, scope), f"triple/{name}"))
    run_parallel(jobs, workers=6)
    log("=== STAGE patterns: DONE ===")


DYNAMICS_TOPICS = [
    ("01_acute_bleeding",         "Острая кровопотеря: первый час → первые сутки → 1-2 нед. По всем 28 параметрам — что меняется первым (PLT/HCT гемодилюция спустя часы), реактивный ретикулоцитоз 3-5 день, NEUT↑ ранний"),
    ("02_acute_infection_bacter", "Острая бактериальная инфекция: WBC dynamics, NEUT shift / bandemia, PLT, NLR, SII; стадия sepsis decompensation = WBC↓↓ + LYMPH↓↓"),
    ("03_acute_viral",            "Острая вирусная инфекция: WBC ↓ или N → LYMPH↑ + atypical; динамика по дням болезни"),
    ("04_iron_def_progression",   "Прогрессия ЖДА: первые недели — HGB N, ferritin↓; затем MCV↓, RBC compensatory↑; терапевтический ответ — RETIC↑ к 5-10 дню, HGB +20 г/л за 4 нед"),
    ("05_b12_folate",             "Дефицит B12/фолата: первые проявления — гиперсегментация, потом MCV↑, потом анемия; ретикулоцитопения; терапия — RETIC crisis на 3-5 день"),
    ("06_chemo_nadir",            "Химиотерапия: nadir по WBC день 7-14, по PLT день 10-14; recovery; MASCC/CISNE, febrile neutropenia как red flag"),
    ("07_radiation",              "Острый лучевой синдром: цитопения по дням 4-30; LYMPH падает первым (часы), PLT/NEUT — 2-3 нед"),
    ("08_TTP_HUS_DIC",            "ТМА/ДВС: динамика PLT (часы-дни), HGB↓ + шистоциты, RETIC↑, фибриноген отдельно. Дифференциация по скорости падения"),
    ("09_chronic_inflammation",   "Хроническое воспаление: PLT↑ устойчивое, MCV↓ (anemia of chronic disease), ESR/SII; стабильность месяцами"),
    ("10_pregnancy",              "Беременность по триместрам: HGB физиологическое снижение, PLT ~slight↓, WBC↑, MCV ~stable; HELLP — острая dynamics"),
    ("11_high_altitude",          "Высокогорная адаптация: HGB↑/HCT↑/RBC↑ за недели; деакклиматизация"),
    ("12_steroids",               "Кортикостероиды: WBC↑ + NEUT↑ + LYMPH↓ + EOS↓ за часы; через 24-48ч — стабильно повышен NEUT, мобилизация маргинального пула"),
    ("13_solid_tumor",            "Солидный рак: anemia of chronic disease, реактивный thromcytosis, NLR/PLR прогноз, leukoerythroblastic при mts в КМ"),
    ("14_MPN_evolution",          "МПЗ: PV/ET/PMF — HGB↑ → ET-like → миелофиброз; dynamics над годами"),
    ("15_recovery_post_aplastic", "Восстановление после апластической анемии / трансплантации: ретикулоциты — первый маркер, потом NEUT, потом PLT"),
]


def dynamics_prompt(name: str, scope: str) -> str:
    return f"""
Раздел временно́й динамики SSA: **{scope}**

Задача — описать как **все 28 параметров CBC** (см. контекст параметров ниже)
ведут себя во времени при данном клиническом сценарии. Не ограничиваться 1-2
параметрами — проходить по всем, отмечая «не меняется» где так есть, «меняется
первым/вторым/последним», и количественно (например, «PLT падает на 30-50%
за 4-6 часов»).

Структура ответа:

## {name} — динамика по 28 параметрам CBC

### Временна́я шкала (фазы)
Перечислить фазы (например: hyperacute 0-6h / acute 6-24h / subacute 1-7d /
chronic >7d / recovery), для каждой фазы — таблица.

### Таблица «параметр → фаза → ожидаемая зона (L2/L1/L0/H1/H2)»
| Параметр | Фаза 1 | Фаза 2 | Фаза 3 | Фаза 4 | Комментарий |
|---|---|---|---|---|---|
| WBC | ... | ... | ... | ... | ... |
| RBC | ... | ... | ... | ... | ... |
| HGB | ... | ... | ... | ... | ... |
| HCT | ... | ... | ... | ... | ... |
| MCV | ... | ... | ... | ... | ... |
| MCH | ... | ... | ... | ... | ... |
| MCHC | ... | ... | ... | ... | ... |
| RDW | ... | ... | ... | ... | ... |
| PLT | ... | ... | ... | ... | ... |
| MPV | ... | ... | ... | ... | ... |
| PDW | ... | ... | ... | ... | ... |
| PCT | ... | ... | ... | ... | ... |
| NEUT_abs | ... | ... | ... | ... | ... |
| NEUT_pct | ... | ... | ... | ... | ... |
| LYMPH_abs | ... | ... | ... | ... | ... |
| LYMPH_pct | ... | ... | ... | ... | ... |
| MONO_abs | ... | ... | ... | ... | ... |
| MONO_pct | ... | ... | ... | ... | ... |
| EOS_abs | ... | ... | ... | ... | ... |
| EOS_pct | ... | ... | ... | ... | ... |
| BASO_abs | ... | ... | ... | ... | ... |
| BASO_pct | ... | ... | ... | ... | ... |
| RETIC | ... | ... | ... | ... | ... |
| ESR | ... | ... | ... | ... | ... |
| NLR | ... | ... | ... | ... | ... |
| PLR | ... | ... | ... | ... | ... |
| SII | ... | ... | ... | ... | ... |
| RDW/PLT | ... | ... | ... | ... | ... |

ВСЕ 28 строк должны быть. Если параметр не меняется — писать `L0` и в комментарии «no change».

### Маркер первого реагирования
Какой параметр меняется первым? Когда? Почему (физиология)?

### Маркер выздоровления
Какой параметр первым возвращается к норме (полезно для мониторинга терапии)?

### Pitfalls в интерпретации dynamics
2-3 ловушки.

### Pearls
3-4 жемчужины.

### Литература
Ссылки на классику в скобках.

Без преамбул. Если упёрся в лимит — `<!-- TBD -->`.
""".strip()


def stage_dynamics():
    log("=== STAGE: dynamics (15 сценариев × 28 параметров) ===")
    jobs = []
    for name, scope in DYNAMICS_TOPICS:
        out = PAT / f"dyn_{name}.md"
        jobs.append((out, dynamics_prompt(name, scope), f"dyn/{name}"))
    run_parallel(jobs, workers=6)
    log("=== STAGE dynamics: DONE ===")


def stage_meta():
    log("=== STAGE: meta-analysis ===")
    jobs = []
    for name, scope in META_SECTIONS:
        out = SRC / f"meta_{name}.md"
        jobs.append((out, meta_prompt(name, scope), f"meta/{name}"))
    run_parallel(jobs, workers=4)
    parts = ["# Мета-анализ методологии SSA\n"]
    for name, _ in META_SECTIONS:
        f = SRC / f"meta_{name}.md"
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
            parts.append("\n---\n")
    (SRC / "meta_analysis.md").write_text("\n".join(parts), encoding="utf-8")
    log("=== STAGE meta: DONE ===")


def stage_core():
    log("=== STAGE: core (9 файлов) ===")
    jobs = []
    for fname in CORE_FILES:
        out = ROOT / fname
        jobs.append((out, core_prompt(fname), f"core/{fname}"))
    run_parallel(jobs, workers=3)
    log("=== STAGE core: DONE ===")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    LOG.write_text(f"=== build started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n", encoding="utf-8")
    log(f"stage={stage} ROOT={ROOT}")
    if stage in ("sources","all"):  stage_sources()
    if stage in ("patterns","all"): stage_patterns()
    if stage in ("dynamics","all"): stage_dynamics()
    if stage in ("meta","all"):     stage_meta()
    if stage in ("core","all"):     stage_core()
    log("=== ALL DONE ===")


if __name__ == "__main__":
    main()
