# Patient as Project — AIM Cornerstone

**Версия:** 1.0
**Дата:** 2026-05-07
**Статус:** Cornerstone framework — задаёт онтологию AIM

---

## Манифест

AIM — **не** clinical decision support tool. AIM — **infrastructure для validation третьего уровня** взаимодействия patient↔AI: пациент как developmental project с измеримой траекторией agency.

Главный outcome metric AIM = **PAM-13 trajectory** (Patient Activation Measure, MCID = 5.4).

---

## Three-Level Framework (L1/L2/L3)

| Level | Patient role | AI role | Empirical status |
|---|---|---|---|
| **L1 — Patient-Object** | Passive data source | Risk calculator, classifier | Confirmed (Fraunhofer IGD MED²ICIN) |
| **L2 — Patient-Narrator** | Information provider | Communication facilitator | **Confirmed Level I** (Tao et al., Nat Med 2026, n=2069) |
| **L3 — Patient-Project** | Active co-manager | Developmental agent | **Theoretical** — AIM existing для validation through RCT |

### L1 — Patient-Object

Patient = source of structured data. Lab values, imaging, vitals → algorithms. AI provides risk scores. Patient's subjective state irrelevant. Не наша primary цель, но AIM делает это (kernel.py + lab interpretation) как foundation.

### L2 — Patient-Narrator

Patient = information provider whose own words matter. AI summarizes, translates, coordinates care. Patient narrates symptoms; AI structures dialogue. Confirmed Level I evidence: co-designed LLM chatbot reduces consultation duration 28.7%, improves coordination 113.1% (Tao et al.). Currently AIM doctor agent + Telegram bot operate здесь.

### L3 — Patient-Project (TARGET)

Patient = active co-manager of own developmental trajectory. AI as developmental agent: motivational interviewing, goal-setting, active listening. Outcome измеряется не через physician satisfaction, but through **patient activation** (PAM-13 score over time).

**L3 — это hypothesis, не factum.** AIM — vehicle для empirical validation L3 через RCT (см. paper §5.2).

---

## Architectural principles

### A1. Co-design > fine-tuning

Per Tao et al. (Nat Med 2026), co-designed LLM outperforms fine-tuned model on local dialogues. Co-design framework:

```
Contextual understanding → Co-creation → Testing → Implementation/evolution
```

В AIM:
- Patient feedback loops в `aim-codesign` crate
- Dialogue review tooling
- Co-design moments как distill candidate kind в hive queen

### A2. Performance-based 4-zone HCI (Blumenthal-Lee)

Per Qazi et al., automation bias = 14pp drop in accuracy даже при AI literacy training. Mitigation через performance-based routing:

| Zone | Strategy |
|---|---|
| Human-dominant | Defer to human judgment |
| AI-dominant | Defer to AI judgment |
| Hybrid review | Independent reviews, then comparison |
| Disagreement resolution | Trigger additional review |

В AIM: `aim-disagreement` crate (Phase 6), wire через orchestrator pre-emit.

### A3. PAM-13 as primary outcome metric

**Минимальный clinically important difference (MCID) = 5.4 points** (95% CI: 3.4–7.4) for CKD; **MDC (individual) = 7.2 points**.

В AIM: `aim-pam` crate (Phase 3), tracking в `MEMORY.md` activation_history.

### A4. Developmental ≠ instrumental agency

**Instrumental agency** (confirmed) = LLM operates autonomously. Подтверждено Tao et al. (PreA-only equivalent to PreA-human).

**Developmental agency** (target) = LLM enhances **patient's** subjective agency. Не подтверждено для LLM — L3 awaits empirical validation.

AIM не просто "automate care" (instrumental) — AIM **builds patient agency** (developmental). Это иначе ставит цели:
- Не "reduce physician burden" (хотя это side benefit)
- А "improve patient capacity to manage own health"

### A5. LLM longitudinal limits

Per Wang et al. (NPJ Digit Med 2026): LLMs **task-dependent** для outcome prediction. F1=0.871 для bone cement leakage, 0.309 для new vertebral fracture. AIM не использует LLM для unverified longitudinal predictions; physician oversight mandatory для high-stakes prognosis.

---

## L0-L4 Safety framework (расширение Asimov + extended laws)

Текущие 7 laws AIM:

```
L0 — Don't harm humanity
L1 — Don't harm this person (allergies, contraindications)
L2 — Obey doctor command (if not violating L0/L1)
L3 — Preserve system integrity
L_PRIVACY — Block PII egress without consent
L_CONSENT — Block external blast actions without user_confirmed
L_VERIFIABILITY — Reject unverified PMIDs/DOIs in emit_text
```

**Новый закон, добавляемый этим framework:**

```
L_AGENCY — Preserve patient developmental agency
```

L_AGENCY blocks decisions which:
- Make recommendations as directives ("you should X") without explanation/rationale
- Skip patient verification step for high-stakes actions
- Replace patient's choice with AI default
- Track patterns of "rapid acceptance" (patient agrees < 5 sec) — flag automation bias

L_AGENCY passes decisions which:
- Frame as options ("one approach is X, another is Y")
- Include verification prompts ("before acting, confirm with your physician")
- Use shared decision-making language
- Elicit patient preferences explicitly

См. `AUDIT_PATIENT_AS_PROJECT_2026-05-07.md` §3.4 для proposed Rust implementation.

---

## Patient state model — orthogonal axes

Текущая `aim-patient-state-machine` имеет одну ось — **clinical phase**:

```
INTAKE → DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT → MONITORING → STABLE → CLOSED
```

**Cornerstone framework вводит вторую ось — activation level (PAM-13 derived):**

```
Level 1 — Disengaged and overwhelmed
Level 2 — Becoming aware but still struggling
Level 3 — Taking action and gaining control
Level 4 — Maintaining behaviors and pushing further
```

Patient state — это **decart product** двух осей: `(clinical_phase, activation_level)`. Например, `(ACTIVE_TREATMENT, level=2)` patient требует **clinical management + activation coaching**. AIM кormit different patterns:

| Patient state | AIM action pattern |
|---|---|
| Phase=INTAKE, level=1 | Build trust + basic education + simple goals |
| Phase=ACTIVE_TREATMENT, level=2 | Treatment + skill-building + small wins |
| Phase=MONITORING, level=3 | Self-management support + accountability |
| Phase=STABLE, level=4 | Peer-support / mentor patterns |

---

## Что AIM делает по этому framework

### Уже делает (confirmed L1, partial L2):

- ✅ Asimov + extended laws kernel (L0-L3 + L_PRIVACY/CONSENT/VERIFIABILITY)
- ✅ Patient lifecycle (INTAKE → CLOSED) через `aim-patient-state-machine`
- ✅ Doctor agent (lab interpretation, regimen validation)
- ✅ Phoenix LiveView `patient_live.ex` — patient dashboard
- ✅ Daily brief / weekly digest для physician oversight

### Будет делать (target L3 validation):

- ⏳ `aim-pam` — PAM-13 measurement, scoring, MCID detection (Phase 3)
- ⏳ `aim-coach` — coaching patterns (MI, goal-setting, active listening) (Phase 4)
- ⏳ L_AGENCY extended law (Phase 5)
- ⏳ `aim-disagreement` — 4-zone HCI per Blumenthal-Lee (Phase 6)
- ⏳ `aim-codesign` — patient feedback loops (Phase 7)
- ⏳ AI subproject: `pam_tracker.py`, `automation_bias_detector.py`, `codesign_log.py`
- ⏳ Phoenix `pam_live.ex`, `coach_live.ex`, `activation_dashboard.ex`
- ⏳ Real RCT validation (long-term, Phase 8) — `aim-experiment-owner` уже есть для tracking

---

## Reference paper

Manuscript: Tkemaladze J. (2026) "Patient as a Project: A Theoretical and Empirical Framework for Understanding the Patient as a Developmental Construct in the Era of Generative Artificial Intelligence", *Longevity Horizon* 2(5). DOI:.

Локальная копия в repo: `MANUSCRIPT_PATIENT_AS_PROJECT_2026-05-07.md`.

Key cited evidence:
- Tao X, et al. *Nat Med* 2026;32:934-942 — co-design + instrumental agency confirmed
- Qazi M, et al. *NEJM AI* 2026;3(5) — automation bias 14pp drop
- Blumenthal & Lee, *NEJM AI* 2026;3(5) — 4-zone framework
- MCID for PAM-13, *Kidney Int Rep* 2025;10(7):2275-2283 — 5.4 points
- Alsaad et al., *J Clin Med* 2026;15(1):301 — tailored intervention p=0.004
- Wang T, et al. *NPJ Digit Med* 2026;9:84 — LLM task-dependent prediction limits
- LLMDP trial, *NPJ Digit Med* 2025;8:123 — student training (84 students, 10.5 pt skill gain)

---

## Cornerstone implications

1. **AIM mission shift**: from "AI medical assistant" → "infrastructure for validating L3 patient developmental agency"
2. **Primary outcome metric**: PAM-13 trajectory (not physician satisfaction)
3. **All future development weighed against**: does this advance L3 capability? does this protect patient agency?
4. **L_AGENCY** added as 4-й extended law alongside PRIVACY/CONSENT/VERIFIABILITY
5. **Real RCT** — long-term goal через `aim-experiment-owner` infrastructure для validating L3

---

**Этот документ — cornerstone. Все architectural решения после 2026-05-07 проверяются против него.**
