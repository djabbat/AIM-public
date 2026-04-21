# AIM v7.0 — CONCEPT ↔ CODE Audit

**Дата:** 2026-04-21
**Аудитор:** Claude (agent subprocess)
**Прошлый аудит:** `DEEP_AUDIT_2026-04-21.md` — описывал v6 артефакты (устарел)

---

## 1. Scope

Сопоставление документации (CONCEPT, CLAUDE, README, TODO, UPGRADE) с реальным кодом в `~/Desktop/AIM/`.

Исключены из анализа: `venv/`, `chroma_db/` (отсутствует), `__pycache__/`, `Patients/`, `reports/`, `*.md`, `fonts/`, `media/`, `docs/`, `logs/`, `agents/__pycache__/`.

## 2. Actual code inventory (2026-04-21)

| Файл | LoC | Назначение (из кода) |
|------|-----|----------------------|
| `medical_system.py` | 287 | CLI entry, класс `AIM`, меню m1..m8 |
| `aim_gui.py` | 441 | GUI (customtkinter), класс `AIMGui` |
| `telegram_bot.py` | 317 | Telegram-бот (python-telegram-bot) |
| `llm.py` | 261 | Роутер (`_route`), клиенты 4 провайдеров, `ask/ask_deep/ask_long/ask_multilang/ask_fast` |
| `config.py` | 90 | пути, ключи, модели, эндпоинты, языки, пороги |
| `db.py` | 182 | SQLite: patients, sessions, messages, llm_cache |
| `i18n.py` | 232 | 9 языков, ключи UI и системные промпты |
| `lab_reference.py` | 534 | 59 аналитов + `evaluate`, `format_result`, `batch_evaluate`, `categories`, `list_analytes` |
| `agents/__init__.py` | 6 | Экспорт DoctorAgent, IntakeAgent, LangAgent |
| `agents/doctor.py` | 234 | `DoctorAgent.diagnose/treatment_plan/interpret_labs/chat` |
| `agents/intake.py` | 261 | OCR, PDF, WhatsApp parser, scan_inbox |
| `agents/lang.py` | 212 | `LangAgent.detect/translate/explain_term/simplify` |
| `start.sh` | 6 | launcher (venv + medical_system.py) |
| `requirements.txt` | 22 | openai, dotenv, pytesseract, rapidocr, pymupdf, pdfplumber, python-telegram-bot, customtkinter, httpx |

**Всего:** 13 кодовых файлов, ~3057 LoC Python (соответствует цифре в DEEP_AUDIT).

## 3. Documented vs actual — mismatches

| # | Тип | Где документировано | Реальность | Классификация | Действие |
|---|-----|---------------------|------------|---------------|---------|
| 1 | Missing module | CONCEPT.md §5 table: `router.py` | Отдельного `router.py` нет; логика в `llm._route()` | FIX NOW | CONCEPT.md §5: таблица переписана, `router.py` удалён, добавлено примечание |
| 2 | Stale comment | CLAUDE.md L76: "`aim_gui.py` (когда будет создан)" | Файл создан 2026-04-16, 441 LoC | FIX NOW | CLAUDE.md: "уже существует" |
| 3 | Undocumented module | CLAUDE.md таблица архитектуры не упоминает `aim_gui.py` | Файл работает, m1..m8 | FIX NOW | CLAUDE.md: добавлен в таблицу |
| 4 | Undocumented module | CLAUDE.md не упоминает `telegram_bot.py` | Файл есть (317 LoC), работает | FIX NOW | CLAUDE.md: добавлен в таблицу |
| 5 | Undocumented module | CLAUDE.md не упоминает `lab_reference.py` | 59 аналитов, используется в `medical_system._lab_manual_check()` | FIX NOW | CLAUDE.md: добавлен в таблицу |
| 6 | Undocumented subpkg | CLAUDE.md не упоминает `agents/` | Директория с 3 агентами + __init__ | FIX NOW | CLAUDE.md: добавлены 3 строки (doctor/intake/lang) |
| 7 | Undocumented module | CONCEPT.md §5 table не упоминает `aim_gui.py`, `telegram_bot.py`, `lab_reference.py` | Все 3 существуют | FIX NOW | CONCEPT.md §5: добавлены 3 строки |
| 8 | Stale roadmap | CONCEPT.md §10: этапы 2-8 помечены 🔄 / ⏳ | Всё сделано 2026-04-16 (см. UPGRADE.md) | FIX NOW | CONCEPT.md §10: помечено ✅ + добавлены GUI / Telegram / lab_reference |
| 9 | Missing core files | `feedback_project_core` требует 10-файлового ядра | Есть только 5/10: CONCEPT/CLAUDE/README/TODO/UPGRADE. Нет: PARAMETERS, MAP, KNOWLEDGE, LINKS, MEMORY | FIX LATER | TODO.md: добавлена задача |
| 10 | Fallback incomplete | CONCEPT.md §3 fallback-цепочка включает только KIMI/Qwen/DeepSeek | `llm._fallback()` — то же самое, Groq не участвует | FIX LATER | TODO.md: добавить Groq в fallback |
| 11 | Missing citations | `lab_reference.py` — 59 аналитов | 0 цитирований / ссылок на источник | FIX LATER | TODO.md: добавить для каждого аналита источник |
| 12 | Architecture ambiguity | CONCEPT.md §5 показывает `router.py` как отдельный компонент | Логика внутри `llm.py` | FIX LATER (решение принципа) | TODO.md: решить — выносить или оставить |
| 13 | Non-existent component | CONCEPT.md §6 описывает "[Классификатор]" | Нет отдельного task classifier; агенты вызываются напрямую из CLI | FIX LATER | TODO.md: реализовать или переписать §6 |
| 14 | Stale doc artifact | `DEEP_AUDIT_2026-04-21.md` описывает фиктивные v6-модули (`bayesian_medical.py` etc.) | Этих модулей нет и в плане v7.0 не будет | FIX LATER | TODO.md: удалить/архивировать |
| 15 | Global CLAUDE.md out of sync | `~/CLAUDE.md` (global) строки 167-179 перечисляют v6 модули | Они не существуют в v7.0 | FIX LATER | TODO.md: синхронизировать global CLAUDE.md с локальным v7.0 |

## 4. FIX NOW applied

Всего применено: **5 правок** в 2 файлах (CONCEPT.md, CLAUDE.md).

### `CLAUDE.md`
- Обновлена таблица "Архитектура" — добавлены `aim_gui.py`, `telegram_bot.py`, `lab_reference.py` и 3 агента (doctor/intake/lang).
- Исправлен L76: «(когда будет создан)» → «(уже существует)».

### `CONCEPT.md`
- §5 таблица модулей — удалён несуществующий `router.py`, добавлены `aim_gui.py`, `telegram_bot.py`, `lab_reference.py` + примечание.
- §10 дорожная карта — все выполненные этапы помечены ✅ 2026-04-16, добавлены строки 8/9/10 (lab_reference / telegram / gui).

## 5. FIX LATER → TODO.md

Добавлено 7 пунктов в новую секцию "## CONCEPT↔CODE MISMATCHES (2026-04-21 audit)" в TODO.md.

## 6. Structural issues too big to auto-fix

1. **Core-file gap:** 5 из 10 файлов ядра отсутствуют (PARAMETERS/MAP/KNOWLEDGE/LINKS/MEMORY). Требуется ручная генерация из CONCEPT через DeepSeek.
2. **Архитектурное решение по `router.py`:** оставить в `llm.py` или выделить. Требует решения автора.
3. **`lab_reference.py` без цитирований** — клинически чувствительно, нужно вручную сопоставить нормы с источниками (NCBI / локальные ГОСТы).
4. **Глобальный `~/CLAUDE.md` описывает AIM v6** — устаревшие модули `bayesian_medical.py` и т.д. Нужно синхронизировать с v7.0, но это global config — требуется разрешение пользователя.

## 7. Key finding divergence from prior DEEP_AUDIT

Прошлый аудит (`DEEP_AUDIT_2026-04-21.md`, 28 KB) использовал v6 baseline и описывал несуществующие модули как "отсутствующие в реальности". В действительности CLAUDE.md AIM v7.0 (локальный) **никогда** не упоминал `bayesian_medical.py`, `diagnosis_engine.py` и т.д. — это устаревшие имена из **глобального** `~/CLAUDE.md`. Локальный AIM CLAUDE.md ссылается только на существующие модули и **в основном корректен**, за исключением отсутствующих модулей, которые были созданы после его написания (`aim_gui.py` / `telegram_bot.py` / `lab_reference.py`) + тонкие неточности (`router.py`).

**Вывод:** AIM v7.0 локально в лучшем состоянии, чем казалось по прошлому аудиту. Основная рассинхронизация — между **глобальным** `~/CLAUDE.md` (описывает v6) и реальным кодом (v7).
