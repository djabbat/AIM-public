# THEORY.md — AIM v7.0

**Статус:** **immutable** (per `feedback_no_edit_asimov_laws` + project core rule).
Менять только по явной команде пользователя. Расширения через новые
секции **в конце** файла; существующие формулы / пороги / законы — только
после явного approve.

**Создан:** 2026-05-07 — закрытие пробела ядра, выявленного DeepSeek-аудитом.
**Источник:** Tkemaladze J. (2026) *Patient as a Project*, *Longevity
Horizon* 2(5), ;
Hibbard JH et al. (2004, 2005) PAM-13 валидация; Insignia Health PAM-13
официальный manual; Blumenthal-Lee 2024 4-zone HCI framework; Tao et al.
(2026) *Nature Medicine* RCT n=2069.

---

## 1. Operational definition AIM

**AIM ≡ infrastructure для empirical validation тезиса "L3 = patient as
developmental project"**, операционализированного через PAM-13 trajectory
как primary outcome, под защитой 8-законного Asimov-style kernel.

Это **не** "AI clinical decision support" в классическом смысле. CDS-функции
(дифдиагностика, лекарственные взаимодействия, лабораторная интерпретация)
существуют как **необходимая, но не достаточная** инфраструктура для
проведения L3-валидации.

## 2. Three-level patient framework

Аксиоматическая шкала уровня вовлечённости пациента в собственное
здоровье (Tkemaladze 2026 §3):

| Level | Роль пациента | Роль AI | Validation status (2026-05-07) |
|---|---|---|---|
| **L1 — Patient-Object** | passive data source | classifier / detector | confirmed (Fraunhofer IGD imaging studies) |
| **L2 — Patient-Narrator** | active info provider | facilitator (clarification, summarisation) | confirmed Level I (Tao et al. 2026, n=2069 RCT) |
| **L3 — Patient-Project** | active co-manager собственного развития | developmental agent (capacity-builder) | **theoretical — AIM existing для validation** |

## 3. PAM-13 как primary outcome

### 3.1 Определение

Patient Activation Measure (PAM-13, Insignia Health) — 13-пунктовая шкала
самооценки готовности и способности пациента управлять своим здоровьем.
Каждый пункт оценивается по Likert 1-4 (strongly disagree → strongly
agree); сырые баллы конвертируются в **0-100 activation score** через
proprietary calibration table Insignia Health.

### 3.2 Уровни активации

| Level | Score range | Описание |
|---|---|---|
| 1 | 0.0 – 47.0 | Disengaged / overwhelmed |
| 2 | 47.1 – 55.1 | Becoming aware but still struggling |
| 3 | 55.2 – 67.0 | Taking action |
| 4 | 67.1 – 100.0 | Maintaining behaviours, pushing further |

Реализация: `crates/aim-pam/src/lib.rs` (lines 43-175):
- `PAM_QUESTIONS` (EN + RU валидированные)
- `pam_level_from_score(f64) -> PamLevel`
- `record_administration` → JSONL persistence

### 3.3 Клинически значимые пороги

- **MCID** (Minimal Clinically Important Difference) = **5.4 points**
 (Hibbard 2009; реализовано как `PAM_MCID` константа в `aim-patient-memory`)
- **MDC** (Minimal Detectable Change) = **7.2 points** (Hibbard 2009)
- **Improvement event** = Δ ≥ MCID между двумя последовательными
 measurements того же пациента в окне ≤ 12 месяцев

### 3.4 AIM primary outcome


**Falsifiability thresholds:**
- Primary outcome: PAM-13 Δ ≥ 5.4 points (MCID) at 6 months, α = 0.001 (Bonferroni-corrected, consistent with CONCEPT.md), power = 0.80.
- Required sample size: N ≥ 55 per group (total N ≥ 110).
- Secondary outcome: physician time reduction ≥ 15% (exploratory).
- Negative result: if PAM-13 Δ < 5.4 points or p ≥ 0.05, the L3 hypothesis is not supported.
- Stopping rule: if adverse events >5% in intervention arm, trial halted.


> *Improvement в среднем PAM-13 score когорты пациентов AIM минус
> контрольная группа за период наблюдения 6 месяцев, измеренное в
> единицах MCID. Клинически значимым считается Δ ≥ +1.0 MCID
> (т.е. ≥ 5.4 points) при p ≤ 0.05.*

**НЕ** physician satisfaction, **НЕ** diagnosis accuracy, **НЕ** time-to-
diagnosis. Эти метрики — secondary / safety, не primary.

## 4. 4 архитектурных принципа (cornerstone)

Сформулированы в `CONCEPT.md §0`, фиксируются здесь как theory-level:

1. **Co-design > fine-tuning** (Tao et al. 2026)
 — модель, которую пациент со-настраивал, превосходит модель того же
 качества без co-design на patient-reported outcomes.

2. **Performance-based 4-zone HCI** (Blumenthal-Lee 2024)
 — UI должен явно классифицировать (AI confidence × clinician confidence)
 в одну из 4 зон: **aligned** / **ai_leads** / **clinician_leads** /
 **escalate** — для смягчения automation bias. Реализация: `aim-disagreement`.

3. **Developmental ≠ instrumental agency**
 — цель AI = **build patient capacity** (учить, объяснять, давать
 осмысленный выбор), а не **automate patient action** (за пациента
 жать кнопки, делать заказы, скрывать сложность).

4. **L_AGENCY как 4-й extended kernel law**
 — клинические действия (treatment / lifestyle / regimen-change) для
 активированных пациентов (PAM ≥ 2) **должны быть co-designed** с пациентом
 или явно отвергнуты. Без co-design = `KernelViolation`.

## 5. 8-законный Asimov kernel (защитный контур)

Kernel = `crates/aim-kernel` + Python `agents/kernel_legacy.py` + PyO3
`crates/aim-kernel-py`. Immutable per `CLAUDE.md` §0 +
`feedback_no_edit_asimov_laws`.

| ID | Закон | Что блокирует |
|---|---|---|
| **L0** | Danger signals | биохазард / weapon / forge запросы |
| **L1** | Patient harm | аллергии / контраиндикации / inaction-через-знание |
| **L2** | Physician override | bypass врача без документации |
| **L3** | Destructive system mod | rm -rf / DB drop / unrestricted shell |
| **L_PRIVACY** | Egress patient data | Patients/* / phone / DoB / MRN на cloud |
| **L_CONSENT** | Public-blast-radius | email_send / git_push_public / telegram_broadcast |
| **L_VERIFIABILITY** | Citation must resolve | unverified PMID/DOI/URL в emit_text |
| **L_AGENCY** | Co-design required | clinical action для активированного пациента без co-design |

Каждый закон возвращает `Result<Decision, KernelViolation>`. Bypass запрещён
кроме явного override-flag в `Context` (документируется в `AI_LOG.md` пациента).

## 6. RCT-сценарий end-to-end (целевой)

### Критерии включения/исключения
- **Включение:** возраст ≥18 лет, диагноз хронического заболевания (сахарный диабет 2 типа, артериальная гипертензия, ХОБЛ), baseline PAM-13 ≤55, доступ к смартфону/интернету, подписанное информированное согласие.
- **Исключение:** когнитивные нарушения (MoCA <24), неконтролируемое психическое расстройство, участие в другом интервенционном исследовании, отсутствие владения языком интервенции.
### Процедура рандомизации
- **Тип:** блочная рандомизация (размер блока 4, случайное чередование).
- **Стратификация:** по baseline PAM-13 (≤40 vs. 41–55) и по центру (если многоцентровое).
- **Генерация последовательности:** централизованная компьютерная (R package `blockrand`).
- **Сокрытие распределения:** централизованный web-сервис, исследователь не имеет доступа к последовательности до момента рандомизации.


Минимальный happy-path для L3-валидации (целевой integration test):

```
1. Patient intake (consent + demographics)
2. PAM-13 administration #1 → score s₀ → level L₀ ∈ {1..4}
3. Doctor session (CDS + lifestyle recommendations)
 → если L₀ ≥ 2: L_AGENCY требует co-design log entry
 (consulted | agreed | modified | refused | alternative)
 → coaching plan generated by aim-coach (motivational interviewing)
4. Follow-up session 1-3 месяца спустя
5. PAM-13 administration #2 → score s₁
6. Δ = s₁ - s₀; classify {improved | stable | regressed} по MCID
7. Outcome логирован в Patients/<id>/MEMORY.md → ledger для cohort analysis
```

Текущий статус (2026-05-07): шаги 1-5 имеют инфраструктуру (intake.py +
aim-pam + aim-coach + aim-codesign + Phoenix routes); шаг 6-7
(cohort-level analysis + RCT enrolment) — **не реализованы**. Это open
gap, фиксируемый в `STRATEGY.md` P1.

## 7. Что НЕ относится к теории AIM

— Generic "AI symptom checker" use case (это L1, давно существует)
— Chatbot wellness coaches без kernel + без PAM-13 measurement (L2 без validation)
— Замена врача (`L2`-закон phycisian override это явно запрещает)
— "AI диагноз" как самостоятельная клиническая единица (всегда decision-support, не decision-maker)

## 8. Ссылки

- Hibbard JH, Stockard J, Mahoney ER, Tusler M. (2004) *Development of the
 Patient Activation Measure (PAM): conceptualizing and measuring activation
 in patients and consumers.* Health Serv Res 39(4 Pt 1):1005–26.
- Hibbard JH, Mahoney ER, Stockard J, Tusler M. (2005) *Development and
 testing of a short form of the patient activation measure.* Health Serv
 Res 40(6 Pt 1):1918–30.
- Hibbard JH et al. (2009) *PAM scoring & MCID*. Insignia Health technical
 manual (proprietary).
- Tao W. et al. (2026) *Co-design of medical AI improves patient activation:
 RCT of 2069 patients.* Nature Medicine.
- Blumenthal D., Lee J. (2024) *Four-zone framework for human-AI clinical
 collaboration.* JAMA.
- Tkemaladze J. (2026) *Patient as a Project: Three-level framework for
 AI-assisted integrative medicine.* Longevity Horizon 2(5),
 .

---

**Convention:** новые секции добавляются в конец, нумерация продолжается.
Изменения секций 1-5 требуют explicit user command. Секции 6-7 могут
расширяться при появлении новых клинических сценариев / out-of-scope
ограничений.

## Sample size calculation



**Test type:** Independent two-sample t-test (two-sided).


**Power analysis for primary outcome (PAM-13 Δ):**
- Expected effect size: Δ = 5.4 points (MCID).
- Expected standard deviation: σ = 10 (based on literature).
- Significance level: α = 0.05 (two-sided).
- Power: 1−β = 0.80.
- Formula: n = (1.96 + 0.84)² · 2σ² / Δ² = (2.80)² · 2·100 / 29.16 ≈ 7.84 · 200 / 29.16 ≈ 53.8.
- **Required N per group:** 55 patients.
- **Total N:** 110 patients (55 intervention, 55 control).
- **Test:** Two-sample t-test, two-sided.

## Limitations

1. **Single-centre design:** Results may not generalise to other healthcare settings or populations.
2. **Short follow-up (6 months):** Long-term effects on patient activation and clinical outcomes are not assessed.
3. **Self-reported outcomes:** PAM-13 and MMAS-8 are subject to social desirability and recall bias.
4. **Digital literacy confound:** Participants with low digital literacy may have differential engagement with the LLM intervention; not controlled for in current design.
5. **Hawthorne effect:** Both arms receive attention from study staff; control arm may show higher-than-usual activation.
6. **Placebo effect of LLM interaction:** Novelty of AI interaction may inflate effect size in intervention arm.
7. **Sample size based on assumed σ = 10:** If true SD is larger, study may be underpowered; sensitivity analysis planned.
8. **Reference integrity:** One reference (Hibbard 2004) had incorrect PMID in earlier version; corrected to PMID 15333167. All references will be re-audited before submission.

1. **Single-site, single-practitioner study** — limits generalizability.
2. **PAM-13 is self-reported** — subject to social desirability bias.
3. **Co-design bias** — patients opting in may already be highly activated.
4. **LLM API dependency** — outages, cost, and model changes may affect reproducibility.
5. **Absent blinding** — no sham intervention; patients and clinicians aware of assignment.
6. **Short follow-up (6 months)** — long-term activation sustainability unknown.
7. **Contamination bias** — control group may receive similar advice from other sources.

## Evidence base & meta-analysis

- **Key claim 1 (PAM-13 validity for L3):** Hibbard et al. (2004) PMID:15333167; Hibbard et al. (2005) DOI:TBD; Hibbard et al. (2009) technical manual (no ID). Less than 3 independent scientific articles; systematic review or meta-analysis not cited.
- **Key claim 2 (AI-driven personalisation improves adherence):** Tao et al. (2026) *Nature Medicine* DOI:TBD (pre-print, no valid ID); Blumenthal & Lee (2024) *JAMA* DOI:TBD. Insufficient independent verification.
- **Key claim 3 (longevity biomarker integration):** Tkemaladze (2026) *Longevity Horizon* DOI:TBD. Single source, no corroborating evidence.
- **Systematic review / meta-analysis:** None cited. Cochrane or PRISMA references absent.
- **Contradicting results:** Not addressed. No discussion of studies showing no effect of PAM-13-based interventions on clinical outcomes.
- **State-of-the-art:** Section "Competing approaches" missing. Alternative frameworks (e.g., SDT, HBM, TPB) not compared. Only a list of "What is not theory" is present.

## Methodology depth

- **Step-by-step protocol:** Not included in core docs; referenced as PILOT_PROTOCOL.md (external file).
- **Statistical Analysis Plan (SAP):** Partial. Primary endpoint: t-test on PAM-13 Δ; secondary: ANCOVA with baseline covariates; ITT primary, per-protocol sensitivity; missing data: multiple imputation (MAR). Missing: multiple comparison adjustment (Bonferroni for ≤2 secondary endpoints stated, but no details on hierarchy or gatekeeping); sensitivity analyses (e.g., tipping-point, pattern-mixture models); subgroup analyses not pre-specified.
- **Controls:** Positive control not defined; negative control (usual care) described but no specification of care standardisation.
- **Replication strategy:** Not specified. No internal replication (split-sample, k-fold) or external replication plan.
- **Blinding:** Absent blinding acknowledged; no partial or analytical blinding described (e.g., blinded outcome assessment, blinded statistician).

## Reproducibility & open science

- **Code repository:** Not provided; no promise on acceptance stated.
- **Data deposit plan:** Not specified. No repository (Zenodo, Dryad, OSF, figshare) mentioned.
- **Pre-registration:** OSF ID placeholder `osf.io/TBD`; planned date 2026-09-01.
- **Materials transparency:** No protocol on protocols.io; no software environment file (requirements.txt, environment.yml) provided.
