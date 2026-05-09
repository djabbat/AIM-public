# AIM rust-core

Cargo workspace для нативного ядра AIM. Заменяет Python-модули из
`agents/`, `llm.py`, `lab_reference.py`, `i18n.py`, `medical_system.py`.

## Сервисы и порты

| Crate | Port | Что делает | Замещает Python |
|---------------|-------|---------------------------------------------------------|--------------------------------------------------|
| `aim-common` | — | shared error / health / telemetry / cors | — |
| `aim-llm` | 8770 | LLM-роутер (DeepSeek/Groq/Anthropic/Gemini/Ollama) | `llm.py` |
| `aim-rag` | 8771 | embeddings + GraphRAG + memory_index | `agents/embed_*.py`, `graphrag*.py`, `memory_index.py` |
| `aim-medkb` | 8772 | lab reference + drug interactions + i18n строки | `lab_reference.py`, `i18n.py` |
| `aim-doctor` | 8773 | пайплайн диагностики (intake → diff → план) | `agents/intake.py`, `agents/doctor.py`, `agents/orchestrator.py` |
| `diffdx-api` | 8765 | дифдиагнозы (Vinogradov+Taylor) — отдельный workspace | существующий |
| `ssa-api` | 8766 | синдромальный анализ CBC — отдельный workspace | существующий |

## Зависимости общие

`aim-common` экспортирует:
- `ApiError` / `ApiResult` — единый JSON error envelope.
- `health_handler` — `GET /health` с именем сервиса, версией, временем старта.
- `init_tracing` — настройка `tracing-subscriber` от `RUST_LOG`.
- `cors_layer` — permissive в dev, строгий по `AIM_CORS_ORIGIN` при `AIM_ENV=prod`.

## Сборка

```sh
cd rust-core
cargo check # все 5 крейтов
cargo build --release
cargo run --bin aim-llm # :8770
```

## Переменные окружения

| Var | Назначение |
|--------------------------|-----------------------------------------|
| `DEEPSEEK_API_KEY` | DeepSeek |
| `GROQ_API_KEY` | Groq |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` | Google Gemini |
| `OLLAMA_URL` | по умолчанию `http://127.0.0.1:11434` |
| `AIM_ENV=prod` | переключает CORS в строгий режим |
| `AIM_CORS_ORIGIN` | разрешённый origin в проде |
| `AIM_LLM_PORT` и т. п. | переопределение портов сервисов |

## Что осталось (TODO)

Все провайдеры в `aim-llm/src/providers/*.rs` возвращают `bail!("TODO")`.
Перенос реальных HTTP-вызовов из `llm.py` — следующий шаг.
