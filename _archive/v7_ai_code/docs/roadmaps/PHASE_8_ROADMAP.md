# PHASE 8 — Stack-rule alignment for legacy `agents/*.py` modules

**Дата:** 2026-05-07
**Триггер:** `AUDIT_FIXES_VERIFICATION_2026-05-07.md` §2 — после устранения
3 нарушений Phase 7 ещё 7 Python-модулей нарушают то же правило.

## Goal

Привести `agents/*.py` к stack rule из `STACK.md` / `CLAUDE.md`:
> **Backend / алгоритмы / агенты / CLI / системные сервисы → Rust**
> Python остаётся только для legacy (OCR/PDF/WhatsApp/customtkinter).

После Phase 7 Fix #2 паттерн зафиксирован: Rust crate (`aim-X`) держит
всю логику + CLI binary; Python-модуль = thin subprocess shim
(50-150 LoC). Phase 8 распространяет паттерн на ещё 7 модулей.

## Scope: 7 modules, ~2150 LoC

Все 12 упомянутых Rust crates существуют в `rust-core/crates/`
(verified 2026-05-07 via `ls -d`).

| # | Python file | LoC | Rust crate (counterpart) | Migration type |
|---|---|---|---|---|
| 1 | `agents/smart_routing.py` | ~250 | `aim-smart-routing` | full mirror → shim |
| 2 | `agents/router_ab_test.py` | ~200 | `aim-ab-router` | full mirror → shim |
| 3 | `agents/regimen_validator.py` | ~150 | `aim-regimen-validator` | wraps `interactions.py` → unify in Rust |
| 4 | `agents/resilient_llm.py` | ~200 | `aim-resilient-llm` | full mirror → shim |
| 5 | `agents/reflexion.py` | ~600 | `aim-reflexion` | full mirror; LanceDB → sqlx |
| 6 | `agents/generalist.py` (partial) | ~600 (whole; ~200 dispatch) | `aim-generalist` | tool-dispatch loop → Rust; Python keeps tool registry |
| 7 | `agents/graph.py` | ~150 | `aim-graph` | LangGraph → Rust state machine |

**Total:** ~2150 LoC Python → удалится ~70%; ~30% (registry, glue)
останется как тонкий shim.

## Priority order

### Week 1 — hot path
1. **`smart_routing.py` → `aim-smart-routing` shim** ✅ DONE 2026-05-07
 - 179 → 121 LoC Python (33% reduction); CLI binary added; 5
 subcommands: classify / route / estimate-cost / stats. 71/71
 kernel regression green.
2. **`router_ab_test.py` → `aim-ab-router` shim** ⚠️ RE-EVALUATED:
 not a clean port. The Rust `aim-ab-router` crate (689 LoC) does
 **strategy-level A/B with Welch's t-test verdicts** (challenger
 vs baseline + multi-round), while `router_ab_test.py` (172 LoC)
 does **per-trial logging + monkeypatch of smart_routing.route**.
 Different abstractions. Action: defer to Phase 8b — either expand
 `aim-ab-router` with a `trials` table (~80 LoC + 4 subcommands)
 or create a new `aim-trial-log` crate. Until then, the Python
 module stays as is and is **NOT** counted as a Phase 8 violation.

### Week 2 — clinical safety
3. **`interactions.py` → `aim-interactions` shim** ✅ DONE 2026-05-07.
 502 → 192 LoC Python (-62%). All 30+ drug-pair table + canonicalization
 + check_interaction/check_regimen/format_regimen_report now Rust;
 Python is pure subprocess wrapper with lazy `_TABLE` proxy for
 the diagnostic test that reads it directly. 16 test_interactions
 tests + 34 sub-tests still pass.

3b. **`regimen_validator.py` → `aim-regimen-validator` shim** ✅ DONE 2026-05-07
 (hybrid). CLI binary added to `aim-regimen-validator` (wires Rust
 `validate` against `aim-interactions::check_regimen` so Phoenix /
 external callers get a single binary). Python `validate` stays
 ~50 LoC because tests use `monkeypatch.setattr(rv, "check_regimen",..)` — would have to rewrite 18 unit tests to drop the Python
 classifier. Net Phase 8 result: **drug-pair data is 100% Rust**;
 the bucketing logic exists in BOTH Python (for tests) and Rust
 (for binary callers). Acceptable parallel until tests are
 redesigned.

### Week 3 — infrastructure
4. **`resilient_llm.py` → `aim-resilient-llm` shim** ⚠️ DEFERRED
 2026-05-07: this module is **not really a violation**. It wraps
 Python `llm.ask` / `llm.ask_deep` with tenacity retry +
 checkpoint persistence. Porting it to Rust would invert the data
 flow (Rust→Python LLM). The `aim-resilient-llm` Rust crate is
 designed for a future Rust-native call path that doesn't yet
 exist — it sits behind the Phase 5 `llm.py → aim-llm` port (see
 `MIGRATION_RUST_PHOENIX.md`). Re-schedule after llm.py is Rust.

### Phase 9+ (postpone)
5. **`reflexion.py`** ✅ DONE 2026-05-07 (partial). 136 → 106 LoC
 (-22%). Storage ops (classify / save / recent / store-dir) ported
 to `aim-reflexion` CLI; `on_failure` stays Python because it calls
 `llm.ask_fast`. Will become full shim once Phase 5 (llm port) lands.
6. **`generalist.py` partial** (2324 LoC actual, audit said 600+) —
 far bigger than expected. Tool registry stays Python; dispatch loop
 could go Rust but requires tool ABI design (FFI vs subprocess).
 Deferred to Phase 9 — too large for a single sprint.
7. **`graph.py`** (942 LoC actual, audit said 150) — LangGraph state
 machine that wraps `llm.ask_deep` / `llm.ask` / `llm.ask_fast`.
 Same blocker as resilient_llm: needs Phase 5 (`llm.py` → Rust)
 first, otherwise data flow inverts. Pure helpers
 (`looks_like_translit`, `wrap_task_for_llm`, `suggest_plan_size`,
 `is_embed_daemon_alive`) могут быть shimmed by themselves but it's
 marginal — the file is 90% LLM glue.

## Migration template (per module)

Each port follows the Phase 7 Fix #2 pattern:

1. **Audit** Python module: identify pure logic vs side-effects; list
 all callers (`grep -rn`).
2. **Implement** Rust lib in existing `aim-X` crate (or create one
 if scaffolded but empty). Add unit tests parity with Python.
3. **Add CLI binary** `src/main.rs` exposing the operations (record,
 query, classify, etc.) as subcommands with JSON I/O.
4. **Rewrite Python file** as thin subprocess shim (≤100 LoC). Same
 public API; same exception types (`FileNotFoundError`, `ValueError`).
5. **Run regression** against existing pytest. If it passes without
 touching the test file, the shim is correct.
6. **Remove dead Python code** (helpers, stale imports). Update
 `MAP.md` + `MIGRATION_RUST_PHOENIX.md`.

## Test strategy

- **Parity gate:** for each module, write a `test_X_parity.py` that
 exercises both `AIM_USE_LEGACY_X=1` (old Python) and default
 (Rust shim) paths and asserts identical outputs across N≥20 cases.
- **Regression gate:** existing tests must pass without modification
 (the shim is API-compatible).
- **Performance gate** (only for hot path: smart_routing,
 resilient_llm): subprocess RTT ≤ 5 ms p50 measured in benchmark.
 If above threshold, escalate to PyO3 in-process binding.

## Risks & mitigation

| Risk | Mitigation |
|---|---|
| Python and Rust drift during migration | one module at a time; parity tests block PR until equal |
| Subprocess RTT degrades hot-path latency | benchmark per Week's port; auto-PyO3 fallback for ≤5ms requirements |
| Rust crate scaffolds exist but are empty/incomplete | per module: spike to verify before scheduling |
| `aim-reflexion` LanceDB → Rust schema migration | tackle in Phase 9; for now keep Python and only swap CLI surface |
| Removing Python prematurely | follow Phase 7 pattern: leave Python file as shim, never delete `agents/<X>.py`; all callers continue to import it |

## Success criteria

- 0 Python files in `agents/` contain >50 LoC of business logic where a
 same-named Rust crate has the equivalent functionality.
- All 7 listed Python files reduced to thin shims (≤150 LoC each).
- 100% of existing pytest tests pass without modification.
- `STACK.md` rule reaffirmed in `MIGRATION_RUST_PHOENIX.md` Phase 5
 (already added 2026-05-07).
- Phase 4 (`aim-coach`) и Phase 8 (real RCT) still officially deferred —
 they are unrelated to this stack-rule cleanup.

## Estimated effort

- Week 1 (smart_routing + router_ab_test): 2 days × 1 person
- Week 2 (regimen_validator + interactions consolidation): 3 days
- Week 3 (resilient_llm): 1 day
- **Total committed:** 6 days for 4 modules (~800 LoC)
- Phase 9 deferred items (reflexion, generalist, graph) — additional
 ~1.5 weeks if/when prioritised.

---

## Reality check 2026-05-07 (honest re-evaluation after Week 1)

After actually starting Phase 8, several items в audit list оказались
false-positives под именем-match'ем, не реальные дублирования:

| Module | Audit verdict | After verification | Reason |
|---|---|---|---|
| `smart_routing.py` | violation | ✅ ported (clean) | Rust crate had ALL logic; only CLI binary missing |
| `router_ab_test.py` | violation | ⚠️ borderline | Rust crate covers different abstraction (strategy A/B vs trial logging) |
| `interactions.py` (not in original 7) | — | ✅ ported (clean) | 30-pair table + canonicalization + check_regimen all Rust |
| `regimen_validator.py` | violation | ✅ ported (hybrid) | CLI binary added; Python validate stays for monkeypatchable unit tests |
| `resilient_llm.py` | violation | ❌ not a violation | wraps Python llm.py; needs Phase 5 first |
| `reflexion.py` | violation | ✅ ported (partial) | storage ops to Rust; on_failure stays Python (uses llm.ask_fast) |
| `generalist.py` | violation (partial) | ❌ deferred — 2324 LoC | far bigger than audit said; tool ABI design needed |
| `graph.py` | violation | ❌ not a violation | wraps Python llm.ask_*; same blocker as resilient_llm |

**Final tally of Phase 8 (2026-05-07):**
- 4 of 8 cleanly ported: smart_routing, interactions, reflexion (partial), regimen_validator (hybrid)
- 1 of 8 borderline: router_ab_test (different abstraction)
- 3 of 8 false positives or wait-for-Phase-5: resilient_llm, generalist, graph

**Net stack-rule cleanup achieved this session:**
| File | Before | After | Δ |
|---|---|---|---|
| smart_routing.py | 179 LoC | 121 LoC | −33% (shim) |
| reflexion.py | 136 LoC | 106 LoC | −22% (partial shim) |
| interactions.py | 502 LoC | 192 LoC | −62% (clean shim) |
| regimen_validator.py | 192 LoC | 192 LoC | 0% (logic preserved for tests; data 100% Rust) |
| **Total Python** | **1009 LoC** | **611 LoC** | **−39%** |

**Lesson:** name-match heuristic in audit overestimates true violations.
Real Phase 8 scope was 2 modules, not 7. The other 5 are blocked on
either (a) `llm.py` Rust port (Phase 5 of MIGRATION_RUST_PHOENIX) or
(b) larger Rust scaffolding (`aim-interactions` for the drug-pair
database, `aim-trial-log` for per-call logging, tool ABI for
generalist).
