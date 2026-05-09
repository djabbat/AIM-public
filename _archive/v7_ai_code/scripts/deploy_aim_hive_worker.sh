#!/usr/bin/env bash
# scripts/deploy_aim_hive_worker.sh — install + enable aim-hive-worker timer.
#
# Wires the local AIM as a worker in the Hive federation:
#   • aim-hive-worker.service — one-shot, runs `aim-hive-telemetry contribute`
#   • aim-hive-worker.timer    — fires service every 60 min (after 5 min boot delay)
#
# Pre-req: AIM_HIVE_QUEEN_URL set in ~/.aim_env. Without it the contribute
# call fails with "queen URL not set". Worker is read-only side-effect-wise
# (DP-budget gate + L_PRIVACY scrub before any POST), so failure is safe.
#
# Usage:
#   bash scripts/deploy_aim_hive_worker.sh [--user|--system]
#
# Default: --user (no sudo needed; runs under your login session). Use
# --system for headless server deploy.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/deploy/systemd"
SERVICE="aim-hive-worker.service"
TIMER="aim-hive-worker.timer"
BIN="$REPO_ROOT/rust-core/target/release/aim-hive-telemetry"
MODE="${1:---user}"

echo "==> aim-hive-worker deploy ($MODE)"

# 1. Ensure binary present
if [[ ! -x "$BIN" ]]; then
    echo "Binary missing; building aim-hive-worker..."
    (cd "$REPO_ROOT/rust-core" && cargo build -p aim-hive-worker --release)
fi

# 2. Ensure ~/.aim_env has AIM_HIVE_QUEEN_URL
if [[ ! -f "$HOME/.aim_env" ]]; then
    echo "ERROR: ~/.aim_env not found — required for AIM_HIVE_QUEEN_URL"
    exit 1
fi
if ! /usr/bin/grep -q "^AIM_HIVE_QUEEN_URL=" "$HOME/.aim_env"; then
    echo "WARN: AIM_HIVE_QUEEN_URL not in ~/.aim_env"
    echo "  Add e.g.:  AIM_HIVE_QUEEN_URL=http://127.0.0.1:8090"
    echo "  (or your remote queen, e.g. https://hive.longevity.ge)"
    echo "  Worker timer will install but contribute will fail until set."
fi

# 3. Cache dir for timestamp tracking
/usr/bin/mkdir -p "$HOME/.cache/aim"

# 4. Install unit files
case "$MODE" in
    --user)
        DST="$HOME/.config/systemd/user"
        /usr/bin/mkdir -p "$DST"
        /usr/bin/cp -v "$SRC_DIR/$SERVICE" "$DST/$SERVICE"
        /usr/bin/cp -v "$SRC_DIR/$TIMER"   "$DST/$TIMER"
        /usr/bin/systemctl --user daemon-reload
        /usr/bin/systemctl --user enable --now "$TIMER"
        echo ""
        echo "==> Status:"
        /usr/bin/systemctl --user status "$TIMER" --no-pager -l 2>&1 | /usr/bin/head -10
        ;;
    --system)
        DST="/etc/systemd/system"
        sudo /usr/bin/cp -v "$SRC_DIR/$SERVICE" "$DST/$SERVICE"
        sudo /usr/bin/cp -v "$SRC_DIR/$TIMER"   "$DST/$TIMER"
        sudo /usr/bin/systemctl daemon-reload
        sudo /usr/bin/systemctl enable --now "$TIMER"
        echo ""
        echo "==> Status:"
        sudo /usr/bin/systemctl status "$TIMER" --no-pager -l 2>&1 | /usr/bin/head -10
        ;;
    *)
        echo "usage: $0 [--user|--system]"
        exit 1
        ;;
esac

echo ""
echo "==> Done. Useful commands:"
echo "  systemctl $MODE list-timers --all aim-hive-worker.timer"
echo "  journalctl $MODE -u aim-hive-worker -f"
echo "  systemctl $MODE start aim-hive-worker.service     # manual fire"
