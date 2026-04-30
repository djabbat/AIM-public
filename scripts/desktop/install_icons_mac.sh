#!/usr/bin/env bash
# install_icons_mac.sh — install AIM and AIM AI launchers on macOS.
#
# Creates two double-clickable .app bundles on the user's Desktop:
#     ~/Desktop/AIM.app          — opens Terminal and runs AIM full menu
#     ~/Desktop/AIM AI.app       — opens Terminal and runs AIM generalist
# Both bundles get proper Retina icons (.icns) generated from the PNG masters.
#
# Re-run any time — overwrites in place.

set -e

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is for macOS. On Linux use install_icons.sh, on Windows install_icons.ps1" >&2
  exit 1
fi

AIM_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ICON_SRC="$AIM_ROOT/scripts/desktop/icons"
DESKTOP="$HOME/Desktop"

bold()  { printf "\033[1m%s\033[0m\n"  "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

bold "AIM desktop launcher installer (macOS)"
echo  "AIM_ROOT = $AIM_ROOT"
echo  ""

# 1. Build PNG icons if missing --------------------------------------------

if [ ! -f "$ICON_SRC/aim.png" ] || [ ! -f "$ICON_SRC/aim_ai.png" ]; then
  bold "[1/3] building icon assets"
  if [ -x "$AIM_ROOT/venv/bin/python" ]; then
    "$AIM_ROOT/venv/bin/python" "$AIM_ROOT/scripts/desktop/build_icons.py"
  else
    python3 "$AIM_ROOT/scripts/desktop/build_icons.py"
  fi
fi

# 2. Convert PNG → .icns via iconutil --------------------------------------

bold "[2/3] converting PNGs to .icns"

make_icns() {
  local prefix="$1"
  local iconset
  iconset="$(mktemp -d /tmp/aim_icns.XXXXXX)/${prefix}.iconset"
  mkdir -p "$iconset"
  cp "$ICON_SRC/${prefix}_16.png"   "$iconset/icon_16x16.png"
  cp "$ICON_SRC/${prefix}_32.png"   "$iconset/icon_16x16@2x.png"
  cp "$ICON_SRC/${prefix}_32.png"   "$iconset/icon_32x32.png"
  cp "$ICON_SRC/${prefix}_64.png"   "$iconset/icon_32x32@2x.png"
  cp "$ICON_SRC/${prefix}_128.png"  "$iconset/icon_128x128.png"
  cp "$ICON_SRC/${prefix}_256.png"  "$iconset/icon_128x128@2x.png"
  cp "$ICON_SRC/${prefix}_256.png"  "$iconset/icon_256x256.png"
  cp "$ICON_SRC/${prefix}_512.png"  "$iconset/icon_256x256@2x.png"
  cp "$ICON_SRC/${prefix}_512.png"  "$iconset/icon_512x512.png"
  iconutil -c icns "$iconset" -o "$ICON_SRC/${prefix}.icns"
  rm -rf "$iconset"
  echo "  $ICON_SRC/${prefix}.icns"
}
make_icns aim
make_icns aim_ai

# 3. Build .app bundles ----------------------------------------------------

bold "[3/3] building .app bundles on Desktop"

build_app() {
  local app_name="$1"          # e.g. "AIM" or "AIM AI"
  local bundle_id="$2"         # e.g. com.longevity.aim
  local icns_path="$3"         # absolute path to .icns
  local exec_cmd="$4"          # the bash command the app runs

  local app="$DESKTOP/${app_name}.app"
  rm -rf "$app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

  # Info.plist
  cat > "$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>${app_name}</string>
  <key>CFBundleDisplayName</key>     <string>${app_name}</string>
  <key>CFBundleIdentifier</key>      <string>${bundle_id}</string>
  <key>CFBundleVersion</key>         <string>7.0</string>
  <key>CFBundleShortVersionString</key><string>7.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>launcher</string>
  <key>CFBundleIconFile</key>        <string>${app_name// /_}</string>
  <key>LSMinimumSystemVersion</key>  <string>10.13</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
EOF

  # Resources / icon
  cp -f "$icns_path" "$app/Contents/Resources/${app_name// /_}.icns"

  # The launcher script: opens Terminal.app with the desired command,
  # via osascript so we get a normal terminal window with PATH/login shell.
  local launcher="$app/Contents/MacOS/launcher"
  cat > "$launcher" <<EOF
#!/bin/bash
osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "${exec_cmd//\"/\\\"}"
end tell
APPLESCRIPT
EOF
  chmod +x "$launcher"

  # Touch the bundle so Finder picks up the new icon immediately.
  touch "$app"
  echo "  $app"
}

build_app "AIM" \
          "com.longevity.aim" \
          "$ICON_SRC/aim.icns" \
          "cd \"$AIM_ROOT\" && bash start.sh cli"

# AIM AI uses the dedicated free-form ReAct entry script created by
# install_icons.sh on Linux; reuse the same idea here.
AI_ENTRY="$AIM_ROOT/scripts/desktop/ai_loop.sh"
if [ ! -f "$AI_ENTRY" ]; then
  cat > "$AI_ENTRY" <<EOF
#!/usr/bin/env bash
cd "$AIM_ROOT"
[ -d venv ] && source venv/bin/activate
python3 - <<'PY'
import sys
sys.path.insert(0, "$AIM_ROOT")
print("AIM AI assistant — free-form ReAct loop. Empty line = quit.\n")
from agents.generalist import run
while True:
    try:
        task = input("you> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not task:
        break
    out = run(task, max_iters=12)
    print()
    print(out["answer"])
    print()
    print(f"[tools: {', '.join(out['tools_used'])}  iters: {out['iters']}]\n")
PY
EOF
  chmod +x "$AI_ENTRY"
fi

build_app "AIM AI" \
          "com.longevity.aim.ai" \
          "$ICON_SRC/aim_ai.icns" \
          "$AI_ENTRY"

# Bust Finder's icon cache for these specific bundles
touch "$DESKTOP"
killall Finder 2>/dev/null || true

green ""
green "✓ done."
green ""
echo "  Two launchers placed on the Desktop:"
echo "    • AIM.app       — full menu"
echo "    • AIM AI.app    — free-form AI assistant"
echo ""
echo "  First time you double-click, macOS Gatekeeper may say"
echo "    \"AIM cannot be opened because the developer cannot be verified\"."
echo "  Either Right-click → Open  (one-time bypass)"
echo "  or System Settings → Privacy & Security → Open Anyway."
