# AIM_FS ↔ aim-doctor / clinical agents — integration guide

**Дата:** 2026-05-08
**Статус:** Round 21 — pattern documented, validators in place
**Goal:** clinical AI agents (aim-doctor, generalist with delegate_doctor)
must NEVER write to `Patients/<key>/` directly. Every diagnosis or recipe
goes through AIM_FS `propose()` → doctor reviews in `/inbox` → approve.

---

## 1. Что меняется

### Раньше (do not do)

```rust
// aim-doctor's recipe agent writes file directly:
let recipe = format!("# Treatment plan...\n");
fs::write(format!("Patients/{patient_key}/recipes/{ts}.md"), recipe)?;
```

Issues:
- No approval loop — AI's recommendation lands in patient record without
  doctor having seen it
- No provenance — who/when/with what confidence
- No conflict detection — duplicate recipes compound silently
- No graph link to underlying diagnosis

### Теперь (canonical)

```rust
use aim_fs::{NewEntity, Source, ApprovalPolicy};

let new = NewEntity {
    schema: "recipe_v1".into(),                      // strict validator
    schema_version: 1,
    title: Some("Vitamin D 5000 IU/day × 8 weeks".into()),
    body: Some(format!(
        "Препарат: Cholecalciferol\n\
         Доза: 5000 IU\n\
         Частота: 1 раз в день\n\
         Длительность: 8 недель\n\
         \n\
         Обоснование: 25(OH)D = 18 ng/mL (deficiency).  PMID 32679784.\n\
         Контроль: 25(OH)D через 8 недель."
    )),
    source: Source::System,                          // AI-generated
    user_id: doctor_id.into(),
    llm_model: Some("deepseek-reasoner".into()),
    confidence: Some(0.85),
    requires_verification: true,                     // doctor must check
    scope_patient_ids: vec![patient_pseudonym],      // PII via pseudonym only
    scope_global: false,
    tags: vec!["recipe".into(), "vitamin_d".into()],
    initial_links: vec![InitialLink {
        target_id: source_diagnosis_id,              // link to dx
        link_type: LinkType::DependsOn,
    }],
    decay_ttl_days: Some(56),                        // 8 weeks
    decay_on_expire: Some("deprecate".into()),
    /* ...defaults... */
};

let outcome = aim_fs.propose(
    doctor_id,
    new,
    Some("AI generalist suggestion based on lab review"),
    None,
    &policy_with_recipe_in_require_approval_for(),
)?;

// recipe_v1 is in `require_approval_for` → outcome.entity_status = Pending.
// Доктор увидит в /inbox и approve / reject.
```

---

## 2. Strict schema validators (in `aim-fs/src/schemas.rs`)

### `recipe_v1`

| Rule | Reason |
|------|--------|
| `title` non-empty | Index search relies on it |
| `scope.patient_ids` non-empty | Otherwise it's not a recipe |
| body contains `dose` / `доза` / `Доза` | Audit-trace explicit dosing |

### `diagnosis_v1`

| Rule | Reason |
|------|--------|
| `title` non-empty | |
| `scope.patient_ids` non-empty | |
| body contains `Differential` / `Дифдиагноз` / `DDx` / `Working diagnosis` | Forces a structured DDx, not a one-liner |
| `confidence` is Some(_) | AI-derived diagnoses MUST quantify uncertainty |

Both schemas are NOT in default auto-approve policy — they always end up
in `/inbox` for doctor review.

---

## 3. ApprovalPolicy для clinical agents

```rust
let clinical_policy = ApprovalPolicy {
    auto_approve_user_commands: false,           // even doctor commands need review
    auto_approve_observational_with_confidence_above: 1.0,  // never auto-approve AI dx
    auto_approve_service_events: true,           // sweeper / index maintenance OK
    require_approval_for: vec![
        "recipe_v1".into(),
        "diagnosis_v1".into(),
        "lab_interpretation_v1".into(),
        "referral_v1".into(),
    ],
    max_inactivity_days: 7,                      // shorter window for clinical
};
```

Phoenix InboxLive auto-refreshes via PubSub → doctor sees the new
proposal within 1-2 seconds of the AI agent calling propose().

---

## 4. Linkage pattern

Чтобы граф был полезен в дифдиагностике, recipes ↔ diagnoses ↔ labs
связываются через `InitialLink`:

```text
patient_anamnesis_v1 (initial visit)
        ↑ depends_on
diagnosis_v1 (working dx)
        ↑ depends_on
recipe_v1 (treatment plan)
        ↑ refines
recipe_v2 (revised dose after follow-up)
```

При propose v2 c `link_type=Supersedes` старый recipe_v1 автоматически
становится `superseded` (см. SPEC §6).  Doctor видит в /fs/entity/<id>
полную цепь решений.

---

## 5. Existing aim-doctor → AIM_FS bridge points

Generalist tools — already in place:
- `memory_save_aim_fs` — generic propose (use schema=recipe_v1 etc.)
- `memory_recall_aim_fs` — FTS5 BM25 search before generating
- `inbox_pending_aim_fs` — agent can see what's awaiting human review
- `inbox_approve_aim_fs` / `inbox_reject_aim_fs` — agent can act on
  another agent's proposals (rare; usually human)

Per `aim-generalist/src/tools/aim_fs_tools.rs`. Wire any agent
(aim-doctor / aim-coach / aim-pam) to these tools with schema-specific
adapters; no direct file writes.

---

## 6. Migration: switching aim-doctor's recipe agent

Mechanical change in (e.g.) `aim-doctor/src/recipe.rs`:

```diff
-fs::write(format!("Patients/{key}/recipes/{ts}.md"), &recipe_md)?;
+let outcome = self.aim_fs.propose(
+    &doctor_id,
+    NewEntity { schema: "recipe_v1".into(), /* ... */ },
+    Some(&rationale),
+    None,
+    &CLINICAL_POLICY,
+)?;
+self.notify_inbox(outcome.proposal_id);
```

Then in `Phoenix InboxLive`, doctor:
1. Sees the proposal с rationale + confidence + linked diagnosis
2. Edits if needed (Phase 2 — currently approve/reject only)
3. Approves → entity becomes `active`, stays in DB scoped to patient
4. Telegram bridge `/inbox` mirror works the same

---

## 7. Audit trail

Every `recipe_v1` propose produces 2 events:
1. `created` (entity_id, schema=recipe_v1)
2. `proposed` (proposal_id, rationale)

After approve:
3. `approved` (approver_user_id, ts)

These render in `/fs/audit` LiveView with colour-coded badges, so
clinical workflow review at end of day shows every AI suggestion the
doctor saw + their decision.

GDPR-friendly: PII in body is encrypted (Phase B.0.5) when the entity
is scoped to a `_patient_pseudonym` directory; metadata (title /
description / scope IDs) remains readable for index purposes.
