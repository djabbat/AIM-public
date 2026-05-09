# PILOT_PROTOCOL.md — AIM PAM-13 trajectory pilot study

**Статус:** **DRAFT — требует review + sign-off от Dr. Jaba Tkemaladze (MD).**
Все клинические детали (eligibility, dosing, co-interventions, lab schedule)
обозначены как `[CLIN-FILL]` и должны быть подтверждены MD до enrolment.

**Цель:** STRATEGY.md P1-3 (закрытие главной 6-месячной ставки).

---

## 1. Title

**Pilot validation of L3 (Patient-as-Project) intervention via AIM-assisted
integrative-medicine consultations: a single-center, single-arm, prospective
pre-post cohort study (N=30).**

## 2. Objectives

### Primary

- Detect a within-subject improvement in **PAM-13 score ≥ +1.0 MCID
 (= +5.4 points)** at the 3-month follow-up vs. baseline, in ≥ 50% of
 enrolled participants (descriptive; not powered for hypothesis test).

### Secondary

- Safety: zero **critical-grade kernel violations** logged by `aim-kernel`
 during the 3-month observation window across the cohort.
- Adherence: ≥ 70% of enrolled patients complete both PAM-13 administrations
 + ≥ 1 documented co-design event.
- Acceptability: SUS (System Usability Scale) ≥ 70 from clinician + patient
 surveys at month 3.

### Exploratory

- Correlation between number of co-design events and Δ PAM-13.
- Distribution of Blumenthal-Lee 4-zone HCI states across consultations.
- Cost per patient-month (DeepSeek + Gemini API spend ÷ active patient).

## 3. Design

- Single-center: DrJaba clinic (Tbilisi).
- Single-arm: every consenting eligible patient receives AIM-assisted
 consultation; **no control arm** in this pilot (descriptive study, hypothesis
 generation only).
- Pre-post: PAM-13 at baseline (T0) and at 3 months (T1).
- Duration: enrolment over 6 weeks; follow-up at week 12-14.

## 4. Eligibility — `[CLIN-FILL]`

### Inclusion (proposed; review by MD)

- Age ≥ 18 years.
- Active patient at DrJaba clinic.
- Stable chronic condition managed by integrative protocols (cardiology /
 geriatrics / nutritional optimization / phytotherapy via Regenesis).
- Russian, English, OR Georgian speaking sufficient for PAM-13 self-report.
- Capacity to consent (no documented cognitive impairment).
- Smartphone access OR willing to use clinic kiosk for follow-up forms.

### Exclusion (proposed)

- Active psychiatric crisis or hospitalization within 30 days.
- Pregnancy (separate protocol — AIM scope не покрывает obstetrics).
- Acute oncology under active chemotherapy (different decision context).
- Prior enrolment in AIM development or testing (selection bias).
- Inability to attend in-person follow-up at month 3.

## 5. Sample size

**N = 30** (target). Justification (descriptive pilot):

- Powered to detect a 0.5 SD effect at α = 0.05 with 80% power requires
 n ≈ 33 paired observations (paired t-test). 30 is 90% of that — adequate
 for **signal detection**, not confirmatory.
- Operationally feasible at clinic load of ~50 active patients.
- Allows graceful 20% drop-out → 24 evaluable.

## 6. Workflow per patient

```
T0 (baseline visit)
├── Informed consent (см. § 9)
├── Demographics + condition + meds intake (existing clinic flow)
├── PAM-13 administration #1 → aim-pam record
├── First AIM-assisted consultation:
│ ├── Doctor agent generates differential / regimen suggestion
│ ├── Disagreement classifier (aim-disagreement) for any AI-clinician
│ │ confidence mismatch (logged automatically)
│ ├── L_AGENCY: если PAM-13 level ≥ 2 → mandatory aim-codesign event
│ │ (consulted | agreed | modified | refused | alternative)
│ └── aim-coach motivational-interviewing turn (1-2 utterances)
├── Patient receives written summary + next-step plan
└── Follow-up scheduled: 6 weeks (interim) + 12 weeks (T1)

T0 + 6 weeks (interim, optional)
├── Brief check-in (in-person OR Telegram bot)
├── Symptoms + adherence review (no PAM measurement here)
└── Adjustments via aim-coach + aim-codesign

T1 (3 months)
├── PAM-13 administration #2 → aim-pam record
├── Δ classification automatic (aim-pam latest-delta)
├── Patient SUS survey (paper or kiosk)
├── Clinician SUS survey (post-visit)
└── Exit interview (free-text feedback)
```

## 7. Data captured (per patient)

| Source | Path | Format |
|---|---|---|
| PAM-13 administrations | `Patients/<id>/_pam_history.jsonl` | JSONL |
| Co-design events | `Patients/<id>/_codesign.jsonl` | JSONL |
| Disagreement events | `Patients/<id>/_disagreement.jsonl` | JSONL |
| AI decision audit | `Patients/<id>/AI_LOG.md` | Markdown |
| Free-text MEMORY | `Patients/<id>/MEMORY.md` | Markdown |
| Kernel violations | `~/.cache/aim/diagnostic_ledger.db` (sidecar table) | SQLite |
| Cost per patient | `~/.cache/aim/cost_ledger.db` | SQLite |

Cohort-level extraction script — `scripts/pilot_cohort_extract.py` — TBD
(P1-3 implementation).

## 8. Statistical analysis (descriptive)

Primary endpoint:
- Per-patient Δ = PAM_T1 - PAM_T0
- Classify: improved (Δ ≥ MCID 5.4) / stable / regressed (Δ ≤ -MCID).
- Report: % improved, mean Δ ± SD, median Δ [IQR].
- Bootstrap 95% CI on % improved (n=10000 resamples).

Safety:
- Tally critical-grade kernel violations.
- Tally Blumenthal-Lee zone distribution; flag any "escalate" or
 "conflict_high_stakes" sessions for case-by-case review.

## 9. Ethics / consent

### Regulatory frame

- **Georgian Personal Data Protection Law 2014** (single-centre standard).
- IRB-equivalent approval — `[CLIN-FILL]` Dr. Jaba to identify local ethics
 committee (or document equivalent process).
- НЕ под FDA jurisdiction (no US patients, no FDA-regulated device claim).
- НЕ под EMA jurisdiction (Georgia, не EU).

### Informed consent

Patient sees and signs Consent Form (`docs/operational/CONSENT_TEMPLATE.md`
— TBD) covering:

1. Что такое AIM — clinical decision support tool, not replacement for MD.
2. PAM-13 — purpose, anonymous aggregation для cohort analysis.
3. Data storage — local on clinic machine; LLM-запросы → DeepSeek API
 с PII-scrubbing per `agents/intake.py::_anonymize`.
4. Right to withdraw at any time without affecting routine care.
5. No financial compensation.
6. Pилот результаты могут быть опубликованы в peer-reviewed journal с
 anonymized aggregate data only.

## 10. Adverse event reporting

- **Kernel violation** → `~/.cache/aim/diagnostic_ledger.db` + `AI_LOG.md`
 пациента + email-уведомление Dr. Jaba (через `agents.notify`).
- **Clinical adverse event** → стандартный clinic AE log + paused enrolment
 pending review.
- **Privacy breach** → STOP study, notify Georgian DPA within 72h per
 Personal Data Protection Law 2014.

## 11. Timeline

| Week | Activity |
|---|---|
| W-4 to W-1 | Protocol finalized, IRB-equivalent submission, Consent Form ready, `scripts/pilot_cohort_extract.py` written |
| W0 | Recruitment open; 1st enrolment |
| W1-W6 | Active enrolment (target: ~5/week); each gets T0 visit |
| W6 | Enrolment closed (target N=30) |
| W12-W14 | T1 visits; 3-month follow-up |
| W15 | Cohort extraction + statistical analysis |
| W16-W18 | Manuscript draft (target journal: *npj Digital Medicine* OR *Lancet Digital Health*; vsp. в *Longevity Horizon*) |

## 12. Roles

| Role | Person |
|---|---|
| Principal Investigator | Dr. Jaba Tkemaladze, MD |
| Data steward | Dr. Jaba (clinical); developer (technical) |
| AIM technical lead | Developer (AIM repository owner) |
| Statistical analysis | TBD (consider biostatistician collaborator) |
| Ethics liaison | `[CLIN-FILL]` |

## 13. What is **out of scope** for this pilot

- Comparative effectiveness vs. standard care (no control arm).
- Long-term outcomes (> 3 months).
- Multi-center generalizability.
- Pediatric / obstetric / oncology subpopulations.
- Cost-effectiveness analysis (only descriptive cost-per-month).

These belong in a follow-up RCT (sample size, power, randomization, masking,
multi-arm) once pilot signal supports it.

---

## Open questions for Dr. Jaba review

> The technical / statistical scaffolding above is best-effort.
> The following items **require MD sign-off** before recruitment:

1. **Eligibility criteria** — confirm or amend § 4 inclusion / exclusion lists.
2. **Specific clinic conditions** in scope (cardiology / geriatrics /
 nutritional / phytotherapy — все четыре или подмножество?).
3. **MD time commitment** per AIM consultation (target ≤ 20 min above
 baseline visit?).
4. **IRB-equivalent body** в Тбилиси — какое именно одобрение нужно?
5. **Recruitment script** — что говорить пациенту при предложении.
6. **Compensation** — действительно zero, или nominal travel reimbursement?
7. **Co-investigators** — нужен ли second clinician для MD verification of
 AIM suggestions (single MD = bias risk)?

---

**Convention:** при clinical sign-off — переименовать `[CLIN-FILL]` маркеры
в фактические значения, удалить раздел "Open questions", добавить в
`CHANGELOG.md` `[Unreleased]`. До sign-off этот файл — DRAFT, recruitment
**не открывать**.
