#!/usr/bin/env bash
# AIM Rust + Phoenix installer — Linux (systemd)
#
# Builds the Rust workspace, the Phoenix release, and wires both as
# native systemd units. No Docker. Per CLAUDE.md HARD CONSTRAINT.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/djabbat/AIM-public/main/install/install-linux.sh | bash
#   # or, from a checkout:
#   ./install/install-linux.sh [--prefix /opt/aim]

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local/aim}"
SERVICE_USER="${USER}"
RUST_MIN="1.78"
ELIXIR_MIN="1.16"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --user)   SERVICE_USER="$2"; shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[aim-install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[aim-install]\033[0m %s\n' "$*" >&2; }
need() { command -v "$1" >/dev/null 2>&1 || { err "need $1 — please install"; exit 1; }; }

# ── prerequisites ────────────────────────────────────────────────────────
log "checking toolchain"
need git
need bash
need cargo
need rustc
if ! command -v elixir >/dev/null 2>&1; then
  err "elixir $ELIXIR_MIN+ required — install via your distro or asdf"
  exit 1
fi
if ! command -v mix >/dev/null 2>&1; then
  err "mix not on PATH"
  exit 1
fi

# ── source ───────────────────────────────────────────────────────────────
SRC="${SRC:-$PWD}"
if [[ ! -f "$SRC/AIM/rust-core/Cargo.toml" ]]; then
  err "run from a LongevityCommon checkout (need AIM/rust-core/Cargo.toml at \$SRC)"
  exit 1
fi

# ── build Rust workspace ─────────────────────────────────────────────────
log "building Rust workspace (release profile)"
(cd "$SRC/AIM/rust-core" && cargo build --release --workspace)

# ── build Phoenix umbrella ───────────────────────────────────────────────
log "building Phoenix umbrella (mix release)"
(cd "$SRC/AIM/phoenix-umbrella" && \
  MIX_ENV=prod mix deps.get --only prod && \
  MIX_ENV=prod mix compile && \
  MIX_ENV=prod mix release --overwrite)

# ── stage into PREFIX ────────────────────────────────────────────────────
log "staging into $PREFIX"
mkdir -p "$PREFIX"/{bin,phoenix,etc,logs}

cp -r "$SRC/AIM/rust-core/target/release/aim-"* "$PREFIX/bin/" 2>/dev/null || true
[[ -x "$SRC/AIM/rust-core/target/release/aim-llm" ]] && cp "$SRC/AIM/rust-core/target/release/aim-llm" "$PREFIX/bin/"

# Phoenix release lives under apps/aim_web/_build/prod/rel/<release_name>/
PHOENIX_REL="$(find "$SRC/AIM/phoenix-umbrella" -maxdepth 6 -type d -name 'rel' | head -1)"
if [[ -d "$PHOENIX_REL" ]]; then
  cp -r "$PHOENIX_REL/." "$PREFIX/phoenix/"
fi

# ── systemd units ────────────────────────────────────────────────────────
log "writing systemd units"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/aim-orchestrator.service" <<EOF
[Unit]
Description=AIM Rust orchestrator (aim-llm)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PREFIX
EnvironmentFile=-$HOME/.aim_env
ExecStart=$PREFIX/bin/aim-llm serve
Restart=on-failure
RestartSec=5
StandardOutput=append:$PREFIX/logs/orchestrator.log
StandardError=append:$PREFIX/logs/orchestrator.err.log

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_DIR/aim-phoenix.service" <<EOF
[Unit]
Description=AIM Phoenix LiveView frontend
After=network-online.target aim-orchestrator.service
Wants=aim-orchestrator.service

[Service]
Type=simple
WorkingDirectory=$PREFIX/phoenix
EnvironmentFile=-$HOME/.aim_env
Environment=MIX_ENV=prod
Environment=PHX_SERVER=true
Environment=PORT=4000
ExecStart=$PREFIX/phoenix/bin/aim_web start
Restart=on-failure
RestartSec=5
StandardOutput=append:$PREFIX/logs/phoenix.log
StandardError=append:$PREFIX/logs/phoenix.err.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
log "units installed → $SYSTEMD_DIR/aim-{orchestrator,phoenix}.service"

# ── PATH symlink ─────────────────────────────────────────────────────────
mkdir -p "$HOME/.local/bin"
[[ -x "$PREFIX/bin/aim-llm" ]] && ln -sf "$PREFIX/bin/aim-llm" "$HOME/.local/bin/aim"

cat <<HINT

✅ AIM installed under $PREFIX

Start:    systemctl --user start aim-orchestrator aim-phoenix
Enable:   systemctl --user enable --now aim-orchestrator aim-phoenix
Logs:     journalctl --user -u aim-orchestrator -f
URL:      http://127.0.0.1:4000/

Set provider keys (DeepSeek / Groq / Anthropic / Gemini) in ~/.aim_env:
    DEEPSEEK_API_KEY=...
    GROQ_API_KEY=...

HINT
