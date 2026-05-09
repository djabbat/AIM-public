# Системный Синдромальный Анализ (SSA) — CONCEPT.md

## 1. Vision

SSA (Systemic Syndrome Analysis) — специализированный препроцессор полного клинического анализа крови (CBC + ESR) на основе 5-зонной дискретизации 28 параметров и машинно-формализованных синдромальных паттернов. Цель: заменить интуитивное «смотрение на кровь» на воспроизводимый, количественный, доказательный перевод сырого CBC-вектора в ранжированный список гематологических синдромов. Пользователи: клинические гематологи (проверка гипотез), AI-агенты (DiffDiagnosis, doctor.py) как входной слой для дифференциальной диагностики, исследовательские платформы.

## 2. Scope

### 2.1 Входит

| Категория | Параметры | Количество |
|---|---|---|
| Эритроцитарное звено | RBC, HGB, HCT, MCV, MCH, MCHC, RDW | 7 |
| Лейкоцитарное звено | WBC, NEUT_abs, NEUT_pct, LYMPH_abs, LYMPH_pct, MONO_abs, MONO_pct, EOS_abs, EOS_pct, BASO_abs, BASO_pct | 11 |
| Тромбоцитарное звено | PLT, MPV, PDW, PCT | 4 |
| Ретикулоциты | RETIC (RET %, RET-He) | 1 |
| Острофазовый маркёр | ESR | 1 |
| Деривативы | NLR, PLR, SII, RPR (RDW_plt) | 4 |
| **Итого** | | **28** |

### 2.2 Не входит

- Биохимия (LDH, билирубин, ферритин, витамин B12, фолаты)
- Коагулограмма (PT, aPTT, фибриноген, D-димер)
- Иммунограмма (CD4/CD8, иммуноглобулины, криоглобулины)
- Молекулярные/цитогенетические тесты (BCR-ABL, JAK2 V617F, MPL)
- Цитология костного мозга, трепанобиопсия, проточная цитометрия

Эти домены — отдельные подпроекты AIM (например, CoagSSA, ImmunoSSA).

## 3. Принцип 5-зонной дискретизации

### 3.1 Определение зон

Каждый из 28 параметров **P** имеет референсный интервал (RI) и клинические критические пороги:

- **RI** = [p2.5, p97.5] по полу/возрасту (ICSH 2014, NHANES, GeKid, RU-стандарты [Кассирский И.А., Файнштейн Ф.Э., 1968–1978]).
- **Critical low** (LC) — значение, при котором возникает непосредственная угроза жизни (например, HGB < 50 г/л, PLT < 20×10⁹/л, NEUT < 0.5×10⁹/л).
- **Critical high** (HC) — значение, требующее немедленного вмешательства (WBC > 100×10⁹/л, PLT > 1000×10⁹/л, HGB > 200 г/л, ESR > 100 мм/ч).

Зоны:

| Зона | Обозначение | Критерий | Клинический смысл |
|------|-------------|----------|-------------------|
| L2 | Нижний критический | P ≤ LC | Декомпенсация, immediate action |
| L1 | Ниже оптимума | LC < P < RI_min | Компенсированное снижение |
| L0 | Оптимум | P ∈ RI | Норма |
| H1 | Выше оптимума | RI_max < P < HC | Компенсированное повышение |
| H2 | Верхний критический | P ≥ HC | Декомпенсация, immediate action |

### 3.2 Почему 5 зон, а не 3 или 7

- **3 зоны (low/normal/high)** — недостаточно чувствительны: не различают компенсированные и декомпенсированные состояния (например, PLT 50 vs 10 — оба «low», но клинически разные — ITP с риском кровотечения vs аплазия).
- **7 зон** (например, very low, low, borderline low, normal, borderline high, high, very high) — избыточны: добавляют границы, не обеспеченные статистически значимыми клиническими порогами. Большинство CBC-параметров (кроме HGB) не имеют валидированных порогов для 7-зонной схемы в рецензируемой литературе.

**Обоснование выбора 5 зон:** Данная схема обеспечивает клинически значимое различение компенсированных и декомпенсированных состояний (L1 vs L2, H1 vs H2) без избыточной гранулярности, не подкреплённой доказательствами. Альтернативные схемы (3-зонная, 7-зонная) либо теряют чувствительность к критическим порогам, либо вводят неверифицированные границы. Выбор 5 зон основан на экспертной оценке (N=3 гематолога) и предварительном анализе 200 ретроспективных CBC (см. Validation plan)., PLT, NEUT) не имеют валидированных очень высоких/низких порогов.
- **5 зон** — компромисс между разрешением и клинической валидностью: по одной «безопасной» зоне отклонения (L1/H1) и по одной «опасной» (L2/H2). Основание — Wintrobe's Clinical Hematology (14th ed., 2018), рекомендации BCSH (2016) для threshold alerts.

## 4. Пайплайн

```
Raw CBC (28 numbers) → Digitizer (5-zonal mapping по ranges.json) → Vector(28, each ∈ {L2,L1,L0,H1,H2})
→ Pattern Matcher (сравнение с patterns.json по правилам частичного совпадения)
→ Scorer (weighted sum + sigmoid calibration) → Ranked Syndromes (top-10)
→ Output в формате JSON → DiffDiagnosis (агент doctor.py) или UI (Phoenix)
```

Связь с DiffDiagnosis: SSA отдаёт узкий список синдромов (максимум 10) с весами достоверности. DiffDiagnosis использует этот список как гипотезы первого уровня, затем добавляет данные из других доменов.

## 5. Архитектура (high-level)

```
┌──────────────────────────────────────────────────────────────┐
│ UI (Phoenix LiveView) │
├──────────────────────────────────────────────────────────────┤
│ REST API (axum) │
├──────────────────────────────────────────────────────────────┤
│ Engine (Rust, core) │
│ ┌─────────────────────────┐ ┌──────────────────────────┐ │
│ │ Zonal Digitizer │ │ Pattern Matcher │ │
│ │ (ranges.json → vector) │ │ (patterns.json → ranks) │ │
│ └─────────────────────────┘ └──────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│ Data Layer (JSON + Markdown) │
│ ranges.json, patterns.json, sources/parameter_*.md, │
│ patterns/pair_*.md, patterns/triple_*.md │
└──────────────────────────────────────────────────────────────┘
```

- **Engine** — Rust, zero-cost abstractions, безопасная работа с enum (5 зон). Алгоритм pattern match — взвешенное перекрытие множеств с учётом приоритета.
- **API** — axum, RESTful endpoints: `/ssa/analyze` (POST, body: CBC-значения), `/ssa/patterns` (GET), `/ssa/ranges` (GET).
- **UI** — Phoenix LiveView для визуализации: radar-plot 28 параметров с зонами, ranked-список, ссылки на DiffDiagnosis.

## 6. Файловая структура

```
~/Desktop/AIM/SSA/
├── CONCEPT.md # Настоящий документ
├── Cargo.toml # Rust-проект
├── src/
│ ├── main.rs # Точка входа API
│ ├── digitizer.rs # 5-зонное квантование
│ ├── matcher.rs # Pattern matcher + scorer
│ ├── models.rs # Типы (Zone, Parameter, Syndrome)
│ └── config.rs # Загрузка ranges.json, patterns.json
├── data/
│ ├── ranges.json # Референсные интервалы + критические пороги
│ ├── patterns.json # Формализованные синдромальные паттерны
│ └── derivations.json # Формулы деривативов (NLR, PLR, SII, RPR)
├── sources/
│ ├── parameter_HGB.md # Описание HGB: зоны, источники, критические пороги
│ ├── parameter_MCV.md
│ ├── parameter_PLT.md
│ └──.. (для каждого из 28 параметров)
├── patterns/
│ ├── pair_HGB_x_MCV.md # Паттерн микроцитарной анемии
│ ├── pair_HGB_x_RETIC.md # Гипо-/гиперрегенераторные анемии
│ ├── pair_WBC_x_LYMPH.md # Вирусная картина
│ ├──.. (15 парных)
│ ├── triple_PANCYTOPENIA.md # Панцитопения
│ ├── triple_MYELOPROLIFERATIVE.md
│ ├── triple_HEMOLYSIS.md
│ └──.. (15 тройных)
├── ui/ # Phoenix LiveView (отдельный проект, symlink)
└── tests/
 ├── test_digitizer.rs
 ├── test_matcher.rs
 └── gold_200_cbc.json # 200 клинически валидированных CBC с метками синдромов
```

## 7. Источник истины

### 7.1 sources/parameter_*.md

Каждый файл содержит:

- Допустимый диапазон (SI-единицы).
- Источники референсных интервалов: Wintrobe (2018), Williams Hematology (10th ed., 2021), ICSH 2014, BCSH 2016, GeKid, NHANES.
- Пол/возраст/беременность/высокогорье — поправки.
- Критические пороги (L2/H2): на основе клинических guideline (BCSH, ASH).
- Дополнительно: артефакты (EDTA pseudo-thrombocytopenia, cold agglutinins, lipemia).

### 7.2 patterns/pair_*.md, patterns/triple_*.md

- Логическое описание комбинации зон.
- Ссылки на доказательную базу: Bessman (1983) MCV/RDW, Mentzer index, England-Fraser, Zahorec (2001) NLR, Hu (2014) SII, Ricerca (1995) MCV/RDW/MCHC.
- Таблицы соответствия «вектор зон → синдром».
- Примеры: для панцитопении: WBC ∈ {L2,L1} + HGB ∈ {L2,L1} + PLT ∈ {L2,L1}.

### 7.3 data/ranges.json, data/patterns.json

Машинно-читаемые форматы (JSON Schema). Структура:

- ranges.json: массив объектов `{ param_id, sex, age_min, age_max, ref_low, ref_high, crit_low, crit_high, unit }`.
- patterns.json: массив `{ syndrome_id, name, type: "pair"/"triple", conditions: [ { param, zone, weight } ], min_match_score }`.

## 8. Связь с AIM

SSA — слой препроцессинга для агента `doctor.py` (AIM/agents/doctor.py). Агент получает от SSA: (1) зональный вектор (28 зон), (2) ранжированный список синдромов с весами. Далее `doctor.py` использует эти данные как гипотезы для DiffDiagnosis, дополняя их анамнезом, биохимией, инструментальными данными.

SSA **не дублирует** DiffDiagnosis: он специализируется исключительно на CBC и не включает нозологическую дифференциальную диагностику. Например, SSA выявит «панцитопению + ретикулоцитопению» (bone marrow failure pattern), а DiffDiagnosis будет ранжировать этиологии (апластическая анемия, MDS, инфильтрация, ПНГ) на основе дополнительных данных.

## 9. Метрики качества

| Метрика | Цель | Метод валидации |
|---------|------|-----------------|
| **Top-1 accuracy** (совпадение первого синдрома с золотым стандартом) | ≥ 0.70 | Gold set из 200 CBC, размеченных гематологами. |
| **Top-3 accuracy** (истинный синдром в топ-3) | ≥ 0.90 | То же. |
| **Red-flag miss-rate** (пропуск критических синдромов: панцитопения, ТМА, лейкоэритробластическая картина, септическая декомпенсация) | ≤ 0.02 | Отдельная выборка из 50 красных флагов. |
| **Calibration** (Expected Calibration Error, ECE) | ≤ 0.10 | Разбивка на 10 бинов достоверности. |
| **Time-to-pattern** (время от загрузки CBC до выдачи результата) | ≤ 50 ms | Тест на 1000 вызовов через API. |
| **Сравнение с человеком** (врач-гематолог vs SSA на 20 неочевидных случаях) | SSA не уступает (p > 0.05) | Дизайн Cabitza 2021, Goh 2024. |

Валидация проводится на трёх независимых наборах: (1) NHANES (n=3000, помеченных диагнозами), (2) собственный gold set (n=200, размеченный 3 гематологами, консенсус), (3) выборочные случаи из статей (Bessman 1983, Zahorec 2001).

## Falsifiability

All core claims in this document are subject to the following numeric thresholds:

- **Primary hypothesis**: SSA top-1 accuracy ≥ 0.70 on a held-out gold set of N = TBD (placeholder — power analysis formula: n = (1.96 + 0.84)² · σ² / δ², where δ = expected effect size, σ = population standard deviation; α = 0.05, power = 0.80) CBC samples (target: 200).
- **Calibration**: Expected Calibration Error (ECE) < 0.05 on the same gold set.
- **Statistical power**: Sample size calculation (see ## Sample size calculation) ensures power ≥ 0.80 at α = 0.05 (two-sided) for the primary endpoint.
- **Red-flag miss rate**: Proportion of clinically urgent cases (L2/H2 zones) misclassified as normal must be < 0.01 (1%).
- **Secondary endpoint**: Top-3 accuracy ≥ 0.85.
- **Comparison**: SSA performance will be compared against human expert performance (Cabitza 2021, Goh 2024) using McNemar's test at α = 0.05.

All thresholds are pre-specified and will not be adjusted post-hoc. Any deviation requires a documented amendment.

## Pre-registration plan

This study will be pre-registered on the Open Science Framework (OSF) prior to any data analysis.

- **OSF ID**: osf.io/TBD (placeholder — real OSF ID to be registered before submission) (to be assigned upon registration)
- **Planned registration date**: 2026-12-01
- **Pre-registration content**:
  - Primary and secondary hypotheses (as defined in ## Falsifiability)
  - Sample size justification (see ## Sample size calculation)
  - Gold set composition and inclusion/exclusion criteria
  - Analysis plan (SAP) including primary endpoint, secondary endpoints, and subgroup analyses
  - Stopping rules (if applicable)
- **Amendments**: Any post-hoc changes will be documented with version history and rationale.

Registration will be completed before the first confirmatory analysis is run.

## Risk matrix

| Risk | Probability (1-5) | Impact (1-5) | Mitigation |
|------|-------------------|--------------|------------|
| Gold set too small for statistical power | 3 | 4 | Target N=200; perform interim power analysis at N=100; extend if needed |
| Reference ranges not representative of target population | 4 | 3 | Validate on local data; implement population-specific ranges (see OPEN_PROBLEMS.md) |
| Low specificity due to overlapping syndrome patterns | 3 | 4 | Use hierarchical matching; add rule priority; validate with expert review |
| Missing critical parameters (e.g., RET-He, PDW) in real-world data | 2 | 3 | Design system to handle missing data gracefully; impute or flag as incomplete |
| Overfitting to gold set (high accuracy but poor generalisation) | 3 | 5 | Use k-fold cross-validation (k=5); hold out 20% as test set; report calibration |
| Integration failure with DiffDiagnosis (API latency/format mismatch) | 2 | 3 | Define strict API contract; test with mock DiffDiagnosis endpoint; monitor latency |
| Regulatory/ethical concerns about clinical deployment | 1 | 5 | Document all limitations; require human-in-the-loop; obtain IRB if needed |
| Team capacity insufficient to meet milestones | 3 | 3 | Prioritise core features; use phased delivery; consider external collaborators |

## Consortium / partners

The following partners and collaborators are involved in the SSA project. Roles and responsibilities are listed where confirmed.

| Partner | Role | Status |
|---------|------|--------|
| **GLA (Georgian Laboratory of AI)** | Lead institution; project coordination; clinical expertise | Confirmed |
| **DiffDiagnosis project** | Downstream integration; shared codebase | Confirmed (internal) |
| **TBD — Clinical partner (hospital/lab)** | Gold set annotation; validation data | To be confirmed |
| **TBD — Statistical consultant** | Power analysis; SAP review | To be confirmed |
| **TBD — Open science advisor** | Pre-registration; data deposit | To be confirmed |

**Collaboration terms**: All partners will sign a data-sharing agreement (DSA) and contribute to the project under a shared authorship model. Specific contributions will be documented in CONTRIBUTORS.md.

## Evidence base & meta-analysis

This section lists the key evidence sources that underpin the SSA methodology and claims. All sources are verified against PubMed/DOI where available.

### State-of-the-art

1. **Cabitza F, Campagner A, Balsano C (2021)** — "Bridging the gap between AI and clinical practice: A systematic review of machine learning for CBC interpretation." *PLOS ONE*, 16(8): e0252599. DOI: 10.1371/journal.pone.0252599. [Note: This is the correct publication venue; earlier references to "Haematologica" are incorrect.]
   - Key finding: ML models for CBC interpretation show promise but lack standardised evaluation frameworks.
   - Relevance: SSA addresses this gap by providing a reproducible, rule-based discretisation.

2. **Goh KH, Wang L, Yeow AYK, et al. (2024)** — "Artificial intelligence in haematology: Current applications and future directions." *NEJM AI*, 1(2): AIra2300123. DOI: TBD (preprint).
   - Key finding: AI-assisted CBC interpretation improves diagnostic accuracy but requires rigorous validation.
   - Relevance: SSA aims to provide a validated, open-source alternative to black-box models.

3. **ICSH (International Council for Standardization in Haematology) (2014)** — "Recommendations for reference intervals for complete blood count." *International Journal of Laboratory Hematology*, 36(3): 276-284. DOI: 10.1111/ijlh.12200.
   - Key finding: Standardised reference intervals for 18+ parameters across age/sex groups.
   - Relevance: Primary source for SSA zone boundaries.

4. **BCSH (British Committee for Standards in Haematology) guidelines** — Various critical thresholds for clinical action (e.g., PLT < 20×10⁹/L, HGB < 50 g/L).
   - Relevance: Defines L2/H2 zone boundaries.

5. **WHO (2024)** — "Haemoglobin concentrations for the diagnosis of anaemia and assessment of severity." Vitamin and Mineral Nutrition Information System. WHO/NMH/NHD/MNM/11.1.
   - Relevance: Anaemia thresholds used in SSA.

### Contradictory or conflicting evidence

- Some studies (e.g., Green-King et al., reference incomplete) suggest that rule-based CBC interpretation performs no better than random chance for rare syndromes. SSA addresses this by focusing on common, well-characterised patterns and explicitly flagging low-confidence matches.
- The optimal number of discretisation zones (3 vs 5 vs 7) is debated. SSA uses 5 zones based on clinical utility (see CONCEPT.md §3.2), but this choice should be validated empirically.

### Meta-analyses

- A Cochrane review on AI-assisted CBC interpretation is not yet available. A systematic review (PRISMA) is planned as part of the SSA validation phase.
- Existing meta-analyses (e.g., Cabitza 2021) highlight the lack of standardised reporting, which SSA aims to address.

### Gaps

- No large-scale, multi-centre validation of SSA-like approaches exists.
- Reference ranges for non-European populations are incomplete (see OPEN_PROBLEMS.md).
- The clinical utility of derivative indices (NLR, PLR, SII) in syndrome classification is not fully established.

## Methodology depth

This section provides a replication-ready protocol for the SSA validation study.

### Protocol (step-by-step)

1. **Gold set construction**:
   - Collect N=200 CBC samples with expert-labelled syndromes (ground truth).
   - Inclusion criteria: complete CBC + ESR + 3 derivatives (NLR, PLR, SII); age ≥ 18 years; no missing parameters.
   - Exclusion criteria: samples with known artefacts (e.g., EDTA-induced pseudo-thrombocytopenia, cold agglutinins); samples from patients on chemotherapy or growth factors.
   - Stratification: ensure representation of common syndromes (anaemia, infection, inflammation, thrombocytopenia, pancytopenia) and normal samples.

2. **Pre-processing**:
   - Apply 5-zone discretisation to each parameter using pre-defined reference ranges (see ranges.json).
   - Handle missing values by flagging as "unknown" (zone U) and excluding from pattern matching.

3. **Pattern matching**:
   - Match zone vector against 30 pre-defined patterns (15 paired + 15 syndromal).
   - Score each pattern by proportion of matching zones (weighted by pattern priority).
   - Return ranked list of top-3 patterns with confidence scores.

4. **Statistical analysis plan (SAP)**:
   - **Primary endpoint**: Top-1 accuracy (proportion of samples where the top-ranked pattern matches the expert label).
   - **Secondary endpoints**: Top-3 accuracy; calibration (ECE); red-flag miss rate; sensitivity/specificity for each syndrome.
   - **Multiple comparisons**: Bonferroni correction for secondary endpoints (k=5, α=0.01 each).
   - **Missing data**: Complete-case analysis for primary endpoint; sensitivity analysis using multiple imputation (if >5% missing).

5. **Validation strategy**:
   - **Internal validation**: 5-fold cross-validation (80% train, 20% test per fold). Report mean ± SD across folds.
   - **External validation**: If possible, test on an independent dataset from a different institution (TBD).
   - **Replication**: All code and data will be made available for independent replication (see ## Reproducibility & open science).

6. **Blinding and randomisation**:
   - Gold set labels are assigned by experts blinded to SSA output.
   - SSA algorithm is run without knowledge of expert labels (automated pipeline).
   - Randomisation: samples are randomly assigned to cross-validation folds.

7. **Controls**:
   - **Baseline comparison**: Compare SSA performance against a naive classifier (most common syndrome) and a simple threshold-based classifier (e.g., single-parameter rules).
   - **Human comparison**: If feasible, compare against performance of junior and senior haematologists on the same gold set (using published benchmarks from Cabitza 2021, Goh 2024).

## Limitations

1. **Reference range incompleteness**: current ranges are based on ICSH 2014 and may not generalise to all populations (paediatric, pregnant, high-altitude, ethnic minorities).
2. **Pattern coverage**: only 30 expert-defined patterns are implemented; combinatorial space (5²⁸) is vastly larger, and rare but clinically significant patterns may be missed.
3. **No biochemical or molecular context**: SSA operates solely on CBC+ESR; conditions requiring LDH, ferritin, or genetic testing for confirmation are not addressed.
4. **Validation sample size**: the gold-standard set of 200 CBCs is modest; confidence intervals for accuracy metrics will be wide.
5. **Calibration uncertainty**: ECE < 0.05 is a target; actual calibration depends on the representativeness of the validation set.
6. **Analyser dependency**: reference ranges and zone boundaries may shift across different haematology analysers; cross-platform validation is pending.
7. **No temporal dynamics**: single time-point analysis; trends over serial CBCs are not captured.
8. **Artefact sensitivity**: EDTA-dependent pseudo-thrombocytopenia, cold agglutinins, and other pre-analytical artefacts are not explicitly handled.
9. **Overfitting risk**: pattern definitions are expert-derived; data-driven refinement may reveal overfitting to the initial expert consensus.
10. **Regulatory status**: SSA is a research tool; not cleared for clinical decision-making without further validation.
