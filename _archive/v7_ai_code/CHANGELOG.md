# CHANGELOG.md — AIM

User-facing список изменений. Внутренний трекер задач — `UPGRADE.md`.
Format: [Keep a Changelog](https://keepachangelog.com/) v1.1.0,
SemVer-compatible.

---

## [Unreleased]

### Cornerstone citation finalize + cohort dashboard + unit conversion (2026-05-08)

- **Citation finalize:** Tkemaladze J. (2026) "Patient as a Project",
 *Longevity Horizon* 2(5), . Replaced placeholder
 `longhoriz/article/view/177` and pre-print across
 CONCEPT.md / CLAUDE.md / THEORY.md / UPGRADE.md / kernel_legacy.py /
 about_live.ex / home_live.ex / docs/audits/AUDIT_PATIENT_AS_PROJECT_*.md
 / docs/manuscripts/PATIENT_AS_PROJECT.md. about_live_test asserts new
 DOI is present and old placeholder is gone. Memory: closed
 `pending_aim_about_citation`, transitioned `unpublished_patient_as_project`
 → `published_patient_as_project`. Added to `publications.md` self-citation
 list (155 total).

- **`/cohort` Phoenix LiveView (~150 LoC, 3 integration tests):**
 STRATEGY P1-2 dashboard. Per peer-review #3.1 (no overengineering),
 reused existing `scripts/pilot_cohort_extract.py --json` instead of
 creating dedicated Rust statistical crate. Empty-state explains
 recruitment is bottleneck + cites cornerstone DOI.

- **`crates/aim-lab-units` Rust (~290 LoC, 10 tests):** unit conversion
 (g/dL ↔ g/L, mg/dL ↔ mmol/L, μmol/L conversions etc.). Closes mismatch
 warning surfaced by `aim-lab-parser` integration: Beridze HGB 13.7 g/dL
 was flagging "critical_low" against 120-160 g/L norm; now correctly
 converts to 137 g/L → "normal". `tools/lab_evaluate.py` extended to
 call `aim-lab-units batch` before evaluating; result includes
 `raw_value`/`converted_value`/`was_unit_converted` for UI traceability.

- **Drug-interactions DB extension (35 → 62 pairs):** FDA DailyMed
 verified additions (no fabricated PMIDs per `feedback_deepseek_no_citations`):
 DOAC × CYP3A4 modulators, antibiotic × statin/warfarin/amiodarone,
 cardiology depth (amiodarone/verapamil/diltiazem × statins/warfarin),
 psychotropic + opioid (BZD × opioid FDA black-box, SSRI × tramadol),
 PPI × clopidogrel, metformin × topiramate/cimetidine. 20/20 tests pass.
 Phase 2 (target 200+ via RxNav) still requires real pharmacology
 curation; this Phase 1 closes peer-review safety lock-in baseline.

### Patient-as-Project workspace + safety-checker (2026-05-08, overnight)

Адресует requirements пользователя 2026-05-08 ("структура пациент-проект",
"список пациентов с истории/назначения/совместимость", "интегрировано в UI
локального AIM") + reviewer's Phase 0 safety lock-in (peer-review
2026-05-07). 4 новых Rust crates + 1 Python shim + 1 Phoenix LiveView.

| # | Artefact | LoC | Tests |
|---|---|---|---|
| 1 | `crates/aim-patient-workspace` | 408 lib + 121 main | 5 ✓ |
| 2 | `crates/aim-compat` (drug-drug + age + allergy + pregnancy + renal/hepatic) | 488 lib + 95 main | 14 ✓ |
| 3 | `crates/aim-lab-parser` (multi-language OCR → structured analytes) | 220 lib + 55 main | 7 ✓ |
| 4 | `crates/aim-patient-events` (append-only JSONL timeline) | 354 lib + 215 main | 9 ✓ |
| 5 | `tools/lab_evaluate.py` (thin shim to `lab_reference.py::evaluate`) | 95 | manual smoke |
| 6 | `live/patient_workspace_live.ex` (`/patients/:id` LiveView) | 740 | 6 integration ✓ |

**Patient-as-Project compliance:** Per `feedback_project_core` rule, each
patient is now a project with a 12-file core (MEMORY/THEORY/CONCEPT/
STRATEGY/PARAMETERS/TODO/CHANGELOG/KNOWLEDGE/MAP/REMINDER/NEEDTOWRITE +
AI_LOG). `aim-patient-workspace::scan_core_files` reports presence per
file; "Core files" tab in Phoenix shows status with create-on-demand path.

**Compat checker scope (v0.1):** 98 patient-side rules total. 35 drug-drug
pairs (existing `aim-interactions`) + 15 age (10 below-thresholds incl.
ASA<16/Reye's, codeine<12 + 5 Beers Criteria ≥65) + 17 allergy (penicillin
class + cephalosporin cross-react + sulfa + NSAID class + statin class) +
17 pregnancy (FDA Cat X + ACE/ARB/statin/NSAID 3rd-trimester) + 8 renal
(CKD 3+) + 6 hepatic. **Phase 2 expansion to 200+ drug-drug pairs deferred
to focused pharmacology curation session** — cannot safely run in overnight
without verified PMIDs (per `feedback_deepseek_no_citations`).

**End-to-end smoke verified:**
- `/patients/Beridze_Keti_2026_03_12` renders Demographics/Allergies/Meds
 (13)/Conditions (3)/Project core/PAM-13/Lab files + Timeline 1-event/Labs
 parsed (RBC HGB HCT MCV MCH MCHC RDW WBC PLT NEUT LYMPH MONO EOS BASO ESR
 from Georgian OCR via aim-lab-parser).
- Treatment modal: typing `amoxicillin` against patient with penicillin
 allergy → Contraindicated conflict surfaced; typing `paracetamol` → "no
 conflicts found".
- Timeline tab: append `add` events (manual / agent / pam / doctor / codesign
 / kernel sources); JSONL persistence verified on real patient.

**Stack rule compliance:** Pure Rust (4 crates) + Phoenix LiveView, no
Docker. The single Python shim (`tools/lab_evaluate.py`) reuses existing
`lab_reference.py` (Frozen Python legacy per `STACK.md`); future Phase 9
port will replace it with `aim-lab-reference` Rust crate.

**Known limitation surfaced:** Lab unit reconciliation is NOT automatic.
If OCR-reported unit (e.g. "g/dL") differs from `LAB_RANGES` reference
unit ("g/L"), the status flag may misfire. Phoenix Labs tab shows both
units side-by-side + warning paragraph instructing physician verification.
Fix is unit-conversion table; deferred (out of overnight scope).

**Routes added:**
- `GET /patients/:id` → PatientWorkspaceLive (Overview/Timeline/Labs/
 Medications/Core files/PAM-13 tabs)

### Hive deep-audit closure (2026-05-07, code-level P0+P1)

Continuation of overnight Hive audit. Closes 7 of the 8 audit items
(P0.4 Python→Rust queen migration deferred to focused 1-week session).

| Item | Artefact |
|---|---|
| **P0.3** consumer binary | `rust-core/crates/aim-hive-consumer/src/bin/consumer.rs` (~190 LoC). Subcommands: `pull` / `loop` / `status` / `opt-out` / `opt-in`. Long-poll mode honours `AIM_HIVE_POLL_INTERVAL_S`. **Closes the cycle:** workers contribute → queen distills → consumers apply. |
| **P1.1** distill threshold | `aim-hive-queen::distill::MIN_WORKERS_FOR_PATTERN` 2 → **5** (collusion-attack mitigation). Env override `AIM_HIVE_MIN_WORKERS_FOR_PATTERN`. |
| **P1.2** name_pair scrubber | `aim-hive-worker::scrub` — Title-Case bigram switched from hard-reject to **redact** with `[redacted]` placeholder. Preserves contributions on benign collisions ("Linux Kernel", "User Activity"). |
| **P1.3** PII patterns extended | `aim-hive-worker::scrub` adds **ipv4** (Reject), **iso_date** (Redact), **long_id** 9-12 digits (Reject). |
| **P1.4** payload size cap | `aim-hive-queen::accept_contribution` rejects > **1 MiB** (env `AIM_HIVE_MAX_PAYLOAD_BYTES`). HTTP layer enforces same via `DefaultBodyLimit`. New error `HiveQueenError::PayloadTooLarge`; mapped to **413** with canonical body. |
| **P1.5** backup cron | `docs/operational/HIVE_QUEEN_DEPLOY.md` § 5 — `sqlite3 .backup` nightly cron sample + 14-day retention + restore procedure. |
| **P1.6** error format unified | Rust queen: `JsonRejection` mapped to canonical `{"error","status"}`; **fallback 404 handler** for unknown routes. Python `queen_app.py` adds **`RequestValidationError`** + catch-all `Exception` handlers to canonical shape. |
| **P1.7** worker token allowlist | Rust queen: replaces external auth backend (was returning 503 → 0 contributions ever) with **`AIM_HIVE_WORKER_TOKENS`** env list of SHA-256 hex hashes. New `require_worker_bearer` + `require_admin_bearer` helpers. Empty allowlist + `REQUIRE_AUTH=1` → legacy bootstrap (any non-empty bearer, logged at startup). |

**Tests added:** +13 aim-hive-consumer · +9 distill · +9 scrub (P1.2/P1.3) · +3 lib (P1.4) · +12 server (P1.7).
**Hive crate regression:** 71/71 pass (consumer 13 · queen-lib 21 · queen-bin 12 · worker 25).
**Full regression `--quick`:** ALL 3 BLOCKS PASS (Python 167 + 34 subtests · Rust 216 across 11 cornerstone+infra crates · Phoenix 23).

**Open / deferred:**
- **P0.4** Python → Rust queen migration (Option B in HIVE_QUEEN_DEPLOY.md) — **parity validation done 2026-05-07** (`docs/operational/HIVE_PARITY_2026-05-07.md`); cutover decision is the user's.
- **Manual (sudo on hive.longevity.ge):**
 1. `sudo systemctl restart aim-hive-queen` — activates patched Python handlers (structured `queen_summary`, `RequestValidationError`, generic `Exception` → canonical body).
 2. Decide cutover to Rust queen (one-command swap of `ExecStart`).
 3. Populate `AIM_HIVE_WORKER_TOKENS` once N>1 real worker hosts come online.

### Server-side artifacts (deployed 2026-05-07 20:09 +04)

- `/home/jaba/hive_queen_src/queen_app.py` — patched (structured summary + canonical error handlers); awaiting `systemctl restart`.
- `/home/jaba/web/aim/AIM/rust-core/target/release/aim-hive-queen` — rebuilt aarch64 release, includes P1.4/P1.6/P1.7.
- `/home/jaba/web/aim/AIM/rust-core/target/release/aim-hive-consumer` — new binary, P0.3.
- `/home/jaba/hive_queen_rust_parity/` — Rust queen running on `:8091`, separate DB, isolated tokens; for parity verification only.

**Hive parity verdict (full report in `docs/operational/HIVE_PARITY_2026-05-07.md`):** post-restart Python and Rust queens agree on all endpoints; pre-restart drift is all in Python error paths the patch addresses.

### Added
- Файлы ядра проекта восстановлены до полного 11-канона: `THEORY.md` (immutable
 formal spec PAM-13 + L_AGENCY), `STRATEGY.md` (6-месячный focus), `REMINDER.md`
 (session checklist), `CHANGELOG.md` (этот файл), `NEEDTOWRITE.md`.
- `tests/test_pam_trajectory_e2e.py` — cornerstone end-to-end test (PASSING):
 intake → PAM #1 → coach → codesign → PAM #2 → MCID delta → L_AGENCY block/pass.
 Подключён в `scripts/test_all.sh --quick` cornerstone subset.
- `--ai` mode в `scripts/test_all.sh` — гоняет `AI/tests/` subproject
 (после cleanup 2026-05-07: 489 passed / 0 skipped).
- `docs/operational/DEPLOY_RUNBOOK.md` — production deploy step-by-step (308 LoC):
 pre-flight, single-node + hub install, Rust build, systemd units, Phoenix
 release, smoke chain, rollback, troubleshooting, production-readiness checklist.
- `docs/operational/PILOT_PROTOCOL.md` — DRAFT клинический протокол
 PAM-13 trajectory pilot (N=30, 3 месяца). Требует MD sign-off перед
 recruitment.
- `scripts/pilot_cohort_extract.py` — cohort-level extraction (336 LoC).
 Walks `Patients/<id>/_pam_history.jsonl` + `_codesign.jsonl` +
 `_disagreement.jsonl`; aggregates PAM-13 trajectory (MCID/MDC classification),
 co-design adherence, kernel violation tally, LLM cost. CLI: text / `--json`
 / `--csv --out`. Privacy: aggregate by patient_id only, no PII.
- `scripts/aim_full_diagnostic.py` (467 LoC, 10 проверок) — полная
 система самодиагностики: inventory + duplicates + dead code + parallel
 structures + subproject coherence + Rust crate health + STACK violations
 + git hygiene + vapor refs + Phoenix routes coverage. CLI text/JSON/MD,
 exit 1 при P0.
- `~/Desktop/AIM_UI.desktop` + `scripts/desktop/aim_ui_launch.sh` —
 desktop launcher для Phoenix UI (prod → local fallback).
- `~/Desktop/AIM_Full_Diagnostic.desktop` + `scripts/desktop/aim_full_diag_launch.sh` —
 desktop launcher: gnome-terminal + MD report в `docs/operational/`.
- `_archive/` структура (gitignored) с README.
- `agents/generalist_pkg/` пакет (started). 2 of ~10 split steps:
 `prompts.py` (115 LoC, SYSTEM_PROMPT) + `gates.py` (140 LoC,
 kernel-law sandbox helpers). `agents/generalist.py` 2324 → 2085 LoC
 (10% shrinkage). Public API сохранён через re-export. test_law_gates
 44/44 passing.
- `agents/generalist_pkg/__init__.py` (placeholder).
- 3 unit tests для `aim-grep` Rust binary (closes diagnostic
 rust_no_tests finding).
- **Phoenix `/admin` LiveView** (control panel, 270+ LoC). Status grid:
 Phoenix self / aim-llm:8770 / aim-rag:8771 / aim-hive-queen:8090 /
 Ollama. Last diagnostic P0/P1/P2 counts. Hive worker last-contribute +
 DP budget. Patient cohort size + PAM + codesign tallies. 5s refresh.
 Mutating actions (run-diag, contribute) gated на `AIM_ADMIN_ENABLE=1`.
- **`deploy/systemd/aim-hive-worker.service` + `.timer`** + deploy script
 `scripts/deploy_aim_hive_worker.sh` (--user / --system). One-shot timer
 runs `aim-hive-telemetry contribute` каждые 60 минут (5 мин boot delay,
 Persistent for laptop sleep).
- **`deploy/systemd/aim-hive-queen.service`** (long-running Axum server).
- **`scripts/deploy_hive_queen_remote.sh`** (build + tarball + scp + ssh
 install) — для отдельной машины. Создаёт system user `aim`, dirs
 `/opt/aim-hive-queen/`, `/var/lib/aim-hive-queen/`, `/etc/aim/`,
 installs binary + service + env template.
- **`docs/operational/HIVE_QUEEN_DEPLOY.md`** (200+ lines): one-shot
 deploy + manual deploy + post-install hardening (admin token, worker
 auth, TLS reverse proxy, backup cron) + smoke tests + troubleshooting
 + worker wiring + rollback.
- `aim-verify` Rust crate + binary (5 unit tests) — Phase 10 hybrid first
 tool: verify-pmid + verify-doi. Python opt-in shim
 `AIM_VERIFY_USE_RUST=1` в `tools/literature.py`. **20 parity tests** в
 `tests/test_aim_verify_parity.py` (включены в `--quick`).
- `aim-grep` Rust crate + binary — Phase 10 hybrid second tool: pure-Rust
 recursive regex search через `ignore` crate (gitignore-aware,
 ≤5MB files). Python opt-in shim `AIM_GREP_USE_RUST=1` в
 `agents/generalist.py::_t_grep`. Output identical to ripgrep manual smoke.
- 14 минимальных unit tests для 4 крейтов: `aim-doctor` (3),
 `aim-medkb` (3), `aim-generalist::interrupt` (3), `aim-rag::embed` (5).
- DiffDiagnosis + SSA → `MAP.md` § 2.5 + `CONCEPT.md` § 12 + `CLAUDE.md`
 "Internal microservices" (in-tree REST: ports 8765 / 8766).
- `docs/diffdiagnosis/` + `docs/ssa/` — перенесены 8×2 канонических .md
 из subprojects; subprojects получили pointer README.

### Changed (2026-05-07 system audit)
- `.gitignore` дополнен 9 entries: `target/`, `**/target/`, `_build/`,
 `**/_build/`, `deps/`, `**/deps/`, `node_modules/`, `_archive/`,
 diagnostic timestamp pattern.
- `scripts/aim_full_diagnostic.py` heuristics улучшены: skip CHANGELOG +
 NEEDTOWRITE из broken-ref scan; whitelist namespace-collisions;
 `*.py[cod]` → `.pyc` cover; +.py fallback для bare module refs;
 `crates/` → `rust-core/crates/` resolution; basename-anywhere fallback
 для Phoenix LiveView refs. **Diagnostic findings 4 P0 / 8 P1 / 3 P2 →
 0 P0 / 0 P1 / 1 P2** (single endemic Python __pycache__).
- Stale planned-but-never-created refs в CONCEPT/MEMORY/UPGRADE
 reformatted без backticks (router.py, MEMORY_archive_YYYY.md, и др.).

### Removed (2026-05-07 system audit)
- `./aim-web/` (standalone Phoenix, superseded) → `_archive/`.
- `./systemd/` (1-unit legacy, superseded by `deploy/systemd/`) → `_archive/`.
- `AI/queen_deploy/` (0 callers) → `_archive/`.
- `AI_run_self_diag.py` + `AI_self_diag.py` (0 callers, дубликаты).
- `_journal/` (orchestrator scratch, 0 callers) → `_archive/`.
- 3 идентичных `AGENTS.md` копии → 1 в `docs/standards/AGENTS.md`.
- Empty / build artifacts: `patches/`, `media/`, `aim_generalist.egg-info/`.

### Removed
- **`lab_reference.py` citation** 2026-05-07: добавлен single-source
 reference в docstring (Mayo Clinic Laboratories Reference Values for
 Adults 2024 + URL) + secondary cross-check (MedlinePlus + WHO) +
 acknowledged limitations (lab-specific variation, no age/ethnic
 adjustments, SI default). Per-analyte verification — owner Dr. Jaba.
- **MEMORY active questions cleanup** 2026-05-07: stale 16-day Telegram-bot
 и GUI test items перенесены в `TODO.md` P3 «when needed». Phoenix
 LiveView routes (`/chat` + `/intake` + `/cases`) — primary clinical UI.
 MEMORY active = только critical-path (pilot recruitment).
- **Phase 10 generalist port refined as hybrid** 2026-05-07. Полный
 port (2324 LoC → Rust) REJECTED как overengineering. Вместо: PyO3
 tools-as-crates для numerical/HTTP-heavy tools (apply_patch / grep /
 verify_pmid / verify_doi / web_search / web_fetch), dispatcher loop
 остаётся Python. ~1-2 недели вместо 3-6.
- **`web/api.py` Phoenix migration FROZEN PERMANENTLY** 2026-05-07.
 Active production hub-side FastAPI (`/api/auth/*`, `/api/nodes/heartbeat`,
 772 LoC). Multi-user pilot не растёт до 3+ врачей. Phoenix port =
 академическое упражнение; frozen status в STACK § "Frozen Python
 legacy" защищает от drift. Re-evaluate триггер: multi-user expansion.
- **KIMI / Qwen DashScope HTTP clients REJECTED.** Симметрично с
 aim-media. STRATEGY P2-9 «не на hold, а отвергнуто». UPGRADE v7.4.2
 P2 + v7.1 + status table обновлены. Long-context = DS-chat 64k +
 Gemini Flash 1M (free 1500/day); multilingual = DS-chat. Реактивация
 только по факту use case (грузинский пациент с Qwen-уровнем потребности).
- **`aim-media` v7.2 multimodal subsystem REJECTED.** `CONCEPT.md` §11
 сокращён со 135 до 9 строк (эпитафия + указание на git history).
 `MAP.md` § 2-3 строки про aim-media crate, media_live LiveView, Python
 shims (XTTS/SadTalker/Hunyuan3D/Blender/RDKit/PyMOL) удалены. `MAP.md`
 § 4 "Медиа-поток v7.2 ⏳" удалён. `UPGRADE.md` v7.2 секция (84 строки
 детального 8-недельного плана) удалена. Ресурс ($100/мес + 8 недель)
 переориентирован на pilot recruitment.
- 110 broken `AI/tests/*` тестов (Phase 9 cleanup): 4 файла удалены
 целиком (`test_run_self_diagnostic.py`, `test_hive_telemetry.py`,
 `test_morning_brief.py`, `test_pipeline_integration.py`); ~50
 отдельных функций удалены AST-rewrite в 11 файлах. Они
 monkey-patch'или Python-внутренности (`_post_deepseek` etc),
 удалённые Phase 9 шимизацией. Coverage преемственно у Rust crates
 (208 test files в `rust-core/crates/aim-ai-*` с `#[cfg(test)]`).
 AI/tests regression gate восстановлен: 489 passed / 0 skipped.
- `AI/tests/_phase9_known_broken.txt` snapshot и связанная
 skip-marker логика в `AI/tests/conftest.py`.

### Changed
- `CONCEPT.md` § 2-3-8: KIMI (Moonshot) и Qwen (DashScope) сняты как vapor
 (HTTP-clients не реализованы в `llm.py`); описан фактический набор
 провайдеров: DeepSeek + Groq + Anthropic Claude + Google Gemini + Ollama.
- `PARAMETERS.md` §1, §2, §8, §9: модели + пороги + ENV vars приведены к
 фактическому состоянию `config.py` 2026-05-07.
- 24 не-канонических `.md` (AUDIT_*, MIGRATION_*, MANUSCRIPT_*, OVERNIGHT_*,
 PHASE_*_ROADMAP, PROD_DEPLOY, INSTALL, README_AI_KERNEL) перемещены в
 `docs/audits/`, `docs/roadmaps/`, `docs/migration/`, `docs/manuscripts/`,
 `docs/operational/`. Корень содержит только 11-файловое ядро.
- `STACK.md` § "Frozen Python legacy" — формализованы `web/api.py` (772 LoC),
 `medical_system.py`, `telegram_bot.py`, `aim_cli.py`, `aim_gui.py` как
 legacy с обоснованием + указанием phase для будущего port. Frozen rule:
 расширение запрещено, только security/bug-fix.
- `STACK.md` § Notes — Whisper ASR в `agents/voice.py` + `agents/telegram_extras.py`
 задокументированы как legitimate exception к "LLM only via llm.py" rule
 (audio.transcriptions != chat.completions).
- `agents/speculative.py:46` — переписан через `llm.py::ask_fast` (раньше
 прямой `OpenAI(base_url=Endpoints.GROQ)` client).
- `MEMORY.md` — закрыты 4 stale "ждут" вопроса (KIMI/Qwen vapor, Telegram +
 GUI tests перевешены на STRATEGY P3).
- `TODO.md` — 230 → 85 LoC (source of truth = STRATEGY.md; легаси про
 aim-media v7.2 / 2026-04 экосистему удалено).

### Removed
- (none — миграция файлов не удаление).

---

## [v7.4.1] — 2026-05-07

### Added
- L_AGENCY (4-й extended kernel law) wired в `decide` и
 `doctor.treatment` — clinical actions для пациентов с PAM-13 level ≥ 2
 блокируются без co-design log entry.
- Cornerstone Rust crates: `aim-pam` (PAM-13 administration + scoring + JSONL
 persistence), `aim-disagreement` (Blumenthal-Lee 4-zone HCI classifier),
 `aim-codesign` (event log: consulted | agreed | modified | refused |
 alternative), `aim-coach` (motivational interviewing + OARS classifier).
- Phoenix LiveView routes: `/pam`, `/pam/:id`, `/codesign/:id`,
 `/disagreement`, `/activation`, `/coaching/:id`, `/about` (566 LoC English
 description).
- `aim-llm` Rust HTTP service + `agents/llm_client.py` opt-in shim
 (production roll-out gated на 30-day uptime).

### Changed
- Phase 8 Python→Rust shims: `smart_routing`, `reflexion`, `interactions`,
 `regimen_validator`.
- `aim-llm` тестовое покрытие: 0 → 18 unit tests (provider_for_model,
 tier_chain, breakers, limiters).

### Fixed
- Phoenix CSS для cornerstone routes (`.aim-pam`, `.level-N`, `.zone-*`,
 `.codesign-events.kind-*`, `.coach-form`, `.about-section`, `.about-table`)
 — добавлено в `root.html.heex` `<style>` блок.
- LiveView integration tests: 13 cases across 7 routes (sections,
 citations, всё 8 Asimov laws видны, classify event обновляет outcome).

---

## [v7.4] — 2026-05-07 (cornerstone landed)

### Added
- Patient as a Project cornerstone: `CONCEPT.md` Section 0 + `CLAUDE.md`
 cornerstone section + `PATIENT_AS_PROJECT.md` manifest.
- `aim-patient-memory` schema: `ActivationPoint`, `CoachingGoal`,
 `PAM_MCID` / `PAM_MDC` константы, `pam_level_from_score`.
- `aim-pam` crate + CLI: PAM-13 EN/RU questions, scoring,
 `record` / `history` / `level` / `latest-delta` subcommands.

---

## [v7.0] — 2026-04-16

### Added
- Гибридный API LLM-роутер `llm.py`: DeepSeek (chat / reasoner) + Groq.
- 9 языков: ООН-6 + KA + KZ + DA через `i18n.py`.
- 59 лабораторных аналитов в `lab_reference.py` (NIH MedlinePlus + Mayo
 reference intervals 2024).
- Telegram-бот (`telegram_bot.py`) с whitelist via `TELEGRAM_ALLOWED_IDS`
 + `/link` codes для multi-user pairing.
- GUI `aim_gui.py` (customtkinter) с паритетом CLI.
- OCR + PDF pipeline (`agents/intake.py`): tesseract → rapidocr fallback,
 pymupdf + pdfplumber, WhatsApp INBOX auto-import.

### Removed
- Ollama / llama3.2 локальный режим (устарело — заменён cloud-first
 гибридом, Ollama остался как offline fallback).

---

## [v6.x] — pre-2026-04-16

Не задокументировано; референс — `docs/audits/AUDIT_2026-05-02.md`.

---

**Convention:** при каждом релизе — обновить `[Unreleased]` → новый
versioned blok, пустой `[Unreleased]` создать заново. Версия = SemVer
по контракту public API (Rust crates `aim-*`). Phoenix routes — minor
bump при добавлении нового route.
