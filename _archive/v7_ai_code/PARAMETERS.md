# PARAMETERS.md — AIM v7.0

**Версия:** 1.0
**Дата:** 2026-04-21
**Назначение:** Ключевые числовые константы, пороги роутинга, модели, лимиты. Источник истины — `CONCEPT.md` + `config.py`.

---

## 1. LLM-провайдеры и модели (фактически в `config.py` 2026-05-07)

| Провайдер | Модель | Контекст | Tier-функция в `llm.py` |
|-----------|--------|---------|---|
| DeepSeek | `deepseek-chat` | 64k | `ask` — default chat |
| DeepSeek | `deepseek-reasoner` | 64k | `ask_deep` — diagnosis / reasoning |
| Groq | `llama-3.3-70b-versatile` | 8k | `ask_fast` (large) |
| Groq | `llama-3.1-8b-instant` | 8k | `ask_fast` (default) |
| Anthropic | `claude-opus-4-7` | 200k | `ask_critical` — гранты, спорные дифдиагнозы |
| Anthropic | `claude-sonnet-4-6` | 200k | `ask_critical` fallback |
| Google | `gemini-2.5-pro` | 1M | `ask_critical` / `ask_long` (free 50/day) |
| Google | `gemini-2.5-flash-lite` | 1M | high-volume free tier |
| Ollama | `qwen2.5:7b` / `:3b` / `deepseek-r1` | local | offline fallback |

> **Не реализовано (vapor cleanup 2026-05-07):** KIMI/Moonshot 128k и Qwen
> DashScope client'ы отсутствуют в `llm.py`. Long-context обслуживается
> DS-chat 64k или Gemini Flash 1M. Многоязычность — DS-chat (без Qwen).

## 2. Пороги роутинга (в `llm.py::_route` + `config.py`)

| Параметр | Значение | Комментарий |
|----------|----------|-------------|
| `REASONING_KEYWORDS` | diagnosis / differential / analysis / reasoning + RU аналоги | → DS-reasoner |
| `is_critical` regex | grant / diagnosis / treatment / contract | → ensemble (Claude + DS-pro + Ollama) |


**Note:** The regex for `is_critical` contains the keywords "grant / diagnosis / treatment / contract". This may cause false-positive routing of non-critical user messages (e.g., "I need a treatment plan" or "grant proposal"). Consider narrowing the regex to require additional context (e.g., presence of urgency markers like "urgent", "immediately", or a numeric threshold). Alternatively, implement a secondary classifier to reduce false positives.

| `LLM_TIMEOUT` | 600s | глобальный per-call |
| Long context cutoff | 30k tokens | выше — DS-chat 64k или Gemini Flash 1M |
| Auto-compact threshold | 30k tokens | history compress в `agents/generalist.py` |

## 3. Языки (9)

`ru · en · fr · es · ar · zh · ka · kz · da` — см. `i18n.py`.

## 4. Лабораторные нормы (`lab_reference.py`)

- Всего аналитов: **59**
- Единицы: SI (по умолчанию); конверсия в conventional units доступна
- Источник: NIH MedlinePlus + Mayo Clinic reference intervals 2024

## 5. База данных (`db.py`)

- SQLite-файл: `aim.db` (в корне проекта, gitignored)
- Таблицы: `patients`, `sessions`, `messages`, `llm_cache`
- TTL LLM-кэша: **24 часа** для одинаковых запросов (hash prompt + model)

## 6. Пациенты

- Формат папки: `SURNAME_NAME_YYYY_MM_DD/`
- INBOX: `Patients/INBOX/` — автоматический intake
- Детектор WhatsApp-контактов: разделитель **P / П / პ** (SURNAME P FIRSTNAME)
- OCR-движки (fallback-цепь): tesseract → rapidocr → ошибка

## 7. Меню CLI/GUI (ключи в `i18n.py`)

`m1 · m2 · m3 · m4 · m5 · m6 · m7 · m8 · mq · mw · mgui`

При добавлении — **править и `medical_system.py`, и `aim_gui.py`**.

## 8. Переменные окружения (`~/.aim_env`)

| Ключ | Обязателен | Комментарий |
|------|-----------|-------------|
| `DEEPSEEK_API_KEY` | да | основной (chat + reasoner) |
| `GROQ_API_KEY` | рекомендуется | скорость, бесплатный tier |
| `ANTHROPIC_API_KEY` | опц. | critical tier (Claude Opus 4.7) |
| `GEMINI_API_KEY` | опц. | free 50/day на 2.5-pro, до 1500/day на flash-lite |
| `TELEGRAM_BOT_TOKEN` | опц. | бот |
| `TELEGRAM_ALLOWED_IDS` | опц. | allow-list (или `/link` через hub) |
| `AIM_HUB_URL`, `AIM_USER_TOKEN` | опц. | multi-user mode (node→hub) |

## 9. Производительность (целевые значения)

| Операция | Целевое время |
|----------|---------------|
| `ask_fast` (Groq llama-3.1-8b) | <1 сек |
| `ask` (DeepSeek-chat) | <5 сек |
| `ask_deep` (DeepSeek-reasoner) | <30 сек |
| `ask_long` (DS-chat 64k или Gemini Flash 1M) | <60 сек |
| `ask_critical` (Claude Opus 4.7 + ensemble) | <45 сек |
| OCR одного скриншота | <10 сек |
| Intake одного пациента (5 файлов) | <120 сек |

---

**Связь:** все числа — продублированы в `config.py`. При расхождении — `config.py` побеждает; обновлять этот файл.
