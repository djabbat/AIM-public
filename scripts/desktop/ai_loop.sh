#!/usr/bin/env bash
# ai_loop.sh — launcher for the "AIM AI" Desktop icon.
# Calls the standalone ai_loop.py so stdin stays bound to the terminal.

cd "$(cd "$(dirname "$0")/../.." && pwd)"
[ -d venv ] && source venv/bin/activate
python3 scripts/desktop/ai_loop.py
echo
echo "(window stays open — close it manually or press Enter)"
read -r _
