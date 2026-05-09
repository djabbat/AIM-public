# aim-patient-owner

Patient as a managed entity — sister to `aim-project-owner`. Loads `Patients/<id>/MEMORY.md` via `aim-patient-memory`, exposes `morning_brief` + hot milestones + overdue follow-ups, and implements `aim_lifecycle::Lifecycle`.

## YAML / Markdown schema

`Patients/<id>/MEMORY.md` is the canonical store. Phase A (2026-05-06) added three sections to the existing schema:

```markdown
## Phase
ACTIVE_TREATMENT

## Milestones
- thyroid-recheck (2026-08-15, medium): pending — TSH result

## Awaiting
- repeat lab K+ (since 2026-05-06, expected 2026-05-13)
```

Pre-existing sections (Demographics / Allergies / Medications / Conditions / History / Known unknowns / Derived) are unchanged. Default `phase` = `INTAKE` for legacy patients without the section.

## Public API

- `patients_dir` — `$AIM_PATIENTS_DIR` override → `Patients/`
- `PatientOwner::new(root)` / `from_env`
- `list_patients` — sorted folder names with `MEMORY.md`
- `load(id)` → `PatientMemory`
- `morning_brief(id, today)` → Telegram-ready string
- `hot_milestones(id, today)` / `overdue_followups(id, today)`
- `all_briefs(today)` — concat for every patient
- impl `Lifecycle`

## CLI binary

```
aim-patient-owner list
aim-patient-owner brief <id> [<YYYY-MM-DD>]
aim-patient-owner all [<YYYY-MM-DD>]
aim-patient-owner phase <id>
```

Used by Python `scripts/daily_brief.py` via subprocess.

## Phase

A (HW1, 2026-05-06).
