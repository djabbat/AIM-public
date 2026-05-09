#!/usr/bin/env bash
# End-to-end functional test: Phoenix gateway → aim-doctor → aim-llm → Ollama.
#
# Requires:
#   - Ollama running on 127.0.0.1:11434 with llama3.2 pulled
#   - Build artifacts (this script will build if missing)
#
# Steps:
#   1. Start all 5 Rust services + Phoenix in background.
#   2. POST /api/v1/chat with admin token.
#   3. POST /api/v1/diagnose using a sample case.
#   4. Verify replies are non-empty.
#   5. Tear down.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/rust-core"
cargo build --bin aim-llm --bin aim-rag --bin aim-medkb --bin aim-doctor --bin aim-generalist

LOG_DIR="$(mktemp -d -t aim-e2e-XXXX)"
echo "logs: $LOG_DIR"
PIDS=()
cleanup() {
  echo "stopping services..."
  kill "${PIDS[@]}" 2>/dev/null || true
  pkill -f phoenix-umbrella 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT

start_rust() {
  ./target/debug/$1 > "$LOG_DIR/$1.log" 2>&1 &
  PIDS+=("$!")
  echo "started $1 (pid $!)"
}

export AIM_GENERALIST_ROOT="${AIM_GENERALIST_ROOT:-$ROOT/Patients}"
start_rust aim-llm
start_rust aim-rag
start_rust aim-medkb
start_rust aim-doctor
start_rust aim-generalist
sleep 2

# Phoenix in background.
cd "$ROOT/phoenix-umbrella"
AIM_REQUIRE_AUTH=1 mix phx.server > "$LOG_DIR/phoenix.log" 2>&1 &
PHX_PID=$!
PIDS+=("$PHX_PID")
echo "started phoenix (pid $PHX_PID)"
sleep 5

# Admin token (read from ~/.aim_env).
TOKEN=$(grep '^AIM_USER_TOKEN=' ~/.aim_env | head -1 | cut -d= -f2)
if [ -z "$TOKEN" ]; then
  echo "ERROR: AIM_USER_TOKEN missing in ~/.aim_env"
  exit 2
fi

PASS=0; FAIL=0
check() {
  local label=$1
  local actual=$2
  local pattern=$3
  if echo "$actual" | grep -qE "$pattern"; then
    echo "  PASS  $label"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $label"
    echo "         response: $(echo "$actual" | head -c 300)"
    FAIL=$((FAIL+1))
  fi
}

echo
echo "── Phoenix gateway health ───"
HG=$(curl -s -m 5 http://127.0.0.1:4003/api/v1/health)
check "gateway /health" "$HG" '"status":"ok"'

echo
echo "── Phoenix system aggregator ───"
HSA=$(curl -s -m 8 http://127.0.0.1:4003/api/v1/system/health)
check "system aggregator overall" "$HSA" '"overall_status":"ok"'

echo
echo "── /api/v1/chat (auth required) ───"
RESP=$(curl -s -m 60 -X POST http://127.0.0.1:4003/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"reply with: pong"}],"provider":"ollama","model_hint":"llama3.2"}')
check "chat reply non-empty" "$RESP" '"reply":"[A-Za-z]'

echo
echo "── /api/v1/diagnose (sample case) ───"
INTAKE=$(curl -s -m 60 -X POST http://127.0.0.1:8773/v1/intake \
  -H 'content-type: application/json' \
  -d '{"complaint":"chest pain"}')
echo "  intake: $(echo "$INTAKE" | head -c 200)"

CASE_ID=$(echo "$INTAKE" | python3 -c "import json,sys;print(json.load(sys.stdin).get('case_id',''))" 2>/dev/null)
if [ -n "$CASE_ID" ]; then
  RESP=$(curl -s -m 60 -X POST http://127.0.0.1:4003/api/v1/diagnose \
    -H "Authorization: Bearer $TOKEN" \
    -H "content-type: application/json" \
    -d "{\"case_id\":\"$CASE_ID\"}")
  check "diagnose returns plan" "$RESP" '"plan":'
else
  echo "  SKIP  no case_id from intake"
fi

echo
echo "═════════════════════════════════════════════"
echo "  E2E result: $PASS passed, $FAIL failed"
echo "═════════════════════════════════════════════"
exit $FAIL
