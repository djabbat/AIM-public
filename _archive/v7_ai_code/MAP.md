# MAP.md — AIM v7.0

**Версия:** 1.1 (refreshed 2026-05-07 после overnight cornerstone session)
**Дата:** 2026-04-21 (initial); 2026-05-07 sync с Phase 4/5/8 + cornerstone
**Назначение:** Архитектурная карта. Зависимости модулей + связь с экосистемой CommonHealth. Источник истины — `CONCEPT.md` §5.

> **2026-05-07 changelog:** добавлены 7 cornerstone Rust crates
> (`aim-pam`, `aim-disagreement`, `aim-codesign`, `aim-coach` +
> `aim-llm` HTTP service hardening + `aim-llm-router` integration);
> 4 Phase-8 Python→Rust shims (`smart_routing`, `reflexion`,
> `interactions`, `regimen_validator`); 6 cornerstone Phoenix routes
> (`/pam`, `/codesign/:id`, `/disagreement`, `/activation`,
> `/coaching/:id`, `/about`); L_AGENCY 4-й extended kernel law
> wired into production `decide` (Fix #1) + `doctor.treatment`
> (P1.1 today). Полный список — `docs/audits/AUDIT_DEEP_2026-05-07.md`.

---

## 1. Карта зависимостей модулей

```
┌──────────────────────────────────────────────────────────┐
│ USER INTERFACES │
│ medical_system.py (CLI) aim_gui.py (GUI) telegram_bot │
└──────────────┬───────────────┬────────────────┬──────────┘
 │ │ │
 └───────┬───────┴────────────────┘
 ▼
 ┌──────────────────────┐
 │ AGENT LOOP │
 │ agents/doctor.py │ ← медицина
 │ agents/intake.py │ ← файлы
 │ agents/lang.py │ ← переводы
 └──────────┬───────────┘
 │
 ┌────────────┼─────────────┐
 ▼ ▼ ▼
 ┌────────┐ ┌────────┐ ┌──────────┐
 │ llm.py │ │ db.py │ │ i18n.py │
 │(router)│ │(SQLite)│ │ (9 lang) │
 └───┬────┘ └───┬────┘ └──────────┘
 │ │
 ┌────┴────┬───────┴───┬─────┐
 ▼ ▼ ▼ ▼
 Groq DeepSeek KIMI Qwen
 (chat/reason)
 │
 ┌──────────▼──────────┐
 │ config.py │ ← ключи, пути, модели
 │ ~/.aim_env │
 └─────────────────────┘

 ┌─────────────────────┐
 │ lab_reference.py │ ← 71 аналит
 └──────────┬──────────┘
 ▼
 ┌─────────────────────┐
 │ Patients/ │
 │ ├── INBOX/ │ (автоматический intake)
 │ └── SURNAME_../ │ (реальные данные)
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
| **Patient as a Project cornerstone (2026-05-07)** | | |
| `crates/aim-patient-memory` | `chrono`, `serde` | `aim-patient-owner`, `aim-pam` |
| `crates/aim-pam` | `aim-patient-memory` | `agents/pam_tracker.py`, `pam_live.ex`, `activation_live.ex` |
| `crates/aim-disagreement` | `serde` | `agents/automation_bias_detector.py`, `disagreement_live.ex` |
| `crates/aim-codesign` | `chrono`, `serde` | `agents/codesign_log.py`, `codesign_live.ex`, L_AGENCY hand-off |
| `crates/aim-kernel` (extended) | `aim-patient-memory` | adds `evaluate_l_agency` + `extended` field on `Scored`; `decide` now enforces all 4 extended laws |
| `agents/pam_tracker.py` (shim) | subprocess `aim-pam` binary | `agents/patient_memory.to_kernel_dict` (auto-populates `activation_level`) |
| `agents/automation_bias_detector.py` (shim) | subprocess `aim-disagreement` | UI for clinician confidence elicitation |
| `agents/codesign_log.py` (shim) | subprocess `aim-codesign` | sets `context.patient_codesigned` for L_AGENCY |
| `pam_live.ex` / `codesign_live.ex` / `disagreement_live.ex` / `activation_live.ex` | System.cmd → Rust binaries; `:timer.send_interval/2` | L3 cornerstone UI (`/pam`, `/codesign/:id`, `/disagreement`, `/activation`) |

## 2.5. Internal microservices (AIM-side, not external ecosystem)

Помимо main agent loop AIM держит **2 in-tree micro-сервиса**, вызываемых
через REST из `aim-doctor` Rust binary. Они физически живут в этом
репозитории, но запускаются как отдельные процессы (Rust backend +
optional frontend) на локальных портах:

| Subproject | Port | Что делает | Backend | Frontend | Caller |
|---|---|---|---|---|---|
| `DiffDiagnosis/` | 8765 | Дет.движок дифдиагностики (Виноградов / Taylor алгоритмы) | Rust (Cargo) | static + Phoenix-style | `aim-doctor::diffdx` (`AIM_DIFFDX_URL`); фигурирует в `about_live.ex` |
| `SSA/` | 8766 | Системный Синдромальный Анализ CBC+ESR (28 параметров → 5-зонная дискретизация) | Rust (Cargo) + `_build_kernel.py` (kernel generator из Excel) | static | `aim-doctor::ssa` (`AIM_SSA_URL`); входной слой для DiffDiagnosis |

**Канонические документы** этих subprojects:
- `docs/diffdiagnosis/{CONCEPT,DESIGN,EVIDENCE,OPEN_PROBLEMS}.md`
- `docs/ssa/{CONCEPT,DESIGN,EVIDENCE,OPEN_PROBLEMS}.md`

Подпроекты НЕ имеют отдельного git-репо (правило `feedback_subproject_git_rule`);
обновление их кода = обычный commit в этот репо.

## 3. Экосистемные связи

```
 ┌──────────────────────────────┐
 │ CommonHealth/ │
 │ (EIC Pathfinder umbrella) │
 └──────┬───────┬───────┬──────┘
 │ │ │
 ┌───────▼─┐ ┌──▼──┐ ┌─▼──────┐
 │ CDATA │ │ Ze │ │BioSense│
 └─────────┘ └─────┘ └────────┘
 ▲
 │ (знания о старении → AIM medical_knowledge)
 │
 ┌────────┴────────┐
 │ AIM/ │ ← (standalone, но опирается на CDATA-знания)
 │ (этот проект) │
 └─────────────────┘
 │
 ├── DrJaba (клиника → источник пациентов)
 ├── Regenesis (протоколы фитотерапии → доктор-агент)
 └── kSystem (8-язычный лексикон → многоязычие)
```

## 4. Данные: потоки

1. **Пациент-поток:** Patient WhatsApp-export → `Patients/INBOX/` → `intake.py` (OCR+PDF+AI) → `Patients/SURNAME_NAME_DATE/` → doctor.py (анализ) → ответ через CLI/GUI/Telegram.
2. **Запрос-поток:** User → CLI/GUI/Bot → Agent classifier → выбор агента → `llm.py::_route` → LLM → ответ → `db.llm_cache` → user.
3. **Кэш-поток:** `llm.py` перед API-вызовом → проверка `db.llm_cache` (hash+model+24h TTL) → если есть — возврат кэша.

## 5. GitHub repos

| Репозиторий | Владелец | Содержимое |
|-------------|----------|------------|
| `djabbat/AIM` | private | полный код, CONCEPT, CLAUDE, TODO, PARAMETERS |
| `djabbat/AIM-public` | public | код минус CONCEPT/CLAUDE/TODO/PARAMETERS/MAP/Patients/ |

---

**Связь с CONCEPT.md:** §5 (архитектура) — этот MAP расширяет её в деталях.
