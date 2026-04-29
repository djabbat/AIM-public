#!/usr/bin/env python3
"""
DiffDiagnosis — оркестратор сборки ядра через DeepSeek-reasoner.

Этапы:
  1. Параллельно: главы Виноградова, главы Taylor.
  2. Параллельно: мета-анализ методологий.
  3. Последовательно: CONCEPT + 8 core .md.
  4. Параллельно: Rust backend + Phoenix frontend (skeleton + manifest).

Запуск:
  cd ~/Desktop/AIM/DiffDiagnosis && python3 _build_kernel.py [stage]
  где stage = sources | meta | core | code | all   (default: all)

Артефакты пишутся в ~/Desktop/AIM/DiffDiagnosis/.
"""

from __future__ import annotations
import os, sys, json, time, traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Подключаем llm.py из ~/Desktop/AIM
ROOT_AIM = Path.home() / "Desktop" / "AIM"
sys.path.insert(0, str(ROOT_AIM))
os.chdir(ROOT_AIM)  # llm.py делает relative imports из agents/

from llm import ask_deep  # noqa: E402

ROOT = Path.home() / "Desktop" / "AIM" / "DiffDiagnosis"
SRC = ROOT / "sources"
LOG = ROOT / "_build.log"
SRC.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


SYSTEM_RU = (
    "Ты — клинический эксперт-методолог. Пишешь академически точно, по-русски, "
    "со ссылками на канонические источники. Используй markdown с заголовками ##/###, "
    "нумерованными алгоритмами, таблицами дифрядов, списками ключевых признаков. "
    "Никаких вступлений и общих фраз — только клинически содержательный материал. "
    "Сохраняй структуру первоисточника."
)


# ─────────────────────────── ВИНОГРАДОВ ─────────────────────────────────────
VINOGRADOV_CHAPTERS = [
    ("01_chest_pain",
     "Главы по болевым синдромам в грудной клетке: стенокардия, ИМ, расслоение аорты, "
     "ТЭЛА, перикардит, плеврит, пневмония, пневмоторакс, эзофагит, ГЭРБ, межрёберная "
     "невралгия, опоясывающий лишай, синдром Титце"),
    ("02_dyspnea_cough_hemoptysis",
     "Одышка, кашель, кровохарканье: ХОБЛ, БА, пневмонии (бактериальная/вирусная/"
     "атипичная/аспирационная), ТЭЛА, отёк лёгких, рак лёгкого, туберкулёз, "
     "интерстициальные поражения, бронхоэктатическая болезнь, гранулёматоз с полиангиитом"),
    ("03_abdominal_pain",
     "Боль в животе: острый живот (аппендицит, холецистит, панкреатит, перфорация, ОКН, "
     "мезентериальная ишемия), почечная/печёночная колика, ИБС-эквивалент, гастрит/ЯБ, "
     "СРК, энтериты, колиты, перитонит, гинекологические причины"),
    ("04_jaundice_hepatomegaly",
     "Желтуха и гепатомегалия: гемолитическая, паренхиматозная (вирусные гепатиты A-E, "
     "алкогольный, лекарственный, аутоиммунный, неалкогольный жировой), механическая "
     "(холедохолитиаз, опухоли, ПСХ, ПБЦ), синдромы Жильбера/Дабина-Джонсона/Ротора, "
     "цирроз, портальная гипертензия"),
    ("05_fever_FUO",
     "Лихорадка и лихорадка неясного генеза: классификация типов температурных кривых, "
     "критерии FUO (Petersdorf/Durack-Street), инфекции (сепсис, эндокардит, ТБ, ВИЧ, "
     "малярия, бруцеллёз), опухолевая, аутоиммунная, лекарственная, симуляционная"),
    ("06_lymphadenopathy_splenomegaly",
     "Лимфаденопатия и спленомегалия: реактивная, инфекционная (мононуклеоз, ТБ, ВИЧ, "
     "токсоплазмоз, сифилис, ЦМВ), опухолевая (лимфомы, лейкозы, метастазы), системные "
     "болезни, болезни накопления, портальная гипертензия"),
    ("07_anemia_cytopenias",
     "Анемии и цитопении: ЖДА, B12/фолат-дефицитная, гемолитические (АИГА, наследственные), "
     "апластическая, анемия хронических болезней, миелодиспластический синдром, "
     "лейкоцитозы/лейкопении, тромбоцитопении (ИТП, ТТП, ДВС), эозинофилии"),
    ("08_proteinuria_hematuria_renal",
     "Заболевания почек: протеинурия, гематурия, нефритический и нефротический синдромы, "
     "ОПП, ХБП, гломерулонефриты, тубулоинтерстициальные нефриты, диабетическая нефропатия, "
     "мочекаменная болезнь, пиелонефриты"),
    ("09_hypertension_hypotension_shock",
     "Артериальное давление: эссенциальная и вторичные АГ (реноваскулярная, "
     "феохромоцитома, синдром Конна, синдром Кушинга, коарктация), гипотония, "
     "обмороки, шок (кардиогенный, гиповолемический, септический, анафилактический, "
     "обструктивный)"),
    ("10_edema_ascites_pleural",
     "Отёчные синдромы: сердечные, почечные, печёночные, эндокринные (микседема), "
     "венозный застой, лимфостаз, гипопротеинемия. Асцит, плевральный выпот: "
     "транссудат vs экссудат, критерии Лайта, дифференциальный ряд"),
    ("11_arthralgia_myalgia",
     "Суставные и мышечные синдромы: РА, ОА, подагра, анкилозирующий спондилит, "
     "СКВ, ССД, дерматомиозит/полимиозит, ревматическая полимиалгия, реактивные "
     "артриты, серонегативные спондилоартриты, септический артрит"),
    ("12_endocrine_metabolic",
     "Эндокринно-метаболические синдромы: гипо- и гипертиреоз, СД 1/2, диабетический "
     "кетоацидоз, гиперосмолярная кома, гипогликемия, надпочечниковая недостаточность, "
     "тиреотоксический криз, нарушения водно-электролитного баланса"),
    ("13_neurological_syndromes",
     "Неврологические синдромы во внутренней клинике: коматозные состояния, делирий, "
     "ОНМК, менингиты/энцефалиты, периферические нейропатии, миастения, рассеянный "
     "склероз — в плане дифференциальной диагностики системных проявлений"),
]


def vinogradov_prompt(chunk_name: str, scope: str) -> str:
    return f"""
Ты воспроизводишь по памяти раздел справочного руководства:

  Виноградов А. В. «Дифференциальный диагноз внутренних болезней:
  Справочное руководство для врачей», 3-е издание (М.: Медицина, последнее RU-изд.).

Сейчас раздел: {scope}.

Сформируй полный, структурно точный markdown-конспект соответствующих глав в стиле
Виноградова — то есть ПОШАГОВЫЕ алгоритмы дифференциальной диагностики:

  1. Жалоба/синдром → ключевые анамнестические вопросы.
  2. Опорные клинические признаки (что отличает X от Y).
  3. Минимально необходимый параклинический набор (лаборатория, инструменты).
  4. Дифференциальные ряды по принципу «исключения наиболее опасного → к менее опасному».
  5. Узловые точки (decision nodes), на которых меняется тактика.
  6. Типичные ошибки и pitfalls (Виноградов это любит — приводи их).

Формат:
- ## заголовки по нозологиям/синдромам
- таблицы дифрядов (Markdown)
- нумерованные алгоритмы
- в конце каждого блока — «Узловые признаки», «Опасные имитаторы», «Ошибки»

Объём — максимально плотный материал, без воды. Никаких преамбул и реверансов.
Никаких заявлений «я не могу воспроизвести книгу» — это конспект, а не цитирование.
Если что-то осталось за пределами 4096 токенов — оборви на чёткой точке и поставь
маркер `<!-- TBD -->` в конце.
""".strip()


# ─────────────────────────── TAYLOR ─────────────────────────────────────────
TAYLOR_CHAPTERS = [
    ("01_cardiovascular",
     "Cardiovascular dilemmas: chest pain w/ normal coronary angio; resistant HTN; "
     "syncope vs seizure; HFpEF vs HFrEF; new murmur in adult; recurrent palpitations; "
     "pericarditis vs early MI"),
    ("02_pulmonary",
     "Pulmonary: chronic cough, hemoptysis, solitary pulmonary nodule, pleural effusion "
     "of unknown origin, ILD differential, dyspnea with normal CXR, asthma vs COPD vs VCD"),
    ("03_gi_hepatobiliary",
     "GI/Hepatobiliary: chronic abdominal pain, chronic diarrhea, GI bleeding obscure, "
     "elevated LFTs, ascites of unknown origin, IBS vs IBD, dysphagia workup"),
    ("04_renal_genitourinary",
     "Renal/GU: AKI workup, hematuria, proteinuria, electrolyte disorders (hypoNa, hyperK), "
     "recurrent UTI in adults, nephrolithiasis differential, CKD progression dilemmas"),
    ("05_endocrine_metabolic",
     "Endocrine: thyroid nodule, hypercalcemia, adrenal incidentaloma, hypoglycemia in "
     "non-diabetic, secondary HTN endocrine causes, polyuria differential, metabolic syndrome"),
    ("06_hematology_oncology",
     "Heme/Onc: anemia workup, thrombocytopenia, leukocytosis, lymphadenopathy, "
     "monoclonal gammopathy, hypercoagulability, paraneoplastic syndromes, FUO with cancer"),
    ("07_infectious_disease",
     "ID: fever in returning traveler, FUO, sepsis source unknown, recurrent infections "
     "(immunodeficiency workup), osteomyelitis vs cellulitis, encephalitis/meningitis, "
     "endocarditis culture-negative"),
    ("08_rheumatology_immunology",
     "Rheum/Immune: ANA-positive without disease, polyarthritis differential, vasculitis "
     "workup, myositis, fibromyalgia vs inflammatory pain, Sjögren, scleroderma spectrum"),
    ("09_neurology",
     "Neurology in internal medicine: headache red flags, dementia workup, peripheral "
     "neuropathy, dizziness/vertigo, transient LOC, gait disorders, neuro-ophth findings"),
    ("10_dermatology_psychiatry_misc",
     "Dermatology dilemmas (rash + fever, drug eruption vs viral exanthem, "
     "paraneoplastic skin), psychiatric (somatic symptom disorder vs occult disease, "
     "depression vs hypothyroid, delirium vs dementia), geriatric & adolescent edges"),
]


def taylor_prompt(chunk_name: str, scope: str) -> str:
    return f"""
Ты воспроизводишь по памяти соответствующий раздел из:

  Robert B. Taylor (ed.). "Difficult Diagnosis", 2nd Edition.
  W. B. Saunders / Elsevier.

Текущий раздел: {scope}.

Стиль Taylor — каждая глава разбирает ОДИН диагностический дилемму как кейс:
  1. Patient presentation (типичный паттерн).
  2. The diagnostic challenge — why it's "difficult".
  3. Differential diagnosis — список с ключевыми отличиями.
  4. Diagnostic approach — пошагово: history → exam → labs → imaging → biopsy/endo.
  5. Pitfalls and pearls.
  6. When to refer / red flags.

Сформируй markdown-конспект для каждой нозологии раздела в этом формате.
Сохраняй классическую таксономию Taylor: глава = диагностическая дилемма.

ОТВЕТ — на русском, но клинические термины с латинскими/английскими эквивалентами
в скобках, чтобы не терять оригинальную терминологию (e.g. «застойная сердечная
недостаточность с сохранённой ФВ (HFpEF)»).

Формат:
- ## заголовки по дилеммам
- ### подразделы (Presentation / Differential / Approach / Pitfalls / Pearls)
- таблицы дифференциалов
- нумерованные алгоритмы

Никакой воды и преамбул. Если упёрся в лимит — `<!-- TBD -->` маркер.
""".strip()


# ─────────────────────────── МЕТА-АНАЛИЗ ────────────────────────────────────
META_SECTIONS = [
    ("01_classical_algorithmic",
     "Классические алгоритмические системы: Виноградов, Тареев, Мясников (русская "
     "школа); Harrison, Cecil, Kelley, Taylor (англо-американская). Что общего/разного "
     "в построении деревьев решений. Роль анамнеза и физикального осмотра как фильтра."),
    ("02_bayesian_kassirer",
     "Байесовский подход: Pauker–Kassirer threshold model, pretest/posttest probability, "
     "likelihood ratios, threshold for testing/treatment. Как формализуется интуиция "
     "клинициста. Sensitivity/specificity vs LR. SpPin/SnNout эвристики."),
    ("03_pattern_recognition_heuristics",
     "Pattern recognition, illness scripts, prototype matching. Dual-process theory "
     "(System 1/2, Croskerry, Kahneman). Когнитивные ошибки: anchoring, premature "
     "closure, availability bias, search satisficing, confirmation bias. Diagnostic "
     "errors literature: Graber, Croskerry, Singh, Newman-Toker."),
    ("04_mnemonics_VINDICATE_etc",
     "Мнемоники как инструменты ширины дифряда: VINDICATE (Vascular, Infectious, "
     "Neoplastic, Drugs/Degenerative, Idiopathic/Iatrogenic, Congenital, Autoimmune, "
     "Trauma/Toxic, Endocrine/Metabolic), MUDPILES, AEIOU-TIPS, HARDUPS, "
     "OLDCARTS/SOCRATES для боли. Когда мнемоника помогает, когда мешает."),
    ("05_evidence_based_guidelines",
     "EBM-guidelines (NICE, USPSTF, ESC, AHA, EASL, KDIGO, GINA, GOLD), Choosing "
     "Wisely, clinical decision rules (Wells, PERC, CHA2DS2-VASc, HEART, Centor, "
     "Ottawa, NEXUS). Как guideline сосуществует с алгоритмом дифдиагностики."),
    ("06_ml_clinical_decision_support",
     "Машинное обучение и CDSS: DXplain, Isabel, Visual DX, Mediktor, Glass, "
     "AMIE/Med-PaLM/GPT-4 в дифдиагностике. Метрики: top-1, top-3, top-10 accuracy. "
     "Hallucination в LLM-диагностике, calibration, chain-of-thought retrieval. "
     "Сравнение с человеком (Singh 2023, Goh 2024). Что делает ML-CDSS клинически "
     "пригодным."),
    ("07_synthesis_for_aim",
     "СИНТЕЗ для проекта AIM/DiffDiagnosis: какие компоненты из всех систем выше "
     "должны войти в движок? Пошаговая архитектура: ввод симптома → ширина дифряда "
     "(VINDICATE как сито) → байесовское ранжирование → алгоритмический фильтр "
     "Виноградова/Taylor по узловым признакам → guideline overlay → output. "
     "Где LLM, где детерминированный engine, где human-in-the-loop. Метрики качества "
     "движка дифдиагностики (top-N accuracy, calibration, time-to-diagnosis, "
     "missed-can't-miss-rate)."),
]


def meta_prompt(chunk_name: str, scope: str) -> str:
    return f"""
Ты пишешь раздел мета-аналитического обзора систем дифференциальной диагностики
для специализированного клинического AI-движка (проект AIM/DiffDiagnosis).

Текущий раздел: {scope}.

Требования:
- Глубокий, академический стиль на русском.
- Каждое утверждение опирается на конкретный источник (Pauker, Kassirer, Croskerry,
  Graber, Singh, Newman-Toker, Goh, Saposnik, Berner, McKinney и др.) или
  каноническое руководство (Harrison, Cecil, Taylor, Виноградов, Тареев, Мясников).
- Цитируй источники в стиле «Автор Год» прямо в тексте; полный список источников
  не нужен (он соберётся в EVIDENCE.md отдельно), но ключевые работы упомяни.
- Структура: ## заголовок раздела → ### подразделы по подтемам → таблицы сравнений
  → итоговые выводы.
- Без воды, без преамбул, без вступлений «в этом разделе мы рассмотрим».

Сразу к делу. Если упёрся в лимит — `<!-- TBD -->`.
""".strip()


# ─────────────────────────── ИСПОЛНИТЕЛЬ ────────────────────────────────────


def run_chunk(out_path: Path, prompt: str, label: str, system: str = SYSTEM_RU) -> str:
    if out_path.exists() and out_path.stat().st_size > 1000:
        log(f"SKIP   {label}  (уже есть, {out_path.stat().st_size} B)")
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


def run_parallel(jobs: list[tuple[Path, str, str]], workers: int = 4) -> None:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(run_chunk, p, prompt, label): label
            for (p, prompt, label) in jobs
        }
        for fut in as_completed(futures):
            _ = fut.result()


def stage_sources() -> None:
    log("=== STAGE: sources (Виноградов + Taylor) ===")
    jobs = []
    for name, scope in VINOGRADOV_CHAPTERS:
        out = SRC / f"vinogradov_{name}.md"
        jobs.append((out, vinogradov_prompt(name, scope), f"vinogradov/{name}"))
    for name, scope in TAYLOR_CHAPTERS:
        out = SRC / f"taylor_{name}.md"
        jobs.append((out, taylor_prompt(name, scope), f"taylor/{name}"))
    run_parallel(jobs, workers=6)
    # сборка index
    idx = ["# Sources index\n"]
    for name, _ in VINOGRADOV_CHAPTERS:
        idx.append(f"- Виноградов · {name} → `vinogradov_{name}.md`")
    for name, _ in TAYLOR_CHAPTERS:
        idx.append(f"- Taylor · {name} → `taylor_{name}.md`")
    (SRC / "INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    log("=== STAGE sources: DONE ===")


def stage_meta() -> None:
    log("=== STAGE: meta-analysis ===")
    jobs = []
    for name, scope in META_SECTIONS:
        out = SRC / f"meta_{name}.md"
        jobs.append((out, meta_prompt(name, scope), f"meta/{name}"))
    run_parallel(jobs, workers=4)
    # склейка
    parts = ["# Мета-анализ систем дифференциальной диагностики\n"]
    for name, _ in META_SECTIONS:
        f = SRC / f"meta_{name}.md"
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
            parts.append("\n---\n")
    (SRC / "meta_analysis.md").write_text("\n".join(parts), encoding="utf-8")
    log("=== STAGE meta: DONE ===")


# ─────────────────────────── CORE ───────────────────────────────────────────


CORE_FILES = [
    ("CONCEPT.md",      "concept"),
    ("README.md",       "readme"),
    ("CLAUDE.md",       "claude_rules"),
    ("THEORY.md",       "theory"),
    ("DESIGN.md",       "design"),
    ("EVIDENCE.md",     "evidence"),
    ("PARAMETERS.md",   "parameters"),
    ("STATE.md",        "state"),
    ("OPEN_PROBLEMS.md","open_problems"),
]


def _read_or(path: Path, default: str = "") -> str:
    return path.read_text(encoding="utf-8") if path.exists() else default


def _digest(label: str, max_chars: int = 4000) -> str:
    """Короткое резюме для контекста CORE синтеза (укладываемся в 4096 токенов вывода
    + входной контекст). Берём только заголовки из source-файлов."""
    head = []
    for p in sorted(SRC.glob(f"{label}*.md")):
        text = p.read_text(encoding="utf-8")
        # вытащим только заголовки ##
        lines = [l for l in text.splitlines() if l.startswith("## ") or l.startswith("### ")]
        head.append(f"### {p.name}\n" + "\n".join(lines[:60]))
    digest = "\n\n".join(head)
    return digest[:max_chars]


def core_prompt(filename: str) -> str:
    vino = _digest("vinogradov", 6000)
    taylor = _digest("taylor", 6000)
    meta = _digest("meta", 6000)

    common_ctx = f"""
КОНТЕКСТ — содержание подпроекта AIM/DiffDiagnosis:

Заголовки разделов Виноградова (наша БД алгоритмов RU-школы):
{vino}

Заголовки разделов Taylor (наша БД диагностических дилемм EN-школы):
{taylor}

Заголовки мета-аналитического обзора:
{meta}

Подпроект живёт в ~/Desktop/AIM/DiffDiagnosis/. Стек: Rust backend (axum + serde) +
Phoenix LiveView frontend. Диагностический движок — детерминированные алгоритмы
поверх JSON-схемы из sources/, плюс LLM-уровень (DeepSeek через AIM-роутер) для
интерпретации свободного текста и генерации отчётов.
""".strip()

    if filename == "CONCEPT.md":
        return common_ctx + "\n\n" + """
Сгенерируй CONCEPT.md по 9-файловой схеме. Состав:

## 1. Vision
Что такое DiffDiagnosis, зачем, где живёт в экосистеме AIM.

## 2. Scope
Что входит, что НЕ входит (только internal medicine; не педиатрия, не хирургия,
не офтальмология).

## 3. Источники канона
Виноградов А.В. (3-е изд.) — RU-школа алгоритмов;
Robert B. Taylor "Difficult Diagnosis" 2nd ed. — EN-школа диагностических дилемм;
мета-анализ — синтез методологий.

## 4. Архитектурный обзор
Слой 1: JSON-схема алгоритмов (algorithm bank).
Слой 2: Rust-движок (axum + serde). REST API.
Слой 3: LLM-уровень (DeepSeek-reasoner через ~/Desktop/AIM/llm.py).
Слой 4: Phoenix LiveView UI.

## 5. Файловая структура
Дерево директорий с короткими комментариями.

## 6. Источник истины
algorithms.json (формализованная версия sources/) — канон.
sources/*.md — человекочитаемая версия.
backend/ — реализация движка.
frontend/ — UI.

## 7. Связь с AIM
agents/doctor.py может звать DiffDiagnosis backend по REST.
DiffDiagnosis НЕ дублирует функции agents/doctor.py — это специализированный
движок дифференциальной диагностики, doctor.py его использует.

Объём — плотный, без воды. Markdown.
""".strip()

    if filename == "README.md":
        return common_ctx + "\n\n" + """
Сгенерируй README.md — public-safe quickstart на русском (с английскими
терминами в скобках, для международной читаемости). Состав:

# DiffDiagnosis
Краткое 2-3 строки описание.

## Зачем
Проблема дифдиагностики, как её решает DiffDiagnosis.

## Как устроено
Высокоуровневая архитектура (3-4 строки).

## Запуск backend (Rust)
```
cd backend
cargo run
```

## Запуск frontend (Phoenix)
```
cd frontend
mix deps.get
mix phx.server
```

## API
Краткое описание REST endpoints.

## Источники
Vinogradov 3rd ed., Taylor "Difficult Diagnosis" 2nd ed., evidence-based guidelines.

## Лицензия
TBD.

Без секретов, без приватных алгоритмов, без deepseek-ключей.
""".strip()

    if filename == "CLAUDE.md":
        return common_ctx + "\n\n" + """
Сгенерируй CLAUDE.md — operating rules для будущих сессий Claude в этом
подпроекте. Состав:

# CLAUDE.md — DiffDiagnosis

## Расположение
~/Desktop/AIM/DiffDiagnosis/ — подпроект AIM.
Git: НЕ собственный репозиторий, монорепо AIM.

## Startup
1. Прочитать CONCEPT.md, STATE.md, OPEN_PROBLEMS.md.
2. Проверить consistency между 9 core .md.
3. Если есть active TODOs в STATE.md — отчитаться.

## LLM правила
Только через ~/Desktop/AIM/llm.py (ask_deep / ask). Никаких прямых вызовов
DeepSeek API.

## Источник истины
sources/*.md — knowledge base.
algorithms.json — формализованная схема.
При изменении алгоритма: сперва обновить .md, потом algorithms.json,
потом backend tests.

## Что НЕ делать
- Не выкидывать главы Виноградова/Taylor.
- Не подменять алгоритмы LLM-генерацией без подписи в EVIDENCE.md.
- Не коммитить Patients/* — это AIM-уровневое правило.

## Тесты
backend: cargo test.
frontend: mix test.

## Деплой
TBD.
""".strip()

    if filename == "THEORY.md":
        return common_ctx + "\n\n" + """
Сгенерируй THEORY.md — формальная модель дифференциальной диагностики, как
она реализована в DiffDiagnosis. Состав:

## 1. Формализм диагностической задачи
D = argmax_{d ∈ Δ} P(d | E), где E — observed evidence, Δ — differential set.

## 2. Байесовское обновление
P(d|E) = P(E|d) · P(d) / P(E). Likelihood ratio chain. Pretest/posttest.

## 3. Threshold theory (Pauker–Kassirer 1980)
test threshold, treatment threshold; формулы; иллюстрация на одной нозологии.

## 4. Алгоритмическая редукция (Виноградов, Taylor)
Decision tree → набор узловых вопросов → отсечение ветвей. Формализация через
JSON-схему (см. DESIGN).

## 5. VINDICATE как ширина дифряда
Категориальный фильтр на старте; используется до байесовского ранжирования.

## 6. Dual-process в архитектуре
System 1: pattern matching по illness script (LLM-уровень / vector match).
System 2: explicit algorithm walk (Rust-движок).

## 7. Метрики качества
top-1 / top-3 / top-10 accuracy; calibration (ECE); miss-rate для can't-miss;
time-to-diagnosis.

## 8. Open formal questions
Где модель ломается (см. OPEN_PROBLEMS.md).

С формулами через `\(...\)` или `$$...$$`. Markdown.
""".strip()

    if filename == "DESIGN.md":
        return common_ctx + "\n\n" + """
Сгенерируй DESIGN.md — архитектурный план реализации. Состав:

## 1. Слои
1. data: sources/*.md → algorithms.json (schema in §3).
2. engine: Rust crate `diffdx-engine` — детерминированный walker по algorithms.json.
3. api: Rust binary `diffdx-api` (axum) — REST.
4. llm-glue: вызовы AIM/llm.py через subprocess или HTTP-обёртку.
5. ui: Phoenix LiveView.

## 2. Контракт REST API
POST /api/v1/case  → принимает свободный текст + структурированные поля.
POST /api/v1/diff  → принимает Case → возвращает Differential[].
GET  /api/v1/algorithm/{id}  → возвращает дерево алгоритма.
GET  /api/v1/sources  → список разделов канона.
WebSocket /ws/case/{id}  → стрим reasoning steps от LLM.

## 3. Схема algorithms.json (JSON Schema)
```json
{
  "id": "vinogradov.chest_pain.angina_vs_mi",
  "source": "vinogradov_01_chest_pain.md",
  "system": "vinogradov" | "taylor",
  "presenting_complaint": "...",
  "nodes": [
    {"id":"q1","question":"...","branches":[{"answer":"...","next":"q2"}]},
    {"id":"q2","question":"...","branches":[{"answer":"...","conclusion":"..."}]}
  ],
  "differentials": [{"name":"...","probability_class":"common|rare|red_flag",...}],
  "red_flags": ["..."]
}
```

## 4. Phoenix LiveView UI
Страницы: /case (форма ввода), /case/:id (live differential), /algorithms (browse),
/sources (документы), /reports/:id (PDF/HTML отчёт).

## 5. Поток данных
case-text → spaCy/regex extractor → Case struct → engine.walk() → Differential
→ LLM rerank (DeepSeek) → UI render.

## 6. Безопасность и приватность
Никаких пациентских данных в логах. Audit trail в SQLite.

## 7. Тестирование
Engine: gold-standard cases (10-20) из обеих книг. CI: cargo test + mix test.

Markdown с диаграммами в ASCII или mermaid.
""".strip()

    if filename == "EVIDENCE.md":
        return common_ctx + "\n\n" + """
Сгенерируй EVIDENCE.md — внешние источники, литература, связанные проекты.
Состав:

## 1. Канонические руководства
- Виноградов А. В. Дифференциальный диагноз внутренних болезней. 3-е изд. М.: Медицина.
- Robert B. Taylor (ed.). Difficult Diagnosis. 2nd ed. W. B. Saunders.
- Harrison's Principles of Internal Medicine (21st ed.).
- Cecil Textbook of Medicine.
- Kelley's Textbook of Internal Medicine.

## 2. Методология дифдиагностики (peer-reviewed)
Pauker SG, Kassirer JP. The threshold approach to clinical decision making. NEJM 1980.
Croskerry P. The importance of cognitive errors in diagnosis. Acad Med 2003.
Graber ML. The incidence of diagnostic error in medicine. BMJ Qual Saf 2013.
Newman-Toker DE. A unified conceptual model for diagnostic errors. Diagnosis 2014.
Singh H. The frequency of diagnostic errors in outpatient care. JAMA Intern Med 2014.
... (расширь до 15-20 ключевых работ).

## 3. Clinical decision rules
Wells score, PERC, HEART, CHA2DS2-VASc, Centor, Ottawa Ankle, NEXUS, qSOFA — со ссылками
на оригинальные публикации.

## 4. EBM-guidelines (top-level)
NICE, USPSTF, ESC, AHA, GINA, GOLD, KDIGO, EASL.

## 5. ML / CDSS
DXplain (Barnett 1987), Isabel (Ramnarayan 2003), Mediktor, Glass Health, AMIE
(Tu/Saab 2024), Med-PaLM 2 (Singhal 2023), Goh et al. NEJM AI 2024 (GPT-4 vs MD).

## 6. Связанные проекты в экосистеме
- AIM (~/Desktop/AIM/) — родительская система.
- BioSense — биомедицинский RAG.
- (другие, если применимо)

## 7. URLs
Список ключевых ссылок (без секретов).

## 8. Reviewers
См. ~/Desktop/Claude/REVIEWERS.md (внешний файл).

Все источники с DOI / PMID если возможно. Markdown.
""".strip()

    if filename == "PARAMETERS.md":
        return common_ctx + "\n\n" + """
Сгенерируй PARAMETERS.md — все численные/конфигурируемые значения проекта.

## 1. Engine
- LLM_RERANK_TOP_K = 10
- MIN_PROBABILITY_TO_REPORT = 0.02
- MAX_DIFFERENTIAL_OUTPUT = 20
- ENGINE_TIMEOUT_MS = 5000

## 2. API
- API_PORT = 8765
- API_RATE_LIMIT_RPM = 60
- API_MAX_REQUEST_KB = 256

## 3. LLM
- LLM_PROVIDER = deepseek (через AIM/llm.py)
- LLM_TEMPERATURE = 0
- LLM_MAX_TOKENS = 4096

## 4. Phoenix
- PHOENIX_PORT = 4000
- LIVEVIEW_HEARTBEAT_MS = 30000

## 5. Метрики качества (target)
- top-1 accuracy ≥ 0.55 на gold-standard cases
- top-3 accuracy ≥ 0.80
- can't-miss-miss-rate ≤ 0.02

## 6. Гранты / дедлайны / бюджет
TBD (если применимо к подпроекту).

## 7. Версии стека
- Rust ≥ 1.78
- Elixir ≥ 1.17, Phoenix ≥ 1.7
- Node ≥ 20 (assets)

Чистая таблица параметров. Markdown.
""".strip()

    if filename == "STATE.md":
        return common_ctx + "\n\n" + """
Сгенерируй STATE.md — волатильное состояние проекта на момент создания.

## Status
- Phase: 0 (kernel bootstrap)
- Created: 2026-04-29
- Owner: Dr. Jaba Tkemaladze (CEO GLA)

## Active TODOs
- [ ] sources/: проверить полноту извлечённых глав Виноградова и Taylor
- [ ] algorithms.json: первая итерация формализации (10-20 алгоритмов)
- [ ] backend: cargo init, axum scaffold, /health endpoint
- [ ] backend: engine.walk() prototype + 5 unit tests
- [ ] frontend: mix phx.new + базовая LiveView /case
- [ ] integration: backend ↔ AIM/llm.py через HTTP-обёртку
- [ ] gold-standard: 20 кейсов из обеих книг
- [ ] EVIDENCE.md: дополнить полным списком ссылок с DOI

## Decision Log
- 2026-04-29: проект создан, выбран стек Rust+Phoenix.
- 2026-04-29: 9-файловая core схема (см. ~/.claude/.../feedback_core_md_files.md).
- 2026-04-29: каноны = Vinogradov 3rd + Taylor "Difficult Diagnosis" 2nd.

## Что НЕ делать
- Не запускать LLM-генерацию алгоритмов в обход sources/*.md.
- Не дублировать функции agents/doctor.py — DiffDiagnosis отдельный движок.
- Не делать собственный git remote — это монорепо AIM.

## Milestones (✅)
- (пока пусто)

## Startup checklist
1. CONCEPT.md, STATE.md, OPEN_PROBLEMS.md прочитаны.
2. cargo check проходит.
3. mix compile проходит.
4. consistency check: 9 файлов на месте.

Markdown.
""".strip()

    if filename == "OPEN_PROBLEMS.md":
        return common_ctx + "\n\n" + """
Сгенерируй OPEN_PROBLEMS.md — лимитации, открытые вопросы, валидационные пробелы.

## 1. Полнота канона
- sources/ извлечены LLM-памятью, не сканом книг → возможны искажения.
- Нужна сверка с физическими экземплярами Vinogradov 3-е изд. и Taylor 2nd ed.

## 2. Формализация алгоритмов
- Не все алгоритмы Виноградова сводятся к decision tree без потери (некоторые —
  иллюстративные кейсы, не tree).
- Taylor — больше нарративный, чем алгоритмический; конверсия в JSON-схему
  ломает прозу.

## 3. Calibration LLM-rerank-уровня
- DeepSeek-reasoner возвращает ранжирование без откалиброванных вероятностей.
- Нужен calibration layer (Platt/isotonic) на gold-standard.

## 4. Can't-miss диагнозы
- Текущая архитектура не гарантирует ширину дифряда (VINDICATE-фильтр не
  внедрён в engine).

## 5. Pediatric / surgical / OB-GYN edges
- Не покрыто. Решение: DiffDiagnosis = только internal medicine, эти зоны —
  отдельные подпроекты или out-of-scope.

## 6. Multilingual UI
- AIM поддерживает 9 языков. DiffDiagnosis-UI — пока только RU+EN. Ka/Es/Fr/...
  отложены.

## 7. Validation set
- 20 кейсов мало. Нужно ≥ 200 для статистически осмысленной оценки.

## 8. Regulatory
- DiffDiagnosis — clinical decision support → потенциально EU MDR / FDA SaMD.
  На стадии R&D пока нерелевантно, но об этом надо помнить (см. PARAMETERS.md).

## 9. Patient safety
- LLM может давать confident-but-wrong rerank. Mitigation: всегда показывать
  узловой алгоритм Виноградова/Taylor, на котором основан вывод.

Markdown.
""".strip()

    return f"# {filename}\n\nTBD"


def stage_core() -> None:
    log("=== STAGE: core (CONCEPT + 8 файлов) ===")
    jobs = []
    for fname, _ in CORE_FILES:
        out = ROOT / fname
        jobs.append((out, core_prompt(fname), f"core/{fname}"))
    # последовательно (контекст уже общий, нет смысла толпиться)
    run_parallel(jobs, workers=3)
    log("=== STAGE core: DONE ===")


# ─────────────────────────── CODE STAGE ─────────────────────────────────────


def stage_code() -> None:
    log("=== STAGE: code (Rust + Phoenix скелеты) ===")

    rust_main_prompt = """
Сгенерируй полный, КОМПИЛИРУЮЩИЙСЯ Cargo.toml + main.rs для бинаря `diffdx-api`:

  Стек: axum 0.7, serde, serde_json, tokio (full), tower-http (cors+trace),
  tracing, tracing-subscriber, uuid.

  Endpoints:
    GET  /health              -> {"status":"ok"}
    POST /api/v1/case         -> создаёт Case, возвращает {"case_id":uuid}
    POST /api/v1/diff         -> body: Case, возвращает Vec<Differential>
    GET  /api/v1/algorithm/:id-> возвращает Algorithm tree из algorithms.json
    GET  /api/v1/sources      -> список разделов

  Структуры (serde):
    Case { id, free_text, structured: HashMap<String, Value>, created_at }
    Differential { name, probability, evidence_for: Vec<String>,
                   evidence_against: Vec<String>, source_algorithm: String }
    Algorithm { id, source, system, nodes, differentials, red_flags }

  Engine logic в этом файле — простейший stub: матчит keywords из free_text по
  presenting_complaint в algorithms.json и возвращает первые 5 differentials.
  Полноценный engine в crate `diffdx-engine` — это отдельный TODO.

ВЫХОД: ровно два markdown-блока:

```toml
# Cargo.toml
...
```

```rust
// src/main.rs
...
```

Без преамбул и комментариев вне блоков.
""".strip()

    rust_engine_prompt = """
Сгенерируй модуль engine в src/engine.rs для бинаря `diffdx-api`. Этот модуль:

1. Загружает algorithms.json (Path указан в env или CLI flag, default = "../algorithms.json").
2. Структуры Algorithm / Node / Branch / Differential — те же, что в main.rs
   (либо move в src/types.rs — на твоё усмотрение, главное чтобы компилировалось).
3. fn walk(case: &Case, algo: &Algorithm) -> Vec<Differential> — детерминированный
   обход дерева по structured полям case.structured.
4. fn rank(case: &Case, algos: &[Algorithm]) -> Vec<Differential> — прогоняет walk()
   по всем алгоритмам, агрегирует и сортирует по probability_class
   (red_flag > common > rare).
5. Простая эвристика probability:
     red_flag    -> 0.30
     common      -> 0.50  (если вошёл в дифряд алгоритма) с поправкой -0.05 за
                          каждое evidence_against
     rare        -> 0.10
   Затем нормализация суммы к 1.0.
6. Тесты: 3 unit тестов с inline JSON.

ВЫХОД:
```rust
// src/engine.rs
...
```

Без преамбул.
""".strip()

    rust_types_prompt = """
Сгенерируй src/types.rs — общие структуры (Case, Differential, Algorithm, Node, Branch,
ProbabilityClass) с serde derive. Один markdown блок:

```rust
// src/types.rs
...
```
""".strip()

    phoenix_router_prompt = """
Сгенерируй полные файлы для Phoenix LiveView frontend проекта `diffdx_web`:

ФАЙЛЫ (отдельные markdown-блоки с путями):

```elixir
# mix.exs
...
```

```elixir
# config/config.exs
...
```

```elixir
# config/dev.exs
...
```

```elixir
# lib/diffdx_web/application.ex
...
```

```elixir
# lib/diffdx_web/endpoint.ex
...
```

```elixir
# lib/diffdx_web/router.ex
- /                 LiveView CaseLive.New
- /case/:id         LiveView CaseLive.Show
- /algorithms       LiveView AlgorithmsLive
- /sources          LiveView SourcesLive
...
```

```elixir
# lib/diffdx_web/live/case_live/new.ex
LiveView с formой: textarea для anamnesis, набор чекбоксов VINDICATE, submit.
При submit — POST на http://localhost:8765/api/v1/diff (Req или :httpc),
получает Vec<Differential>, redirect на /case/:case_id.
...
```

```elixir
# lib/diffdx_web/live/case_live/show.ex
Показ дифряда: top-10, каждый с probability bar, evidence_for/against,
ссылка на source_algorithm.
...
```

Phoenix 1.7+, Elixir 1.17+. Используй current generators API. Без webpack — esbuild.

Без воды между блоками.
""".strip()

    jobs = [
        (ROOT / "backend" / "_main_rs.md",   rust_main_prompt,   "rust/main"),
        (ROOT / "backend" / "_engine_rs.md", rust_engine_prompt, "rust/engine"),
        (ROOT / "backend" / "_types_rs.md",  rust_types_prompt,  "rust/types"),
        (ROOT / "frontend" / "_phoenix.md",  phoenix_router_prompt, "phoenix/router"),
    ]
    run_parallel(jobs, workers=4)
    log("=== STAGE code: artifacts written; ручная распаковка через _extract_code.py ===")


# ─────────────────────────── MAIN ───────────────────────────────────────────


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    LOG.write_text(f"=== build started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n", encoding="utf-8")
    log(f"stage = {stage}")
    log(f"ROOT  = {ROOT}")

    if stage in ("sources", "all"):
        stage_sources()
    if stage in ("meta", "all"):
        stage_meta()
    if stage in ("core", "all"):
        stage_core()
    if stage in ("code", "all"):
        stage_code()

    log("=== ALL DONE ===")


if __name__ == "__main__":
    main()
