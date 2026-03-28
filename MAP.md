# MAP.md — AIM Project Map

Complete file and module map for AIM (Assistant of Integrative Medicine).

---

## Directory Structure

```
~/Desktop/AIM/
│
├── aim_gui.py              ← MAIN ENTRY POINT (GUI + auto-start bot)
├── medical_system.py       ← CLI menu, SYSTEM_PROMPT, interactive shell
├── telegram_bot.py         ← aiogram 3.x Telegram bot "DrJaba"
│
├── ── CORE PIPELINE ──────────────────────────────────────────────────
├── patient_intake.py       ← Full pipeline: OCR → PDF → labs → diagnosis → DB
│     ├── ocr_engine.py         Tesseract / rapidocr fallback
│     ├── lab_parser.py         Extract lab values from text
│     ├── lab_reference.py      165+ reference ranges (gender/age-aware)
│     └── diagnosis_engine.py   Bayesian differential diagnosis + DeepSeek R1
│
├── ── DATA LAYER ─────────────────────────────────────────────────────
├── db.py                   ← SQLite layer (patients, lab_snapshots, diagnoses,
│                             ze_hrv, knowledge, audit_log)
├── audit_log.py            ← Audit log → logs/audit.jsonl
├── config.py               ← Central config, paths, logging setup
├── llm.py                  ← Unified LLM calls (DeepSeek API)
├── i18n.py                 ← All UI strings: RU / KA / EN
├── auth.py                 ← Authentication (session, tokens)
│
├── ── MEDICAL MODULES ────────────────────────────────────────────────
├── space_nutrition.py      ← Nutrition protocol (47 forbidden / 69 allowed)
├── ze_ecg.py               ← RR → Ze-flow, HRV, classification
├── wearable_importer.py    ← BLE Heart Rate Profile (UUID 0x180D)
├── knowledge_graph.py      ← Patient knowledge graph
├── patient_analysis.py     ← Interactive patient case history analysis
├── patient_network.py      ← Patient relationship network
├── medical_parser.py       ← Load patient records from Patients/
├── regenesis_protocol.py   ← Regenesis treatment protocol integration
├── drug_interaction_checker.py ← Drug interaction checking
├── numerology.py           ← Numerological profile from patient DOB
│
├── ── IMPORTERS / BRIDGES ────────────────────────────────────────────
├── whatsapp_importer.py    ← Parse WhatsApp TXT exports
├── tg_desktop_importer.py  ← Parse Telegram Desktop JSON exports
├── telegram_chat_importer.py ← Telegram chat import utilities
├── telegram_search.py      ← Search Telegram history
├── cdata_bridge.py         ← CDATA Rust simulation bridge
├── dietebi_importer.py     ← Import Dietebi clinical cases (.docx)
├── cdata_nutrition.py      ← CDATA × nutrition integration
│
├── ── MONITORING / OUTPUT ────────────────────────────────────────────
├── literature_monitor.py   ← PubMed / arXiv literature monitor
├── pdf_export.py           ← Export PDF patient reports
├── trend_chart.py          ← HRV / lab trend charts
├── voice_input.py          ← Microphone → Whisper → text
├── inbox_watcher.py        ← Watcher for Patients/INBOX/ (2-sec polling)
│
├── ── SYSTEM / OPS ───────────────────────────────────────────────────
├── backup_github.py        ← Auto-backup to GitHub (3rd of month)
├── backup_data.py          ← Local data backup
├── config.json.example     ← Config template (copy to config.json)
├── requirements.txt        ← Python dependencies
├── install.sh              ← First-time install script
├── start.sh                ← Quick launcher (aim_gui.py)
├── build_deploy.sh         ← Build distributable archive
│
├── ── DOCUMENTATION ──────────────────────────────────────────────────
├── README.md               ← Public-facing documentation
├── CONCEPT.md              ← Full architectural spec (v6.0 vision)
├── CLAUDE.md               ← Claude Code instructions (this ecosystem)
├── TODO.md                 ← Tasks and roadmap
├── PARAMETERS.md           ← All configurable parameters
├── MAP.md                  ← This file
├── DOCX_FORMAT.md          ← Document formatting standards
├── INSTALL.md              ← Install instructions (brief)
├── ИНСТРУКЦИЯ.md           ← Instructions in Russian
│
├── ── DATA DIRECTORIES ───────────────────────────────────────────────
├── Patients/               ← Patient records (git-excluded)
│   ├── INBOX/              ← Drop files here for auto-intake
│   └── SURNAME_NAME_YYYY_MM_DD/  ← One folder per patient
├── knowledge/              ← Medical knowledge base files
├── logs/                   ← Log files (git-excluded)
│   └── audit.jsonl         ← Audit log of all actions
├── literature_digest/      ← Downloaded literature digests
├── reports/                ← Generated reports (git-excluded)
├── trend_reports/          ← HRV/lab trend reports (git-excluded)
├── search_results/         ← Search results cache (git-excluded)
├── backups/                ← Local backups (git-excluded)
├── feedback/               ← User feedback data
├── learning/               ← Self-learning data
│
├── ── RUNTIME DATA (git-excluded) ────────────────────────────────────
├── aim.db                  ← SQLite: all structured patient data
├── medical_knowledge.json  ← Self-learning knowledge base
├── processed_files.json    ← OCR processing log
├── medical_bayes.json      ← Bayesian network data
├── nutrition_rules.json    ← Nutrition protocol (editable from GUI)
├── author_publications.json ← Publication metadata
├── chat_history.json       ← Chat session history
├── projects_memory.json    ← General project memory
│
├── ── CODE SUBDIRS ───────────────────────────────────────────────────
├── agents/                 ← Agent base classes
├── integrations/           ← External integration stubs
├── config/                 ← Config files
├── projects/               ← Legacy project memory
│
└── venv/                   ← Python virtual environment (git-excluded)
```

---

## Data Flow

```
Ze + HealthWearable  →  RR/HRV data     →  ze_ecg.py         →  aim.db (ze_hrv)
WhatsApp export      →  .txt            →  whatsapp_importer  →  Patients/
Telegram export      →  .json           →  tg_desktop_importer→  Patients/
Lab PDFs / photos    →  OCR + parse     →  patient_intake     →  aim.db (labs)
CDATA Rust binary    →  aging sim       →  cdata_bridge       →  aim.db (diagnoses)
Regenesis protocol   →  treatment data  →  regenesis_protocol →  knowledge/
Dietebi .docx        →  clinical cases  →  dietebi_importer   →  aim.db (knowledge)
ClinicA              →  patient data    →  patient_intake     →  aim.db

aim.db               →  all data        →  medical_system.py  →  LLM analysis
aim.db               →  all data        →  aim_gui.py         →  GUI display
aim.db               →  patient data    →  telegram_bot.py    →  DrJaba bot replies
```

---

## GitHub Repos

| Repo | Contents | URL |
|------|----------|-----|
| `djabbat/AIM` | Full private repo | git@github.com:djabbat/AIM.git |
| `djabbat/AIM-public` | Public (no patient data, no internal docs) | github.com/djabbat/AIM-public |

Public repo excludes: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `MAP.md`, `Patients/`, `aim.db`, `*.json` (data).

---

## Key Commands

```bash
# Run
cd ~/Desktop/AIM && source venv/bin/activate && python3 aim_gui.py          # GUI
cd ~/Desktop/AIM && source venv/bin/activate && python3 medical_system.py   # CLI
cd ~/Desktop/AIM && source venv/bin/activate && python3 telegram_bot.py     # Bot

# Patient intake
cd ~/Desktop/AIM && source venv/bin/activate && python3 patient_intake.py --all
cd ~/Desktop/AIM && source venv/bin/activate && python3 patient_intake.py --patient SURNAME_NAME_YYYY_MM_DD

# DB
cd ~/Desktop/AIM && source venv/bin/activate && python3 db.py --stats
cd ~/Desktop/AIM && source venv/bin/activate && python3 db.py --migrate

# Backup
cd ~/Desktop/AIM && source venv/bin/activate && python3 backup_github.py

# Deploy archive
cd ~/Desktop/AIM && ./build_deploy.sh
```

---

*Last updated: 2026-03-28*
