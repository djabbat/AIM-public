# MAP.md — AIM v7.0

**Версия:** 1.0
**Дата:** 2026-04-21
**Назначение:** Архитектурная карта. Зависимости модулей + связь с экосистемой CommonHealth. Источник истины — `CONCEPT.md` §5.

---

## 1. Карта зависимостей модулей

```
┌──────────────────────────────────────────────────────────┐
│                    USER INTERFACES                        │
│  medical_system.py (CLI)  aim_gui.py (GUI)  telegram_bot │
└──────────────┬───────────────┬────────────────┬──────────┘
               │               │                │
               └───────┬───────┴────────────────┘
                       ▼
            ┌──────────────────────┐
            │     AGENT LOOP       │
            │  agents/doctor.py    │  ← медицина
            │  agents/intake.py    │  ← файлы
            │  agents/lang.py      │  ← переводы
            └──────────┬───────────┘
                       │
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
     ┌────────┐   ┌────────┐    ┌──────────┐
     │ llm.py │   │ db.py  │    │ i18n.py  │
     │(router)│   │(SQLite)│    │ (9 lang) │
     └───┬────┘   └───┬────┘    └──────────┘
         │            │
    ┌────┴────┬───────┴───┬─────┐
    ▼         ▼           ▼     ▼
  Groq   DeepSeek       KIMI  Qwen
         (chat/reason)
                       │
            ┌──────────▼──────────┐
            │   config.py         │  ← ключи, пути, модели
            │   ~/.aim_env        │
            └─────────────────────┘

            ┌─────────────────────┐
            │  lab_reference.py   │  ← 59 аналитов
            └──────────┬──────────┘
                       ▼
            ┌─────────────────────┐
            │  Patients/          │
            │  ├── INBOX/         │  (автоматический intake)
            │  └── SURNAME_.../   │  (реальные данные)
            └─────────────────────┘
```

## 2. Таблица модулей и их зависимостей

| Модуль | Зависит от | Используется в |
|--------|-----------|----------------|
| `config.py` | `~/.aim_env` | все |
| `i18n.py` | — | `medical_system`, `aim_gui`, `telegram_bot`, `agents/*` |
| `llm.py` | `config`, `db` (кэш) | `agents/*`, `medical_system`, `aim_gui`, `telegram_bot` |
| `db.py` | `config` (путь к SQLite) | `llm`, `agents/doctor`, `agents/intake` |
| `lab_reference.py` | — | `agents/doctor`, `agents/intake` |
| `agents/doctor.py` | `llm`, `db`, `lab_reference`, `i18n` | `medical_system`, `aim_gui`, `telegram_bot` |
| `agents/intake.py` | `llm`, `db`, `i18n`, tesseract, rapidocr, pymupdf, pdfplumber | `medical_system`, `telegram_bot` |
| `agents/lang.py` | `llm`, `i18n` | `medical_system`, `aim_gui`, `telegram_bot` |
| `medical_system.py` | все | entrypoint |
| `aim_gui.py` | `llm`, `i18n`, `db`, `agents/*`, customtkinter | entrypoint (GUI) |
| `telegram_bot.py` | `llm`, `agents/*`, `i18n`, python-telegram-bot | entrypoint (bot) |

## 3. Экосистемные связи

```
          ┌──────────────────────────────┐
          │       CommonHealth/          │
          │   (EIC Pathfinder umbrella)  │
          └──────┬───────┬───────┬──────┘
                 │       │       │
         ┌───────▼─┐  ┌──▼──┐  ┌─▼──────┐
         │  CDATA  │  │  Ze │  │BioSense│
         └─────────┘  └─────┘  └────────┘
                 ▲
                 │ (знания о старении → AIM medical_knowledge)
                 │
        ┌────────┴────────┐
        │      AIM/       │  ← (standalone, но опирается на CDATA-знания)
        │  (этот проект)  │
        └─────────────────┘
                 │
                 ├── DrJaba (клиника → источник пациентов)
                 ├── Regenesis (протоколы фитотерапии → доктор-агент)
                 └── kSystem (8-язычный лексикон → многоязычие)
```

## 4. Данные: потоки

1. **Пациент-поток:** Patient WhatsApp-export → `Patients/INBOX/` → `intake.py` (OCR+PDF+AI) → `Patients/SURNAME_NAME_DATE/` → doctor.py (анализ) → ответ через CLI/GUI/Telegram.
2. **Запрос-поток:** User → CLI/GUI/Bot → Agent classifier → выбор агента → `llm.py::_route()` → LLM → ответ → `db.llm_cache` → user.
3. **Кэш-поток:** `llm.py` перед API-вызовом → проверка `db.llm_cache` (hash+model+24h TTL) → если есть — возврат кэша.

## 5. GitHub repos

| Репозиторий | Владелец | Содержимое |
|-------------|----------|------------|
| `djabbat/AIM` | private | полный код, CONCEPT, CLAUDE, TODO, PARAMETERS |
| `djabbat/AIM-public` | public | код минус CONCEPT/CLAUDE/TODO/PARAMETERS/MAP/Patients/ |

---

**Связь с CONCEPT.md:** §5 (архитектура) — этот MAP расширяет её в деталях.
