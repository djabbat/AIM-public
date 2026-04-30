# CLAUDE.md — AIM v7.0

---

## Startup Protocol

**Полные правила:** `~/Desktop/Claude/protocols/START.md`

---

## Multi-user (Hub + Node)

AIM работает в двух режимах через `AIM_ROLE`:

| Режим | Назначение | LLM | DB | Запуск |
|---|---|---|---|---|
| `hub` (1 шт) | users / tokens / audit / `/link` codes | НЕТ | `aim_hub.db` | `bash start.sh hub` |
| `node` (default, у каждого юзера локально) | chat / memory / patients / LLM | Ollama + DeepSeek-V4 | `aim.db` | `bash start.sh web` |

**Установка:**
- Linux/macOS node: `bash scripts/install_node.sh` (ставит Ollama + qwen2.5:7b/3b + venv + `~/.aim_env`)
- Windows node: `powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1`
- Hub: `bash scripts/install_hub.sh` (минимум deps, без Ollama, создаёт первого admin)

**Auth flow node→hub:**
1. Admin создаёт юзера: `python -m scripts.user_admin create <username>`
2. Admin выдаёт токен: `python -m scripts.user_admin token <username>` → копирует в `~/.aim_env` пользователя как `AIM_USER_TOKEN` + `AIM_HUB_URL`
3. Node при старте бьёт `/api/auth/validate-token` у hub'а, кэширует ответ 24h, шлёт heartbeat в `/api/nodes/heartbeat`
4. Offline grace: 7 дней по кэшу при недоступном hub'е (`AIM_OFFLINE_GRACE`)
5. Telegram /link — admin: `python -m scripts.user_admin link-code <username>` → 6-значный код, юзер шлёт боту `/link 123456`

**LLM на node — приоритеты роутинга:**
1. Reasoning task → DeepSeek-V4-pro (cloud) если есть `DEEPSEEK_API_KEY`, иначе Ollama deepseek-r1
2. Long-context (>30K токенов) → DeepSeek-V4-flash (1M) если есть ключ
3. Default chat → Ollama qwen2.5:7b (local, $0)
4. ask_fast → Ollama qwen2.5:3b (local, instant)

**Без Ollama** node работает на DeepSeek/Groq cloud (как раньше). **Без DeepSeek** — на локальном Ollama. Hybrid рекомендован.

---

## Архитектура

AIM v7.0 — гибридный LLM-роутер. Ядро:

| Файл | Роль |
|------|------|
| `medical_system.py` | Точка входа (CLI), agent loop |
| `aim_gui.py` | GUI (customtkinter), паритет с CLI |
| `telegram_bot.py` | Telegram-бот (python-telegram-bot) с `/link` для multi-user |
| `llm.py` | Роутер: Ollama (local) + DeepSeek-V4 (reasoner/long) + Groq (fast cloud) |
| `config.py` | Ключи, модели, пути, языки |
| `agents/auth.py` | Hub-side: users / JWT / API tokens / audit / link codes |
| `agents/hub_client.py` | Node-side: validate AIM_USER_TOKEN against hub, 24h cache |
| `web/api.py` | FastAPI; `AIM_ROLE=hub`/`node` переключает routes |
| `scripts/user_admin.py` | Hub admin CLI: create / list / token / link-code / nodes / audit |
| `scripts/install_node.{sh,ps1}` | Linux+mac / Windows installer (Ollama + venv + ~/.aim_env) |
| `scripts/install_hub.{sh,ps1}` | Hub installer (минимум deps, бутстрап admin user) |
| `i18n.py` | 9 языков (ООН-6 + KA + KZ + DA) |
| `db.py` | SQLite: пациенты, сессии, кэш |
| `lab_reference.py` | База лабораторных норм (59 аналитов) |
| `agents/doctor.py` | Диагностика, лечение, интерпретация анализов, чат, `check_patient_regimen` |
| `agents/intake.py` | OCR (tesseract/rapidocr), PDF (pymupdf/pdfplumber), WhatsApp, INBOX |
| `agents/lang.py` | Перевод 4 типов, detect, explain_term, simplify |
| `agents/interactions.py` | Drug-drug interaction checker (v0.1 stub, ~30 pairs; P0 audit 2026-04-21). PMID-verified; `check_interaction`, `check_regimen`, `format_regimen_report`. TODO: RxNav/DrugBank integration |
| `tests/test_interactions.py` | Unit tests для `agents/interactions.py` (16 cases) |

---

## Правило LLM

**Никогда не вызывать API напрямую.** Всегда через `llm.py`:

```python
from llm import ask, ask_deep, ask_long, ask_multilang, ask_fast
```

Роутер сам выберет модель.

---

## Правило языков

**9 языков везде.** Ни одна строка UI не пишется жёстко — только через `i18n.py`:

```python
from i18n import t
print(t("menu_title", lang))
```

---

## Пациенты (СТРОГО)

- `Patients/` — **НИКОГДА** не читать, не изменять, не коммитить без явной команды
- Новые файлы → `Patients/INBOX/`
- **Формат папок:** `SURNAME_NAME_YYYY_MM_DD/` где `YYYY_MM_DD` = **дата рождения** пациента
  (определяется auto из анализов через intake pipeline)
- **Если ДР неизвестна ИЛИ сомнительна** → placeholder `2000_01_01` (sentinel: легко
  увидеть в выборках, заведомо не настоящая ДР, требует уточнения у врача).
  Сомнительная = противоречит другим источникам (например, папка датирована визитом
  2026, а в файле внутри ДР 2001) — лучше явный placeholder, чем неверная конкретика.
  Никогда НЕ оставлять без даты (`SURNAME_NAME_/` нарушает naming + ломает intake
  auto-detection)
- **Префикс `_` для AI-сгенерированных файлов:** `_ai_analysis.txt`, `_report_*.pdf`
  (отличает их от исходников: jpeg/pdf от пациента, `*_ocr.txt`/`*_text.txt` — извлечения)
- **Каждая папка должна содержать:** `MEMORY.md` (canonical state, см. `agents/patient_memory.py`)
  + опционально `AI_LOG.md` (создаётся kernel.py при первом decision)
- **Тесты НЕ создают артефакты в `Patients/`** — см. `tests/conftest.py` (PATIENTS_DIR
  изолирован в `tests/_runtime_fixtures/`)

---

## Ключи

Только в `~/.aim_env` (или `%USERPROFILE%\.aim_env` на Windows). Никогда в коде.

```
# Multi-user (если node ходит в hub)
AIM_HUB_URL=https://hub.example.com
AIM_USER_TOKEN=aim_xxx       # выдаёт admin: python -m scripts.user_admin token <user>
AIM_NODE_ID=my-laptop-jaba   # опц. (default: hostname-username)

# LLM
DEEPSEEK_API_KEY=...         # опционально (для reasoner/long-context)
GROQ_API_KEY=...             # опционально (cloud fast tier)
                             # Ollama не требует ключа — только http://127.0.0.1:11434

# Telegram (опц.)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_IDS=123,456 # static allow-list (или используй /link через hub)
```

---

## Git push

Перед каждым push спрашивать: приватный (`djabbat/AIM`) или публичный (`djabbat/AIM-public`)?

Публичный **исключает**: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `Patients/`

---

## При добавлении пункта меню

Изменить **оба** файла: `medical_system.py` + `aim_gui.py` (уже существует).
Источник истины — ключи в `i18n.py` (m1..m8, mq и т.д.).
