# Patient-as-Project — Cornerstone Integration

**Дата:** 2026-05-07
**Статус:** Анализ + предложение. Безопасные additive изменения начаты; high-risk изменения требуют твоего решения.
**Источник:** Tkemaladze J. (2026) "Patient as a Project: A Theoretical and Empirical Framework..", *Longevity Horizon* 2(5), — 

---

## 1. Что говорит статья — 4 ключевых принципа

### 1.1 Three-level framework

| Level | Patient role | AI role | Empirical status (per paper) |
|---|---|---|---|
| **L1** Patient-Object | Passive data source | Risk calculator, classifier | Confirmed (Fraunhofer IGD MED²ICIN) |
| **L2** Patient-Narrator | Information provider | Communication facilitator | **Confirmed Level I** (Tao et al., Nat Med 2026, n=2069 RCT) |
| **L3** Patient-Project | Active co-manager | Developmental agent | **Theoretical** — awaits LLM-specific RCT с PAM-13 primary outcome |

### 1.2 PAM-13 как measurable outcome для developmental agency

- **MCID = 5.4 points** (95% CI: 3.4–7.4) для CKD population (Kidney Int Rep 2025)
- **MDC (individual level) = 7.2 points**
- **Tailored interventions улучшают activation** (p = 0.004; Alsaad 2026)
- Lowest-activation patients (Levels 1–2) — наибольший gain

### 1.3 Co-design > fine-tuning

PreA trial (Nat Med 2026) показал: **co-designed LLM outperforms same model with additional fine-tuning on local dialogues**. Co-design framework: contextual understanding → co-creation → testing → implementation/evolution.

### 1.4 Automation bias — критичное ограничение

- Qazi et al. (NEJM AI 2026, n=44): 14-pp drop in diagnostic accuracy (84.9 → 73.3%, p<0.0001) даже при voluntary consultation + 20h AI literacy training
- Blumenthal-Lee 4-zone framework для mitigation:
 - **Human-dominant** (human accuracy > AI)
 - **AI-dominant** (AI accuracy > human)
 - **Hybrid review** (independent → compare)
 - **Disagreement resolution** (trigger additional review)

### 1.5 LLM longitudinal prediction — task-dependent

Wang et al. (NPJ Digit Med 2026): LLMs **not ready** для independent outcome prediction. F1=0.871 для bone cement leakage, но F1=0.309 для new vertebral fracture.

---

## 2. Mapping к текущему AIM

### 2.1 Что AIM уже делает (L1 + начало L2)

| AIM компонент | Level | Статус |
|---|---|---|
| `agents/kernel.py` (Rust via PyO3) — Asimov + Ze + ethics | **L1** | ✅ Confirmed |
| `agents/labs.py` — lab interpretation через kernel | **L1** | ✅ |
| `agents/doctor.py` — diagnose / treatment / regimen | **L1 → L2 transition** | ✅ |
| `aim-patient-owner` (Phase A) + Phoenix `patient_live.ex` | **L1 → L2 transition** | ✅ |
| Patient `MEMORY.md` schema (Phase + Milestones + Awaiting) | **L2 foundation** | ✅ — но Milestones сейчас clinical (как у врача), не co-designed (как у пациента) |
| Telegram bot interaction | L2 partial | ⚠ Пока однонаправленный (врач → patient), не co-design |

### 2.2 Что AIM НЕ делает (gap analysis vs paper)

| Принцип статьи | AIM текущее состояние | Что нужно |
|---|---|---|
| **L2 co-design** (Tao et al.) | LLM dialogue без structured co-design loop | Add `aim-codesign` patient feedback loops |
| **L3 developmental agency** | Patient lifecycle в YAML, но без agency metrics | Add PAM-13 measurement + tracking + coaching |
| **PAM-13 measurability** | Не измеряется | Add `aim-pam` crate + Phoenix questionnaire UI |
| **Automation bias mitigation** | Asimov L0-L3 + L_PRIVACY + L_CONSENT + L_VERIFIABILITY — но нет L_AGENCY | Add `L_AGENCY` law: block decisions that collapse patient agency |
| **Performance-based 4-zone HCI** | Single decision pipeline | Track per-action accuracy, route decisions через 4 zones |
| **Disagreement resolution** | Нет | Add `aim-disagreement` crate + `disagreement` action_type в kernel |
| **LLM longitudinal validation** | Тhere's `aim-doctor-calibration` для тracking, но нет integration с outcome prediction limits | Mark предсказания `task_dependent_confidence` |
| **Coaching / motivational interviewing** | Нет | Add `aim-coach` crate (developmental agent for L3) |

### 2.3 Самое важное — концептуальный сдвиг

Существующая AIM modeled patient как **clinical case** (история, dx, regimen). Paper предлагает modeled patient как **developmental project** с измеримой траекторией agency (PAM-13 over time).

**Сейчас в AIM:** patient.phase ∈ {INTAKE, DIAGNOSTIC_WORKUP, ACTIVE_TREATMENT, MONITORING, STABLE, CLOSED} — это clinical lifecycle.
**Что нужно добавить:** orthogonal axis "activation_level" ∈ {1, 2, 3, 4} per PAM-13. Patient может быть, например, в `ACTIVE_TREATMENT` phase × `activation_level=2` — нужен coaching для повышения agency.

---

## 3. Concrete изменения

### 3.1 Schema extension — `aim-patient-memory`

Добавить в `MEMORY.md` schema новую секцию:

```markdown
## Activation (PAM-13)
- current_score: 56.4
- current_level: 3
- last_measured: 2026-04-15
- mcid: 5.4
- history:
 - 2026-01-10: 48.2 (level 2)
 - 2026-04-15: 56.4 (level 3)
- coaching_goals:
 - id: hba1c-self-monitor
 target: weekly home glucose check
 set_at: 2026-02-01
 achieved: false
 - id: medication-adherence
 target: 95% pill count by next visit
 set_at: 2026-03-15
 achieved: true (2026-04-15)
```

В Rust `PatientMemory` struct (`crates/aim-patient-memory/src/lib.rs:48`):

```rust
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ActivationPoint {
 pub date: NaiveDate,
 pub score: f64,
 pub level: u8, // 1-4 per PAM-13 categorization
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CoachingGoal {
 pub id: String,
 pub target: String,
 pub set_at: NaiveDate,
 pub achieved: Option<NaiveDate>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct PatientMemory {
 //.. existing fields..
 pub activation_history: Vec<ActivationPoint>,
 pub current_activation_score: Option<f64>,
 pub current_activation_level: Option<u8>,
 pub coaching_goals: Vec<CoachingGoal>,
}
```

### 3.2 New Rust crate — `aim-pam`

```rust
// crates/aim-pam/src/lib.rs

pub const MCID: f64 = 5.4;
pub const MDC: f64 = 7.2;

pub struct PamQuestionnaire {
 pub questions: [&'static str; 13],
 pub responses: Vec<u8>, // 1-4 Likert
}

impl PamQuestionnaire {
 pub fn score(&self) -> f64 {
 // Standard PAM-13 scoring per Insignia Health
 }
 pub fn level(score: f64) -> u8 {
 match score {
 s if s < 47.0 => 1,
 s if s < 55.1 => 2,
 s if s < 67.0 => 3,
 _ => 4,
 }
 }
}

pub fn delta_clinically_significant(old: f64, new: f64) -> bool {
 (new - old).abs >= MCID
}

pub fn delta_individually_significant(old: f64, new: f64) -> bool {
 (new - old).abs >= MDC
}
```

CLI binary:
```bash
aim-pam administer --patient Feradze_Maia_1981_12_20 # interactive
aim-pam history --patient Feradze_Maia_1981_12_20
aim-pam delta --patient Feradze_Maia_1981_12_20 # since last
```

### 3.3 New Rust crate — `aim-coach`

Developmental agent для L3. Не diagnose / treat — а coach.

```rust
// crates/aim-coach/src/lib.rs

pub trait CoachingPattern {
 fn elicit_motivation(&self, patient: &PatientMemory) -> String;
 fn set_goal(&self, patient: &PatientMemory, target: &str) -> CoachingGoal;
 fn check_progress(&self, goal: &CoachingGoal) -> ProgressReport;
}

pub struct MotivationalInterviewing { /* OARS technique */ }
pub struct GoalSetting { /* SMART goals */ }
pub struct ActiveListening { /* reflection patterns */ }
```

Calls aim-llm для actual generation; уровень abstraction — паттерны coaching.

### 3.4 New extended law in kernel — `L_AGENCY`

В Python `agents/kernel_legacy.py` (и потом в Rust `aim-kernel/src/lib.rs`):

```python
def evaluate_l_agency(decision: Decision, patient: dict, context: dict) -> tuple[bool, str]:
 """L_AGENCY — preserve patient developmental agency.
 
 Block decisions that:
 - Make recommendations without explanation
 - Skip patient verification for high-stakes actions
 - Replace patient choice with AI default ("AI thinks you should..")
 
 Pass decisions that:
 - Frame as options, not directives
 - Include "verify with your physician" prompts (Qazi mitigation)
 - Use shared decision-making language
 """
 if decision.action_type in ("treatment", "test", "referral"):
 body = decision.payload.get("description", "")
 # Check for directive language without explanation
 if "you should" in body.lower and "because" not in body.lower:
 return False, "L_AGENCY: directive without rationale undermines patient agency"
 # High-stakes need verification prompt
 if decision.payload.get("severity") in ("major", "critical"):
 if "verify with" not in body.lower and "consult" not in body.lower:
 return False, "L_AGENCY: high-stakes recommendation needs verification prompt"
 return True, "L_AGENCY ok"
```

Добавить в `_VERIFIABILITY_ACTIONS` orchestrator pipeline после L_VERIFIABILITY.

### 3.5 New crate — `aim-disagreement` (Blumenthal-Lee 4-zone)

```rust
// crates/aim-disagreement/src/lib.rs

pub enum Zone {
 HumanDominant { human_accuracy: f64, ai_accuracy: f64 },
 AiDominant { human_accuracy: f64, ai_accuracy: f64 },
 HybridReview,
 DisagreementResolution { reason: String },
}

pub fn classify_zone(
 task_class: &str,
 historical_accuracies: &AccuracyTable,
) -> Zone {.. }

pub fn route_decision(zone: Zone, decision: Decision) -> RoutingPlan {
 match zone {
 Zone::HumanDominant {. } => RoutingPlan::DeferToHuman,
 Zone::AiDominant {. } => RoutingPlan::AcceptAiWithLog,
 Zone::HybridReview => RoutingPlan::IndependentReviews,
 Zone::DisagreementResolution {. } => RoutingPlan::EscalateToTeam,
 }
}
```

### 3.6 Phoenix LiveViews

**Новые LiveViews:**
- `pam_live.ex` — PAM-13 questionnaire administration UI
- `coach_live.ex` — coaching dialogue interface (motivational, goal-setting, active listening modes)
- `activation_dashboard.ex` — patient's PAM trajectory chart over time

**Расширение patient_live.ex** (текущий `apps/aim_web/lib/aim_web_web/live/patient_live.ex`):

```elixir
# Add to patient_live.ex render:
<section class="activation">
 <h2>Activation (PAM-13)</h2>
 <p>Current: <%= p.activation_score %> (Level <%= p.activation_level %>)</p>
 <p :if={p.activation_delta}>Last visit: <%= p.activation_delta_sign %><%= p.activation_delta %> 
 <span :if={p.activation_delta >= 5.4}>(MCID exceeded ✓)</span>
 </p>
</section>
```

### 3.7 AI subproject (`AI/ai/*`)

**Новые modules:**

`AI/ai/pam_tracker.py` — longitudinal analysis патентских PAM траекторий:
- Detect trends (improving, stable, declining)
- Flag patients with declining activation despite intervention
- Compare cohorts (medication-only vs medication+coach)

`AI/ai/automation_bias_detector.py` — мониторит сессии:
- Detect "rapid acceptance" patterns (patient accepts AI recommendation < 5 sec)
- Flag когда patient stop asking questions over time
- Report quarterly: "patient X показывает signs of automation bias"

`AI/ai/codesign_log.py` — track co-design moments:
- Patient суggests change to recommended regimen
- Patient declines proposed test, alternative agreed
- Patient identifies error in AI summary

Эти 3 модуля питают hive_queen `distill_candidates` новыми kinds: `activation_drift`, `automation_bias_pattern`, `codesign_innovation`.

### 3.8 Update `aim-experiment-state-machine` для clinical RCT

Paper proposes RCT design (§5.2): LLM behavioral coach RCT с PAM-13 primary outcome. AIM's `aim-experiment-owner` уже умеет manage experiments. Нужно расширить experiment phases для clinical trial:

```
HYPOTHESIS → PROTOCOL_REVIEW → IRB_PENDING → ENROLLING → ACTIVE_INTERVENTION → 
ANALYSIS → MANUSCRIPT → SUBMITTED → PUBLISHED → ARCHIVED
```

Для AIM это позволит run RCT validating L3 как сам AIM-experiment.

---

## 4. Phased plan

### Фаза 1 — Cornerstone documentation (additive, safe) — **начинаю сейчас**

- Update `CONCEPT.md` с L1/L2/L3 framework
- Update `CLAUDE.md` с PAM-13 как primary outcome metric и automation bias mitigation
- Add `PATIENT_AS_PROJECT.md` core doc — манифест framework

### Фаза 2 — Schema extensions (low-risk)

- Extend `aim-patient-memory` с ActivationPoint + CoachingGoal + PAM history
- Extend MEMORY.md template/parser
- Backward compat: existing 6 patients не имеют этих полей → defaults empty

### Фаза 3 — `aim-pam` crate

- New crate, чистый Rust, no external deps
- 13 questions + scoring + level + delta + MCID/MDC checks
- CLI binary
- Phoenix LiveView для administration

### Фаза 4 — `aim-coach` crate

- Coaching patterns (MI, goal-setting, active listening)
- LLM integration через `aim-llm`
- Phoenix `coach_live.ex`

### Фаза 5 — `L_AGENCY` law

- Add к Python `agents/kernel_legacy.py` (legacy stays Python pour ce piece)
- Mirror в Rust `aim-kernel`
- Wire в orchestrator pipeline

### Фаза 6 — `aim-disagreement` (Blumenthal-Lee 4-zone)

- New crate
- Wire через orchestrator pre-emit phase
- Track historical per-task accuracy

### Фаза 7 — AI subproject extensions

- `pam_tracker.py`, `automation_bias_detector.py`, `codesign_log.py`
- New hive_queen distill candidate kinds
- Weekly digest section: activation trajectories

### Фаза 8 — Run actual RCT (long-term)

- Use `aim-experiment-owner` для tracking
- LLM behavioral coach как intervention arm
- PAM-13 как primary outcome
- Validates L3

---

## 5. Что я делаю сейчас (overnight, безопасно)

**Только additive documentation:**
1. Update `CONCEPT.md` AIM — секция "Patient as Developmental Project (L1/L2/L3)"
2. Create `PATIENT_AS_PROJECT.md` core manifest
3. Update `CLAUDE.md` AIM — добавить L_AGENCY mention в HARD CONSTRAINT секцию + PAM-13 как primary outcome target
4. Create `MANUSCRIPT_PATIENT_AS_PROJECT_2026-05-07.md` — full text статьи как reference в repo

**НЕ трогаю автономно** (требуют твоего решения утром):
- Schema migration существующих 6 пациентов
- New crates `aim-pam` / `aim-coach` / `aim-disagreement` (significant work)
- Modifications kernel logic (`L_AGENCY`)
- Modifications orchestrator pipeline
- Phoenix LiveView additions

---

## 6. Ключевые вопросы для тебя утром

1. **Эта статья — твоя?** (рукопись ready for submission, target Nature Med). Если да — она задаёт research direction. AIM становится **infrastructure для validating L3** через RCT. Это меняет всё.

2. **Готов ли к 8-фазному плану?** Phases 2-7 = ~8-12 weeks if I stay autonomous. Phase 8 (real RCT) = year+, requires IRB, real patients.

3. **Phases 1 (docs only) start tonight?** Я начну Phase 1 сразу сейчас (additive only, безопасно).

4. **L_AGENCY law** — окей добавить как 4-й extended law (после L_PRIVACY, L_CONSENT, L_VERIFIABILITY)? Это материальное изменение kernel поведения.

5. **PAM-13 как primary outcome AIM** — официально записать в CLAUDE.md? Это меняет цель проекта с "medical AI assistant" → "infrastructure for measuring/improving patient activation through AI".

6. **Co-design tooling** — кто пациенты для co-design в pilot? Текущие 6 в `Patients/`?

---

## 7. Логические следствия

**Если статья принята как cornerstone:**

- AIM перестаёт быть "AI clinical decision support" → становится **"AI for patient developmental agency"**
- Главный outcome metric: **PAM-13 trajectory**, не "physician satisfaction"
- L0-L3 + L_PRIVACY/CONSENT/VERIFIABILITY/AGENCY = **полный safety framework для L3**
- Co-design — не feature, **architectural principle**
- Phoenix frontend становится primary patient touchpoint (patient → AI direct, через Phoenix LiveView)
- Hive queen Phase 3 (multi-clinic federation) — vehicle для multi-site validation L3

**Это переориентация всего проекта, не просто добавление features.**

---

**Я начинаю Phase 1 (docs) сейчас. Утром проверишь — если ОК, продолжу phases 2-7 в overnight'ах. Phase 8 (real RCT) — это твоё решение в комитете, не моё.**
