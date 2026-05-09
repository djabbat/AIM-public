#!/usr/bin/env bash
# scripts/desktop/aim_chat_launch.sh
# Open AIM Chat as a standalone window (no browser tabs/toolbar).
#
# UX:
#   * Reuses local Phoenix dev server (port :4000) — boots it via
#     aim_local_launch helpers if not already up.
#   * Shows zenity --progress (pulsate) during boot.
#   * Opens http://127.0.0.1:4000/chat as a Chrome --app= window
#     (PWA-style: just title bar + content, no URL bar / tabs).
#   * Firefox fallback uses --new-window when Chrome unavailable.
set -uo pipefail
REPO_ROOT="/home/oem/Desktop/LongevityCommon/AIM"
PHOENIX="$REPO_ROOT/phoenix-umbrella"
PORT="${AIM_LOCAL_PORT:-4000}"
CHAT_URL="http://127.0.0.1:${PORT}/chat"
LOG="/tmp/aim_local_phx.log"
PIDFILE="/tmp/aim_local_phx.pid"

reachable() {
    /usr/bin/curl -m 2 -sS -o /dev/null -w "%{http_code}" "$1" 2>/dev/null
}

show_error() {
    local title="$1" body="$2"
    if command -v /usr/bin/zenity >/dev/null 2>&1; then
        /usr/bin/zenity --error --width=720 --title="$title" --text="$body" 2>/dev/null
    else
        /usr/bin/notify-send -u critical "$title" "$body" 2>/dev/null || \
            echo "$title: $body" >&2
    fi
}

open_chat_window() {
    local url="$1"
    local profile_dir="$HOME/.cache/aim-chat-chrome"
    /usr/bin/mkdir -p "$profile_dir"
    if command -v /usr/bin/google-chrome >/dev/null 2>&1; then
        /usr/bin/google-chrome \
            --app="$url" \
            --user-data-dir="$profile_dir" \
            --window-size=900,720 \
            --no-first-run \
            --no-default-browser-check \
            >/dev/null 2>&1 &
    elif command -v /usr/bin/firefox >/dev/null 2>&1; then
        /usr/bin/firefox --new-window "$url" >/dev/null 2>&1 &
    else
        /usr/bin/xdg-open "$url" >/dev/null 2>&1 &
    fi
}

# 1) Already running?
if [ "$(reachable "http://127.0.0.1:${PORT}/")" = "200" ]; then
    open_chat_window "$CHAT_URL"
    exit 0
fi

# 2) Stale PID?
if [ -f "$PIDFILE" ]; then
    OLDPID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
        kill "$OLDPID" 2>/dev/null
        sleep 1
        kill -9 "$OLDPID" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
fi

# 3) Boot phx.server detached.
: > "$LOG"
(
    cd "$PHOENIX" || exit 1
    export PHX_SERVER=true
    export AIM_WEB_PORT="$PORT"
    export PORT="$PORT"
    export AIM_ADMIN_ENABLE=1
    exec /usr/bin/mix phx.server >>"$LOG" 2>&1
) &
PHX_PID=$!
echo "$PHX_PID" > "$PIDFILE"

# 4) Progress dialog.
(
    STAGE="Starting Erlang VM…"
    for i in $(/usr/bin/seq 1 240); do
        /usr/bin/sleep 0.5
        echo "# $STAGE" || exit 0
        case "$i" in
            10) STAGE="Compiling Phoenix umbrella…" ;;
            30) STAGE="Loading aim_web LiveViews…" ;;
            60) STAGE="Binding 127.0.0.1:${PORT}…" ;;
            120) STAGE="Still booting (cold compile, please wait)…" ;;
        esac
        CODE="$(reachable "http://127.0.0.1:${PORT}/")"
        if [ "$CODE" = "200" ] || [ "$CODE" = "302" ] || [ "$CODE" = "301" ]; then
            echo "100"
            echo "# Ready — opening chat window"
            /usr/bin/sleep 0.3
            exit 0
        fi
        if ! kill -0 "$PHX_PID" 2>/dev/null; then
            echo "# Phoenix exited unexpectedly"
            /usr/bin/sleep 0.3
            exit 1
        fi
    done
    echo "# Timeout: Phoenix did not bind port within 120s"
    exit 2
) | /usr/bin/zenity --progress \
        --title="AIM Chat — starting" \
        --text="Starting Erlang VM…" \
        --pulsate \
        --auto-close \
        --width=480 \
        --no-cancel 2>/dev/null

# 5) Outcome.
if [ "$(reachable "http://127.0.0.1:${PORT}/")" = "200" ]; then
    open_chat_window "$CHAT_URL"
    exit 0
fi

# Failure.
if kill -0 "$PHX_PID" 2>/dev/null; then
    kill "$PHX_PID" 2>/dev/null
    sleep 1
    kill -9 "$PHX_PID" 2>/dev/null || true
fi
rm -f "$PIDFILE"

TAIL="$(/usr/bin/tail -n 30 "$LOG" 2>/dev/null | /usr/bin/sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
[ -z "$TAIL" ] && TAIL="(empty log — mix produced no output)"
show_error "AIM Chat — Phoenix failed to start" "Port ${PORT} did not respond.\n\nLast 30 lines of ${LOG}:\n\n<tt>${TAIL}</tt>"
exit 1
