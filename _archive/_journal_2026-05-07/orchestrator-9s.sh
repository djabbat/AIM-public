#!/bin/bash
# AIM Phase 3 orchestrator — 9-second cycle (per user 2026-05-04 directive).
#
# WHAT THIS DOES
#   Loops every 9 seconds and performs ONE no-op heartbeat: rebuilds the
#   `_journal/STAGES.md` file from `git log`. Does NOT generate code or
#   port modules — that work happens inside Claude /loop turns when the
#   ScheduleWakeup runtime fires.
#
# WHY 9 SECONDS IS NOT THE CLAUDE LOOP
#   ScheduleWakeup clamps `delaySeconds` to [60, 3600]. This script is an
#   external bash heartbeat that runs alongside any Claude session — it
#   keeps the journal current without depending on Claude itself.
#
# STOP
#   touch /tmp/STOP_AIM_ORCHESTRATOR
#
# START
#   bash _journal/orchestrator-9s.sh &
#   echo $! > /tmp/aim_orchestrator.pid
#
# LOG
#   tail -f ~/.cache/aim/orchestrator.log
set -euo pipefail

REPO="$HOME/Desktop/LongevityCommon/AIM"
JOURNAL="$REPO/_journal"
LOG="$HOME/.cache/aim/orchestrator.log"
STOP_FILE="/tmp/STOP_AIM_ORCHESTRATOR"

mkdir -p "$(dirname "$LOG")"

log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"
}

log "orchestrator started (interval=9s)"
trap 'log "orchestrator stopped (signal)"; exit 0' INT TERM

while true; do
    if [ -f "$STOP_FILE" ]; then
        log "orchestrator stopped ($STOP_FILE present)"
        rm -f "$STOP_FILE"
        exit 0
    fi

    # 1. Regenerate stage journal from git log
    if [ -x "$JOURNAL/regenerate.sh" ]; then
        if "$JOURNAL/regenerate.sh" > "$JOURNAL/STAGES.md.tmp" 2>/dev/null; then
            mv "$JOURNAL/STAGES.md.tmp" "$JOURNAL/STAGES.md"
        else
            rm -f "$JOURNAL/STAGES.md.tmp"
            log "regenerate failed"
        fi
    fi

    # 2. Optional: quick test count signal so we can spot regressions
    n_crates=$(grep -c '^    "crates/' "$REPO/rust-core/Cargo.toml" 2>/dev/null || echo 0)
    last_sha=$(cd "$REPO" && git log -1 --pretty=%h 2>/dev/null || echo "")
    log "tick: crates=$n_crates last=$last_sha"

    sleep 9
done
