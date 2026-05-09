#!/usr/bin/env bash
# start.sh — universal launcher for AIM (Linux / macOS).
# Usage:
#   ./start.sh             # CLI (default, used to be the only mode)
#   ./start.sh gui         # tkinter GUI
#   ./start.sh web         # FastAPI web on 127.0.0.1:8080
#   ./start.sh hub         # run as Hub (multi-user auth server)
#   ./start.sh telegram    # Telegram bot
set -e
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
# shellcheck source=/dev/null
. venv/bin/activate
pip install -q -r requirements.txt

mode="${1:-cli}"
shift || true

case "$mode" in
  cli)      exec python3 medical_system.py "$@" ;;
  gui)      exec python3 aim_gui.py "$@" ;;
  web|node) exec python3 -m web.api --port "${AIM_WEB_PORT:-8080}" "$@" ;;
  hub)      AIM_ROLE=hub exec python3 -m web.api --host 0.0.0.0 \
                                    --port "${AIM_HUB_PORT:-8000}" "$@" ;;
  telegram|bot) exec python3 telegram_bot.py "$@" ;;
  install) exec bash scripts/install_node.sh ;;
  install-hub) exec bash scripts/install_hub.sh ;;
  *) echo "unknown mode: $mode";
     echo "usage: $0 {cli|gui|web|hub|telegram|install|install-hub}";
     exit 1 ;;
esac
