# PARAMETERS.md — AIM Configuration Reference

All configurable parameters for AIM. Source of truth: `config.py` + `~/.aim_env`.

---

## Environment Variables (`~/.aim_env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | **YES** | DeepSeek API key from platform.deepseek.com |
| `TELEGRAM_BOT_TOKEN` | For bot | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_ID` | For bot | Telegram user ID(s), comma-separated |
| `WEARABLE_ADDRESS` | Optional | BLE MAC address of Ze HealthWearable |

Example `~/.aim_env`:
```bash
DEEPSEEK_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=7...
TELEGRAM_ALLOWED_ID=123456789
```
Permissions must be `chmod 600 ~/.aim_env`.

---

## LLM Parameters (`config.py`)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MODEL_FAST` | `deepseek-chat` | DeepSeek V3 — all normal requests |
| `MODEL_DEEP` | `deepseek-reasoner` | DeepSeek R1 — complex diagnosis |
| Default `max_tokens` | 2048 | For `ask_llm()` |
| Deep `max_tokens` | 4096 | For `ask_deep()` |
| `temperature` (fast) | 0.3 | Balanced creativity |
| `temperature` (deep) | 0.1 | Deterministic reasoning |

LLM switches to `deepseek-reasoner` when:
- Bayesian confidence < 60%
- Gap between top diagnoses < 15%

---

## Paths (`config.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `AIM_DIR` | `~/Desktop/AIM/` | Project root |
| `PATIENTS_DIR` | `~/Desktop/AIM/Patients/` | Patient records |
| `INBOX_DIR` | `~/Desktop/AIM/Patients/INBOX/` | Auto-intake drop folder |
| `LOGS_DIR` | `~/Desktop/AIM/logs/` | Log files |
| `DB_PATH` | `~/Desktop/AIM/aim.db` | SQLite database |
| `KNOWLEDGE_FILE` | `~/Desktop/AIM/medical_knowledge.json` | Self-learning knowledge |
| `PROCESSED_LOG` | `~/Desktop/AIM/processed_files.json` | OCR processing log |

---

## OCR Parameters (`config.py`)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `OCR_LANGS` | `rus+kat+eng` | Tesseract language string |
| `OCR_MIN_DPI` | 300 | Upscale images below this DPI |

Tesseract packages required: `tesseract-ocr-rus`, `tesseract-ocr-kat`, `tesseract-ocr-kaz`.

---

## Nutrition Protocol (`nutrition_rules.json`)

Editable from GUI → tab **Nutrition** → **Save to AIM core**.

| Parameter | Value |
|-----------|-------|
| Forbidden products | 47 (11 categories) |
| Allowed products | 69 (12 categories) |
| Source | "Mesto Sily" + clinical protocol, 09.03.2026 |

The nutrition context is auto-injected into any LLM prompt that contains food-related queries.

---

## Lab Reference Ranges (`lab_reference.py`)

| Parameter | Value |
|-----------|-------|
| Total parameters | 165+ |
| Gender-aware | Yes (separate ranges for M/F) |
| Age-aware | Yes (pediatric/adult/elderly) |

---

## Telegram Bot Parameters (`telegram_bot.py`)

| Parameter | Description |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From `.aim_env` |
| `TELEGRAM_ALLOWED_ID` | Whitelist of allowed Telegram user IDs |
| Voice input | Whisper (openai-whisper) → text |
| Languages | RU / KA / EN |

---

## Inbox Watcher (`inbox_watcher.py`)

| Parameter | Value |
|-----------|-------|
| Poll interval | 2 seconds |
| Trigger | New files in `Patients/INBOX/` |
| Action | `patient_intake.py --all` |

---

## Database (`aim.db` — SQLite via `db.py`)

Tables: `patients`, `lab_snapshots`, `diagnoses`, `ze_hrv`, `knowledge`, `audit_log`

Migration: `python3 db.py --migrate`
Stats: `python3 db.py --stats`

---

## GitHub Backup (`backup_github.py`)

| Parameter | Value |
|-----------|-------|
| Schedule | 3rd of each month (cron) |
| Trigger (manual) | `python3 backup_github.py` |
| Private repo | `djabbat/AIM` |
| Public repo | `djabbat/AIM-public` |
| Excluded from public | `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `MAP.md`, `Patients/`, `*.db` |

---

## WhatsApp / Telegram Import

Patient contact name format: `SURNAME П FIRSTNAME`
Separator variants: `П` (ru) / `п` (lower) / `პ` (ka)
Examples: `Иванова П Мария`, `Beridze პ Giorgi`

---

*Last updated: 2026-03-28*
