# AIM — Migration to Rust backend + Phoenix frontend

**Дата:** 2026-05-04
**Контекст:** user directive "delai vse na Rust", "frontend na Phoenix".
Существующий AIM написан на Python (agents, AI/ai/, FastAPI queen,
customtkinter GUI). Цель — постепенно перенести логику на Rust workspace
(`rust-core/crates/*`), а UI — на Phoenix LiveView (как Ze/BioSense/FCLC
уже у нас сделано).

## Текущее состояние Rust workspace

`rust-core/crates/`:
- `aim-common` — shared types, telemetry, health, config, metrics, error
- `aim-llm` — LLM router (DeepSeek + Groq + Ollama + Anthropic)
- `aim-rag` — retrieval-augmented generation (LanceDB)
- `aim-medkb` — medical knowledge base
- `aim-doctor` — diagnostic + regimen agent
- `aim-generalist` — tool-using executor
- **`aim-dp` (новое 2026-05-04)** — DP-budget accountant + Gaussian noise

`DiffDiagnosis/backend/` и `SSA/backend/` — отдельные workspace, та же логика.

## Migration plan — backends на Rust

### Phase 1 · Hive (текущий sprint)

| Python модуль | Rust crate | Status |
|---|---|---|
| `AI/ai/dp_accountant.py` (план из FCLC_BORROW.md P1) | `aim-dp` | ✅ DONE 2026-05-04 |
| `AI/ai/hive_telemetry.py` | `aim-hive-worker` (TODO) | планируется |
| `AI/ai/hive_queen.py` | `aim-hive-queen` (TODO) | планируется |
| `AI/ai/hive_consumer.py` | `aim-hive-worker::consumer` (TODO) | планируется |
| `AI/queen_deploy/queen_app.py` (FastAPI) | `aim-hive-queen` Axum binary | планируется |

### Phase 2 · Closed-loop self-improvement

`AI/ai/*` модули (~25 файлов: diagnostic_ledger, regression_detector,
fix_planner, dashboard, etc.) → собственный crate `aim-ai-loop`. SQLite
ledger-операции уже хорошо ложатся на `sqlx` или `rusqlite`. LLM-запросы
маршрутизируются через `aim-llm`.

### Phase 3 · Operational stack

`agents/*`:
- `auth.py` (Hub side) → `aim-hub` Axum binary
- `hub_client.py` (Node side) → `aim-node-client` library
- `intake.py` (OCR/PDF/WhatsApp) → `aim-intake` (использует Python OCR
 через subprocess либо tesseract-rs)
- `doctor.py`, `interactions.py` → `aim-doctor` (уже частично готов)
- `worktree.py` → `aim-worktree`
- `email_agent.py` → `aim-email`

### Phase 4 · CLI/Entry points

- `medical_system.py` → `aim` CLI (clap)
- `aim_cli.py` → unified subcommand dispatcher
- `telegram_bot.py` → `aim-telegram` Axum/teloxide binary

## Frontend на Phoenix

Текущий `aim_gui.py` (customtkinter) → Phoenix LiveView приложение по
паттерну Ze/BioSense:

```
AIM/aim-web/ # Phoenix umbrella OR single app
├── lib/aim_web/
│ ├── live/
│ │ ├── chat_live.ex # ai conversation, tool-call trace
│ │ ├── diagnostic_live.ex # 9-phase prompt builder + ledger view
│ │ ├── patient_live.ex # MEMORY.md viewer/editor (gated)
│ │ ├── hive_live.ex # bee status, queen connection
│ │ └── settings_live.ex # ~/.aim_env editor
│ ├── controllers/
│ └── components/layouts/
├── assets/
└── config/
```

Бэкенд Rust выставляет JSON API (Axum), Phoenix LiveView на нём строит
UI. WebSocket — Phoenix Channels. Тот же deployment-паттерн что и для
ze.longevity.ge / biosense.longevity.ge / fclc.longevity.ge — native
systemd, `mix release`.

URL-план (опционально):
- `aim.longevity.ge` — публичный hub
- локально каждый node поднимает Phoenix на 127.0.0.1:4200, GUI =
 браузер на этот URL

## Что остаётся на Python

- **Patients/ pipeline** — OCR через rapidocr_onnxruntime, PDF через
 pymupdf. Эти библиотеки не имеют зрелых Rust-аналогов; шим через
 subprocess из Rust целесообразен.
- **Тестовые fixtures и smoke-тесты** — `tests/`, на pytest, оставляем.
- **Миграции** — `migrations/migrator.py`, эфемерный, можно не трогать.

## Совместимость во время миграции

- Rust-крейты выставляют JSON API на 127.0.0.1, Python вызывает их
 через HTTP (или unix socket). Это позволяет миграцию по одному
 модулю.
- Postgres / SQLite базы остаются общие — Rust и Python обращаются
 через одни и те же таблицы.
- Logging унифицирован через `tracing` (Rust) и `logging` (Python),
 оба в JSON формате.

## Сейчас сделано

- ✅ `aim-dp` crate — 10 unit + 1 doc test passing
 - `DpAccountant::new(budget)` / `from_env` / `with_path(p, b)`
 - `spend(eps)` — атомарный across-process через `fs2` flock
 - `remaining` / `fraction_consumed` / `epsilon_projection`
 - `gaussian_noise_sigma` / `gaussian_noise` / `add_gaussian_noise`
 - Persistence в `~/.cache/aim/dp_accountant.json`
 - Env: `AIM_HIVE_DP_BUDGET`, `AIM_HIVE_DP_EPS_PER_ROUND`,
 `AIM_HIVE_DP_DELTA`

## Phase 5 · Patient as a Project cornerstone (✅ 2026-05-07)

| Python модуль | Rust crate / Phoenix LiveView | Status |
|---|---|---|
| `agents/patient_memory.py` (`ActivationPoint` field) | `aim-patient-memory` lib (Rust) | ✅ done |
| (новое) | `aim-pam` lib + bin (PAM-13 scoring + JSONL store) | ✅ done |
| (новое) | `aim-disagreement` lib + bin (Blumenthal-Lee 4-zone) | ✅ done |
| (новое) | `aim-codesign` lib + bin (JSONL co-design log) | ✅ done |
| (новое — kernel) | L_AGENCY в `aim-kernel`; `decide` enforces | ✅ done |
| `agents/pam_tracker.py` | thin shim → `aim-pam` binary | ✅ done |
| `agents/automation_bias_detector.py` | thin shim → `aim-disagreement` binary | ✅ done |
| `agents/codesign_log.py` | thin shim → `aim-codesign` binary | ✅ done |
| (новое) | Phoenix `pam_live.ex` (`/pam`, `/pam/:patient_id`) | ✅ done |
| (новое) | Phoenix `codesign_live.ex` (`/codesign/:patient_id`) | ✅ done |
| (новое) | Phoenix `disagreement_live.ex` (`/disagreement`) | ✅ done |
| (новое) | Phoenix `activation_live.ex` (`/activation`) | ✅ done |
| ⏸️ deferred | `aim-coach` crate (motivational interviewing) | Phase 4 |
| ⏸️ deferred | PyO3 in-process bindings for pam/disagreement/codesign | when subprocess RTT becomes hot path |

## Следующие шаги (в порядке)

1. **`aim-hive-worker` crate** — порт `hive_telemetry.py` на Rust;
 интегрировать `aim-dp::spend` как gate перед POST.
2. **`aim-hive-queen` crate** — порт `hive_queen.py` + `queen_app.py`
 (Axum) на Rust.
3. **`aim-web` Phoenix app** — first LiveView: HiveLive (статус
 соединения с queen, последние contributions, текущий ε-budget).
4. Постепенно отъедать остальные модули из `agents/` и `AI/ai/`.

Источники истины при миграции:
- Каждый Rust crate должен иметь полный test suite, паритетный с
 Python-предком.
- Python модули НЕ удаляются до тех пор, пока Rust замена не покрывает
 100% сценариев и проходит eval-harness.
