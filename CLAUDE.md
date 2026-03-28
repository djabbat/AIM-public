# CLAUDE.md — AIM Project Instructions

This file provides guidance to Claude Code when working with AIM code.

---

## Project Identity

**AIM (Assistant of Integrative Medicine)** — Dr. Jaba Tkemaladze's local AI assistant for integrative medicine practice.

- Location: `~/Desktop/AIM/`
- Entry point (GUI): `aim_gui.py`
- Entry point (CLI): `medical_system.py`
- Entry point (bot only): `telegram_bot.py`
- DB: `aim.db` (SQLite via `db.py`)
- All LLM calls: `llm.py` (`ask_llm()` / `ask_deep()`)
- All audit records: `audit_log.py`

---

## Startup / Ecosystem Protocols

**Full startup rules:** `~/.claude/protocols/START.md` — read at every session start.

**Writing backlog:** `~/.claude/writing/NEEDTOWRITE.md`

**Concepts archive:** `~/.claude/writing/CONCEPTS.md`

---

## Key Rules

### 1. All LLM tasks → DeepSeek API

Route ALL text/reasoning tasks through DeepSeek API. Key: `~/.aim_env → DEEPSEEK_API_KEY`.
Entry: `~/Desktop/AIM/llm.py` → `ask_llm()` (fast) / `ask_deep()` (reasoning).

Models:
- `deepseek-chat` — all normal requests, chat, lab analysis
- `deepseek-reasoner` — diagnosis (Bayesian confidence < 60% or gap < 15%)

### 2. Architecture invariants

- All DB operations → `db.py`
- All LLM calls → `llm.py`
- All audit entries → `audit_log.py`
- Patient data **never** goes to git (covered by `.gitignore`)
- New modules must be added to `requirements.txt` and documented in `TODO.md`

### 3. Menu parity rule

`medical_system.py` (terminal menu) and `aim_gui.py` (GUI) must stay in sync.
When adding/removing a menu item → **change both files**.
Source of truth: key list in `i18n.py` (`m1`..`mw`, `mgui`, etc.).

### 4. Git push rule

Before every `git push`: ask "private or public repo?" → use `djabbat/AIM` (private) or `djabbat/AIM-public` (public).
Public repo excludes: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `MAP.md`.

### 5. Patient data

Patient folders live in `Patients/SURNAME_NAME_YYYY_MM_DD/`.
New files dropped in `Patients/INBOX/` are auto-processed by `inbox_watcher.py`.
WhatsApp contacts must be named `SURNAME П FIRSTNAME` (separator П/п/პ).

---

## Running AIM

```bash
# GUI mode (main, auto-starts Telegram bot)
cd ~/Desktop/AIM && source venv/bin/activate && python3 aim_gui.py

# CLI mode
cd ~/Desktop/AIM && source venv/bin/activate && python3 medical_system.py

# Bot only (headless server)
cd ~/Desktop/AIM && source venv/bin/activate && python3 telegram_bot.py

# Process all patients (OCR + PDF + AI)
cd ~/Desktop/AIM && source venv/bin/activate && python3 patient_intake.py --all

# DB stats / migration
cd ~/Desktop/AIM && source venv/bin/activate && python3 db.py --stats
cd ~/Desktop/AIM && source venv/bin/activate && python3 db.py --migrate

# Quick launcher
cd ~/Desktop/AIM && ./start.sh
```

---

## Module Map (quick reference)

| Module | Role |
|--------|------|
| `aim_gui.py` | Main GUI (tkinter), auto-starts bot |
| `medical_system.py` | CLI menu, SYSTEM_PROMPT |
| `db.py` | SQLite layer — patients, labs, diagnoses, ze_hrv |
| `llm.py` | Unified LLM calls (DeepSeek API) |
| `audit_log.py` | Audit log → `logs/audit.jsonl` |
| `patient_intake.py` | Pipeline: OCR → PDF → labs → diagnosis → DB |
| `ocr_engine.py` | Tesseract / rapidocr |
| `lab_parser.py` | Extract lab values from text |
| `lab_reference.py` | 165+ reference ranges |
| `diagnosis_engine.py` | Bayesian + DeepSeek R1 |
| `space_nutrition.py` | Nutrition protocol (47 forbidden / 69 allowed) |
| `ze_ecg.py` | RR → Ze-flow, HRV, classification |
| `wearable_importer.py` | BLE Heart Rate (UUID 0x180D) |
| `telegram_bot.py` | aiogram 3.x bot "DrJaba" |
| `inbox_watcher.py` | Watcher for Patients/INBOX/ |
| `whatsapp_importer.py` | Parse WhatsApp TXT exports |
| `tg_desktop_importer.py` | Parse Telegram Desktop JSON exports |
| `cdata_bridge.py` | CDATA Rust simulation bridge |
| `knowledge_graph.py` | Patient knowledge graph |
| `pdf_export.py` | PDF patient report export |
| `backup_github.py` | Auto-backup to GitHub (3rd of each month) |
| `i18n.py` | All UI strings (RU/KA/EN) |
| `config.py` | Central config, paths, logging |
| `auth.py` | Authentication |

---

## Ecosystem integrations

| Source | Data | Module |
|--------|------|--------|
| Ze + HealthWearable | RR/HRV | `ze_ecg.py` |
| WhatsApp/Telegram | Correspondence | importers |
| Labs (PDF/photo) | OCR + parse | `patient_intake.py` |
| ClinicA | Clinic patients | `patient_intake.py` |
| CDATA | Aging simulation | `cdata_bridge.py` |
| Regenesis | Treatment protocols | `knowledge/` |
| Dietebi | Clinical cases | `dietebi_importer.py` |

---

*AIM — Assistant of Integrative Medicine. Dr. Jaba Tkemaladze, Georgia. 2026.*
