#!/usr/bin/env bash
# build_packages.sh — собирает 3 distribution archive AIM:
#   release/dist/aim-<version>-linux.tar.gz
#   release/dist/aim-<version>-macos.tar.gz
#   release/dist/aim-<version>-windows.zip
#
# Каждый архив = source tree без venv / Patients / *.db / __pycache__ +
# OS-specific README. Распаковка → запуск install_node.{sh,ps1}.
#
# Usage:  ./release/build_packages.sh [VERSION]    (default: VERSION file)

set -euo pipefail

cd "$(dirname "$0")/.."
AIM_ROOT="$PWD"

# Parse args: optional --public flag, optional VERSION override.
PUBLIC=0
VERSION=""
for arg in "$@"; do
  case "$arg" in
    --public) PUBLIC=1 ;;
    *)        VERSION="$arg" ;;
  esac
done
VERSION="${VERSION:-$(cat release/VERSION 2>/dev/null || echo 0.1.0)}"

if [[ $PUBLIC -eq 1 ]]; then
  DIST="$AIM_ROOT/release/dist-public"
  SUFFIX=""
else
  DIST="$AIM_ROOT/release/dist"
  SUFFIX=""
fi

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

bold ">> Building AIM packages v$VERSION"
mkdir -p "$DIST"
rm -f "$DIST"/aim-*.tar.gz "$DIST"/aim-*.zip "$DIST"/aim-*.sha256

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Common exclusion list — never ships in any package.
EXCLUDES=(
  --exclude='venv'
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='.pytest_cache'
  --exclude='node_modules'
  --exclude='*.db'
  --exclude='*.db-shm'
  --exclude='*.db-wal'
  --exclude='*.db.backup-*'
  --exclude='Patients'
  --exclude='chroma_db'
  --exclude='backups'
  --exclude='logs'
  --exclude='*.log'
  --exclude='.cache'
  --exclude='release/dist'
  --exclude='aim_generalist.egg-info'
  --exclude='*.bak.*'
  --exclude='claude_memory_analysis.*'
  # Rust / Elixir build artefacts — only sources ship; users rebuild locally
  --exclude='target'
  --exclude='_build'
  --exclude='deps'
  --exclude='Cargo.lock.bak.*'
  # Patient INBOX, screenshots, anything ad-hoc
  --exclude='*.jpeg'
  --exclude='*.jpg'
  --exclude='*.png'
  --exclude='*.pdf'
  --exclude='*.docx'
  --exclude='*.zip'
  --exclude='*.tar.gz'
)

# Public packages additionally exclude internal docs (per CLAUDE.md rule).
if [[ $PUBLIC -eq 1 ]]; then
  EXCLUDES+=(
    --exclude='CONCEPT.md'
    --exclude='CLAUDE.md'
    --exclude='TODO.md'
    --exclude='PARAMETERS.md'
    --exclude='AUDIT_*.md'
    --exclude='DEEP_AUDIT_*.md'
    --exclude='ROADMAP_*.md'
    --exclude='CONCEPT_CODE_AUDIT_*.md'
    --exclude='AI/CLAUDE.md'
    --exclude='AI/FCLC_BORROW.md'
  )
fi

# Stage source tree once (rsync-style copy via tar).
bold ">> Staging source"
mkdir -p "$STAGE/aim-$VERSION"
tar "${EXCLUDES[@]}" -cf - -C "$AIM_ROOT" . | tar -xf - -C "$STAGE/aim-$VERSION"
green "   staged $(du -sh "$STAGE/aim-$VERSION" | cut -f1) at $STAGE"

# OS-specific READMEs go on top of the staged tree.
make_readme() {
  local plat=$1; local target=$2
  cat > "$target" <<EOF
AIM — Adaptive Intelligence for Medicine
========================================
Version: $VERSION
Platform: $plat
Source:   https://github.com/djabbat/LongevityCommon-public

Quick start
-----------
EOF
  if [[ "$plat" == "windows" ]]; then
    cat >> "$target" <<'EOF'
1. Open PowerShell in this directory.
2. Run:

       powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1

The installer will set up Python venv, optionally install Ollama,
and create %USERPROFILE%\.aim_env with your settings.

After install:
       python aim_cli.py            # interactive CLI
       python aim_gui.py            # GUI

To join a Hive (optional):
       echo AIM_HIVE_QUEEN_URL=https://hive.longevity.ge >> %USERPROFILE%\.aim_env
EOF
  else
    cat >> "$target" <<'EOF'
1. cd into this directory.
2. Run:

       bash scripts/install_node.sh

The installer will set up Python venv, optionally install Ollama,
and create ~/.aim_env with your settings.

After install:
       ./aim_cli.py                 # interactive CLI
       ./aim_gui.py                 # GUI (requires customtkinter)

To join the Hive (optional):
       echo 'AIM_HIVE_QUEEN_URL=https://hive.longevity.ge' >> ~/.aim_env
EOF
  fi
  cat >> "$target" <<EOF

License
-------
MIT (see LICENSE)

Documentation
-------------
- README.md — feature overview
- AI/CLAUDE.md — closed-loop self-improvement subproject
- scripts/install_node.{sh,ps1} — installer source
EOF
}

# 1. Linux package
bold ">> Linux"
LINUX_DIR="$STAGE/aim-$VERSION-linux"
cp -r "$STAGE/aim-$VERSION" "$LINUX_DIR"
make_readme linux "$LINUX_DIR/README-INSTALL.txt"
# Linux uses .sh; remove .ps1 to keep archive lean.
rm -f "$LINUX_DIR/scripts/install_node.ps1"
tar -czf "$DIST/aim-$VERSION-linux.tar.gz" -C "$STAGE" "aim-$VERSION-linux"
green "   $(ls -lh "$DIST/aim-$VERSION-linux.tar.gz" | awk '{print $5}') $DIST/aim-$VERSION-linux.tar.gz"

# 2. macOS package — same content as linux + .ps1 dropped
bold ">> macOS"
MAC_DIR="$STAGE/aim-$VERSION-macos"
cp -r "$STAGE/aim-$VERSION" "$MAC_DIR"
make_readme macos "$MAC_DIR/README-INSTALL.txt"
rm -f "$MAC_DIR/scripts/install_node.ps1"
tar -czf "$DIST/aim-$VERSION-macos.tar.gz" -C "$STAGE" "aim-$VERSION-macos"
green "   $(ls -lh "$DIST/aim-$VERSION-macos.tar.gz" | awk '{print $5}') $DIST/aim-$VERSION-macos.tar.gz"

# 3. Windows package — uses .ps1; .sh dropped; ZIP format
bold ">> Windows"
WIN_DIR="$STAGE/aim-$VERSION-windows"
cp -r "$STAGE/aim-$VERSION" "$WIN_DIR"
make_readme windows "$WIN_DIR/README-INSTALL.txt"
rm -f "$WIN_DIR/scripts/install_node.sh"
( cd "$STAGE" && zip -qr "$DIST/aim-$VERSION-windows.zip" "aim-$VERSION-windows" )
green "   $(ls -lh "$DIST/aim-$VERSION-windows.zip" | awk '{print $5}') $DIST/aim-$VERSION-windows.zip"

# SHA-256 manifests
bold ">> Hashes"
( cd "$DIST" && sha256sum aim-"$VERSION"-*.{tar.gz,zip} > aim-"$VERSION".sha256 )
cat "$DIST/aim-$VERSION.sha256"

green ""
green "Built 3 packages in $DIST"
ls -1 "$DIST"
