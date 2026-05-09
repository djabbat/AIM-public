# DEPLOY_RUNBOOK.md — AIM production deploy

**Дата:** 2026-05-07 (создан под `NEEDTOWRITE.md` 🔥).
**Аудитория:** sysadmin / developer, поднимающий AIM на новом сервере.
**Платформа:** Linux (systemd), без Docker (правило `STACK.md`).

> **Source-of-truth:** этот документ → `scripts/install_*.sh` →
> `scripts/deploy_aim_llm.sh` → `systemd/*.service`. При расхождении
> правится skрипт, потом этот файл.

---

## 0. Pre-flight

### Required

- Linux x86_64 с systemd ≥ 245 (Ubuntu 22.04+ / Debian 12+ / Fedora 39+)
- Python 3.10+ (`venv` будет создан автоматически)
- Rust ≥ 1.78 + cargo (`rustup default stable`)
- Elixir 1.17 + Erlang/OTP 27 (только если нужен Phoenix UI)
- git, gcc, sqlite3-dev, ffmpeg (для intake/voice), tesseract-ocr (для OCR)

### API keys в `~/.aim_env`

Минимум:
```bash
DEEPSEEK_API_KEY=.. # обязателен — основной LLM
GROQ_API_KEY=.. # рекомендуется — fast tier
```

Опционально (по `PARAMETERS.md` § 8):
```bash
ANTHROPIC_API_KEY=.. # critical tier (Claude Opus 4.7)
GEMINI_API_KEY=.. # free 50/day на 2.5-pro
TELEGRAM_BOT_TOKEN=.. # бот
TELEGRAM_ALLOWED_IDS=.. # static allow-list
AIM_HUB_URL=.. # multi-user node
AIM_USER_TOKEN=.. # multi-user node auth
```

Permissions: `chmod 600 ~/.aim_env` (содержит секреты).

---

## 1. Single-node install (default — node mode)

### 1.1 Linux / macOS

```bash
git clone https://github.com/djabbat/AIM ~/Desktop/LongevityCommon/AIM
cd ~/Desktop/LongevityCommon/AIM
bash scripts/install_node.sh
```

`install_node.sh` делает:
1. Создаёт `venv/` (Python).
2. Устанавливает Python deps (`pip install -r requirements.txt`).
3. Устанавливает Ollama + pull `qwen2.5:7b-instruct` + `qwen2.5:3b-instruct`
 (offline fallback).
4. Создаёт `~/.aim_env` шаблон (если нет).
5. Smoke-test `python3 medical_system.py --version`.

### 1.2 Windows

```powershell
git clone https://github.com/djabbat/AIM
cd AIM
powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1
```

### 1.3 Hub (multi-user admin server)

```bash
bash scripts/install_hub.sh
# Создаёт первого admin user, выдаёт token.
python -m scripts.user_admin create <username>
python -m scripts.user_admin token <username> # → выдать пользователю
```

Подробнее multi-user flow — `CLAUDE.md` § "Multi-user (Hub + Node)".

---

## 2. Build all Rust binaries (production)

```bash
cd rust-core
cargo build --workspace --release
```

Время: ~10-15 минут на холодную (192 крейта); ~30 секунд на тёплый
incremental. Артефакты в `rust-core/target/release/`.

Critical binaries для production:

| Binary | Используется |
|--------|--------------|
| `aim-llm` | HTTP shim для cloud LLM (port 8770 default) |
| `aim-pam` | PAM-13 administration / scoring (cornerstone) |
| `aim-coach` | Motivational interviewing classifier (cornerstone) |
| `aim-codesign` | Co-design event log (cornerstone, L_AGENCY) |
| `aim-disagreement` | Blumenthal-Lee 4-zone HCI classifier |
| `aim-doctor` | Wiring smoke test |
| `aim-ai-*` | 30+ AI/ai shim binaries (Phase 9) |
| `aim-daily-brief`, `aim-weekly-project-digest` | systemd-driven brief jobs |

---

## 3. systemd services

### 3.1 aim-llm HTTP service (recommended)

```bash
bash scripts/deploy_aim_llm.sh
# Идемпотентен — re-run = upgrade in place.
# Bind: 127.0.0.1:8770 (по AIM_LLM_PORT env).
# Log: journalctl --user -u aim-llm -f
```

После старта — активировать в `medical_system.py`:
```bash
echo 'AIM_LLM_HTTP_URL=http://127.0.0.1:8770' >> ~/.aim_env
```
`agents/llm_client.py` opt-in shim перехватит `ask` / `ask_deep` / `ask_long`
/ `ask_fast` / `ask_critical` → HTTP вместо direct Python provider clients.
Fallback на legacy `llm.py` если `/health` не отвечает.

### 3.2 Daily brief / weekly digest

```bash
# Python legacy (current production):
systemctl --user enable aim-daily-brief.timer
systemctl --user enable aim-weekly-project-digest.timer
systemctl --user start aim-daily-brief.timer

# Rust alternative (одинаковая семантика, можно переключиться):
systemctl --user disable aim-daily-brief.service
systemctl --user enable aim-daily-brief-rust.service
```

> **Правило:** только ОДИН из пары (Python ↔ Rust) `systemctl --user
> enable`'d одновременно. Иначе оба файла brief'а перезаписывают друг друга.

### 3.3 Long-running owners

`aim-serve-daemon.service` (Python `agents/serve_daemon.py`) — long-running
owner для project/patient/experiment auto-discovery. Запускать только если
есть `USER/projects/*.yaml` или `USER/experiments/*.yaml`.

---

## 4. Phoenix LiveView UI

```bash
cd phoenix-umbrella
mix deps.get --only prod
MIX_ENV=prod mix assets.deploy
MIX_ENV=prod mix release aim_web
```

Артефакт: `phoenix-umbrella/_build/prod/rel/aim_web/bin/aim_web`.

Запуск как сервис:
```bash
sudo cp /path/to/aim-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aim-web.service
```

Bind: `127.0.0.1:4000` (по `PORT` env). Reverse-proxy через Caddy / nginx.

Routes (см. `phoenix-umbrella/apps/aim_web/lib/aim_web_web/router.ex`):
- `/` HomeLive · `/about` AboutLive (566 LoC English description)
- `/chat` `/intake` `/cases` `/cases/:id` `/consult` `/dashboard` `/drugs`
 `/settings`
- Cornerstone: `/pam` `/pam/:patient_id` `/codesign/:patient_id`
 `/disagreement` `/activation` `/coaching/:patient_id`
- Project mgmt: `/patients` `/experiments`
- Health: `/health` `/status`

---

## 5. Verify deploy

### 5.1 Smoke chain

```bash
cd ~/Desktop/LongevityCommon/AIM

# 1. Python imports clean
venv/bin/python -c "from medical_system import main; print('OK')"

# 2. Rust binaries present
for bin in aim-llm aim-pam aim-coach aim-codesign aim-disagreement aim-doctor; do
 test -x rust-core/target/release/$bin && echo "✓ $bin" || echo "✗ $bin"
done

# 3. Wiring probe
rust-core/target/release/aim-ai-doctor summary

# 4. Cornerstone E2E (no LLM call, all local subprocess)
venv/bin/python -m pytest tests/test_pam_trajectory_e2e.py -v

# 5. Full quick regression
bash scripts/test_all.sh --quick
```

Ожидается: `ALL 3 BLOCKS PASS`.

### 5.2 LLM live check

```bash
# Direct
venv/bin/python -c "from llm import ask; print(ask('say hi in russian')[:80])"

# Через aim-llm HTTP service (если запущен)
curl -s http://127.0.0.1:8770/v1/providers | head -c 200
```

### 5.3 Cornerstone routes

```bash
# Если Phoenix запущен:
curl -s http://127.0.0.1:4000/about | grep -o "<title>.*</title>"
curl -s http://127.0.0.1:4000/pam | grep -c "PAM-13"
```

---

## 6. Common ops

### 6.1 Update в production

```bash
cd ~/Desktop/LongevityCommon/AIM
git pull
cd rust-core && cargo build --workspace --release
systemctl --user restart aim-llm
# Phoenix:
cd./phoenix-umbrella
MIX_ENV=prod mix release aim_web --overwrite
sudo systemctl restart aim-web
bash scripts/test_all.sh --quick # final smoke
```

### 6.2 Rollback Rust kernel

```bash
AIM_USE_LEGACY_KERNEL=1 venv/bin/python medical_system.py
# или в ~/.aim_env постоянно. Откатывает PyO3 → Python `kernel_legacy.py`.
```

### 6.3 Backup

```bash
# AI/ai SQLite ledger + sidecars (suppressions, prompt_versions, health_scores):
rust-core/target/release/aim-ai-backup write --out ~/.cache/aim/backup_$(date +%F).json

# Patients/ — НИКОГДА в общий бэкап без явной команды (правило MEMORY-2).
```

### 6.4 Logs

```bash
journalctl --user -u aim-llm -f
journalctl --user -u aim-daily-brief -n 100
sudo journalctl -u aim-web -f # Phoenix
~/Desktop/LongevityCommon/AIM/AI/artifacts/self_diag_*.md # adversarial audits
~/.cache/aim/sessions/*.jsonl # generalist runs
```

---

## 7. Troubleshooting

| Симптом | Проверить | Fix |
|---|---|---|
| `aim-llm: no API key found` | `~/.aim_env` permissions, имя ключа | `chmod 600 ~/.aim_env`; `DEEPSEEK_API_KEY=..` |
| Phoenix `Address already in use` | `ss -tlnp \| grep 4000` | kill старый release или сменить `PORT` |
| `aim-pam: patient directory missing` | существует ли `Patients/<id>/` | создать вручную или через intake |
| `cargo build` падает на `rusqlite` | dev headers | `apt install libsqlite3-dev` |
| `pyo3` linker error | Python headers / version | `apt install python3-dev`; venv с правильным Python |
| L_AGENCY блокирует treatment | пациент с `activation_level >= 2` | вызвать `aim-codesign record <pid> agreed <topic>` или explicit override |
| Phase 9 AI/tests fail при rerun | `_phase9_known_broken.txt` устарел | `pytest --collect-only` → regen list |

---

## 8. Production readiness checklist

Before exposing AIM to non-developer users:

- [ ] `~/.aim_env` имеет `chmod 600`
- [ ] `Patients/` существует и в `.gitignore`
- [ ] `bash scripts/test_all.sh --quick` зелёная
- [ ] `bash scripts/test_all.sh --ai` зелёная (505 / 110 skipped норма)
- [ ] `aim-llm` systemd unit running + `/health` отвечает
- [ ] Phoenix `/about` + `/pam` отвечают HTTP 200
- [ ] L_AGENCY enforcement работает (`tests/test_pam_trajectory_e2e.py`)
- [ ] Multi-user если включён: hub valid token + node heartbeat reaches hub
- [ ] Backup настроен (cron / systemd timer для `aim-ai-backup`)
- [ ] reverse-proxy (Caddy/nginx) терминирует TLS перед Phoenix
- [ ] firewall: только 80/443 наружу; 4000/8770 — только loopback

---

**Convention:** при критических изменениях deploy-pipeline — обновить
**этот** файл + `scripts/deploy_*.sh` + соответствующий `systemd/*.service`.
Mention в `CHANGELOG.md` `[Unreleased]` секции.
