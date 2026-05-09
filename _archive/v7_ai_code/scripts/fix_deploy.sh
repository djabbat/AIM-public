#!/usr/bin/env bash
# Fix the two deploy bugs:
#   1. release binaries missing  → cargo build --release
#   2. ~/.aim_env has shell `export ` prefix → strip for systemd

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "── 1. Stripping 'export ' from ~/.aim_env (backup kept) ───"
ENV_FILE="$HOME/.aim_env"
cp "$ENV_FILE" "${ENV_FILE}.before-export-strip-$(date +%Y%m%d-%H%M%S)"
# Remove leading "export " on every line; keep KEY=VALUE.
sed -i 's/^export //' "$ENV_FILE"
echo "  done. lines that still start with non-KEY=:"
grep -nE '^[^A-Za-z_#]' "$ENV_FILE" || echo "  (none — file is clean)"

echo
echo "── 2. Building release binaries (this takes 1-3 min) ───"
cd "$ROOT/rust-core"
cargo build --release \
  --bin aim-llm --bin aim-rag --bin aim-medkb --bin aim-doctor --bin aim-generalist
ls -la target/release/aim-* | grep -v '\.d$'

echo
echo "── 3. Optional: stop the crash-loop right now ───"
echo "  Run as your user (no sudo password needed if --user systemd):"
echo "  sudo systemctl stop aim-doctor"
echo
echo "── 4. After this script, re-load systemd & start ───"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl restart aim.target"
echo "  journalctl -fu aim-doctor"
