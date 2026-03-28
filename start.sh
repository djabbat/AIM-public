#!/bin/bash
# AIM — Quick launcher
# Starts the GUI (which auto-starts the Telegram bot)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

[ -f "$HOME/.aim_env" ] && source "$HOME/.aim_env"
[ -d "venv" ] && source venv/bin/activate

exec python3 aim_gui.py
