#!/usr/bin/env bash
# Interactive wizard to populate ~/.aim_env with API keys.
# Existing values are preserved unless --overwrite is given.

set -euo pipefail

ENV_FILE="$HOME/.aim_env"
OVERWRITE=0
[ "${1:-}" = "--overwrite" ] && OVERWRITE=1

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Backup once.
if [ ! -f "${ENV_FILE}.backup-$(date +%Y%m%d)" ]; then
  cp "$ENV_FILE" "${ENV_FILE}.backup-$(date +%Y%m%d)"
fi

ask() {
  local key=$1
  local desc=$2
  local current=""
  if grep -q "^${key}=" "$ENV_FILE"; then
    current=$(grep "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
  fi
  if [ -n "$current" ] && [ "$OVERWRITE" -ne 1 ]; then
    echo "[skip] $key already set (use --overwrite to replace)"
    return
  fi
  read -r -p "$desc [$key, blank to skip]: " val
  if [ -n "$val" ]; then
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i.bak "/^${key}=/d" "$ENV_FILE"
    fi
    echo "${key}=${val}" >> "$ENV_FILE"
    echo "  saved $key"
  fi
}

echo "═══ AIM key setup wizard ═══"
echo "Editing: $ENV_FILE"
echo

echo "─ LLM providers ─"
ask DEEPSEEK_API_KEY "DeepSeek API key (deepseek.com)"
ask GROQ_API_KEY     "Groq API key (groq.com)"
ask ANTHROPIC_API_KEY "Anthropic API key (claude.ai/console)"
ask GEMINI_API_KEY   "Google Gemini key (aistudio.google.com/apikey, free 50/day)"

echo
echo "─ Telegram ─"
ask TELEGRAM_BOT_TOKEN     "Telegram bot token (BotFather)"
ask TELEGRAM_WEBHOOK_SECRET "Telegram webhook secret (set via setWebhook)"
ask TELEGRAM_ALLOWED_IDS   "Comma-separated allowed user IDs (or empty = use /link codes)"

echo
echo "─ Gmail (optional, for delegate_email -> gmail_send) ─"
ask GMAIL_CLIENT_ID     "Google OAuth client_id"
ask GMAIL_CLIENT_SECRET "Google OAuth client_secret"
ask GMAIL_REFRESH_TOKEN "Gmail refresh_token (run OAuth flow once)"

echo
echo "─ Hub/Node (multi-user only) ─"
ask AIM_ROLE       "AIM_ROLE [hub | node | empty for standalone]"
ask AIM_HUB_URL    "AIM_HUB_URL (only on nodes)"
ask AIM_USER_TOKEN "AIM_USER_TOKEN (issued by hub admin)"

echo
echo "─ Production safety toggles ─"
ask AIM_ENV          "AIM_ENV [prod | dev]"
ask AIM_REQUIRE_AUTH "AIM_REQUIRE_AUTH [1 to enforce bearer auth in prod]"
ask SECRET_KEY_BASE  "SECRET_KEY_BASE (Phoenix; gen via: mix phx.gen.secret)"
ask PHX_HOST         "PHX_HOST (public hostname)"

echo
echo "Done. Verify with: cat $ENV_FILE | head -30"
