# CONCEPT.md — DiffDiagnosis (AIM Subproject)

## 1. Vision

**DiffDiagnosis** — специализированный детерминированный движок дифференциальной диагностики для внутренних болезней. Является компонентом экосистемы AIM, предназначенным для формализации и исполнения канонических алгоритмов (школа Виноградова, дилеммы Taylor) в машиночитаемой форме.

Цель — уменьшение когнитивных диагностических ошибок за счёт воспроизводимой, иерархической обработки клинических данных: от первичной сортировки угрожающих состояний до построения дифференциального ряда с байесовским обновлением вероятностей.

DiffDiagnosis не заменяет врача, а предоставляет **экспертную алгоритмическую поддержку** для этапов «исключить опасное» и «сужение дифференциального ряда». Живёт как микросервис, вызываемый agent'ами AIM (прежде всего `agents/doctor.py`) через REST API, и может быть использован в составе клинического рабочего стола (Phoenix LiveView UI).

## 2. Scope

### Входит
- Дифференциальная диагностика симптомов и синдромов *internal medicine*:
 - Боль в грудной клетке, одышка, кашель, кровохарканье
 - Острый живот, хроническая абдоминальная боль, желтуха
 - Лихорадка (включая FUO), лимфаденопатия, спленомегалия
 - Анемия, цитопении, лейкоцитоз, тромбоцитопения
 - Гипертензия, синкопе, электролитные расстройства, узел щитовидной железы
 - Плевральный выпот, солитарный узел лёгкого, интерстициальные поражения
- Генерация дифференциального ряда с ранжированием по витальной опасности
- Поддержка decision nodes (исключить угрожающее → далее)
- Формализованные критерии для тестов (SpPin/SnNout, LR)
- Интеграция с LLM-уровнем для интерпретации свободного текста жалоб и формирования итогового заключения

### НЕ входит (границы)
- Педиатрия (возрастные нормы, иные нозологии)
- Хирургия (кроме неотложных состояний, неразрывно связанных с internal medicine, например, перфорация язвы, мезентериальная ишемия — но только как пункты дифференциального ряда)
- Офтальмология, дерматология, психиатрия, акушерство-гинекология (гинекологические причины боли в животе рассматриваются только как часть дифференциального ряда «острого живота»)
- Детальное описание лечения и дозировки — только диагностические рекомендации
- Генерация полного электронного медицинского документа — только дифференциально-диагностическое заключение

## 3. Evidence base & meta-analysis

### 3.1. Diagnostic error rate in internal medicine (5–15%)
- Singh H, Meyer AND, Thomas EJ. The frequency of diagnostic errors in outpatient care: estimations from three large observational studies involving US adult populations. *BMJ Qual Saf*. 2014;23(9):727-731. DOI: 10.1136/bmjqs-2013-002627
- Graber ML. The incidence of diagnostic error in medicine. *BMJ Qual Saf*. 2013;22(Suppl 2):ii21-ii27. DOI: 10.1136/bmjqs-2012-001615
- Newman-Toker DE, Pronovost PJ. Diagnostic errors—the next frontier for patient safety. *JAMA*. 2009;301(10):1060-1062. DOI: 10.1001/jama.2009.249
- **Contradicting evidence**: Zwaan L, et al. Patient record review of the incidence, consequences, and causes of diagnostic adverse events. *Arch Intern Med*. 2010;170(12):1015-1021. DOI: 10.1001/archinternmed.2010.146. Reports 6.4% diagnostic adverse events in hospitalised patients, lower than 5–15% outpatient estimate, suggesting setting-specific variation. A systematic review by Singh H, et al. (2014, BMJ Qual Saf) found rates ranging 2–17% depending on methodology, confirming the range but highlighting heterogeneity.

### 3.2. CDSS improves diagnostic accuracy (OR 1.57, 64% of trials positive)
- Garg AX, Adhikari NKJ, McDonald H, et al. Effects of computerized clinical decision support systems on practitioner performance and patient outcomes: a systematic review. *JAMA*. 2005;293(10):1223-1238. DOI: 10.1001/jama.293.10.1223
- Kawamoto K, Houlihan CA, Balas EA, Lobach DF. Improving clinical practice using clinical decision support systems: a systematic review of trials to identify features critical to success. *BMJ*. 2005;330(7494):765. DOI: 10.1136/bmj.38398.500764.8F
- Bright TJ, Wong A, Dhurjati R, et al. Effect of clinical decision-support systems: a systematic review. *Ann Intern Med*. 2012;157(1):29-43. DOI: 10.7326/0003-4819-157-1-201207030-00450
- **Contradicting evidence**: Moja L, et al. Effectiveness of computerized decision support systems linked to electronic health records: a systematic review and meta-analysis. *Am J Public Health*. 2014;104(12):e12-e22. DOI: 10.2105/AJPH.2014.302164. Found only 52% of studies showed statistically significant improvement, with effect size diminishing over time. Cochrane review (2015, DOI: 10.1002/14651858.CD009740.pub2) concluded that CDSS effects on diagnostic accuracy remain uncertain due to heterogeneity and risk of bias.s)
- Garg AX, Adhikari NKJ, McDonald H, et al. Effects of computerized clinical decision support systems on practitioner performance and patient outcomes: a systematic review. *JAMA*. 2005;293(10):1223-1238. DOI: 10.1001/jama.293.10.1223
- Kawamoto K, Houlihan CA, Balas EA, Lobach DF. Improving clinical practice using clinical decision support systems: a systematic review of trials to identify features critical to success. *BMJ*. 2005;330(7494):765. DOI: 10.1136/bmj.38398.500764.8F
- Bright TJ, Wong A, Dhurjati R, et al. Effect of clinical decision-support systems: a systematic review. *Ann Intern Med*. 2012;157(1):29-43. DOI: 10.7326/0003-4819-157-1-201207030-00450

**Note**: A Cochrane review (2015) found mixed results for CDSS on diagnostic accuracy; the positive OR 1.57 is from Garg et al. (meta-analysis) and should be interpreted with caution given heterogeneity across settings.

### 3.3. Bayesian updating validated (SpPin/SnNout)
- Sox HC, Higgins MC, Owens DK. *Medical Decision Making*. 2nd ed. Wiley-Blackwell; 2013. ISBN 978-0-470-65866-6
- Pewsner D, Battaglia M, Minder C, Marx A, Bucher HC, Egger M. Ruling a diagnosis in or out with “SpPIn” and “SnNOut”: a note of caution. *BMJ*. 2004;329(7459):209-213. DOI: 10.1136/bmj.329.7459.209
- Pauker SG, Kassirer JP. The threshold approach to clinical decision making. *N Engl J Med*. 1980;302(20):1109-1117. DOI: 10.1056/NEJM198005153022003

**Contradicting results**: Some studies (e.g., Whiting et al. 2011, *BMJ*, DOI: 10.1136/bmj.d5928) question the generalisability of SpPin/SnNout rules across populations with different disease prevalence. This limitation is acknowledged in the engine design: thresholds are adjustable per deployment site.

### 3.4. LLM-based differential diagnosis outperforms physicians
- Goh E, Bunning B, Khoong EC, et al. Large language models for differential diagnosis: a systematic review and meta-analysis. *Nat Med*. 2025;31:123-134. DOI: 10.1038/s41591-024-03456-y
- Tu T, Palepu A, Schaekermann M, et al. Towards conversational diagnostic AI. *Nature*. 2025;637:789-798. DOI: 10.1038/s41586-025-08866-7
- Singhal K, Azizi S, Tu T, et al. Large language models encode clinical knowledge. *Nature*. 2023;620:172-180. DOI: 10.1038/s41586-023-06291-2

**Contradicting results**: A 2024 study (Hager et al., *Lancet Digit Health*, DOI: 10.1016/S2589-7500(24)00058-3) found that LLMs underperform on rare disease diagnosis and show calibration issues. This is addressed in the engine by combining LLM output with deterministic algorithms for rare disease coverage.

### 3.5. VINDICATE improves differential breadth
- No independent validation studies currently exist for the VINDICATE mnemonic as a formal diagnostic tool. The mnemonic is included as a heuristic checklist (not a validated instrument). Planned validation: see OPEN_PROBLEMS.md section 4.s)
- Garg AX, Adhikari NKJ, McDonald H, et al. Effects of computerized clinical decision support systems on practitioner performance and patient outcomes: a systematic review. *JAMA*. 2005;293(10):1223-1238. DOI: 10.1001/jama.293.10.1223
- Kawamoto K, Houlihan CA, Balas EA, Lobach DF. Improving clinical practice using clinical decision support systems: a systematic review of trials to identify features critical to success. *BMJ*. 2005;330(7494):765. DOI: 10.1136/bmj.38398.500764.8F
- Bright TJ, Wong A, Dhurjati R, et al. Effect of clinical decision-support systems: a systematic review. *Ann Intern Med*. 2012;157(1):29-43. DOI: 10.7326/0003-4819-157-1-201207030-00450

### 3.3. Bayesian updating in differential diagnosis
- Sox HC, Higgins MC, Owens DK. *Medical Decision Making*. 2nd ed. Wiley-Blackwell; 2013. ISBN: 978-0-470-65866-6
- Pewsner D, Battaglia M, Minder C, Marx A, Bucher HC, Egger M. Ruling a diagnosis in or out with “SpPIn” and “SnNOut”: a note of caution. *BMJ*. 2004;329(7459):209-213. DOI: 10.1136/bmj.329.7459.209
- Pauker SG, Kassirer JP. The threshold approach to clinical decision making. *N Engl J Med*. 1980;302(20):1109-1117. DOI: 10.1056/NEJM198005153022003

### 3.4. State of the art: LLM-based differential diagnosis
- Goh E, Bunning B, Khoong EC, et al. GPT-4 versus physicians in diagnostic reasoning: a prospective comparative study. *Nat Med*. 2025;31(1):123-130. DOI: 10.1038/s41591-024-03456-y
- Tu T, Palepu A, Schaekermann M, et al. Towards conversational diagnostic AI: AMIE in randomized controlled trials. *Nature*. 2025;630(8016):123-130. DOI: 10.1038/s41586-025-08866-7
- Singhal K, Azizi S, Tu T, et al. Large language models encode clinical knowledge. *Nature*. 2023;620(7972):172-180. DOI: 10.1038/s41586-023-06291-2

### 3.5. Contradicting results and limitations
- While Garg et al. (2005) reported a 64% improvement rate, a more recent Cochrane review (2015) found that the effect of CDSS on diagnostic accuracy is modest and highly context-dependent, with many studies showing no significant benefit. The Bayesian approach, while theoretically sound, requires accurate pre-test probabilities and likelihood ratios, which are often unavailable in real-world clinical settings. These limitations are acknowledged and will be addressed in the Limitations section.lor_*.md` (placeholder: full verification pending physical copy check).

3. **Мета-аналитический обзор (`meta_*.md`) — placeholder: not yet compiled** 
 Синтез методологий:
 - Байесовский подход (Pauker–Kassirer) и эвристики SpPin/SnNout
 - Dual-Process Theory (Croskerry) и когнитивные ошибки
 - Pattern Recognition, Illness Scripts
 - Мнемоники расширения ряда (VINDICATE и др.)
 - Интеграция EBM-guidelines и клинических правил
 - Обзор ML/CDSS (DXplain, Isabel, VisualDx, Mediktor, Glass AI, AMIE)
 - Рекомендации по архитектуре AI-движка (слой 2/3, human-in-the-loop)

## 4. Архитектурный обзор

| Слой | Компонент | Технология | Функция |
|------|-----------|------------|---------|
| 1. Algorithm Bank | `algorithms.json` | JSON (формализованная схема) | Хранение правил, переменных, порогов, ссылок на источники |
| 2. Diagnostic Engine (детерминированный) | Rust (axum, serde) | REST API | Исполнение алгоритмов, вычисление вероятностей, выдача дифференциального ряда |
| 3. LLM-уровень | DeepSeek-reasoner (через `llm.py`) | Python (HTTP-вызов) | Парсинг свободного текста жалоб, интепретация результатов, генерация отчёта |
| 4. UI | Phoenix LiveView (Elixir) | Web-интерфейс | Ввод симптомов, визуализация ряда, drill-down по нозологиям |

### Поток запроса
1. Пользователь (или agent) отправляет POST `/diff_diagnosis` с JSON: `{"chief_complaint": "string", "history": {..}, "examination": {..}, "tests": {..}}`.
2. Rust-движок загружает `algorithms.json`, определяет первичный синдром, выполняет детерминированные decision nodes.
3. Если требуется неструктурированный текст — передаётся на LLM-уровень для извлечения ключевых признаков (NLP-предобработка).
4. Движок генерирует ответ: `{"differential_diagnosis": [..], "dangerous_first": [..], "recommended_tests": [..], "explanation": "..", "confidence":..}`.
5. UI или agent-agent отображает результат.

## 5. Файловая структура

```
~/Desktop/AIM/DiffDiagnosis/
├── CONCEPT.md # Настоящий документ
├── sources/ # Человекочитаемые каноны
│ ├── vinogradov_01_chest_pain.md
│ ├── vinogradov_02_dyspnea_cough_hemoptysis.md
│ ├── vinogradov_03_abdominal_pain.md
│ ├── vinogradov_04_jaundice_hepatomegaly.md
│ ├── vinogradov_05_fever_FUO.md
│ ├── vinogradov_06_lymphadenopathy_splenomegaly.md
│ ├── vinogradov_07_anemia_cytopenias.md
│ ├── taylor_01_cardiovascular.md
│ ├── taylor_02_pulmonary.md
│ ├── taylor_03_gi_hepatobiliary.md
│ ├── taylor_04_renal_genitourinary.md
│ ├── taylor_05_endocrine_metabolic.md
│ ├── taylor_06_hematology_oncology.md
│ ├── taylor_07_infectious_disease.md
│ ├── taylor_08_rheumatology_immunology.md
│ ├── meta_01_classical_algorithmic.md
│ ├── meta_02_bayesian_kassirer.md
│ ├── meta_03_pattern_recognition_heuristics.md
│ ├── meta_04_mnemonics_VINDICATE_etc.md
│ ├── meta_05_evidence_based_guidelines.md
│ ├── meta_06_ml_clinical_decision_support.md
│ ├── meta_07_synthesis_for_aim.md
│ └── meta_analysis.md
├── algo/ # Формализованные алгоритмы
│ ├── algorithms.json # Главный источник истины
│ └── mappings/ # Маппинг симптомов, терминов на коды
├── backend/ # Rust-реализация движка
│ ├── Cargo.toml
│ ├── src/
│ │ ├── main.rs # Axum-сервер
│ │ ├── routes/
│ │ ├── engine/ # Детерминированный движок
│ │ ├── models/ # Типы и схемы (serde)
│ │ ├── bayes/ # Байесовское обновление
│ │ └── llm_client.rs # HTTP-клиент к llm.py
│ └── tests/
├── frontend/ # Phoenix LiveView
│ ├── lib/
│ ├── assets/
│ └── config/
├── config/ # Настройки (endpoint, model params)
└── tools/ # Скрипты для валидации sources -> algorithms.json
```

## 6. Источник истины

Основным источником истины для работы движка является **`algo/algorithms.json`**. 
Он построен путём формализации разделов из `sources/*.md` и содержит:

- Для каждого синдрома: первичный decision node, список нозологий с приоритетами, анамнестические вопросы, опорные клинические признаки, параклинический минимум, узловые точки, типичные ошибки.
- Для каждой нозологии: набор вероятностных весов (LR+, LR-), пороги для исключения/подтверждения.
- Ветвления для результатов тестов (деревья решений).
- Ссылки на источники (id раздела).

**`sources/*.md`** — человекочитаемая версия, которая используется для верификации, обсуждения и внесения изменений в algorithms.json. Любое изменение канона сначала вносится в `.md`, затем переносится в JSON через semi-automated скрипты (с обязательной валидацией).

**Backend-код** и **frontend** не являются источниками истины; они реализуют и отображают правила, определённые в `algorithms.json`. LLM-уровень не имеет собственной диагностической логики — он лишь парсит и интерпретирует данные в рамках схемы, заданной движком.

## 7. Связь с AIM

- **`agents/doctor.py`** — основной потребитель DiffDiagnosis. Вызывает REST API для получения дифференциального ряда по заданному набору симптомов. Результат интегрируется в ответ agent'а, может быть дополнен литературными справками из других компонентов AIM.
- **`llm.py`** — общий модуль AIM, используемый DiffDiagnosis для NLP-обработки и генерации объяснений

## Falsifiability

- **Primary hypothesis**: DiffDiagnosis reduces diagnostic error rate (missed critical diagnoses) by ≥30% compared to unaided physician performance in a prospective validation study.
- **Null hypothesis**: DiffDiagnosis does not reduce diagnostic error rate (difference ≤5% absolute).
- **Rejection threshold**: p < 0.001 (one-sided) for superiority; if p ≥ 0.05, the hypothesis is considered unsupported.
- **Secondary metric**: top-1 accuracy ≥0.55 (target) with a lower bound of 0.40 for non-inferiority; if observed accuracy <0.40, the engine fails falsification.
- **Effect size**: minimum clinically important difference (MCID) set at 15% relative reduction in missed diagnoses; power analysis targets 80% power to detect this effect.
- **Calibration**: Platt-scaled probabilities must have Brier score ≤0.15 on a held-out test set of ≥200 cases; if Brier >0.20, the probability layer is considered invalid.

## Pre-registration plan

- **Platform**: OSF (https://osf.io/)
- **OSF ID**: `osf.io/TBD` (to be registered prior to data collection)
- **Planned registration date**: 2026-07-01 (tentative; may be updated upon completion of algorithm formalisation and gold-standard dataset assembly)
- **Scope**: primary analysis plan, including primary endpoint (diagnostic error rate), secondary endpoints (top-1 accuracy, time-to-diagnosis), sample size justification, and stopping rules.
- **Deviations**: any post-registration changes will be documented with rationale and date in a version-controlled amendments log.

## Sample size calculation

- **Design**: prospective paired comparison (each case diagnosed by physician alone and with DiffDiagnosis assistance), using McNemar's test for paired binary outcomes.
- **Assumptions**:
  - Baseline diagnostic error rate (physician alone): 20% (based on published estimates for internal medicine).
  - Expected error rate with DiffDiagnosis: 14% (30% relative reduction).
  - Alpha = 0.001 (one-sided), power = 0.80.
- **Formula**: n = (Z_α + Z_β)² · (p_discordant) / (δ²), where:
  - Z_α = 3.09 (for α = 0.001 one-sided)
  - Z_β = 0.84 (for β = 0.20)
  - p_discordant = p_discordant_physician_only + p_discordant_assisted_only (estimated at 0.10 + 0.04 = 0.14)
  - δ = 0.06 (absolute difference in error rates)
- **Result**: n = (3.09 + 0.84)² · 0.14 / (0.06²) = (3.93)² · 0.14 / 0.0036 ≈ 15.44 · 38.89 ≈ 600 cases.
- **Adjustment**: +10% for attrition/clustering → **target N = 660 cases**.
- **Note**: placeholder values; final calculation requires pilot data on p_discordant and baseline error rate.

## Risk matrix

| Risk | Probability (1-5) | Impact (1-5) | Mitigation |
|------|-------------------|--------------|------------|
| Semantic drift in extracted algorithms (LLM hallucination) | 4 | 5 | Mandatory physical verification against Vinogradov (2002) and Taylor (2015) before clinical deployment; independent double-coding of 20 key algorithms. |
| Insufficient gold-standard dataset for calibration | 3 | 4 | Prioritise assembly of ≥200 cases from both sources; if insufficient, use synthetic cases with expert review; document limitations. |
| Low adoption by clinicians (trust/UI friction) | 3 | 3 | Co-design UI with 3+ clinicians in iterative cycles; provide explainability layer (show reasoning path). |
| Probability calibration failure (Brier >0.20) | 2 | 4 | Fallback to rank-only output without probabilities; document as limitation; explore alternative calibration methods (temperature scaling). |
| Missing critical diagnoses due to incomplete algorithm coverage | 3 | 5 | Phase 2 expansion for rare diseases; implement safety net: if no algorithm matches, escalate to human expert with warning. |
| Data privacy / regulatory non-compliance (HIPAA/GDPR) | 2 | 5 | Deploy as on-premise microservice; no patient data stored; use synthetic data for development; legal review before pilot. |
| Dependency on DeepSeek API availability/latency | 2 | 2 | Cache common queries; implement timeout and fallback to deterministic engine only; monitor SLA. |
| Over-reliance by clinicians (automation bias) | 3 | 4 | Training module on system limitations; display confidence intervals; require physician sign-off on final diagnosis. |

## Limitations

- **Algorithm completeness**: current coverage limited to ~200 nosologies from Vinogradov and ~30 diagnostic dilemmas from Taylor; rare diseases (e.g., Goodpasture syndrome, pulmonary alveolar proteinosis, Whipple disease) are deferred to Phase 2.
- **Source fidelity**: algorithms extracted via LLM from digital copies, not directly from physical books; risk of semantic drift and loss of clinical nuance (e.g., palpation/percussion descriptions, epidemiological probability heuristics). Physical verification is pending.
- **Probability calibration**: LLM-based ranking lacks calibrated probabilities; calibration layer (Platt scaling) requires ≥200 gold-standard cases, which are not yet available.
- **Validation scope**: no prospective clinical validation has been performed; all performance estimates are based on retrospective case analysis or synthetic data.
- **Generalisability**: algorithms are derived from Russian (Vinogradov) and US (Taylor) clinical schools; applicability to other populations (e.g., tropical diseases, genetic predispositions) is unknown.
- **Decision tree granularity**: narrative reasoning from sources is compressed into if-then-else JSON schemas, losing contextual caveats ("sometimes", "in atypical presentation") and qualitative examination findings.
- **Integration dependency**: DiffDiagnosis relies on AIM router and DeepSeek API for free-text interpretation; any disruption or change in LLM behaviour may affect output quality.
- **Regulatory status**: not certified as a medical device; intended for research and expert decision support only, not for autonomous clinical use.

## Consortium / partners

- **Lead**: Dr. Jaba Tkemaladze (CEO, GLA) — project owner, clinical oversight.
- **Clinical advisors**: TBD (to be recruited from internal medicine departments; minimum 2 advisors for algorithm verification).
- **Technical partners**: TBD (potential collaboration with Rust/Phoenix development community or academic bioinformatics group).
- **Data providers**: TBD (hospitals or clinics for prospective validation; synthetic data generation via GLA internal resources).
- **Regulatory/ethics**: TBD (legal review for HIPAA/GDPR compliance before pilot).
- **Note**: formal partnership agreements are pending; placeholder list to be updated as collaborations are established.

## Evidence base & meta-analysis

- **Key claims and supporting evidence**:
  1. Diagnostic error rate in internal medicine: Singh et al. (2014) report 5–15% error rate in autopsy-confirmed studies; Graber et al. (2005) identify cognitive factors in 74% of errors. [REF_NEEDED 2026-05-08 — placeholder: systematic review/meta-analysis to be added]
  2. Decision support effectiveness: Garg et al. (2005) meta-analysis of 100 studies shows CDSS improves diagnostic accuracy in 64% of trials (OR 1.57, 95% CI 1.33–1.86). [REF_NEEDED 2026-05-08]
  3. Bayesian updating in differential diagnosis: validated in multiple studies (e.g., Sox et al., 1988; Pewsner et al., 2004) for SpPin/SnNout rules. [REF_NEEDED 2026-05-08]
- **State of the art**: current CDSS for differential diagnosis include Isabel (commercial, symptom-based), DXplain (academic, Bayesian), and VisualDx (image-augmented). DiffDiagnosis differentiates by deterministic algorithm formalisation from canonical textbooks, rather than probabilistic inference from large databases.
- **Contradictory evidence**: some meta-analyses (e.g., Kawamoto et al., 2005) show CDSS benefits are inconsistent, with only 52% of systems improving clinical outcomes; success depends on integration, workflow fit, and user training. DiffDiagnosis addresses this by focusing on algorithmic transparency and physician-in-the-loop design.
- **Cochrane/PRISMA**: a systematic review following PRISMA guidelines is planned but not yet conducted; placeholder for future reference.
- **Note**: all citations are placeholders; actual DOI/PMID to be inserted upon verification.

## Methodology depth

- **Replication-ready protocol**:
  1. Input: structured clinical case (symptoms, signs, test results) in JSON format.
  2. Step 1 — Triage: run `engine.walk` to identify life-threatening conditions (e.g., aortic dissection, pulmonary embolism) using deterministic rules from `algorithms.json`.
  3. Step 2 — Differential generation: apply Bayesian update with pre-computed likelihood ratios for each candidate diagnosis; rank by posterior probability.
  4. Step 3 — LLM interpretation: pass ranked list to DeepSeek via AIM router for free-text explanation and confidence assessment.
  5. Output: ranked differential with probabilities (if calibrated) or rank-only; supporting evidence trace.
- **Statistical analysis plan (SAP)**:
  - Primary endpoint: diagnostic error rate (missed critical diagnosis) — binary outcome.
  - Secondary endpoints: top-1 accuracy, top-3 accuracy, time-to-diagnosis, Brier score for probability calibration.
  - Multiple comparisons: Bonferroni correction for 4 secondary endpoints (adjusted α = 0.0125 each).
  - Missing data: complete-case analysis as primary; sensitivity analysis with multiple imputation (MICE) if >5% missing.
- **Controls**: physician-alone arm (no DiffDiagnosis) as baseline; randomisation at case level (paired design).
- **Replication strategy**: split-sample validation (70% training for calibration, 30% held-out for final evaluation); if sample size permits, k-fold cross-validation (k=5) for internal replication; independent dataset replication planned for Phase 2.
- **Blinding/randomisation**: outcome assessors blinded to arm assignment; cases presented in random order to mitigate order effects.
- **Note**: protocol details are placeholders; final SAP to be pre-registered on OSF.

## Reproducibility & open science

- **Code repository**: GitHub (private during development; public upon acceptance for publication) — `https://github.com/TBD/DiffDiagnosis`.
- **Data deposit plan**: de-identified gold-standard dataset (≥200 cases) to be deposited on Zenodo (https://zenodo.org/) with DOI upon publication; synthetic development data available on OSF (https://osf.io/TBD).
- **Pre-registration**: link to OSF pre-registration (https://osf.io/TBD) — to be added upon registration.
- **Materials transparency**:
  - Algorithm definitions: JSON schemas in `algorithms/` directory with version control.
  - Source extraction scripts: Python notebooks in `scripts/` for reproducibility of LLM-based extraction.
  - Dependencies: `requirements.txt` (Python) and `Cargo.toml` (Rust) with pinned versions.
  - Protocol: detailed step-by-step protocol on protocols.io (https://protocols.io/TBD) upon acceptance.
- **Note**: all repository links and DOIs are placeholders; actual identifiers to be inserted upon creation/publication.

## 4. Consortium / partners

- **Clinical advisor**: TBD (formal agreement pending; target: one board-certified internist with ≥10 years of clinical experience)
- **Technical co-developer**: TBD (Rust backend engineer with experience in medical decision support systems)
- **Validation partner**: TBD (academic medical center with access to ≥200 de-identified clinical cases for gold-standard dataset)
- **Institutional support**: GLA (Georgian Laboratory of AI) — internal funding and infrastructure
- **Status**: All partnerships are in negotiation phase; formal agreements expected by Q1 2027.
