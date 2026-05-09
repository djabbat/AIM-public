# Phase 9 — `AI/ai/*.py` → `aim-ai-*` Rust shims

**Дата:** 2026-05-07
**Триггер:** `AUDIT_DEEP_2026-05-07.md` §6.4 — 14 806 LoC Python в `AI/ai/`
параллельных существующим 30 `aim-ai-*` Rust crates. Самый крупный
остаточный stack-rule violation.

## Goal

Привести `AI/ai/` к stack rule (per `STACK.md` / `CLAUDE.md`): новое =
Rust + Phoenix; Python = legacy/shim. После Phase 8 паттерн зафиксирован
(`agents/smart_routing.py`, `reflexion.py`, `interactions.py`,
`regimen_validator.py`) — каждый Python модуль становится thin
subprocess shim над Rust binary.

Phase 9 распространяет этот паттерн на 35 модулей `AI/ai/*.py`.

## Inventory + dependency graph

35 модулей, 14 806 LoC. Dependency graph (по lazy imports
`from AI.ai.X import..`):

```
diagnostic_ledger ←──┬── compliance_promoter
 ├── safety_gate
 ├── self_modify
 ├── prompt_impact
 ├── case_archiver ────┬── morning_brief
 ├── meta_evaluator ←──┴── stable_run
 ├── regression_detector ←── regression_alert
 └── doctor ←──┬── explainer
 └── morning_brief

meta_evaluator ←─── diagnostic_ledger (циклический — оба читают друг друга)

prompt_versions ←──┬── prompt_impact
 ├── doctor (через health_score)
 ├── backup
 └── hive_telemetry

run_self_diagnostic ←──┬── stable_run
 ├── backup
 ├── finding_validator
 └── doctor

dashboard — depends on 11 others (terminal node)
auto_sweep — depends on 7 others (terminal node)
```

**Foundation modules** (depended on by ≥3 others):
- `diagnostic_ledger.py` (232 LoC) — SQLite ledger CRUD
- `meta_evaluator.py` (226 LoC) — peer-review scoring
- `prompt_versions.py` (169 LoC) — prompt change tracking
- `regression_detector.py` (156 LoC)
- `run_self_diagnostic.py`
- `health_score.py`

**Leaf modules** (no dependents in `AI/ai/`):
- `regression_alert.py` (77 LoC)
- `dashboard.py` (170 LoC) — depends on 11 others, but no one depends on it
- `auto_sweep.py` (188 LoC)
- `morning_brief.py` (156 LoC)
- `case_validator.py` · `findings_to_evals.py` · `skill_standard.py`
- and many others — total ~25 leaves

## Migration order

### Tier 1 (Week 1) — foundation ✅ DONE 2026-05-07
1. ✅ **`diagnostic_ledger.py`** → `aim-ai-ledger` shim. CLI binary added (record/recent/all/trend/summary/prune-phantom/path). Python 232 LoC stays as backward-compat shim; Row dataclass preserved. 83 callers regression: ALL 3 BLOCKS PASS.
2. ✅ **`prompt_versions.py`** → `aim-ai-prompt-versions` shim. CLI binary added (prompt-path/db-path/fingerprint/record-current/history/drift-since-last/summary). Python 169 LoC. Fingerprint dataclass preserved. Smoke verified (recorded SELF_DIAGNOSTIC_PROMPT.md sha=acbaa851e5ce, 17845b/355l).
3. ✅ **`meta_evaluator.py`** → `aim-ai-meta-evaluator` shim. CLI binary added (parse/measure/shared-only/summary). Python 226 LoC. ReportFacts + Reproducibility dataclasses preserved with line_compliance + signal_to_noise methods. Temp-file pattern for text→file bridging (Rust binary takes file paths).

### Tier 2 (Week 2) — single-dependency modules ✅ DONE 2026-05-07
4. ✅ `compliance_promoter.py` → `aim-ai-compliance-promoter` shim (138 LoC). CLI: recommend/summary. Recommendation dataclass preserved.
5. ✅ `safety_gate.py` → `aim-ai-safety-gate` shim (143 LoC). CLI: can-run/summary. Verdict dataclass preserved; daily_cost/daily_budget bridged via env vars.
6. ✅ `self_modify.py` → `aim-ai-self-modify` shim (142 LoC). CLI: can-self-modify/propose/apply/summary. Verdict, Proposal (with eval_case_id), ApplyResult preserved.
7. ✅ `prompt_impact.py` → `aim-ai-prompt-impact` shim (145 LoC). CLI: per-revision/summary. ImpactRow with compliance_delta/crit_delta + _fmt_* helpers preserved.
8. ✅ `regression_detector.py` → `aim-ai-regression` shim (153 LoC). CLI: detect/summary. Regression dataclass + grade_improved/grade_worsened/regressed/improved properties preserved; finding_suppressions filter applied Python-side post-detect.
9. ✅ `regression_alert.py` → `aim-ai-regression-alert` shim (112 LoC). CLI: check/build (stdin Regression JSON → Alert JSON). agents.notify dispatch stays in Python; build is side-effect free.
10. ✅ `case_archiver.py` → `aim-ai-case-archiver` shim (115 LoC). CLI: candidates/archive/summary. Candidate + ArchiveResult preserved; binary owns slug normalisation, ledger scan, fs moves.

### Tier 3 (Week 3-4) — multi-dependency ✅ DONE 2026-05-07
11. ✅ `doctor.py` → `aim-ai-doctor` hybrid shim (162 LoC). Python keeps modules-import + api_key probes (no Rust equivalent for `import`); Rust binary owns db_writable/workspace/artifacts/direction_rule/latest_report. CLI: diagnose/summary.
12. ✅ `health_score.py` → transitive port (298 LoC unchanged). Composer of already-Rust-shimmed sub-modules (doctor / regression_detector / diagnostic_ledger / case_validator / prompt_versions). Persistence Python-sqlite3 layer preserved with schema parity to `aim-ai-health` Rust crate (`HealthStore`).
13. ✅ `run_self_diagnostic.py` → `aim-ai-diag` shim (132 LoC). Subprocess to Rust binary which owns full pipeline (safety gate, prompt build, DeepSeek POST + chat fallback, compliance retry, save, ledger record, prompt fingerprint). Python keeps `_api_key` + `project_root` (consumed by doctor + finding_validator).
14. ✅ `morning_brief.py` → `aim-ai-brief` shim (107 LoC). Calls `aim-ai-brief --json` for regression / ledger / archive / deadlines; overlays Python wiring section from the doctor shim (since AI.ai.doctor still imports `agents/*`).
15. ✅ `case_validator.py` → `aim-ai-cases` shim (102 LoC). CLI: validate-one/validate-dir/summary. CaseStatus + Report + all_ok preserved.
16. ✅ `findings_to_evals.py` → `aim-ai-findings-to-evals` shim (114 LoC). CLI: case-from-finding/generate/yaml/write/summary. CaseSpec dataclass preserved.
17. ✅ `finding_validator.py` → `aim-ai-finding-validator` shim (129 LoC). 5 contradiction rules + markdown parsing in Rust. Status PascalCase→snake_case translated in shim.
18. ✅ `finding_suppressions.py` → `aim-ai-suppressions` shim (154 LoC). CLI: suppress/unsuppress/is-suppressed/active/all/filter/prune-expired/summary. SQLite mute table on the ledger DB.
19. ✅ `skill_standard.py` → `aim-ai-skill-standard` shim (89 LoC). CLI: to-agentskills/from-agentskills/round-trip/export-dir/import-dir.
20. ✅ `gap_detector.py` → `aim-ai-gap-detector` shim (163 LoC). Python post-filters by window_days (Rust crate has no native window). Surrender / Gap dataclasses preserved.
21. ✅ `reflexion_cluster.py` → `aim-ai-reflexion` shim (178 LoC). Rust owns Jaccard clustering + token / filler list. Python keeps memory-source loaders (`feedback_*.md` + reflexion buckets — both Python conventions).

### Tier 4 (Week 5-6) — terminal nodes (depend on many, no one depends) — partially done 2026-05-07
22. ✅ `dashboard.py` — transitive composer (171 LoC unchanged). All 11 sections call `AI.ai.X.summary` shims that subprocess into Rust binaries; Rust `aim-ai-dashboard` binary is a parallel ~14-section view.
23. ✅ `auto_sweep.py` → `aim-ai-sweep` shim (94 LoC). Full Rust port; 7-step orchestration in Rust crate.
24. ✅ `stable_run.py` → orchestrator shim (209 LoC). Python iterates calls to `aim-ai-diag --no-save --quiet` and consolidates via `AI.ai.meta_evaluator.measure` (which is itself a Rust shim).
25. ✅ `explainer.py` — transitive composer (188 LoC unchanged). Calls `health_score.score` (transitive Rust) + per-component sub-module summaries (each a Rust shim).
26. ✅ `backup.py` → `aim-ai-backup` shim (91 LoC). CLI: snapshot/write/restore/summary.
27. ⏸ `distillation_tracker.py` — kept Python (245 LoC). Caller-injected per-tier `runner_fn` closures + Python-side LLM tier integration are inherently Python; sqlite3 layer schema-compatible with Rust `aim-ai-distillation` `DistillStore`.
28. ⏸ `eval_synthesiser.py` — kept Python (409 LoC). Pattern-miner findings + feedback_*.md note loaders are Python-side conventions; Rust crate `aim-ai-eval-synthesiser` exists with `synthesise_from_finding/reflexion/yaml_dump/write_case` for downstream consumers.
29. ✅ `hive_telemetry.py` → `aim-hive-telemetry` shim (109 LoC). Added [[bin]] to `aim-hive-worker`. CLI: contribution/preview/contribute. L_PRIVACY PII scrubber + DP-budget gate + queen POST live in Rust crate.
30. — `runner.py` — file does not exist; remove from roadmap.
31. ⏸ `self_diagnostic.py` — kept Python (222 LoC). Python uses `ast` for accurate introspection vs Rust regex; 15 Python-specific tests assert legacy "Run-time Snapshot" prompt format (different from Rust crate's "Phase 0 — frozen inventory" format). Rust crate `aim-ai-self-diagnostic` is independently used by `aim-ai-diag` binary at runtime.

### Tier 5 (Week 7) — cleanup
32-35. Edge cases / scaffolding only modules. Reassess if still needed.

## Per-module migration template

For each `AI/ai/X.py`:

1. **Audit** Python module: data flow, side effects (SQLite reads/writes,
 network calls, filesystem), public functions used by callers.
2. **Verify** Rust counterpart `aim-ai-X` exists; review its API surface.
3. **Spike** — try invoking `aim-ai-X` lib functions from a small Rust
 binary; confirm output matches Python `X.py` for ≥10 inputs.
4. **Add CLI binary** to `aim-ai-X`. Subcommands match Python public
 functions. JSON I/O on stdout/stdin.
5. **Rewrite Python** as thin subprocess shim (≤120 LoC). Same public
 API; same exception types.
6. **Run regression** of all callers (other AI/ai modules + tests).
7. **Remove** dead Python helpers / stale imports.
8. **Update** `MAP.md` + this `PHASE_9_ROADMAP.md` (mark item ✅).

## Test strategy

- **Parity gate** (per module): write `tests/test_X_parity.py` exercising
 both legacy Python (via `AIM_USE_LEGACY_AI_X=1`) and new shim across
 N≥20 cases. Block PR until 100% match.
- **Regression gate**: existing tests must pass without modification.
- **Integration smoke**: after each tier, run `bash scripts/test_all.sh`
 + manual `mix phx.server` smoke of `/about`/`/status`/cornerstone routes.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| SQLite schema drift (Rust vs Python writers) | Use single `aim-ai-ledger` Rust crate as authority; Python shim writes go through CLI. Lock schema migrations. |
| Subprocess RTT degrades hot-path latency | `dashboard.py` calls 11 sub-modules — could mean 11 subprocess spawns per refresh. Mitigate: add `aim-ai-dashboard` CLI that aggregates internally. |
| Removed Python prematurely | Always keep Python file as shim, never delete `AI/ai/X.py` — callers import it. |
| Circular dep (`diagnostic_ledger` ↔ `meta_evaluator`) | Both Rust crates already exist; lib boundary already broken in Rust. Port both in same PR. |
| `dashboard.py` is HTML output for AIM/AI dashboard, not a service | Keep Python rendering layer (~50 LoC), move computation to Rust. |

## Success criteria

- 0 Python files in `AI/ai/` contain >100 LoC of business logic where a
 same-named Rust crate has the equivalent functionality.
- All 35 listed Python files reduced to thin shims (≤150 LoC each).
- All existing pytest tests pass.
- Performance: `dashboard.py` refresh time stays <2 s after migration
 (vs current ~0.3 s baseline).

## Estimated effort

| Tier | Modules | Days |
|---|---|---|
| 1 (foundation) | 3 | 4 |
| 2 (single dep) | 7 | 5 |
| 3 (multi dep) | 11 | 7 |
| 4 (terminal) | 10 | 5 |
| 5 (cleanup) | 4 | 1 |
| **Total** | **35** | **22 days** ≈ 4-5 weeks |

## Reality-check after Phase 8

Phase 8 audit overestimated «easy ports» in `agents/`. Same risk for
Phase 9: many `AI/ai/*.py` files probably touch `llm.ask` or
`agents.notify` which are pure-Python orchestration. Realistic outcome:
≈70% of modules will become clean shims; ≈30% will remain hybrid
(Python orchestrator + Rust data layer).

## What this Phase 9 does NOT cover

- `agents/generalist.py` (2 324 LoC) — separate P3.2.
- `agents/graph.py` (942 LoC) — separate P3.3.
- `web/api.py` (772 LoC) → Phoenix migration — P2.2.
- `aim_cli.py` / `medical_system.py` / `telegram_bot.py` — P3.5-3.7.
- `aim-media` crate (TTS/Image/Video/3D) — separate v7.2 roadmap.
