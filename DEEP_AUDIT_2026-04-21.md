# DEEP AUDIT — AIM v7.0 (Assistant of Integrative Medicine)

**Audit date:** 2026-04-21
**Auditor:** Autonomous (Claude Opus 4.7 1M, cold read of repo)
**Scope:** Medical claims · Evidence base · Architecture · Regulation · Competitors · Grant-reviewer concerns
**Target standard:** NIH R01 / EIC Pathfinder / ERC Advanced / Wellcome Digital Tech Health
**Codebase:** 3 057 LoC Python across 11 modules, 9 languages, 4 LLM providers
**Status (one line):** *Working engineering prototype with zero clinical validation, zero regulatory path, and outdated self-description in project `CLAUDE.md`.*

---

## 0. Ground truth — what AIM actually is (2026-04-21)

The repository is **smaller and simpler** than the project-level `~/CLAUDE.md` claims. A cold read of `~/Desktop/AIM/` reveals:

| Claim in `~/CLAUDE.md` (outdated) | Reality in `~/Desktop/AIM/` (v7.0) |
|---|---|
| `diagnosis_engine.py` — "Bayesian differential diagnosis" | **Does not exist.** |
| `bayesian_medical.py` — "per-patient Bayesian networks" | **Does not exist.** |
| `treatment_recommender.py` — "evidence-based protocols" | **Does not exist.** |
| `medical_knowledge.json` — "self-learning KB" | **Does not exist.** |
| `lab_parser.py` — "extracts lab values, evaluates vs ranges" | **Does not exist.** Only `lab_reference.py` (static dict). |
| `ocr_engine.py`, `whatsapp_importer.py`, `patient_intake.py` | Replaced by `agents/intake.py` (261 LoC). |
| `medical_system.py` described as "self-learning AI" | Actually a menu-driven CLI loop (287 LoC) that dispatches to LLM APIs. |

**Implication for grant reviewers:** if an NIH/EIC reviewer receives a proposal that cites these modules, they will pull the repo, fail to find them, and the submission dies on first contact. **This must be fixed before any submission.**

---

## 1. Medical Claim Verification

### 1.1 Hardcoded diagnostic thresholds and reference ranges

**File:** `/home/oem/Desktop/AIM/lab_reference.py` (534 LoC)
**Contents:** 59 analytes across 9 categories (CBC, Biochemistry, Kidney, Liver, Thyroid, Vitamins, Electrolytes, Hormones, Inflammation, Coagulation).

#### Critical findings

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 1 | **No source citation on any of 59 analytes** | 🔴 Critical | Zero `source:` field, zero PMID, zero guideline reference (ADA / ESC / KDIGO / Endocrine Society). Reviewer will ask "who wrote these numbers?" and the answer today is "the author, from memory." |
| 2 | **No provenance of unit choice** | 🟠 High | SI units used in most places (`mmol/L`, `μmol/L`, `nmol/L`) but `insulin` is in `мкЕд/мл`, `HOMA-IR` in `усл. ед.`, `TSH` in `мМЕ/л`, `calcium` in `mmol/L` — mixed Russian and English notation inside the same file. Inconsistent, hard to localize to EU/US labs. |
| 3 | **Age- and sex-specific ranges partially missing** | 🟠 High | Sex-split for Hb, Hct, RBC, HDL, ferritin, creatinine, uric acid, testosterone, DHEA-S — OK. But **no pediatric ranges**, **no pregnancy ranges**, **no age-stratified ranges for eGFR, TSH, IGF-1** (IGF-1 notes say "for 40 y/o" — but clinical IGF-1 is age-banded 1-100 y with ≥10 bins per sex). |
| 4 | **HbA1c cutoff 5.7 / 6.5** — correct per ADA 2023 | ✅ OK | But not cited. |
| 5 | **Vitamin D 75-250 nmol/L "optimum 100-200"** | 🟡 Medium | ≥75 nmol/L is **Endocrine Society 2011** (sufficiency); however, **IOM / NAM 2011** says ≥50 nmol/L is sufficient. The two bodies disagree; AIM silently picks the Endocrine Society position without disclosure. A grant reviewer will flag this as "advocacy bundled as fact." |
| 6 | **TSH "optimum 1.0-2.5"** | 🟠 High | This is an **integrative-medicine/functional-medicine** position, not mainstream endocrinology. AACE/ATA guidelines give 0.4-4.0 mIU/L for adults. Marking 2.5 as the upper "optimum" without citation is a defendable *philosophical* position for an integrative practice but indefensible as a hardcoded default in a CDS tool. |
| 7 | **homocysteine "optimum <10"** | 🟡 Medium | Sensible but not guideline-level; most labs report 5-15 μmol/L as reference. No citation. |
| 8 | **HOMA-IR cutoff 2.7** | 🟡 Medium | Literature cutoffs vary 1.9-3.16 across populations. 2.7 is acceptable but **population-specific** (Chinese and Hispanic cohorts use different cutoffs). Needs a citation. |
| 9 | **hs-CRP 1/3 mg/L ASCVD risk tiers** | ✅ OK | Matches AHA/CDC 2003. Not cited. |
| 10 | **No drift/update mechanism** | 🔴 Critical | Reference ranges change (ADA, KDIGO, ATA update yearly). There is no versioning, no `last_reviewed` field, no re-review schedule. A CDS tool that freezes 2026 ranges and drifts for 5 years becomes actively harmful. |

#### Recommendation — mandatory rework before submission

Add to every entry in `LAB_RANGES`:
```python
"hba1c": {
    ...
    "source": "ADA Standards of Care 2023, Section 2",
    "doi": "10.2337/dc23-S002",
    "last_reviewed": "2026-04-21",
    "population": "adults, non-pregnant",
    "evidence_grade": "A",
},
```
Without this, the file is **not defensible** in any formal submission.

### 1.2 Hardcoded treatment protocols

**Finding:** `agents/doctor.py` contains **no hardcoded drug/dose/protocol data**. All treatment recommendations are delegated to the LLM via system prompts (e.g. `"Структура: 1) Конвенциональная терапия (первая линия), 2) Интегративные подходы (нутрицевтики, фитотерапия, физиотерапия), 3) Образ жизни"`).

**Consequence:** every therapeutic recommendation AIM produces is a **fresh LLM generation** with no grounding. This is the single biggest clinical-safety issue — see §3.2.

**Self-citation footprint:** zero hardcoded references to the author's own papers (CDATA, dasatinib+quercetin senolytic, Tkemaladze 2023 PMID 36583780). Good — prevents self-promotion in patient-facing output; bad — the system produces output without the author's *evidence* backing anything.

### 1.3 Disclaimers

**Finding:** `agents/doctor.py` line 78-88 has a hard-coded multilingual `DISCLAIMER` dict and `_ensure_disclaimer()` appends it to every response. This is the **only medical-safety guardrail in the system.**

Disclaimer text (RU): *"⚠️ Информационная поддержка. Не является медицинским советом. Проконсультируйтесь с лечащим врачом."*

**Weakness:** disclaimer does not state:
- AIM is not a medical device.
- AIM is not validated for clinical use.
- Data may be sent to third-country API servers (CN, US, EU).
- The user takes full responsibility for acting on AIM output.

**Fix:** extend to 4 sentences covering these 4 points, in all 9 languages.

---

## 2. Integrative-Medicine Evidence Base — Literature Gaps

### 2.1 Current state of AIM's literature review

- `docs/literature_daily/PUBMED_AIM_2026-04-18.md` and `2026-04-19.md` — **both failed** with HTTP 429 (rate limited).
- `docs/REFERENCE_AUDIT_AIM.md` — 0 PMIDs flagged but also **0 PMIDs present** in the codebase (literally nothing to audit).
- `docs/META_ANALYSIS_AIM.md` — 13 lines, cites only the peer-review score 2.5/10.

**Conclusion:** AIM has no living literature base. This is not acceptable for a clinical-decision-support grant.

### 2.2 Critical literature that MUST be cited in any serious submission

Searched (offline, from training cutoff Jan 2026). **The following are the landmark papers a reviewer will expect:**

#### A. AI clinical decision support, general (2020-2025)

- **Singhal K et al.** (Google/DeepMind). *Large language models encode clinical knowledge.* Nature 2023;620:172-180. PMID 37438534. (Med-PaLM, **must-cite** — sets the bar AIM is measured against.)
- **Singhal K et al.** *Toward expert-level medical question answering with LLMs.* Nature Medicine 2025. (Med-PaLM 2.)
- **Tu T et al.** *Towards generalist biomedical AI.* NEJM AI 2024. (Med-Gemini.)
- **McDuff D et al.** *Towards accurate differential diagnosis with large language models.* Nature 2025. (AMIE, **directly compares** GPT-4 vs clinicians on differential dx — the exact framing AIM needs.)
- **Goh E et al.** *LLM influence on diagnostic reasoning.* JAMA Network Open 2024. (Showed GPT-4 alone *outperforms* physicians + GPT-4 — the "automation bias" problem AIM's roadmap ignores.)
- **Omiye JA et al.** *Large language models propagate race-based medicine.* npj Digital Medicine 2023. (**Must cite** for bias discussion.)

#### B. Integrative medicine + AI

- **Ng JY et al.** *AI in integrative medicine scoping review.* BMC Complementary Medicine and Therapies 2024.
- **Kwon C-Y et al.** on ChatGPT + traditional/complementary medicine — multiple 2024 papers.
- **Cochrane Complementary Medicine Field** — methodology for integrative evidence grading.

**Gap:** AIM does not reference any integrative-medicine evidence framework. For a tool calling itself "Assistant of **Integrative** Medicine," this is a fatal omission. Reviewers will assume the integrative label is marketing.

#### C. Multilingual medical AI (relevant to AIM's 9-language claim)

- **Jin Q et al.** *Matching patients to clinical trials with large language models.* Nature Communications 2024.
- **Wang B et al.** *Multilingual medical LLM benchmark (MedMCQA, MMLU-Medical).* ACL 2024.
- **No published work** exists on Georgian or Kazakh medical LLM benchmarking. This is AIM's **one genuine niche** — but unexploited: no benchmark dataset built, no evaluation run.

#### D. FDA/EMA regulation of AI-CDS

- FDA. *Clinical Decision Support Software — Guidance for Industry and FDA Staff.* September 2022.
- FDA. *Marketing Submission Recommendations for a Predetermined Change Control Plan for AI-Enabled Device Software Functions.* December 2024.
- MDCG 2019-11 (EU). *Guidance on Qualification and Classification of Software in MDR and IVDR.*

**Gap:** AIM has zero regulatory literature awareness in the repo.

#### E. Lab reference provenance

- **CLSI EP28-A3c.** *Defining, Establishing, and Verifying Reference Intervals in the Clinical Laboratory.* 2010 (re-verified 2020).
- **Ichihara K et al.** *Asian committee for reference intervals and decision limits (C-RIDL) multicentre study.* Clin Chim Acta 2017. (Relevant for Central-Asian populations AIM targets.)

**Gap:** `lab_reference.py` sources none of these.

---

## 3. Clinical Decision Support Architecture Review

### 3.1 "Bayesian diagnosis"

**FINDING:** *No Bayesian engine exists in AIM v7.0.*

- `~/CLAUDE.md` claims `bayesian_medical.py` and `diagnosis_engine.py` — both absent.
- Actual diagnostic path: `doctor.py::diagnose()` builds a prompt → sends to DeepSeek-reasoner → returns free text.
- Prior probability = implicit in LLM training data (unknowable).
- Likelihood = implicit in LLM attention (unknowable).
- Posterior = token-sampled free text (non-reproducible at temperature 0.3; log line in `ask_deep` uses temperature 0).

**Verdict:** **The Bayesian framing in the project-level CLAUDE.md is false advertising.** Either:
- (a) remove all Bayesian claims from grant materials and call it "LLM-assisted differential diagnosis with explicit uncertainty prompting" — honest but less impressive, OR
- (b) implement a real Bayesian layer: naive-Bayes over a curated signs-and-symptoms → disease probability table (e.g. Symcat/DDXPlus/MIMIC-IV-ED derived), then use the LLM to translate posteriors into prose. Option (b) is 2-4 weeks of work and gives AIM a real differentiator.

**Recommendation:** before any submission, pick (a) or (b) and align the CLAUDE.md, CONCEPT.md, and code. Keeping the current gap is a guaranteed reviewer kill-shot.

### 3.2 Drug interaction checking

**FINDING:** *Not implemented.*

- Zero references to DDI, drug interaction, contraindication, or any pharmacology DB in the entire codebase (verified via grep).
- No integration with: DrugBank, RxNorm, FDA Orange Book, Medi-Span, First Databank, Lexi-Comp, Stockley's.
- The LLM will *attempt* to answer drug-interaction questions, but without grounding it will hallucinate — the highest-harm failure mode in any CDS tool.

**Verdict:** **This is the #1 clinical-safety hole.** For an integrative practice that stacks conventional drugs + nutraceuticals + herbs + senolytics (dasatinib + quercetin per the author's own published work), DDI checking is **mandatory**, not optional.

**Minimum fix before grant submission:**
- Add `drug_interactions.py` module.
- Load RxNorm + NLM DailyMed interactions (free, CC0, US NLM).
- Optionally: Natural Medicines Database API (licensed, ~$2k/yr) for herb-drug interactions — most relevant to integrative medicine.

### 3.3 Lab reference ranges — source and currency

Already covered in §1.1. Summary: 59 analytes, 0 citations, 0 timestamps, 0 population context, 0 update plan.

### 3.4 Fallback chain — silent correctness drift

`llm.py::_fallback()` (lines 150-181) tries DeepSeek → Qwen → KIMI in order. **Problem:** each model has a different medical knowledge cutoff, different language quality, different hallucination profile. A diagnostic query that succeeds with DeepSeek-reasoner but silently falls back to Qwen-turbo may return a clinically different answer. The log line says `"Fallback succeeded with {model}"` but the caller (DoctorAgent) has no way to propagate this to the user. **Patients / doctors will not know which brain answered.** This is a latent safety issue and a documentation requirement under FDA Predetermined Change Control guidance.

### 3.5 Caching

`DoctorAgent.diagnose()` uses `cache_get(cache_key)` keyed on `hash(prompt)`. **Problem:**
- Same prompt from different patients returns cached answer → potential HIPAA/GDPR leakage if cache is shared across sessions.
- No TTL, no invalidation on guideline update.
- Python `hash()` is salt-randomized per process — cache is per-process, not durable — probably not the intended design.

### 3.6 Language detection

`llm.py::_detect_lang()` uses Unicode-block regex. Works for ar/zh/ka. Russian vs Kazakh heuristic = presence of `әіңғүұқөһ`. **Edge cases:** code-mixed text, Latin-transliterated Kazakh, Arabic-script Kazakh (historical). Acceptable as a v1 heuristic; document the limits.

### 3.7 Missing in architecture entirely

- **Provenance / audit log** — `db.py` saves messages but no model id, no token count, no safety flag, no user override.
- **Uncertainty quantification** — no confidence score attached to any output.
- **Human-in-the-loop gate** — no "physician must confirm before output is shown to patient" flow.
- **De-identification layer** — patient name/DOB sent verbatim to third-country APIs.
- **Adverse-event reporting** — no mechanism for the clinician to flag an AIM error.
- **Version pinning of LLMs** — model names in `config.py::Models` but upstream providers can silently update the model behind the name (DeepSeek-chat in particular has been updated ≥4 times since 2024). FDA PCCP requires this to be controlled.

---

## 4. Regulatory Status

### 4.1 FDA (US) — Software as a Medical Device

**FDA CDS guidance (2022) four-criterion test:** a CDS is **exempt** from FDA oversight only if all four hold:
1. It does not acquire/process/analyze a medical image or signal.
2. It displays/analyzes medical information normally communicated between HCPs.
3. It provides recommendations (not specific directives).
4. **The HCP can independently review the basis of the recommendation.**

AIM passes (1), (2), (3) trivially. **AIM fails (4)** — LLM output is not explainable; the clinician cannot "independently review the basis." Therefore AIM **is a medical device** under 21 CFR 880 if sold/distributed in the US.

**Likely class:** II (moderate risk), requiring 510(k) clearance — unless De Novo pathway is chosen because no predicate device for "hybrid multi-LLM integrative-medicine CDS" exists. Recent precedents: IDx-DR (De Novo 2018), Aidoc (multiple 510(k)).

**Verdict:** AIM is **not FDA-cleared** and **cannot be marketed in the US** as a CDS. For current personal-use by one physician (Dr. Tkemaladze) on his own patients, "practice of medicine" doctrine (FDCA §1006) provides cover — **but this exemption evaporates the moment the tool is offered to a second clinician, licensed, or white-labeled.** Any grant pitch involving scale-out must include an FDA strategy.

### 4.2 EU — MDR and CE marking

**MDCG 2019-11 rule:** software intended to provide information used for diagnosis or therapeutic decisions = medical device software (MDSW). Classification by Rule 11 of MDR Annex VIII:
- Provides information for decisions with therapy/diagnosis purpose → **Class IIa minimum**.
- Can cause *serious deterioration* of health → **Class IIb**.
- Can cause death → Class III.

AIM, as marketed ("diagnosis", "treatment protocols"), lands at **Class IIa or IIb**. CE marking requires:
- ISO 13485 quality management system.
- ISO 14971 risk management.
- IEC 62304 software lifecycle.
- Clinical evaluation per MDR Annex XIV.
- Notified Body review (Class IIa+).

**Estimated path:** 18-30 months, €150k-€500k. None of this is in AIM's roadmap.

**Also applicable:** **EU AI Act** (in force from 2024, high-risk provisions from August 2026). Medical-device AI is explicitly a **high-risk** category (Annex III). Adds: risk management, data governance, technical documentation, transparency, human oversight, accuracy/robustness/cybersecurity, post-market monitoring. AIM satisfies **none** of the high-risk AI Act obligations today.

### 4.3 Disclaimers — current state

Per §1.3: present but minimal. Does not satisfy FDA §502 or EU MDR labelling requirements for commercial use.

### 4.4 Data residency (HIPAA/GDPR)

**Critical issue.** AIM sends patient text to:
- `api.deepseek.com` (China)
- `api.moonshot.cn` (China)
- `dashscope-intl.aliyuncs.com` (Singapore, Alibaba)
- `api.groq.com` (US)

**Consequences:**
- **GDPR:** transfer to China = adequacy decision absent = requires Standard Contractual Clauses (SCC) + Transfer Impact Assessment. Neither is in the repo.
- **HIPAA:** no BAA signed with DeepSeek, Moonshot, Alibaba, Groq (verify — but I've seen no such BAA in public). Therefore AIM cannot legally process US patient PHI.
- **Georgia's Personal Data Protection Law (2011/2023 amendments):** cross-border transfer requires adequacy or explicit consent. AIM does not obtain documented consent for CN/US transfer.

**Minimum mitigation before grant submission:**
1. De-identification layer (Safe Harbor 18 identifiers removed before LLM call).
2. Explicit patient consent form in all 9 languages.
3. Local fallback (Ollama + Llama 3.1-8B or Mistral-7B-instruct) for PHI-sensitive queries.
4. Documentation of which data flows to which jurisdiction.

---

## 5. Competitor Landscape

### 5.1 Detailed comparison

| Tool | Core | Scope | Regulatory | Strength | Weakness |
|------|------|-------|------------|----------|----------|
| **UpToDate** (Wolters Kluwer) | Curated expert summaries, graded evidence | All medicine | CDS Exempt (reference content only) | Gold-standard evidence synthesis, 12M users, deeply EMR-integrated (Epic, Cerner) | Expensive ($550/user/yr), English-first, slow to update (~1.5 yr lag), no integrative content |
| **DynaMed / DynaMed Decisions** (EBSCO) | Evidence-graded POC reference + CDS | All medicine | FDA Cleared (DynaMed Decisions 2023) | Explicit GRADE/USPSTF grading, fast updates, shared decision-making | English/Spanish only, no AI conversation, no multilingual |
| **Ada Health** | Symptom-check chatbot | Primary care triage | CE Mark Class IIa (EU), not FDA-cleared in US as diagnostic | 70+ languages, 13M users, Bayesian symptom→condition engine | Consumer-facing, not clinician workflow; accuracy studies mixed (~70% top-5) |
| **Babylon Health** | AI triage + telemedicine | Primary care | CE Class I (downgraded) | Was large in UK; bankruptcy 2023 → cautionary tale | Collapsed financially; UK NHS GP-at-Hand terminated |
| **Med-PaLM 2 / AMIE** (Google) | Medical LLM | Research | None (research artifact) | Matches/exceeds physician on USMLE; AMIE beats PCPs on DDx (Nature 2025) | Not a product; API access restricted |
| **OpenEvidence** | LLM-over-NEJM-corpus search | Evidence retrieval | CDS Exempt (reference) | 2024 breakout, used by ~40% US physicians; grounded in peer-reviewed corpus | English-only, not integrative, not multilingual |
| **Glass Health** | LLM-assisted DDx and plan | Clinical reasoning | CDS Exempt stance | Clean clinician UI, growing; NEJM AI coverage 2024 | US-only, English-only |
| **Hippocratic AI** | Voice agents for patient outreach | Nursing/care-team tasks | Partner hospital validation, not FDA cleared | Large funding ($500M+); safety-first stance | Not diagnosis; not comparable to AIM |

### 5.2 Honest differentiation statement for AIM (grant pitch, 2 sentences)

> *AIM is the only clinical decision-support system purpose-built for integrative-medicine practice in the Caucasus and Central Asia, with native clinician-grade support for Georgian, Kazakh, Russian, Arabic, and Chinese — language pairs that UpToDate, DynaMed, Ada, OpenEvidence and Glass do not serve. AIM's hybrid LLM router allocates tasks across four commercial providers by cost, latency, language, and context length, with a fall-back chain for provider-independent availability.*

**Honest caveats to include in any pitch:**
- AIM does **not** yet claim diagnostic parity with Med-PaLM or AMIE (no benchmark run).
- AIM does **not** replace UpToDate's evidence synthesis (no curated knowledge base).
- AIM does **not** have CE/FDA clearance.

### 5.3 Unique-feature gap analysis

| Feature | UpToDate | Ada | AIM v7.0 | AIM should add? |
|---------|----------|-----|----------|-----------------|
| Evidence grading (GRADE/USPSTF) | ✅ | ❌ | ❌ | **Yes — critical** |
| Drug interactions | ✅ (Lexi) | ❌ | ❌ | **Yes — critical** |
| ICD-10/ICD-11 coding | ✅ | Partial | ❌ | Yes (mid-priority) |
| Patient-facing handouts | ✅ | N/A | via `lang.py::simplify()` | Already a strength |
| Multilingual (≥9 languages) | Partial | ✅ (70+) | ✅ | Defend this |
| Integrative/herbal content | ❌ | ❌ | Claimed but not curated | **Turn into real differentiator** |
| Offline/on-prem option | ✅ | ❌ | ❌ | Yes (for EU/GDPR scale) |
| EMR integration (FHIR) | ✅ | Partial | ❌ | Yes (phase 2) |

---

## 6. Top 5 Grant Reviewer Concerns (NIH / EIC level)

Ranked by expected severity in reviewer comments.

### Concern 1 — "Where is the evidence this helps patients?" (Impact & Approach)
*No validation plan. No pilot data. No benchmark. No clinical-viaggnette study. No n, no RCT, no retrospective chart review, no comparison to standard of care.*
**Fix before submission:** add §11 "Clinical Validation Protocol" with (a) retrospective analysis of 100-300 anonymized cases from the existing `Patients/` folder; (b) blinded comparison of AIM differential vs physician differential on MedQA-style vignettes (n≥50); (c) prospective time-motion study in the practice (before/after AIM).

### Concern 2 — "Is this a medical device, and if so, where is the regulatory plan?" (Environment / Feasibility)
*No CE/FDA analysis in repo. Sending PHI to CN servers. No de-identification. No consent. No BAA.*
**Fix before submission:** add §12 "Regulatory & Compliance Strategy" covering FDA CDS four-criterion analysis, EU MDR Rule 11 classification, AI Act high-risk obligations, GDPR/HIPAA data-flow map, de-identification layer design.

### Concern 3 — "Why a router instead of fine-tuning one medical LLM?" (Innovation)
*Router is engineering, not science. No head-to-head data showing router > single best model. Peer review score 2.5/10 already flagged this.*
**Fix:** add a benchmark run — MedQA + MedMCQA + PubMedQA + MMLU-Medical — comparing AIM (router) vs each single provider vs GPT-4 baseline. If the router actually wins on some axis (cost/token or a specific language), **that is the paper**. If not, pivot the narrative to the multilingual + integrative niche.

### Concern 4 — "What is your safety framework when the LLM hallucinates?" (Risk)
*No uncertainty quantification. No hallucination detection. No abstention threshold. No adverse-event logging.*
**Fix:** add a confidence layer (self-consistency sampling; entropy of token distribution; citation-grounding check against a local KB), an abstention threshold ("AIM cannot answer with sufficient confidence"), and an `incident_log` table in `db.py`.

### Concern 5 — "How do you update clinical knowledge? What happens when ADA updates HbA1c cutoffs?" (Post-market surveillance)
*Ranges in `lab_reference.py` have no timestamp, no source, no re-review plan. Provider models can silently change under `"deepseek-chat"` alias.*
**Fix:** add a `CHANGELOG_CLINICAL.md`, a quarterly-review SOP, pin model versions in `config.py` by hash/date, and subscribe to guideline-update feeds (ADA, ESC, KDIGO, ATA, NICE).

### Bonus (Concern 6 — Co-PI / Team)
Reviewers will ask who is on the team besides the PI. Current repo shows single-PI development; for EIC Pathfinder umbrella this is fine (see `project_eic_umbrella` memory — CommonHealth WP structure), but a biostatistician, clinical validator, and regulatory consultant are essential named roles. Align with the existing EIC variant C plan.

---

## 7. Pre-Submission Checklist (actionable, P0/P1)

### P0 (must do before any submission)
- [ ] Reconcile `~/CLAUDE.md` (top-level) with actual AIM v7.0 file list. Remove references to `bayesian_medical.py`, `diagnosis_engine.py`, `treatment_recommender.py`, `medical_knowledge.json`, `lab_parser.py`, `ocr_engine.py`, `whatsapp_importer.py`, `patient_intake.py`, `patient_analysis.py`.
- [ ] Add `source` / `doi` / `last_reviewed` field to every entry in `lab_reference.py` (59 entries × ~5 min = ~5 hrs work via DeepSeek).
- [ ] Tighten disclaimer to 4 sentences × 9 languages; state non-device status, data-jurisdiction transparency, user responsibility.
- [ ] Add de-identification function in `agents/intake.py` (strip Safe Harbor 18 identifiers before any LLM call).
- [ ] Add minimal drug-interaction check (load RxNorm TAB files, simple A-interacts-with-B lookup).
- [ ] Run a MedQA / MedMCQA benchmark (n=100 questions) against AIM, record scores.

### P1 (needed for EIC/NIH full submission)
- [ ] Add §11 Validation Protocol and §12 Regulatory Strategy to CONCEPT.md.
- [ ] Pin LLM model versions in `config.py` with expected-behavior hashes.
- [ ] Implement per-response provenance logging (`model_used`, `tokens_in/out`, `confidence`, `fallback_triggered`).
- [ ] Add an `incident_log` table in `db.py`.
- [ ] Add model-version changelog markdown.
- [ ] Write a 2-page "AIM as AI-Act high-risk compliant CDS — Technical Documentation" stub.
- [ ] Assemble named team: biostatistician, clinical evaluator (3 blinded physicians), regulatory consultant.

### P2 (post-submission / v7.2 roadmap)
- [ ] Replace LLM-only diagnosis with a real Bayesian layer (curated signs→disease prior table).
- [ ] Add FHIR export for EMR interop.
- [ ] On-premise Ollama fallback for PHI-sensitive queries.
- [ ] CE marking pre-audit with a notified body.

---

## 8. One-Paragraph Executive Summary

AIM v7.0 is a clean, working, 3 000-LoC engineering prototype of a multi-LLM router for integrative-medicine consultations in 9 languages. It is **not** a scientifically validated clinical decision support system: there is no Bayesian engine (despite `~/CLAUDE.md` claiming one), no drug-interaction database, no citation for any of the 59 hardcoded lab reference ranges, no regulatory analysis, no validation plan, and no clinical safety framework beyond a one-sentence disclaimer. In its present state, AIM would receive 2-3/10 from a serious NIH/EIC biomedical-AI reviewer — as the attached internal DeepSeek peer review (`docs/PEER_REVIEW_AIM.md`, 2.5/10) already concluded. However, AIM has one genuine, defensible niche: native clinician-grade Georgian, Kazakh, and Arabic support combined with integrative-medicine orientation — a gap no major competitor (UpToDate, Ada, OpenEvidence, Glass) fills. Before any 2026 submission the codebase must be reconciled with its own documentation, reference ranges must be cited and timestamped, a minimum drug-interaction layer and de-identification layer must be added, and a concrete 12-month validation protocol (MedQA benchmark + blinded clinical-vignette study + prospective time-motion study in the practice) must be written. These fixes are **2-6 weeks of focused work**, not a new project.

---

*End of audit. Next action: decide P0 sequence with user and open peer-review loop per `feedback_upgrade_peer_review_first` rule before implementation.*
