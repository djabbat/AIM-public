# Миграция AIM: Python → Rust + Phoenix

## Состояние на 2026-05-02

Скелет создан и компилируется:

- **`rust-core/`** — Cargo workspace, 5 крейтов (`aim-common`, `aim-llm`, `aim-rag`, `aim-medkb`, `aim-doctor`). `cargo check` — зелёный.
- **`phoenix-umbrella/`** — 4 приложения (`aim_web`, `aim_gateway`, `aim_orchestrator`, `aim_memory`). `mix compile` — зелёный.
- **`DiffDiagnosis/`**, **`SSA/`** — оставлены как есть (отдельные workspace'ы Rust + Phoenix фронт каждого).

## Что НЕ перенесено (только заглушки `TODO`)

Перенос реальной логики — следующая фаза по очереди:

1. `llm.py` (988 строк) → `aim-llm/providers/*.rs` (HTTP, retry, circuit breaker, rate-limit, cache).
2. `db.py` (383 строки) → `aim_memory` Ecto-схемы (читать существующий `aim.db` без миграции).
3. `lab_reference.py` (534) + `i18n.py` (254) → `aim-medkb` (загрузка JSON + REST).
4. `agents/intake.py`, `agents/doctor.py`, `agents/orchestrator.py` → `aim-doctor` пайплайн.
5. `web/api.py` (30K) → `aim_gateway` контроллеры (по ручкам, постепенно).
6. `aim_gui.py` (483) → LiveView в `aim_web`.
7. `telegram_bot.py` (434) → `AimGateway.TelegramController` + GenServer-poller (или webhook).
8. `agents/memory_*.py` (~10 файлов, ~70K) → `aim_memory` + `aim-rag`.
9. `agents/embed_*.py`, `graphrag*.py` → `aim-rag` (через существующий embed-сервер или порт `fastembed-rs`).

## Запуск всей системы (после переноса)

```sh
# 1) Rust core
cd rust-core
cargo run --release --bin aim-llm & # :8770
cargo run --release --bin aim-rag & # :8771
cargo run --release --bin aim-medkb & # :8772
cargo run --release --bin aim-doctor & # :8773

# 2) Existing services (separate workspaces)
cd ../DiffDiagnosis/backend && cargo run --release & # :8765
cd ../SSA/backend && cargo run --release & # :8766

# 3) Phoenix umbrella
cd ../../phoenix-umbrella
mix phx.server # aim_web :4002, aim_gateway :4003
```

## Архитектура целиком

```
 ┌────────── browser ──────────┐
 │ │
 ┌──────▼──────┐ ┌──────▼──────┐
 │ aim_web │ │ aim_gateway │
 │ :4002 LV │ │ :4003 API │
 └──────┬──────┘ └──────┬──────┘
 │ Phoenix umbrella │
 └────────────┬────────────────┘
 │
 ┌─────────▼─────────┐
 │ aim_orchestrator │ aim_memory (Ecto)
 │ (HTTP client) │ │
 └─────────┬─────────┘ ▼
 │ aim.db (sqlite)
 ┌──────────────┬────────────┼────────────┬──────────────┐
 ▼ ▼ ▼ ▼ ▼
 aim-llm:8770 aim-rag:8771 aim-medkb:8772 aim-doctor:8773 diffdx:8765 / ssa:8766
 (DeepSeek/ (embeddings, (lab refs, (orchestrates (existing)
 Groq/...) GraphRAG) i18n) everything)
```
