#!/usr/bin/env bash
# install_icons.sh — install Linux Desktop launchers for AIM and AIM AI.
#
# Creates:
#   ~/Desktop/AIM.desktop              — full menu (medical_system.py)
#   ~/Desktop/AIM-AI.desktop           — generalist ReAct loop
#   ~/.local/share/applications/AIM.desktop      (+ AIM-AI.desktop)
#   ~/.local/share/icons/aim/{aim,aim_ai}.png
#
# Works on Cinnamon / GNOME / KDE / XFCE / MATE.
# Re-run any time — it's idempotent.

set -e

AIM_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ICON_SRC="$AIM_ROOT/scripts/desktop/icons"
ICON_DST="$HOME/.local/share/icons/aim"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="$HOME/.local/share/applications"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
bold()  { printf "\033[1m%s\033[0m\n"  "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }

bold "AIM desktop launcher installer (Linux)"
echo  "AIM_ROOT     = $AIM_ROOT"
echo  "DESKTOP_DIR  = $DESKTOP_DIR"
echo  ""

# 1. Build icons if missing or stale ----------------------------------------

if [ ! -f "$ICON_SRC/aim.png" ] || [ ! -f "$ICON_SRC/aim_ai.png" ]; then
  bold "[1/3] building icon assets"
  if [ -x "$AIM_ROOT/venv/bin/python" ]; then
    "$AIM_ROOT/venv/bin/python" "$AIM_ROOT/scripts/desktop/build_icons.py"
  else
    python3 "$AIM_ROOT/scripts/desktop/build_icons.py"
  fi
fi

# 2. Copy PNGs into user icon dir -------------------------------------------

bold "[2/3] installing icons → $ICON_DST"
mkdir -p "$ICON_DST"
cp -f "$ICON_SRC/aim.png"     "$ICON_DST/aim.png"
cp -f "$ICON_SRC/aim_ai.png"  "$ICON_DST/aim_ai.png"

# Pick a terminal we know is installed.
TERM_BIN=""
for t in gnome-terminal x-terminal-emulator konsole xfce4-terminal mate-terminal alacritty kitty; do
  if command -v "$t" >/dev/null 2>&1; then TERM_BIN="$t"; break; fi
done
if [ -z "$TERM_BIN" ]; then
  red "no terminal emulator found — install gnome-terminal or konsole"
  exit 1
fi

# Each terminal has its own "run a command and stay open" syntax.
case "$TERM_BIN" in
  gnome-terminal|mate-terminal)
    TERM_RUN_AIM="$TERM_BIN -- bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli; exec bash'"
    TERM_RUN_AI="$TERM_BIN -- bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli && echo Press A then Enter inside AIM menu; exec bash'"
    ;;
  konsole)
    TERM_RUN_AIM="konsole --hold -e bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli'"
    TERM_RUN_AI="konsole --hold -e bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli'"
    ;;
  xfce4-terminal)
    TERM_RUN_AIM="xfce4-terminal --hold -e \"bash -lc 'cd \\\"$AIM_ROOT\\\" && bash start.sh cli'\""
    TERM_RUN_AI="xfce4-terminal --hold -e \"bash -lc 'cd \\\"$AIM_ROOT\\\" && bash start.sh cli'\""
    ;;
  alacritty|kitty|x-terminal-emulator)
    TERM_RUN_AIM="$TERM_BIN -e bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli; exec bash'"
    TERM_RUN_AI="$TERM_BIN -e bash -lc 'cd \"$AIM_ROOT\" && bash start.sh cli; exec bash'"
    ;;
esac

# Special launcher for the generalist (free-form ReAct loop) — bypasses menu.
# We use a tiny inline Python invocation so it works without modifying CLI.
AI_ENTRY="$AIM_ROOT/scripts/desktop/ai_loop.sh"
cat > "$AI_ENTRY" <<EOF
#!/usr/bin/env bash
cd "$AIM_ROOT"
[ -d venv ] && source venv/bin/activate
python3 - <<'PY'
import sys, os
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

case "$TERM_BIN" in
  gnome-terminal|mate-terminal)
    TERM_RUN_AI="$TERM_BIN -- bash -lc '\"$AI_ENTRY\"; exec bash'"
    ;;
  konsole)
    TERM_RUN_AI="konsole --hold -e \"$AI_ENTRY\""
    ;;
  xfce4-terminal)
    TERM_RUN_AI="xfce4-terminal --hold -e \"$AI_ENTRY\""
    ;;
  alacritty|kitty|x-terminal-emulator)
    TERM_RUN_AI="$TERM_BIN -e \"$AI_ENTRY\""
    ;;
esac

# 3. Write .desktop files ---------------------------------------------------

bold "[3/3] writing .desktop launchers"
mkdir -p "$APPS_DIR" "$DESKTOP_DIR"

write_desktop() {
  local path="$1" name="$2" comment="$3" icon="$4" exec_line="$5"
  cat > "$path" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$name
Comment=$comment
Exec=$exec_line
Icon=$icon
Terminal=false
Categories=Education;Science;MedicalSoftware;Utility;
StartupNotify=true
EOF
  chmod +x "$path"
}

write_desktop "$DESKTOP_DIR/AIM.desktop"     \
  "AIM" \
  "Assistant of Integrative Medicine — full menu" \
  "$ICON_DST/aim.png" \
  "$TERM_RUN_AIM"

write_desktop "$DESKTOP_DIR/AIM-AI.desktop"  \
  "AIM AI" \
  "AIM AI assistant — free-form ReAct loop with tools" \
  "$ICON_DST/aim_ai.png" \
  "$TERM_RUN_AI"

# Mirror in the user applications dir so the items appear in the app menu.
cp -f "$DESKTOP_DIR/AIM.desktop"    "$APPS_DIR/AIM.desktop"
cp -f "$DESKTOP_DIR/AIM-AI.desktop" "$APPS_DIR/AIM-AI.desktop"

# Cinnamon / Nautilus require explicit "trusted" metadata on .desktop files
# (otherwise the user sees "untrusted launcher" each time). Mark them now.
if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_DIR/AIM.desktop"    metadata::trusted true 2>/dev/null || true
  gio set "$DESKTOP_DIR/AIM-AI.desktop" metadata::trusted true 2>/dev/null || true
fi

# Refresh icon cache (best-effort)
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -t -q "$HOME/.local/share/icons" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q "$APPS_DIR" 2>/dev/null || true
fi

green ""
green "✓ done."
green ""
echo "  Two launchers were placed on your Desktop:"
echo "    • AIM        — full menu"
echo "    • AIM AI     — free-form AI assistant (ReAct loop)"
echo ""
echo "  If they appear with a generic icon at first, right-click → Properties"
echo "  → mark Allow launching (Cinnamon/GNOME), then double-click."
