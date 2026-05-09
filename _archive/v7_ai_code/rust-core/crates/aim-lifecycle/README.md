# aim-lifecycle

Object-safe trait that any managed entity (project / patient / experiment) implements. Storage stays separate per type — only the API converges so consumers like the daily brief can iterate them uniformly.

## Public API

- `EntityKind` — enum (Project / Patient / Experiment) + emoji + str
- `HotItem` — time-anchored item (milestone or awaiting follow-up)
- `LifecycleError` — unified error type
- `Lifecycle` — object-safe trait (works in `Box<dyn Lifecycle>`)
- `render_unified_brief(&[Box<dyn Lifecycle>], today)` — multi-entity brief

## Implementations

- `aim-project-owner` — projects (DRAFT → … → PUBLISHED)
- `aim-patient-owner` — patients (INTAKE → … → CLOSED + re-engagement)
- `aim-experiment-owner` — experiments (COMMISSIONING → … → ARCHIVED)

## Phase

A (HW1, 2026-05-06).
