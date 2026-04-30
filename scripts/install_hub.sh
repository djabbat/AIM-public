#!/usr/bin/env bash
# install_hub.sh — bootstrap an AIM Hub on Linux or macOS.
#
# A Hub is a single multi-user instance:
#   • manages users, JWT cookies, API tokens
#   • issues Telegram /link codes
#   • collects audit log + node heartbeats
#   • does NOT run LLM (each user's node does that locally)
#
# Usage:
#   ./scripts/install_hub.sh                    # interactive
#   AIM_HUB_PORT=8000 ./scripts/install_hub.sh  # custom port

set -e

AIM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$HOME/.aim_env"
HUB_PORT="${AIM_HUB_PORT:-8000}"

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }

bold "AIM Hub installer"
echo  "AIM_ROOT = $AIM_ROOT"
echo  "Port     = $HUB_PORT"
echo

# 1. Python venv -----------------------------------------------------------

if [ ! -d "$AIM_ROOT/venv" ]; then
  bold "[1/3] creating Python venv"
  python3 -m venv "$AIM_ROOT/venv"
fi
# shellcheck source=/dev/null
. "$AIM_ROOT/venv/bin/activate"
pip install --upgrade pip >/dev/null
bold "[1/3] installing minimal hub deps"
# Hub doesn't need LLM/DB/intake stack — just FastAPI + auth.
pip install fastapi uvicorn argon2-cffi python-dotenv pydantic >/dev/null
green "      OK"

# 2. Bootstrap admin user --------------------------------------------------

bold "[2/3] bootstrapping admin user"
cd "$AIM_ROOT"
existing="$(python -c 'from agents import auth; print(len(auth.list_users()))')"
if [ "$existing" = "0" ]; then
  read -r -p "Admin username: " admin_u
  python -m scripts.user_admin create "$admin_u" --role admin
  green "      admin '$admin_u' created"
else
  echo "      $existing user(s) already exist — skipping bootstrap"
  echo "      to add more: python -m scripts.user_admin create <username>"
fi

# 3. systemd / launchd unit (optional) -------------------------------------

bold "[3/3] writing run script"
cat > "$AIM_ROOT/start_hub.sh" <<EOF
#!/usr/bin/env bash
cd "$AIM_ROOT"
. venv/bin/activate
export AIM_ROLE=hub
export AIM_HUB_HTTPS=\${AIM_HUB_HTTPS:-0}
exec python -m web.api --host 0.0.0.0 --port $HUB_PORT
EOF
chmod +x "$AIM_ROOT/start_hub.sh"
green "      $AIM_ROOT/start_hub.sh"

echo
green "AIM Hub ready."
echo
echo "Start it with:"
echo "    bash $AIM_ROOT/start_hub.sh"
echo
echo "Behind nginx with TLS recommended for public deployment."
echo "Set AIM_HUB_HTTPS=1 in environment to flag JWT cookies as Secure."
