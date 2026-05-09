#!/usr/bin/env bash
# aim-self-dev-eval.sh — scheduled self-dev eval harness.
#
# Detects regressions in AIM and emits a `self_dev_proposal` entity into the
# AIM_FS inbox for the user to review. Per `feedback_no_edit_asimov_laws` the
# proposal NEVER touches Asimov-kernel laws without explicit user command —
# the proposal is just a record; applying it is manual.
#
# Schedule via systemd-user timer (see aim-self-dev-eval.timer):
#   systemctl --user enable --now aim-self-dev-eval.timer
#
# Each run:
#   1. Run cheap regression checks (rust tests, schema drift, sweeper sanity).
#   2. For each FAIL or WARN, build a JSON answers map and pipe to
#      aim-onboard --template self_dev_proposal.yaml --non-interactive,
#      which proposes a `proposal_v1` entity into AIM_FS inbox.
#   3. Emit a summary line to stdout (captured by journald via the .service).
#
# Designed to be safe to run repeatedly: the resulting proposals carry the
# default approval policy (require_approval_for: ["proposal", ...]), so they
# always land in inbox awaiting human review.
set -euo pipefail

AIM_ROOT="${AIM_FS_ROOT:-$HOME/.aim_fs}"
TENANT="${AIM_FS_TENANT:-djabbat}"
ONBOARD="${AIM_ONBOARD_BIN:-aim-onboard}"
TEMPLATE="${AIM_ONBOARD_TEMPLATES_DIR:-/opt/aim/templates}/self_dev_proposal.yaml"

if [ ! -x "$(command -v "$ONBOARD")" ]; then
    echo "aim-self-dev-eval: $ONBOARD not on PATH; skipping"
    exit 0
fi
if [ ! -f "$TEMPLATE" ]; then
    echo "aim-self-dev-eval: template missing at $TEMPLATE; skipping"
    exit 0
fi

# Helper: emit a self_dev_proposal via aim-onboard --non-interactive.
emit_proposal() {
    local title=$1
    local proposal_type=$2
    local priority=$3
    local rationale=$4
    local what=$5
    shift 5
    # Remaining args are evidence lines.
    local evidence_json
    evidence_json=$(jq -nc '$ARGS.positional' --args "$@")

    jq -nc \
        --arg title "$title" \
        --arg proposal_type "$proposal_type" \
        --arg priority "$priority" \
        --arg blast_radius "low" \
        --arg rationale "$rationale" \
        --arg what_proposed "$what" \
        --argjson evidence "$evidence_json" \
        --argjson risks '["self-dev eval is conservative; may emit false positives"]' \
        --arg rollback "Reject the proposal in AIM Inbox UI." \
        --argjson kernel_law_touch false \
        '{title:$title, proposal_type:$proposal_type, priority:$priority,
          blast_radius:$blast_radius, rationale:$rationale,
          what_proposed:$what_proposed, evidence:$evidence,
          risks:$risks, rollback:$rollback, kernel_law_touch:$kernel_law_touch}' \
        | "$ONBOARD" \
            --template "$TEMPLATE" \
            --tenant-id "$TENANT" \
            --aim-root "$AIM_ROOT" \
            --non-interactive
}

count=0
report() {
    echo "[$(date -Iseconds)] aim-self-dev-eval: $*"
}

# Check 1: cargo tests on aim-fs (cheap if release artifacts exist).
if command -v cargo >/dev/null && [ -d "${AIM_RUST_CORE:-$HOME/Desktop/LongevityCommon/AIM/rust-core}" ]; then
    cd "${AIM_RUST_CORE:-$HOME/Desktop/LongevityCommon/AIM/rust-core}"
    if ! cargo test -p aim-fs --lib --quiet 2>/dev/null; then
        emit_proposal \
            "aim-fs unit tests failing" \
            "doc_fix" \
            "P0" \
            "Daily eval ran cargo test -p aim-fs and one or more tests failed." \
            "Investigate failing test, fix code or test, re-run." \
            "cargo test exit code != 0 at $(date -Iseconds)"
        count=$((count + 1))
        report "regression detected: aim-fs tests failing"
    fi
fi

# Check 2: AIM_FS sweeper sanity. Issue a sweep + measure latency; > 1 s
# on a fresh DB indicates concern.
if command -v aim-fs >/dev/null; then
    start=$(date +%s%N)
    if printf '{"op":"sweep"}\n' | aim-fs >/dev/null 2>&1; then
        end=$(date +%s%N)
        elapsed_ms=$(((end - start) / 1000000))
        if [ "$elapsed_ms" -gt 1000 ]; then
            emit_proposal \
                "Sweeper latency exceeds budget" \
                "param_tune" \
                "P1" \
                "Sweep took ${elapsed_ms}ms (SPEC budget: <200ms on 1k entities). Likely candidate: missing index on (status, decay_expires_at)." \
                "Profile sweeper SQL with EXPLAIN QUERY PLAN; add covering index if absent." \
                "sweep_latency_ms=${elapsed_ms}" \
                "spec_budget_ms=200"
            count=$((count + 1))
            report "regression detected: sweeper too slow (${elapsed_ms}ms)"
        fi
    fi
fi

# Check 3: inbox backlog. > 50 pending = doctor not reviewing; surface as P2.
if command -v aim-fs >/dev/null; then
    pending_n=$(printf '{"op":"list_pending","tenant_id":"%s","limit":1000}\n' "$TENANT" \
        | aim-fs 2>/dev/null \
        | jq -r '.result | length' 2>/dev/null || echo 0)
    if [ "${pending_n:-0}" -gt 50 ]; then
        emit_proposal \
            "Inbox backlog exceeds 50 pending" \
            "rule" \
            "P2" \
            "Approval queue at $pending_n pending; doctor likely not reviewing daily." \
            "Either lower auto_approve_observational_with_confidence_above (currently 0.95) or add Telegram nudge when count > 50." \
            "pending_count=$pending_n" \
            "max_inactivity_days=30"
        count=$((count + 1))
        report "policy concern: inbox at $pending_n pending"
    fi
fi

if [ "$count" -eq 0 ]; then
    report "all checks pass — no proposals emitted"
else
    report "emitted $count self_dev_proposal entries to inbox"
fi
