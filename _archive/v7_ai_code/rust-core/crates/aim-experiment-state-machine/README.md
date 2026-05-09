# aim-experiment-state-machine

Robotic / instrumented experiment phases. AIM is mission-control; rig driver is external (Claude Code in headless mode, custom Rust binary, or anything that speaks MCP).

## Phases

```
COMMISSIONING — hardware assembly, firmware install, integration tests
CALIBRATING — pre-run calibration cycles, sensor zero, alignment
RUNNING — live data collection, AI making routine decisions
DATA_PROCESSING — run finished, analysis / QA / packaging
REPORTED — preprint / paper / dataset published
ARCHIVED — closed, rig may be reused for next experiment
```

## Allowed transitions

```
COMMISSIONING → CALIBRATING, ARCHIVED
CALIBRATING → COMMISSIONING (regression), RUNNING, ARCHIVED
RUNNING → DATA_PROCESSING, CALIBRATING (recalibrate), ARCHIVED
DATA_PROCESSING → REPORTED, RUNNING (more data needed), ARCHIVED
REPORTED → ARCHIVED
ARCHIVED → (terminal)
```

## Public API

- `Phase` enum (Commissioning / Calibrating / Running / DataProcessing / Reported / Archived)
- `legal_moves(src)` / `is_legal(src, dst)`
- `next_actions(phase)` — operations advisory
- `StateMachine::transition` + `history` + `phase_advisory`
- Audit log: `~/.cache/aim/experiment_phase_history.jsonl`

## Phase

B (HW1, 2026-05-06).
