# aim-patient-state-machine

Patient phase transitions. Mirror to `aim-project-state-machine` with clinical vocabulary.

## Phases

```
INTAKE — first contact, demographics + chief complaint
DIAGNOSTIC_WORKUP — labs / imaging being collected
ACTIVE_TREATMENT — intervention in progress
MONITORING — post-intervention observation
STABLE — periodic surveillance, no active intervention
CLOSED — episode ended (discharged / loss / transfer)
```

## Allowed transitions

```
INTAKE → DIAGNOSTIC_WORKUP, MONITORING, CLOSED
DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT, MONITORING, CLOSED
ACTIVE_TREATMENT → MONITORING, CLOSED
MONITORING → ACTIVE_TREATMENT, STABLE, CLOSED
STABLE → MONITORING (relapse), CLOSED
CLOSED → INTAKE (re-engagement / new episode)
```

`CLOSED → INTAKE` is the re-engagement path: the same patient folder hosts a new episode, history accumulates in `AI_LOG.md`, phase audit in `~/.cache/aim/patient_phase_history.jsonl`.

## Public API

- `Phase` enum + `parse` + `as_str` + `all`
- `legal_moves(src) -> Vec<Phase>` (sorted)
- `is_legal(src, dst) -> bool`
- `next_actions(phase) -> Vec<&'static str>` (clinical advisory)
- `StateMachine::transition(patient_id, src, dst, reason, actor)` — validates + audits to JSONL
- `StateMachine::history(patient_id?)` — replay
- `StateMachine::phase_advisory(phase)` — Telegram-ready string

## Phase

A (HW1, 2026-05-06).
