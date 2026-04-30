#!/usr/bin/env bash
# install_node.sh — bootstrap an AIM node on Linux or macOS.
#
# Installs:
#   • Python venv with AIM dependencies
#   • Ollama (if missing)        ← local LLM (qwen2.5:7b + qwen2.5:3b)
#   • ~/.aim_env with hub URL, user token, optional DeepSeek key
#
# Usage:
#   ./scripts/install_node.sh                      # interactive
#   AIM_HUB_URL=https://hub.example.com \
#   AIM_USER_TOKEN=aim_xxx ./scripts/install_node.sh   # non-interactive

set -e

AIM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$HOME/.aim_env"

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }

OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM=linux  ;;
  Darwin*) PLATFORM=macos  ;;
  *) red "Unsupported OS: $OS (this installer is for Linux / macOS; use install_node.ps1 on Windows)"
     exit 1 ;;
esac

bold "AIM node installer  (platform: $PLATFORM)"
echo  "AIM_ROOT = $AIM_ROOT"
echo

# 1. Python venv ------------------------------------------------------------

if [ ! -d "$AIM_ROOT/venv" ]; then
  bold "[1/5] creating Python venv"
  python3 -m venv "$AIM_ROOT/venv"
fi
# shellcheck source=/dev/null
. "$AIM_ROOT/venv/bin/activate"
pip install --upgrade pip >/dev/null
bold "[1/5] installing Python deps"
pip install -r "$AIM_ROOT/requirements.txt" >/dev/null
pip install argon2-cffi httpx >/dev/null
green "      OK"

# 2. Ollama -----------------------------------------------------------------

bold "[2/5] checking Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  echo "      Ollama not found, installing…"
  if [ "$PLATFORM" = "linux" ]; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    if command -v brew >/dev/null 2>&1; then
      brew install ollama
    else
      red  "      Homebrew not installed. Download Ollama for macOS from:"
      red  "        https://ollama.com/download/Ollama-darwin.zip"
      red  "      then re-run this installer."
      exit 1
    fi
  fi
fi

# Start ollama service in the background if not running
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "      starting ollama serve in background…"
  if [ "$PLATFORM" = "linux" ]; then
    if command -v systemctl >/dev/null && systemctl --user list-unit-files ollama.service >/dev/null 2>&1; then
      systemctl --user start ollama || nohup ollama serve >/tmp/ollama.log 2>&1 &
    else
      nohup ollama serve >/tmp/ollama.log 2>&1 &
    fi
  else
    # macOS: ollama starts automatically as a launch agent on `brew install`
    nohup ollama serve >/tmp/ollama.log 2>&1 &
  fi
  sleep 3
fi
green "      OK"

# 3. Pull default models ----------------------------------------------------

bold "[3/5] pulling local models (this can take 10–30 min on first run)"
for model in qwen2.5:3b-instruct qwen2.5:7b-instruct; do
  if ! ollama list 2>/dev/null | grep -q "^${model%%:*}"; then
    echo "      pulling $model …"
    ollama pull "$model"
  else
    echo "      already present: $model"
  fi
done
echo "      tip: also try  ollama pull deepseek-r1:7b   for a local reasoner"
green "      OK"

# 4. Configure ~/.aim_env ---------------------------------------------------

bold "[4/5] configuring ~/.aim_env"

# Helper: read existing value or empty
get_env_var() {
  [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | head -1
}

set_env_var() {
  local key="$1" val="$2"
  if [ -f "$ENV_FILE" ] && grep -qE "^$key=" "$ENV_FILE"; then
    # macOS sed wants -i ''; GNU sed wants -i without arg.
    if [ "$PLATFORM" = "macos" ]; then
      sed -i '' "s|^$key=.*|$key=$val|" "$ENV_FILE"
    else
      sed -i "s|^$key=.*|$key=$val|" "$ENV_FILE"
    fi
  else
    echo "$key=$val" >> "$ENV_FILE"
  fi
}

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Hub URL
if [ -z "${AIM_HUB_URL:-}" ]; then
  current="$(get_env_var AIM_HUB_URL)"
  read -r -p "AIM Hub URL [$current] (leave blank for local-only): " new
  AIM_HUB_URL="${new:-$current}"
fi
set_env_var AIM_HUB_URL "$AIM_HUB_URL"

# User token (only if hub URL set)
if [ -n "$AIM_HUB_URL" ]; then
  if [ -z "${AIM_USER_TOKEN:-}" ]; then
    current="$(get_env_var AIM_USER_TOKEN)"
    masked="$(printf '%s' "$current" | head -c 12)…"
    [ -z "$current" ] && masked=""
    read -r -p "AIM_USER_TOKEN [$masked]: " new
    AIM_USER_TOKEN="${new:-$current}"
  fi
  set_env_var AIM_USER_TOKEN "$AIM_USER_TOKEN"
fi

# DeepSeek key (optional, for cloud-tier tasks)
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  current="$(get_env_var DEEPSEEK_API_KEY)"
  masked=""
  [ -n "$current" ] && masked="$(printf '%s' "$current" | head -c 8)…"
  read -r -p "DeepSeek API key (optional, for cloud reasoner) [$masked]: " new
  DEEPSEEK_API_KEY="${new:-$current}"
fi
[ -n "$DEEPSEEK_API_KEY" ] && set_env_var DEEPSEEK_API_KEY "$DEEPSEEK_API_KEY"

green "      ~/.aim_env updated"

# 5. Smoke test -------------------------------------------------------------

bold "[5/5] smoke test"
cd "$AIM_ROOT"
python -c "
from llm import providers_status
import json
print(json.dumps(providers_status(), indent=2))
"
echo
green "AIM node ready."
echo
echo "Next steps:"
echo "  • run AIM web :  python -m web.api --port 8080"
echo "  • run AIM CLI :  python medical_system.py"
echo "  • run AIM GUI :  python aim_gui.py"
echo "  • run Telegram:  python telegram_bot.py    (requires TELEGRAM_BOT_TOKEN)"
