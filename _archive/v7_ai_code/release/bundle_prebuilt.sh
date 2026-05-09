#!/usr/bin/env bash
# bundle_prebuilt.sh — упаковывает pre-built Rust binaries + Phoenix release
# в portable архив с setup-скриптом внутри. Запускается из GitHub Actions
# на каждом OS-runner отдельно.
#
# Usage:  bundle_prebuilt.sh <platform>     где platform = linux | macos | windows
#
# Ожидает что:
#   AIM/rust-core/target/release/aim-*    — Rust бинарники собраны
#   AIM/phoenix-umbrella/_build/prod/rel/aim_web/  — mix release собран
#
# Результат:
#   AIM/release/dist-prebuilt/aim-<version>-<platform>-x86_64.{tar.gz|zip}

set -euo pipefail

PLATFORM="${1:?usage: bundle_prebuilt.sh <linux|macos|windows>}"

cd "$(dirname "$0")/.."
AIM_ROOT="$PWD"
VERSION="$(cat release/VERSION 2>/dev/null || echo 0.1.0)"

case "$PLATFORM" in
  linux)   ARCHIVE_EXT="tar.gz"; ARCH="x86_64-linux"  ;;
  macos)   ARCHIVE_EXT="tar.gz"; ARCH="x86_64-macos"  ;;
  windows) ARCHIVE_EXT="zip";    ARCH="x86_64-windows";;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac

NAME="aim-$VERSION-$ARCH"
DIST="$AIM_ROOT/release/dist-prebuilt"
STAGE="$DIST/$NAME"

mkdir -p "$DIST"
rm -rf "$STAGE"
mkdir -p "$STAGE"/{bin,phoenix,docs}

echo ">> staging Rust binaries"
RUST_TARGET="$AIM_ROOT/rust-core/target/release"
# Ship a curated set of user-facing binaries (the workspace builds 150+).
WANTED_BINS=(aim-llm aim-cli aim-orchestrator aim-web-api aim-doctor aim-memory-cli)
for b in "${WANTED_BINS[@]}"; do
  for ext in "" ".exe"; do
    if [[ -f "$RUST_TARGET/$b$ext" ]]; then
      cp "$RUST_TARGET/$b$ext" "$STAGE/bin/"
    fi
  done
done

echo ">> staging Phoenix release"
PHOENIX_REL="$AIM_ROOT/phoenix-umbrella/_build/prod/rel/aim_web"
if [[ ! -d "$PHOENIX_REL" ]]; then
  echo "ERROR: Phoenix release not found at $PHOENIX_REL" >&2
  exit 1
fi
# Pipe via tar — single portable mechanism that works on Linux GNU,
# macOS BSD, and Git Bash on Windows. cp -R fails on Git Bash when the
# Phoenix release contains identical-name files reachable through
# multiple paths (erts hard-links / case-insensitive duplicates).
rm -rf "$STAGE/phoenix"
mkdir -p "$STAGE/phoenix"
( cd "$PHOENIX_REL" && tar -cf - . ) | ( cd "$STAGE/phoenix" && tar -xf - )

echo ">> writing setup scripts"
if [[ "$PLATFORM" == "windows" ]]; then
  cat > "$STAGE/install.cmd" <<'CMD'
@echo off
REM AIM prebuilt setup — Windows. Распаковали? Дважды кликнули? Установлено.
setlocal
set "PREFIX=%LOCALAPPDATA%\aim"
echo Installing AIM into %PREFIX%
if not exist "%PREFIX%" mkdir "%PREFIX%"
xcopy /E /I /Y bin     "%PREFIX%\bin"     >nul
xcopy /E /I /Y phoenix "%PREFIX%\phoenix" >nul

REM Register logon-time scheduled tasks (no admin required).
schtasks /Create /F /SC ONLOGON /TN "AIM Orchestrator" ^
  /TR "\"%PREFIX%\bin\aim-llm.exe\" serve" >nul
schtasks /Create /F /SC ONLOGON /TN "AIM Phoenix" ^
  /TR "\"%PREFIX%\phoenix\bin\aim_web.bat\" start" >nul

echo.
echo  AIM installed.
echo  Start now:    schtasks /Run /TN "AIM Orchestrator" ^&^& schtasks /Run /TN "AIM Phoenix"
echo  Open UI:      http://127.0.0.1:4000/
echo  Provider key: edit %USERPROFILE%\.aim_env  (DEEPSEEK_API_KEY=...)
pause
CMD
else
  cat > "$STAGE/install.sh" <<'SH'
#!/usr/bin/env bash
# AIM prebuilt setup — Linux/macOS. Распаковали? Запустили install.sh? Установлено.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

case "$(uname -s)" in
  Linux)  PREFIX="${PREFIX:-$HOME/.local/aim}";  KIND=linux ;;
  Darwin) PREFIX="${PREFIX:-$HOME/Library/Application Support/aim}"; KIND=macos ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac

echo ">> Installing AIM into $PREFIX"
mkdir -p "$PREFIX"/{bin,phoenix,logs}
cp -R "$HERE/bin/."     "$PREFIX/bin/"
cp -R "$HERE/phoenix/." "$PREFIX/phoenix/"
chmod +x "$PREFIX/bin/"* 2>/dev/null || true
chmod +x "$PREFIX/phoenix/bin/"* 2>/dev/null || true

mkdir -p "$HOME/.local/bin"
ln -sf "$PREFIX/bin/aim-cli" "$HOME/.local/bin/aim" 2>/dev/null || true

if [[ "$KIND" == "linux" ]]; then
  UNITS="$HOME/.config/systemd/user"
  mkdir -p "$UNITS"
  cat > "$UNITS/aim-orchestrator.service" <<EOF
[Unit]
Description=AIM Rust orchestrator
After=network-online.target
[Service]
Type=simple
WorkingDirectory=$PREFIX
EnvironmentFile=-$HOME/.aim_env
ExecStart=$PREFIX/bin/aim-llm serve
Restart=on-failure
StandardOutput=append:$PREFIX/logs/orchestrator.log
StandardError=append:$PREFIX/logs/orchestrator.err.log
[Install]
WantedBy=default.target
EOF
  cat > "$UNITS/aim-phoenix.service" <<EOF
[Unit]
Description=AIM Phoenix LiveView
After=network-online.target aim-orchestrator.service
Wants=aim-orchestrator.service
[Service]
Type=simple
WorkingDirectory=$PREFIX/phoenix
EnvironmentFile=-$HOME/.aim_env
Environment=PHX_SERVER=true
Environment=PORT=4000
ExecStart=$PREFIX/phoenix/bin/aim_web start
Restart=on-failure
StandardOutput=append:$PREFIX/logs/phoenix.log
StandardError=append:$PREFIX/logs/phoenix.err.log
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  echo
  echo " AIM installed into $PREFIX"
  echo " Start:   systemctl --user enable --now aim-orchestrator aim-phoenix"
  echo " Open UI: http://127.0.0.1:4000/"
  echo " Keys:    edit ~/.aim_env  (DEEPSEEK_API_KEY=...)"
else
  LA="$HOME/Library/LaunchAgents"
  mkdir -p "$LA"
  cat > "$LA/com.longevitycommon.aim.orchestrator.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.longevitycommon.aim.orchestrator</string>
  <key>ProgramArguments</key><array>
    <string>$PREFIX/bin/aim-llm</string><string>serve</string>
  </array>
  <key>WorkingDirectory</key><string>$PREFIX</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PREFIX/logs/orchestrator.log</string>
  <key>StandardErrorPath</key><string>$PREFIX/logs/orchestrator.err.log</string>
</dict></plist>
EOF
  cat > "$LA/com.longevitycommon.aim.phoenix.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.longevitycommon.aim.phoenix</string>
  <key>ProgramArguments</key><array>
    <string>$PREFIX/phoenix/bin/aim_web</string><string>start</string>
  </array>
  <key>WorkingDirectory</key><string>$PREFIX/phoenix</string>
  <key>EnvironmentVariables</key><dict>
    <key>PHX_SERVER</key><string>true</string>
    <key>PORT</key><string>4000</string>
  </dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PREFIX/logs/phoenix.log</string>
  <key>StandardErrorPath</key><string>$PREFIX/logs/phoenix.err.log</string>
</dict></plist>
EOF
  echo
  echo " AIM installed into $PREFIX"
  echo " Start:   launchctl load $LA/com.longevitycommon.aim.{orchestrator,phoenix}.plist"
  echo " Open UI: http://127.0.0.1:4000/"
  echo " Keys:    edit ~/.aim_env  (DEEPSEEK_API_KEY=...)"
fi
SH
  chmod +x "$STAGE/install.sh"
fi

cat > "$STAGE/docs/README.txt" <<EOF
AIM $VERSION — $ARCH
========================================
Pre-built portable bundle. Rust binaries + Phoenix release with bundled ERTS.
No system-wide dependencies needed at runtime.

Install:
  Linux/macOS:  ./install.sh
  Windows:      double-click install.cmd

After install, point your browser at http://127.0.0.1:4000/
Configure provider keys in ~/.aim_env.
EOF

echo ">> archiving"
cd "$DIST"
case "$ARCHIVE_EXT" in
  tar.gz) tar -czf "$NAME.tar.gz" "$NAME" ;;
  zip)
    if command -v 7z >/dev/null 2>&1; then 7z a -tzip "$NAME.zip" "$NAME" >/dev/null
    else                                     zip -qr "$NAME.zip" "$NAME"
    fi
    ;;
esac

# Hash for release manifest.
case "$(uname -s)" in
  Darwin) shasum -a 256 "$NAME.$ARCHIVE_EXT" ;;
  *)      sha256sum    "$NAME.$ARCHIVE_EXT" ;;
esac > "$NAME.$ARCHIVE_EXT.sha256"

ls -lh "$NAME.$ARCHIVE_EXT" "$NAME.$ARCHIVE_EXT.sha256"
echo ">> done: $DIST/$NAME.$ARCHIVE_EXT"
