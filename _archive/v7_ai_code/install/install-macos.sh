#!/usr/bin/env bash
# AIM Rust + Phoenix installer — macOS (launchd)
#
# Builds the Rust workspace, the Phoenix release, wires launchd plists.
# No Docker. Per CLAUDE.md HARD CONSTRAINT.

set -euo pipefail

PREFIX="${PREFIX:-$HOME/Library/Application\ Support/aim}"
PREFIX="${PREFIX// /\\ }"
PREFIX_RAW="${PREFIX//\\ / }"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX_RAW="$2"; shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[aim-install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[aim-install]\033[0m %s\n' "$*" >&2; }
need() { command -v "$1" >/dev/null 2>&1 || { err "need $1 — install via brew"; exit 1; }; }

log "checking toolchain"
need git
need cargo
need rustc
need elixir
need mix

SRC="${SRC:-$PWD}"
if [[ ! -f "$SRC/AIM/rust-core/Cargo.toml" ]]; then
  err "run from a LongevityCommon checkout (need AIM/rust-core/Cargo.toml at \$SRC)"
  exit 1
fi

log "building Rust workspace (release profile)"
(cd "$SRC/AIM/rust-core" && cargo build --release --workspace)

log "building Phoenix umbrella (mix release)"
(cd "$SRC/AIM/phoenix-umbrella" && \
  MIX_ENV=prod mix deps.get --only prod && \
  MIX_ENV=prod mix compile && \
  MIX_ENV=prod mix release --overwrite)

log "staging into $PREFIX_RAW"
mkdir -p "$PREFIX_RAW"/{bin,phoenix,etc,logs}

cp -r "$SRC/AIM/rust-core/target/release/aim-"* "$PREFIX_RAW/bin/" 2>/dev/null || true

PHOENIX_REL="$(find "$SRC/AIM/phoenix-umbrella" -maxdepth 6 -type d -name 'rel' | head -1)"
if [[ -d "$PHOENIX_REL" ]]; then
  cp -R "$PHOENIX_REL/" "$PREFIX_RAW/phoenix/"
fi

# ── launchd plists ───────────────────────────────────────────────────────
LA_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LA_DIR"

cat > "$LA_DIR/com.longevitycommon.aim.orchestrator.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.longevitycommon.aim.orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PREFIX_RAW/bin/aim-llm</string>
    <string>serve</string>
  </array>
  <key>WorkingDirectory</key><string>$PREFIX_RAW</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PREFIX_RAW/logs/orchestrator.log</string>
  <key>StandardErrorPath</key><string>$PREFIX_RAW/logs/orchestrator.err.log</string>
</dict>
</plist>
EOF

cat > "$LA_DIR/com.longevitycommon.aim.phoenix.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.longevitycommon.aim.phoenix</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PREFIX_RAW/phoenix/bin/aim_web</string>
    <string>start</string>
  </array>
  <key>WorkingDirectory</key><string>$PREFIX_RAW/phoenix</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MIX_ENV</key><string>prod</string>
    <key>PHX_SERVER</key><string>true</string>
    <key>PORT</key><string>4000</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PREFIX_RAW/logs/phoenix.log</string>
  <key>StandardErrorPath</key><string>$PREFIX_RAW/logs/phoenix.err.log</string>
</dict>
</plist>
EOF

mkdir -p "$HOME/.local/bin"
[[ -x "$PREFIX_RAW/bin/aim-llm" ]] && ln -sf "$PREFIX_RAW/bin/aim-llm" "$HOME/.local/bin/aim"

cat <<HINT

✅ AIM installed under $PREFIX_RAW

Start:    launchctl load ~/Library/LaunchAgents/com.longevitycommon.aim.orchestrator.plist
          launchctl load ~/Library/LaunchAgents/com.longevitycommon.aim.phoenix.plist
Stop:     launchctl unload ~/Library/LaunchAgents/com.longevitycommon.aim.{orchestrator,phoenix}.plist
URL:      http://127.0.0.1:4000/

Provider keys go in ~/.aim_env:
    DEEPSEEK_API_KEY=...

HINT
