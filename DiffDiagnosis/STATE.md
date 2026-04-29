# AIM/DiffDiagnosis — STATE.md

## Status
- Phase: 0 (kernel bootstrap)
- Created: 2026-04-29
- Owner: Dr. Jaba Tkemaladze (CEO GLA)
- Location: `~/Desktop/AIM/DiffDiagnosis/`
- Stack: Rust (axum + serde) backend, Phoenix LiveView frontend
- Diagnostic engine: deterministic algorithms over JSON schema + LLM layer (DeepSeek via AIM router)

## Active TODOs
- [ ] `sources/`: проверить полноту извлечённых глав Виноградова и Taylor
- [ ] `algorithms.json`: первая итерация формализации (10–20 алгоритмов)
- [ ] backend: `cargo init`, axum scaffold, `/health` endpoint
- [ ] backend: `engine.walk()` prototype + 5 unit tests
- [ ] frontend: `mix phx.new` + базовая LiveView `/case`
- [ ] integration: backend ↔ AIM/llm.py через HTTP-обёртку
- [ ] gold-standard: 20 кейсов из обеих книг
- [ ] `EVIDENCE.md`: дополнить полным списком ссылок с DOI

## Decision Log
- 2026-04-29: проект создан, выбран стек Rust+Phoenix.
- 2026-04-29: 9-файловая core схема (см. `~/.claude/.../feedback_core_md_files.md`).
- 2026-04-29: каноны = Vinogradov 3rd + Taylor "Difficult Diagnosis" 2nd.

## Что НЕ делать
- Не запускать LLM-генерацию алгоритмов в обход `sources/*.md`.
- Не дублировать функции `agents/doctor.py` — DiffDiagnosis отдельный движок.
- Не делать собственный git remote — это монорепо AIM.

## Milestones (✅)
- (пока пусто)

## Startup checklist
1. `CONCEPT.md`, `STATE.md`, `OPEN_PROBLEMS.md` прочитаны.
2. `cargo check` проходит.
3. `mix compile` проходит.
4. consistency check: 9 файлов core схемы на месте.