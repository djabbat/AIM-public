# AIM — Installation Guide

AIM v7.0 runs as a distributed system:

- **Hub** — one shared server. Manages users, tokens, audit log. *Does not run AI.*
- **Node** — installed on each user's own computer (Linux / macOS / Windows).
  Runs the full AIM stack locally with **its own LLM** (Ollama) and optional cloud
  fallback to DeepSeek-V4. Patient data and conversations stay on the user's machine.

```
┌─────────────────────┐        ┌──────────────────────┐
│  AIM HUB            │  auth  │  AIM NODE (per user) │
│  (one server, e.g.  │◄──────►│  • own DeepSeek key  │
│   longevity.ge)     │ tokens │  • own Ollama        │
│                     │ audit  │  • own SQLite        │
│  • users, roles     │        │  • own Patients/     │
│  • /link codes      │        │  • LLM → local first │
│  • node heartbeats  │        │    cloud fallback    │
└─────────────────────┘        └──────────────────────┘
```

LLM compute happens on each user's own hardware. The hub never sees prompts or
responses. Users pay for their own DeepSeek API quota (if they choose to enable
the cloud tier).

---

## 1. Install the Hub (one-time, on a server)

> Skip this if a hub is already running and you only need to install a Node.

The hub is a small FastAPI service. ~50 MB Python deps, no LLM, no GPU needed.
Any always-on Linux box works (1 vCPU / 1 GB RAM / 5 GB disk is plenty).

```bash
git clone <repo-url> AIM
cd AIM
bash scripts/install_hub.sh
```

The installer:
1. Creates a Python virtualenv.
2. Installs hub-only dependencies (`fastapi`, `uvicorn`, `argon2-cffi`, `pydantic`).
3. Asks for an **admin username** and password, creates the first admin.
4. Writes `start_hub.sh` for launching the hub.

Start the hub:

```bash
bash start_hub.sh                      # listens on 0.0.0.0:8000
```

For public deployment, put it behind nginx + Let's Encrypt and set:

```bash
export AIM_HUB_HTTPS=1                 # marks JWT cookies as Secure
```

The hub admin UI is at `https://your-hub-host/` after login.

### Add users (on the hub)

```bash
python -m scripts.user_admin create alice              # prompts for password
python -m scripts.user_admin create bob --role admin
python -m scripts.user_admin list

# Issue a long-lived API token for a node:
python -m scripts.user_admin token alice
# → aim_2N3xK9...      (give this to alice for her ~/.aim_env)
```

Or do it from the web UI: log in to `https://your-hub-host/` and use the
"Create user" / "issue token" buttons.

---

## 2. Install a Node (on each user's computer)

A node is a per-user local AIM install. **Each user installs their own.**
LLM runs locally via [Ollama](https://ollama.com) (free, offline, private).
Cloud DeepSeek-V4 is optional and used as a fallback for heavy reasoning /
long-context tasks.

### Prerequisites (all platforms)

- **Python 3.10+** — `python3 --version`
- **8 GB RAM minimum** for the small `qwen2.5:3b` model. **16 GB recommended**
  for `qwen2.5:7b`. With a CUDA / Metal GPU, models run much faster but it's
  not required.
- **20 GB disk free** (Ollama + 2 models + venv).

### Linux (Ubuntu / Debian / Fedora / Arch)

```bash
git clone <repo-url> AIM
cd AIM
bash scripts/install_node.sh
```

The installer will:
1. Create a Python virtualenv.
2. Install AIM dependencies.
3. Install Ollama (via the official `curl ollama.com/install.sh | sh` script).
4. Pull `qwen2.5:3b-instruct` and `qwen2.5:7b-instruct` (10–30 min on first run).
5. Prompt for `AIM_HUB_URL`, `AIM_USER_TOKEN`, optional `DEEPSEEK_API_KEY`
   and write them to `~/.aim_env` (mode 600).
6. Run a smoke test that prints which providers are available.

### macOS

```bash
git clone <repo-url> AIM
cd AIM
bash scripts/install_node.sh
```

Same steps as Linux. If `ollama` is not on `PATH`, the installer uses Homebrew
to install it (`brew install ollama`). If you don't have Homebrew, install it
first from <https://brew.sh> or download Ollama manually from
<https://ollama.com/download>.

### Windows 10 / 11

Open **PowerShell** in the AIM folder:

```powershell
.\scripts\install_node.ps1
```

If PowerShell blocks the script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_node.ps1
```

The installer downloads `OllamaSetup.exe` from ollama.com and launches the
standard Windows installer. After it completes, **close and re-open PowerShell**
so `ollama` is on `PATH`, then re-run the script — it will resume from the
"pull models" step.

Configuration is written to `%USERPROFILE%\.aim_env` (i.e. `C:\Users\<you>\.aim_env`).

---

## 3. Daily use

Once a node is installed, all of these work the same on Linux, macOS, Windows:

```bash
bash start.sh web         # local web UI on http://127.0.0.1:8080
bash start.sh gui         # tkinter desktop GUI
bash start.sh cli         # CLI menu
bash start.sh telegram    # Telegram bot (needs TELEGRAM_BOT_TOKEN in ~/.aim_env)
```

Windows equivalents:

```cmd
start.bat web
start.bat gui
start.bat cli
start.bat telegram
```

### Linking your Telegram account

If you want to use AIM via Telegram:

1. Create a bot via [@BotFather](https://t.me/BotFather), get the token.
2. Add `TELEGRAM_BOT_TOKEN=...` to `~/.aim_env`.
3. Ask your hub admin to issue you a 6-digit link code:
   ```bash
   python -m scripts.user_admin link-code alice
   # → 123456    (valid 10 minutes)
   ```
4. Start the bot: `bash start.sh telegram`
5. In Telegram, send: `/link 123456`
6. The bot replies "✅ linked" and from now on accepts your messages.

Static fallback (no hub): set `TELEGRAM_ALLOWED_IDS=123456789,987654321` in
`~/.aim_env` — comma-separated list of allowed Telegram user IDs.

---

## 4. ~/.aim_env reference

All settings live in `~/.aim_env` (Linux / macOS) or `%USERPROFILE%\.aim_env`
(Windows). Mode `0600` recommended on Unix.

```bash
# ── Hub (multi-user mode) ──────────────────────────────────────
AIM_HUB_URL=https://hub.your-org.example
AIM_USER_TOKEN=aim_xxxxxxxxxxxxxxxxxxxx     # from admin
AIM_NODE_ID=jaba-thinkpad                   # optional, defaults to hostname-username
AIM_OFFLINE_GRACE=168                       # hours to trust cached identity if hub down (default 7d)

# ── LLM providers (all optional; at least one required) ────────
# Ollama runs locally — no key needed; URL only if non-default:
# AIM_OLLAMA_URL=http://127.0.0.1:11434/v1
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx    # for ask_deep / ask_long via cloud
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx       # optional fast cloud fallback

# ── Models (override defaults if desired) ──────────────────────
# AIM_OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct
# AIM_OLLAMA_FAST_MODEL=qwen2.5:3b-instruct
# AIM_OLLAMA_REASONER_MODEL=deepseek-r1:7b
# AIM_DS_CHAT_MODEL=deepseek-v4-flash
# AIM_DS_REASONER_MODEL=deepseek-v4-pro

# ── Telegram (optional) ────────────────────────────────────────
TELEGRAM_BOT_TOKEN=12345:ABCDEF...
TELEGRAM_ALLOWED_IDS=123456789               # comma-separated; or use /link

# ── Web ────────────────────────────────────────────────────────
AIM_WEB_PORT=8080
AIM_WEB_HOST=127.0.0.1                       # 0.0.0.0 if you trust your LAN
```

---

## 5. Verifying your install

After install completes:

```bash
cd AIM
venv/bin/python -c "from llm import providers_status; import json; print(json.dumps(providers_status(), indent=2))"
```

You should see something like:

```json
{
  "deepseek": true,
  "groq":     false,
  "ollama":   true,
  "models": {
    "default_chat":     "qwen2.5:7b-instruct",
    "default_fast":     "qwen2.5:3b-instruct",
    "default_reasoner": "deepseek-v4-pro"
  }
}
```

`ollama: true` confirms the local model server is reachable.

Run the auth tests:

```bash
venv/bin/python -m pytest tests/test_auth.py -q
# 9 passed
```

Start the local web UI:

```bash
bash start.sh web
# → AIM web starting in role=node on 127.0.0.1:8080
# → Node authenticated as user 'alice' (role=user)
```

Open <http://127.0.0.1:8080> in your browser.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `AIM: cannot authenticate this node` | `AIM_USER_TOKEN` invalid or hub unreachable | run `venv/bin/python -m scripts.user_admin token <you>` on the hub, copy fresh token to `~/.aim_env` |
| `ollama: false` in `providers_status()` | Ollama service not running | Linux: `nohup ollama serve >/tmp/ollama.log 2>&1 &`<br>macOS: `ollama serve` or relaunch app<br>Windows: open Ollama from Start menu |
| `ollama pull` is very slow | First-run download | `qwen2.5:7b` is ~5 GB; let it finish once, subsequent starts are instant |
| Telegram bot says `⛔ Доступ закрыт` | Account not linked yet | get a code from admin: `python -m scripts.user_admin link-code <you>` and send `/link <CODE>` to the bot |
| `ModuleNotFoundError: argon2` | venv missing deps | `venv/bin/pip install -r requirements.txt` |
| `python: command not found` (zsh) | bare `python` not on PATH | use `python3` or `venv/bin/python` |

For deeper debugging, set `AIM_LOG_LEVEL=DEBUG` and re-run.

---

## 7. Updating

```bash
cd AIM
git pull
venv/bin/pip install -r requirements.txt
# Restart whatever you were running (web / gui / telegram).
```

Hub updates:

```bash
cd AIM
git pull
venv/bin/pip install -r requirements.txt
# Restart start_hub.sh (the SQLite schema is upgraded automatically).
```
