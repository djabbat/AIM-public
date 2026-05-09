#!/usr/bin/env bash
# AIM end-to-end smoke test.
# Starts all 5 Rust services in background, probes each endpoint, prints OK/FAIL.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUST_CORE="$ROOT/rust-core"

cd "$RUST_CORE"

# 1. Build (release in CI; debug locally for speed).
PROFILE="${PROFILE:-debug}"
if [ "$PROFILE" = "release" ]; then
  cargo build --release --bin aim-llm --bin aim-rag --bin aim-medkb --bin aim-doctor --bin aim-generalist
  BIN_DIR="$RUST_CORE/target/release"
else
  cargo build --bin aim-llm --bin aim-rag --bin aim-medkb --bin aim-doctor --bin aim-generalist
  BIN_DIR="$RUST_CORE/target/debug"
fi

LOG_DIR="$(mktemp -d -t aim-smoke-XXXX)"
echo "logs: $LOG_DIR"
PIDS=()

start() {
  local name=$1; shift
  "$BIN_DIR/$name" "$@" > "$LOG_DIR/$name.log" 2>&1 &
  PIDS+=("$!")
  echo "started $name (pid $!)"
}

cleanup() {
  echo "stopping ${#PIDS[@]} services"
  kill "${PIDS[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT

export AIM_GENERALIST_ROOT="${AIM_GENERALIST_ROOT:-$ROOT/Patients}"

start aim-llm
start aim-rag
start aim-medkb
start aim-doctor
start aim-generalist

# Wait for ports.
sleep 2

PASS=0; FAIL=0
check() {
  local label=$1; local url=$2; local match=$3
  local out
  out=$(curl -s -m 5 "$url" 2>&1) || true
  if echo "$out" | grep -q "$match"; then
    echo "  PASS  $label"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $label  ($url)"
    echo "         $out" | head -c 200
    echo
    FAIL=$((FAIL+1))
  fi
}

echo
echo "── Health endpoints ───"
check "aim-llm health"       http://127.0.0.1:8770/health     '"status":"ok"'
check "aim-rag health"       http://127.0.0.1:8771/health     '"status":"ok"'
check "aim-medkb health"     http://127.0.0.1:8772/health     '"status":"ok"'
check "aim-doctor health"    http://127.0.0.1:8773/health     '"status":"ok"'
check "aim-generalist health" http://127.0.0.1:8774/health    '"status":"ok"'

echo
echo "── Metrics endpoints (any HTTP 200) ───"
check "aim-llm metrics"   http://127.0.0.1:8770/metrics   ''
check "aim-rag metrics"   http://127.0.0.1:8771/metrics   ''

echo
echo "── Functional ───"
check "aim-llm providers list" http://127.0.0.1:8770/v1/providers      'default_model'
check "aim-medkb lab list"     http://127.0.0.1:8772/v1/lab             'hemoglobin_m'
check "aim-medkb hemoglobin_m" http://127.0.0.1:8772/v1/lab/hemoglobin_m 'g/L'
check "aim-medkb interactions warfarin+aspirin" \
      'http://127.0.0.1:8772/v1/interactions?drugs=warfarin,aspirin'  '"severity":"major"'
check "aim-generalist tools"   http://127.0.0.1:8774/v1/tools          '"count":'

echo
echo "── Rag round-trip (upsert+search via curl) ───"
curl -s -X POST http://127.0.0.1:8771/v1/upsert \
  -H 'content-type: application/json' \
  -d '{"id":"smoke","text":"hemoglobin anemia diagnosis"}' >/dev/null
SEARCH=$(curl -s -X POST http://127.0.0.1:8771/v1/search \
  -H 'content-type: application/json' \
  -d '{"query":"anemia","k":1}')
if echo "$SEARCH" | grep -q '"id":"smoke"'; then
  echo "  PASS  rag upsert+search round-trip"
  PASS=$((PASS+1))
else
  echo "  FAIL  rag round-trip ($SEARCH)"
  FAIL=$((FAIL+1))
fi

echo
echo "═════════════════════════════════════════════"
echo "  Smoke result: $PASS passed, $FAIL failed"
echo "═════════════════════════════════════════════"
exit $FAIL
