#!/usr/bin/env bash
# scripts/test_all.sh — single-command full regression for AIM (P3 helper).
#
# Runs: Python pytest + Rust workspace tests + Phoenix mix test.
# Skips network-marked Python tests by default (set AIM_TEST_NETWORK=1
# to include them — risks Groq circuit-breaker hangs).
#
# Usage:
#   bash scripts/test_all.sh              # all three tiers, no network
#   bash scripts/test_all.sh --python     # just Python
#   bash scripts/test_all.sh --rust       # just Rust
#   bash scripts/test_all.sh --phoenix    # just Phoenix
#   bash scripts/test_all.sh --quick      # cornerstone-relevant subset only

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_BLOCKS=()

cyan() { printf '\033[1;36m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
red() { printf '\033[1;31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }

VENV_PY="$REPO_ROOT/venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$(command -v python3)"

mode="${1:-all}"

# ── Python ──────────────────────────────────────────────────────────────

run_python_quick() {
    cyan "▶ Python — cornerstone subset"
    local marks="not network"
    [[ "${AIM_TEST_NETWORK:-0}" == "1" ]] && marks=""
    if "$VENV_PY" -m pytest \
        tests/test_kernel.py \
        tests/test_kernel_extended.py \
        tests/test_kernel_scenarios.py \
        tests/test_patient_as_project_phase7.py \
        tests/test_phase8_shims.py \
        tests/test_interactions.py \
        tests/test_regimen_validator.py \
        tests/test_llm_client.py \
        tests/test_coach_shim.py \
        tests/test_pam_trajectory_e2e.py \
        tests/test_aim_verify_parity.py \
        -q --no-header ${marks:+-m "$marks"} 2>&1 | tail -8; then
        PASS=$((PASS + 1))
        green "✓ Python cornerstone subset"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("Python cornerstone subset")
        red "✗ Python cornerstone subset"
    fi
}

run_python_full() {
    cyan "▶ Python — full suite"
    local marks="not network"
    [[ "${AIM_TEST_NETWORK:-0}" == "1" ]] && marks=""
    if "$VENV_PY" -m pytest tests/ \
        --ignore=tests/test_kernel_parity.py \
        -q --no-header ${marks:+-m "$marks"} 2>&1 | tail -5; then
        PASS=$((PASS + 1))
        green "✓ Python full"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("Python full")
        red "✗ Python full (note: parity tests skipped due to Groq circuit hangs)"
    fi
}

run_ai_subproject() {
    cyan "▶ Python — AI/tests/ subproject"
    # 110 known Phase-9 broken tests are auto-skipped via
    # AI/tests/conftest.py + AI/tests/_phase9_known_broken.txt.
    # See STRATEGY.md P1-2 for rewrite plan.
    if "$VENV_PY" -m pytest AI/tests/ \
        -q --no-header --tb=no 2>&1 | tail -3; then
        PASS=$((PASS + 1))
        green "✓ AI subproject"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("AI subproject")
        red "✗ AI subproject"
    fi
}

# ── Rust ────────────────────────────────────────────────────────────────

run_rust_cornerstone() {
    cyan "▶ Rust — cornerstone+infra crates"
    local crates=(aim-coach aim-llm aim-llm-router aim-kernel aim-pam
                  aim-disagreement aim-codesign aim-interactions
                  aim-regimen-validator aim-smart-routing aim-reflexion)
    local cmd="cargo test --lib"
    for c in "${crates[@]}"; do cmd+=" -p $c"; done
    if (cd rust-core && eval "$cmd" 2>&1 | grep "test result" | tail -15); then
        PASS=$((PASS + 1))
        green "✓ Rust cornerstone"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("Rust cornerstone")
        red "✗ Rust cornerstone"
    fi
}

run_rust_workspace() {
    cyan "▶ Rust — full workspace (~192 crates)"
    if (cd rust-core && cargo test --workspace --lib 2>&1 | tail -3); then
        PASS=$((PASS + 1))
        green "✓ Rust workspace"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("Rust workspace")
        red "✗ Rust workspace"
    fi
}

# ── Phoenix ─────────────────────────────────────────────────────────────

run_phoenix() {
    cyan "▶ Phoenix — aim_web tests"
    if (cd phoenix-umbrella && mix test apps/aim_web/test/ 2>&1 | tail -3); then
        PASS=$((PASS + 1))
        green "✓ Phoenix"
    else
        FAIL=$((FAIL + 1))
        FAILED_BLOCKS+=("Phoenix")
        red "✗ Phoenix"
    fi
}

# ── Dispatch ────────────────────────────────────────────────────────────

START=$(date +%s)

case "$mode" in
    --python)  run_python_full ;;
    --rust)    run_rust_workspace ;;
    --phoenix) run_phoenix ;;
    --quick)
        run_python_quick
        run_rust_cornerstone
        run_phoenix
        ;;
    --ai)
        run_ai_subproject
        ;;
    all|--all|"")
        run_python_full
        run_ai_subproject
        run_rust_workspace
        run_phoenix
        ;;
    *)
        echo "usage: $0 [all|--python|--rust|--phoenix|--quick]"
        echo ""
        echo "ENV:"
        echo "  AIM_TEST_NETWORK=1   include network-marked Python tests"
        exit 1
        ;;
esac

DUR=$(($(date +%s) - START))

echo ""
cyan "═══════════════════════════════════════"
if [[ $FAIL -eq 0 ]]; then
    green "ALL ${PASS} BLOCKS PASS  (${DUR}s)"
    exit 0
else
    red "${FAIL} of $((PASS + FAIL)) BLOCKS FAILED  (${DUR}s)"
    for b in "${FAILED_BLOCKS[@]}"; do
        red "  ✗ $b"
    done
    exit 1
fi
