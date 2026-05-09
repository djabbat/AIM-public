# aim-experiment-owner

Experiment as a managed entity — sister to `aim-project-owner` and `aim-patient-owner`.

## YAML schema

`USER/experiments/<name>.yaml`:

```yaml
name: E0
canonical: /home/oem/Desktop/PhD/E0
phase: COMMISSIONING
goals:
 - Stabilise rig for 6-month autonomous CDATA imaging
milestones:
 - id: hardware-ordering-phase1
 deadline: 2026-05-03
 status: blocked
 blockers: ["Tsomaia phase 1 component selection"]
 criticality: high
awaiting:
 - topic: Tsomaia ordering decision
 since: 2026-04-27
 expected_by: 2026-05-03
journal_paths:
 - "~/.cache/aim/microscopy/sessions/"
daily_checks:
 - "Tsomaia phase 1 ordering status"
```

## Public API

- `experiments_dir` — `$AIM_EXPERIMENTS_DIR` override
- `ExperimentOwner::new(root)` / `from_env`
- `list_experiments` / `load(name)` / `morning_brief(name, today)` / `all_briefs(today)`
- impl `Lifecycle`

## CLI binary

```
aim-experiment-owner list
aim-experiment-owner brief <name> [<YYYY-MM-DD>]
aim-experiment-owner all [<YYYY-MM-DD>]
aim-experiment-owner phase <name>
```

Used by Python `scripts/daily_brief.py` and `scripts/weekly_project_digest.py` via subprocess.

## Pilot configs

- `USER/experiments/E0.yaml` — PhD/E0 commissioning
- `USER/experiments/AutomatedMicroscopy.yaml` — CDATA Phase A imaging rig

## Phase

B (HW1, 2026-05-06).
