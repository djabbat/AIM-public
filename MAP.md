# MAP.md — AIM v8.0 · Карта экосистемы LongevityCommon

**Версия:** 8.0.0
**Дата:** 2026-05-09
**Назначение:** Архитектурная карта. Зависимости между проектами экосистемы. Источник истины — `CONCEPT.md` + `registry.json`.

---

## 1. Структура AIM v8.0

```
AIM/
├── CONCEPT.md              ← канон: что такое AIM и зачем
├── registry.json           ← машиночитаемый реестр 15 проектов
├── registry.toml           ← человекочитаемый реестр (генерируется из JSON)
├── MAP.md                  ← этот файл: карта зависимостей
├── README.md               ← краткое описание для посторонних
├── CLAUDE.md               ← инструкция для Claude
├── TODO.md                 ← что делать дальше
├── CHANGELOG.md            ← история версий
├── .gitignore
│
├── validate/               ← кросс-проектная валидация
│   ├── counter_numbering.py   ← номера счётчиков C#1–C#5 согласованы
│   ├── ze_vstar.py            ← v* единообразен (Ze, BioSense, Poincaré)
│   ├── references.py          ← PMID/DOI без фабрикаций и дубликатов
│   └── concept_versions.py    ← версии CONCEPT.md не конфликтуют
│
├── dashboard/              ← статус-дашборд экосистемы
│   ├── status.py              ← генератор сводки
│   └── index.html             ← HTML-дашборд
│
├── graph/                  ← граф проектов
│   ├── ecosystem.dot          ← Graphviz DOT
│   └── ecosystem.mermaid      ← Mermaid (для GitHub)
│
└── _archive/               ← AIM v7.0 (AI-код, удалён 2026-05-09)
    └── v7_ai_code/            ← llm.py, agents/, Patients/, etc.
```

---

## 2. Граф зависимостей

```
                         AIM (СЕРДЦЕ)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐          ┌──────────┐          ┌──────────┐
   │  MCOA    │          │Ze Theory │          │   HAP    │
   │ (meta)   │          │(math)    │          │(независ.)│
   └────┬─────┘          └────┬─────┘          └──────────┘
        │                     │
   ┌────┼────┬────┬────┐      ├──────────┐
   ▼    ▼    ▼    ▼    ▼      ▼          ▼
CDATA Telom Mito Epi  Prot  BioSense  Poincaré
(C#1) (C#2) (C#3)(C#4)(C#5)   │
   │                           │
   ▼                           ▼
CellLineageTree               FCLC
   │
   ▼
AutomatedMicroscopy


IQALTO ───► Korkoti
(внешний)    (подпроект)
```

---

## 3. Слои экосистемы

| Слой | Проекты | Описание |
|------|---------|----------|
| **Theoretical** | MCOA | Мета-теория счётчиков |
| **Molecular-cellular** | CDATA, Telomere, MitoROS, EpigeneticDrift, Proteostasis, CellLineageTree | 5 счётчиков + экспериментальная платформа C#1 |
| **Mathematical** | Ze Theory, Poincaré | Математический фундамент χ_Ze |
| **Applied** | BioSense | Носимые биосенсоры |
| **Infrastructure** | AutomatedMicroscopy, FCLC | Лабораторная автоматизация + приватность |
| **Theory (indep.)** | HAP | Гепатогенная теория эмоций |
| **External** | Iqalto, Korkoti | Образование + пищевые технологии |

---

## 4. Ключевые кросс-проектные параметры

| Параметр | Значение | Где определён | Где используется |
|----------|---------|---------------|-------------------|
| v* (Python form) | 0.45631 | `Ze/PARAMETERS.md` §1 | Ze, BioSense, Poincaré |
| v* (Article form) | −0.08738 | `Ze/PARAMETERS.md` §1 | Статьи (канонический cross-subproject) |
| χ_Ze формула | 1 − |v−v*|/max(v*, 1−v*) | Ze Theory | BioSense |
| α (primary endpoint) | 0.05 | MCOA, все счётчики | Все эксперименты |
| M4 falsification | partial r² < 0.05 при N≥2000, α=0.001 | MCOA CONCEPT.md | Вся экосистема |
| Номера счётчиков | C#1=CDATA, C#2=Telomere, C#3=MitoROS, C#4=EpiDrift, C#5=Proteostasis | MCOA + CDATA | Все counter-modules |

---

## 5. Статусы проектов (кратко)

| Проект | Статус | Критично? |
|--------|--------|-----------|
| MCOA | Submitted, не peer-reviewed | Да — флагман |
| CDATA | Inconclusive (ABL-2 p=0.12) | Да — требует Cell-DT v4.0 |
| Telomere, MitoROS, EpiDrift, Proteostasis | Concept stage | Нет — ждут funding |
| Ze Theory | Активная, не peer-reviewed | Да — нужна статья |
| BioSense | ЭЭГ валидирован, остальное в проекте | Средне |
| FCLC | v13.4 PASS, но semi-honest | Да — GDPR blocker |
| CellLineageTree | Concept, 48h pilot | Средне — нужен PI и funding |
| HAP | STRONG v4.0, принята к публикации | Нет — независимая |
| Iqalto / Korkoti | Концепция | Нет — внешние |

---

## 6. Иерархия authority

1. `LongevityCommon/CONCEPT.md` — верховный авторитет
2. `AIM/registry.json` — канонический реестр (производный от CONCEPT.md)
3. `<subproject>/CONCEPT.md` — авторитет внутри подпроекта
4. `AIM/CONCEPT.md` — операционный документ (как работает AIM)

При конфликте: верхний уровень всегда прав. AIM — интегратор, не диктатор.
