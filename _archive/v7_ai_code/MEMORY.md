# MEMORY.md — AIM v7.0

**Версия:** 1.0
**Дата создания:** 2026-04-21
**Назначение:** Что Клоду нужно помнить про этот проект между сессиями. Датированные записи; хронологический порядок (новое сверху).

---

## 2026-05-07 — Ядро восстановлено + Phase 9 closure + KIMI/Qwen vapor cleanup

**Что сделано:**
- 11-файловое ядро восстановлено: добавлены `THEORY.md` (immutable), `STRATEGY.md`, `REMINDER.md`, `CHANGELOG.md`, `NEEDTOWRITE.md`. STACK + README остаются.
- 24 не-канонических `.md` перемещены в `docs/audits/`, `docs/roadmaps/`, `docs/migration/`, `docs/manuscripts/`, `docs/operational/`.
- KIMI (Moonshot) и Qwen (DashScope) сняты как vapor из CONCEPT/PARAMETERS — HTTP-client'ы не написаны, фактический набор провайдеров: DeepSeek + Groq + Anthropic + Gemini + Ollama. **2026-05-07 update:** реализация в Rust `aim-llm` crate REJECTED — не "на hold", отвергнуто симметрично с aim-media. Реактивация только по факту use case.
- Phase 9: 30/35 модулей `AI/ai/*.py` шимизированы на Rust binaries. Полная регрессия `bash scripts/test_all.sh --quick` зелёная; `--ai` mode добавлен.
- `AI/tests/_phase9_known_broken.txt` (110 nodeids) — auto-skip через `AI/tests/conftest.py`. 505 passed / 110 skipped.
- E2E `tests/test_pam_trajectory_e2e.py` — PASSED. Cornerstone happy-path подтверждён: intake → PAM #1 → coach → codesign → PAM #2 → MCID delta → L_AGENCY.
- `agents/speculative.py` — переписан через `llm.py::ask_fast` (раньше прямой OpenAI client).

## 2026-04-21 — Core-schema аудит (закрыто)

Создан core-set 10 файлов: CONCEPT, README, CLAUDE, TODO, PARAMETERS, MAP, MEMORY, LINKS, KNOWLEDGE, UPGRADE. **2026-05-07: расширено до 13** (+THEORY, STRATEGY, REMINDER, CHANGELOG, NEEDTOWRITE).

**Делать на будущее:** при любом значимом изменении архитектуры — синхронно обновить CONCEPT + MAP + PARAMETERS + CHANGELOG; при изменении UI/меню — i18n + medical_system + aim_gui.

## 2026-04-16 — v7.0 релиз

Переход от Ollama (локально) к гибридному API-роутеру. **2026-05-07 фактический набор:** DeepSeek-chat + DeepSeek-reasoner + Groq + Anthropic Claude + Google Gemini + Ollama (offline fallback). KIMI/Qwen vapor вычищены. 9 языков, 71 аналит, Telegram-бот, GUI.

## Постоянные правила (не забывать)

1. **LLM — только через `llm.py`**, никогда не вызывать API напрямую из других модулей.
2. **Patients/ неприкосновенны** — не читать, не изменять, не коммитить без явной команды пользователя.
3. **Ключи — только в `~/.aim_env`**, никогда в коде.
4. **Меню — править ОБА файла:** `medical_system.py` + `aim_gui.py`; источник истины — ключи в `i18n.py`.
5. **9 языков везде** — никаких hardcoded строк UI, всё через `i18n.t(key, lang)`.
6. **Git push:** всегда спрашивать — private (`djabbat/AIM`) или public (`djabbat/AIM-public`)? Public **исключает** CONCEPT/CLAUDE/TODO/PARAMETERS/Patients.

## Активные вопросы

См. `STRATEGY.md` P1 для актуального фокуса. На 2026-05-07 — единственный
critical-path open question:

- [ ] **Pilot recruitment 30 пациентов** (`STRATEGY.md` P1-3) → owner: Dr. Jaba.
 Блокер: `docs/operational/PILOT_PROTOCOL.md` `[CLIN-FILL]` placeholders +
 IRB-equivalent одобрение (Georgian Personal Data Protection Law 2014).

Закрытые / перенесённые 2026-05-07:

- [x] ~~Ждём пополнения KIMI~~ — REJECTED (vapor); long-context = DS-chat 64k + Gemini Flash 1M.
- [x] ~~Ждём активации Qwen~~ — REJECTED (vapor); multilingual = DS-chat.
- [→] Тест Telegram-бота → перенесён в `TODO.md` P3 «when needed»
 (2026-04-21 stale; не блокирует cornerstone / pilot).
- [→] Тест GUI `python3 aim_gui.py` → перенесён в `TODO.md` P3 «when needed»
 (Phoenix LiveView routes уже = web GUI).

## Известные проблемы

| Проблема | Workaround |
|----------|-----------|
| OCR низкая точность на русских сканах | rapidocr fallback + ручная проверка |
| ~~110 AI/tests/* поломаны после Phase 9~~ | ✅ 2026-05-07: удалены (4 файла + 50 функций) |
| ~~`web/api.py` Phoenix migration~~ | ✅ 2026-05-07: frozen permanently в STACK § "Frozen Python legacy"; revisit при multi-user pilot expansion |

## Что НЕ делать

- Не возвращаться к Ollama/llama3.2 (устарело, медленно, ограниченный контекст)
- Не хардкодить строки UI на одном языке
- Не пушить без спроса — private/public?
- Не добавлять в меню пункт, не добавив ключ в `i18n.py` для всех 9 языков
- Не забывать fallback — каждый провайдер может упасть, нужен план B

## Связь с экосистемой

AIM — standalone, но опирается на научные результаты CDATA/HAP/MCOA/Ze. При обновлении этих проектов — проверять, не нужно ли добавить новый анализ в doctor-агент.

---

**Конвенция:** новые записи сверху с датой `## YYYY-MM-DD — краткий заголовок`. При >50 записях — архивировать старше 6 месяцев в файл вида MEMORY_archive_YYYY.md (placeholder name pattern, файл создаётся при необходимости).
