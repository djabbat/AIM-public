# AIM phoenix-umbrella

Phoenix umbrella, замещающий Python-фронтенд + API:
`web/api.py`, `aim_gui.py`, `telegram_bot.py`, `cli/__main__.py`.

## Приложения

| App | Port | Назначение | Замещает |
|--------------------|------|------------------------------------------------------------|----------------------------|
| `aim_web` | 4002 | LiveView UI (chat, intake, cases) | `aim_gui.py`, web/templates|
| `aim_gateway` | 4003 | JSON API + Telegram webhook | `web/api.py`, `telegram_bot.py` |
| `aim_orchestrator` | — | бизнес-логика: ensemble, debate, reflexion; HTTP к Rust | `agents/orchestrator.py` и др. |
| `aim_memory` | — | Ecto-репозиторий (SQLite сейчас, Postgres в будущем) | `db.py`, `agents/memory_*.py` |

## Карта апстримов (config/config.exs)

```
aim_orchestrator → llm :8770 (aim-llm)
 → rag :8771 (aim-rag)
 → medkb :8772 (aim-medkb)
 → doctor:8773 (aim-doctor)
 → diffdx:8765 (существующий Rust)
 → ssa :8766 (существующий Rust)
```

Переопределяется через `AIM_LLM_URL`, `AIM_RAG_URL`, ...

## Запуск

```sh
cd phoenix-umbrella
mix deps.get
mix compile
iex -S mix # с REPL
# или
mix phx.server # после доводки endpoint'ов
```

## Прод-блокеры

- `SECRET_KEY_BASE` обязателен в `:prod` (см. `config/runtime.exs`).
- `PHX_HOST` — публичный хост.
- В `aim_web/endpoint.ex` сейчас сессионный salt `aimweb01` — заменить на сгенерированный.
- LiveView сейчас не подключён к реальной логике; контроллеры в `aim_gateway`
 возвращают результат `AimOrchestrator.chat/2`, но провайдеры в Rust ещё TODO.

## Маппинг Python → новая архитектура

| Python | Куда переносить |
|---------------------------------------|----------------------------------------------------|
| `llm.py` | `rust-core/crates/aim-llm` |
| `db.py` | `aim_memory/lib/aim_memory/{repo,schemas/*}.ex` |
| `web/api.py` | `aim_gateway/lib/aim_gateway_web/controllers/*` |
| `web/webhooks.py` | `aim_gateway/.../telegram_controller.ex` |
| `aim_gui.py` | `aim_web/lib/aim_web_web/live/*` |
| `cli/__main__.py` | Rust binary `aim-cli` (новый крейт, опционально) |
| `agents/intake.py` | `rust-core/crates/aim-doctor` (intake handler) |
| `agents/doctor.py` | `rust-core/crates/aim-doctor` (diagnose handler) |
| `agents/orchestrator.py` + ensemble | `aim_orchestrator` (Elixir GenServer pipelines) |
| `agents/memory_*.py` | `aim_memory` + `aim-rag` (vector store + GraphRAG) |
| `lab_reference.py`, `i18n.py` | `rust-core/crates/aim-medkb` |
| `telegram_bot.py` | `aim_gateway/.../telegram_controller.ex` |
