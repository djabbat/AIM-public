#!/usr/bin/env bash
# scripts/deploy_aim_llm.sh — install + start aim-llm systemd unit (P2.5)
# Usage: bash scripts/deploy_aim_llm.sh
# Idempotent: re-running upgrades the service in place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$REPO_ROOT/systemd/aim-llm.service"
UNIT_DST="$HOME/.config/systemd/user/aim-llm.service"
BINARY="$REPO_ROOT/rust-core/target/release/aim-llm"
PORT="${AIM_LLM_PORT:-8770}"

echo "==> aim-llm deploy"

# 1. Ensure binary is built
if [[ ! -x "$BINARY" ]]; then
    echo "Binary missing; building..."
    (cd "$REPO_ROOT/rust-core" && cargo build -p aim-llm --release)
fi

# 2. Ensure ~/.aim_env exists (EnvironmentFile target)
if [[ ! -f "$HOME/.aim_env" ]]; then
    echo "ERROR: ~/.aim_env not found — required for API keys"
    echo "Create it with at least: GROQ_API_KEY=... DEEPSEEK_API_KEY=..."
    exit 1
fi

# 3. Install user systemd unit
mkdir -p "$(dirname "$UNIT_DST")"
cp "$UNIT_SRC" "$UNIT_DST"

# 4. Reload + enable + start
systemctl --user daemon-reload
systemctl --user enable aim-llm.service
systemctl --user restart aim-llm.service

# 5. Wait for bind
for i in {1..30}; do
    if ss -tln 2>/dev/null | grep -q ":$PORT"; then
        echo "✓ Bound on :$PORT"
        break
    fi
    sleep 1
done

# 6. Smoke
echo "==> /health:"
curl -s -m 3 "http://127.0.0.1:$PORT/health" || echo "(unreachable)"
echo ""
echo "==> /v1/providers:"
curl -s -m 3 "http://127.0.0.1:$PORT/v1/providers" | head -c 400
echo ""
echo "==> deploy complete"
echo "    journalctl --user -u aim-llm -f      # live logs"
echo "    systemctl --user status aim-llm      # status"
