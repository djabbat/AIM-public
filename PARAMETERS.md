# PARAMETERS.md — AIM v7.0

**Версия:** 1.0
**Дата:** 2026-04-21
**Назначение:** Ключевые числовые константы, пороги роутинга, модели, лимиты. Источник истины — `CONCEPT.md` + `config.py`.

---

## 1. LLM-провайдеры и модели

| Провайдер | Модель | Контекст (макс) | Использование |
|-----------|--------|-----------------|---------------|
| Groq | `llama-3.3-70b-versatile` | 8k | `ask_fast()` — простые запросы <3k токенов, ответ <1 сек |
| DeepSeek | `deepseek-chat` | 64k | `ask()` — стандартные RU/EN/FR/ES, код |
| DeepSeek | `deepseek-reasoner` | 64k | `ask_deep()` — диагностика, рассуждения |
| KIMI | `moonshot-v1-128k` | 128k | `ask_long()` — PDF, выписки, длинные документы |
| Qwen | `qwen-turbo` | 8k | `ask_multilang()` — AR/ZH/KA/KZ/DA (лёгкие) |
| Qwen | `qwen-max` | 32k | `ask_multilang()` — сложный многоязычный анализ |

## 2. Пороги роутинга (в `llm.py::_route()`)

| Параметр | Значение | Комментарий |
|----------|----------|-------------|
| `LONG_CONTEXT_THRESHOLD` | 16,000 токенов | выше — KIMI |
| `FAST_THRESHOLD` | 3,000 токенов | ниже + простой запрос — Groq |
| `QWEN_LANGS` | `{ar, zh, ka, kz, da}` | эти языки → Qwen |
| `REASONING_TRIGGERS` | `{diagnosis, differential, analysis, reasoning}` | → DeepSeek-reasoner |

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
| `DEEPSEEK_API_KEY` | да | основной |
| `KIMI_API_KEY` | рекомендуется | PDF/длинный контекст |
| `QWEN_API_KEY` | рекомендуется | многоязычность |
| `GROQ_API_KEY` | рекомендуется | скорость |
| `TELEGRAM_BOT_TOKEN` | опционально | бот |
| `TELEGRAM_ALLOWED_ID` | опционально | allow-list |

## 9. Производительность (целевые значения)

| Операция | Целевое время |
|----------|---------------|
| `ask_fast()` (Groq) | <1 сек |
| `ask()` (DeepSeek-chat) | <5 сек |
| `ask_deep()` (DeepSeek-reasoner) | <30 сек |
| `ask_long()` (KIMI, PDF) | <60 сек |
| OCR одного скриншота | <10 сек |
| Intake одного пациента (5 файлов) | <120 сек |

---

**Связь:** все числа — продублированы в `config.py`. При расхождении — `config.py` побеждает; обновлять этот файл.
