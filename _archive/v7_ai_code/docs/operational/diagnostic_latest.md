# AIM full-system diagnostic

## Inventory

| Metric | Count |
|---|---|
| core_md | 345 |
| top_level_py | 11 |
| agents_py | 128 |
| ai_ai_py | 34 |
| tests_py | 85 |
| ai_tests_py | 32 |
| scripts_files | 59 |
| rust_crates | 203 |
| rust_files | 358 |
| phoenix_apps | 4 |
| phoenix_ex | 75 |
| docs_md | 83 |

## Summary: 1 P0 / 2 P1 / 1 P2 findings

## 🔴 P0 — Blocking

### `subproject_orphan` — Subproject `AI/queen_deploy/` not referenced in core

  Exists on disk; absent from MAP.md / CLAUDE.md / CONCEPT.md. Add as Internal subproject OR archive.

**Paths** (1):
- `AI/queen_deploy`

## 🟡 P1 — Important

### `duplicate` — Identical file copies: 2

  docs/AIM_FS/SPEC.v11.md === docs/AIM_FS/SPEC_LATEST.md

**Paths** (2):
- `docs/AIM_FS/SPEC.v11.md`
- `docs/AIM_FS/SPEC_LATEST.md`

### `rust_no_tests` — Rust crates without #[test]: 1

  Production-critical crates need at least 1 test. Excused: aim-common, aim-kernel-py.
    aim-cohort

**Paths** (1):
- `rust-core/crates/aim-cohort`

## 🟢 P2 — Cosmetic

### `git_hygiene` — Build cruft on disk: 7 dirs

  Run: find . -name __pycache__ -type d | xargs rm -rf; find . -name '*.egg-info' -type d | xargs rm -rf

**Paths** (7):
- `__pycache__`
- `tests/__pycache__`
- `tools/__pycache__`
- `AI/ai/__pycache__`
- `AI/tests/__pycache__`
- `agents/__pycache__`
- `agents/generalist_pkg/__pycache__`
