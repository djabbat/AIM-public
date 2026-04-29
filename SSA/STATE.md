# STATE.md — SSA (Systemic Syndrome Analysis) Kernel

## Status
- **Phase**: 0 (kernel bootstrap)
- **Created**: 2026-04-29
- **Owner**: Dr. Jaba Tkemaladze (CEO GLA)
- **Path**: `~/Desktop/AIM/SSA/`
- **Stack**: Rust (axum) backend + Phoenix LiveView frontend; LLM bridge via `~/Desktop/AIM/llm.py`
- **Connection**: SSA → ranked syndrome list → DiffDiagnosis (HTTP)

## Active TODOs

### Core data sources (`sources/`)
- [x] 28‑parameter list documented (CBC + ESR + 3 derivatives)
- [ ] Verify completeness: all 28 parameters covered by reference ranges JSON
- [ ] Cross‑check optional parameters (RET-He, PDW, PCT) against ICSH‑2014 standards

### Pattern definitions (`patterns/`)
- [x] 15 paired patterns documented
- [x] 15 triple/syndromal patterns documented
- [ ] Verify all 30 patterns have explicit zonal mapping in `patterns.json`
- [ ] Add edge‑case patterns (e.g. EDTA‑dependent pseudo‑thrombocytopenia, cold agglutinin artefact)

### Reference ranges (`ranges.json`)
- [ ] Formalise ICSH‑2014 reference intervals for all 28 parameters (including paediatric/geriatric/sex‑specific)
- [ ] Include clinical critical thresholds (L2/H2 zones) from BCSH/WHO
- [ ] Store JSON under `backend/data/ranges.json`

### Pattern mapping (`patterns.json`)
- [ ] Formalise all 30 patterns as JSON objects with:
  - zonal signature (e.g. `{"HGB": "L1|L2", "MCV": "L0|L1", …}`)
  - rule priority (higher = more specific)
  - differential diagnosis suggestions (list of strings)
- [ ] Validate with 10 hand‑crafted test cases (normal, microcytic, macrocytic, pancytopenia, etc.)

### Backend (Rust + axum)
- [ ] `cargo init` + `axum` scaffold (endpoints: `/digitize`, `/match`)
- [ ] Implement `digitize()`: given 28 float values → zone vector (5‑zone encoding)
- [ ] Implement `match_patterns()`: zone vector → ranked list of patterns (with score)
- [ ] Write 10 unit tests (5 normal/abnormal CBCs, 5 edge cases: extreme values, missing parameters)
- [ ] Expose REST API: `POST /api/ssa/analyze` (input: JSON CBC; output: ranked syndrome list + confidence)

### Frontend (Phoenix LiveView)
- [ ] `mix phx.new .` in `frontend/` (or integrate with existing DiffDiagnosis umbrella)
- [ ] LiveView route: `/cbc` — form with 28 fields + submit
- [ ] Display ranked syndrome list with expandable differentials

### Validation
- [ ] Build gold‑set: 200 CBCs with expert‑labelled syndromes (ground truth)
- [ ] Compute top‑1/top‑3 accuracy, calibration (ECE), red‑flag‑miss rate
- [ ] Compare with human performance (Cabitza 2021, Goh 2024)

### Integration
- [ ] SSA → DiffDiagnosis HTTP call: `POST /api/diff/input` with syndrome vector
- [ ] Wire SSA output as pre‑filled **presenting syndrome** in DiffDiagnosis UI

## Decision Log
| Date | Decision |
|------|----------|
| 2026-04-29 | Project created under `AIM/SSA`. 5‑zone discretisation adopted as canonical. |
| 2026-04-29 | 28 parameters fixed: 24 CBC + ESR + 3 derivative (NLR, PLR, SII/RDW‑PLT). |
| 2026-04-29 | Stack locked to Rust + Phoenix (mirroring DiffDiagnosis). LLM only through `llm.py`. |

## Что НЕ делать
- ❌ Не заменять ICSH‑2014 референсы LLM‑генерацией — все диапазоны строго из стандартов.
- ❌ Не дублировать функции DiffDiagnosis — SSA только пред‑обработка CBC (зонная разметка + синдромальная группировка).
- ❌ Не упрощать 5 зон до 3 — это потеря клинической информации (критические L2/H2).
- ❌ Не вводить более 28 параметров (например, не считать гистограммы — только численные результаты анализатора).

## Milestones (✅)
*(ни одного достигнутого — всё в Active TODOs)*

## Startup checklist
1. [ ] Прочитать CONCEPT.md, STATE.md, OPEN_PROBLEMS.md.
2. [ ] `cargo check` — проходит ли компиляция Rust‑бэкенда?
3. [ ] `mix compile` — проходит ли компиляция Phoenix‑фронтенда?
4. [ ] 9 core .md файлов на месте (CONCEPT, STATE, OPEN_PROBLEMS, и по каждому из 6 разделов мета‑аналитики).
5. [ ] `ranges.json` и `patterns.json` существуют в `backend/data/`.
6. [ ] `gold_set.json` (200 CBC) существует в `validation/`.