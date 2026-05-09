#!/usr/bin/env bash
# scripts/desktop/aim_ui_launch.sh
# Launches AIM Phoenix LiveView UI:
#   - if production aim.longevity.ge reachable → open in browser
#   - else if localhost:4000 already up → open in browser
#   - else `mix phx.server` in foreground in new gnome-terminal, then open browser
set -uo pipefail
REPO_ROOT="/home/oem/Desktop/LongevityCommon/AIM"
PHOENIX="$REPO_ROOT/phoenix-umbrella"
PORT="${AIM_UI_PORT:-4000}"
PROD_URL="https://aim.longevity.ge/"
LOCAL_URL="http://127.0.0.1:${PORT}/"

# Helper: silent reachability test, ≤3 s
reachable() {
    /usr/bin/curl -m 3 -sS -o /dev/null -w "%{http_code}" "$1" 2>/dev/null
}

# 1) Try prod first (zero-friction default for daily use).
prod_code=$(reachable "$PROD_URL")
if [ "$prod_code" = "200" ]; then
    /usr/bin/xdg-open "$PROD_URL" >/dev/null 2>&1 &
    exit 0
fi

# 2) Try local already-running.
local_code=$(reachable "$LOCAL_URL")
if [ "$local_code" = "200" ]; then
    /usr/bin/xdg-open "$LOCAL_URL" >/dev/null 2>&1 &
    exit 0
fi

# 3) Boot local mix phx.server in a visible gnome-terminal.
/usr/bin/gnome-terminal --title="AIM Phoenix dev server" -- \
    /usr/bin/bash -lc "
        cd '${PHOENIX}' || exit 1;
        echo '── starting AIM Phoenix LiveView (port ${PORT}) ──';
        echo 'Run mix deps.get first if you see compile errors.';
        PORT=${PORT} /usr/bin/mix phx.server;
        echo;
        echo 'phx.server exited; press Enter to close window.';
        read
    "

# Give server ~6s to bind, then open browser. Polite poll.
for i in $(/usr/bin/seq 1 12); do
    /usr/bin/sleep 0.5
    code=$(reachable "$LOCAL_URL")
    if [ "$code" = "200" ]; then
        /usr/bin/xdg-open "$LOCAL_URL" >/dev/null 2>&1 &
        exit 0
    fi
done

# Server didn't bind — fall back to opening localhost anyway (browser will
# show "can't connect" — the terminal will explain why).
/usr/bin/xdg-open "$LOCAL_URL" >/dev/null 2>&1 &
exit 0
