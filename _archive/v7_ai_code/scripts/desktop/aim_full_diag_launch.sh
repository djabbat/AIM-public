#!/usr/bin/env bash
# scripts/desktop/aim_full_diag_launch.sh
# Glubokaya samodiagnostika i tshcatelnaya kalibrovka AIM.
#
# Делает:
#   1. python scripts/aim_full_diagnostic.py --md --out report.md
#   2. python scripts/aim_full_diagnostic.py (text) → terminal
#   3. Открывает report.md в текстовом редакторе (fallback: cat in terminal)
#
# Выход:
#   • exit code 0 = нет P0 findings, система здорова
#   • exit code 1 = есть P0 (см. terminal output + report.md)
set -uo pipefail
REPO_ROOT="/home/oem/Desktop/LongevityCommon/AIM"
VENV_PY="$REPO_ROOT/venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$(/usr/bin/which python3)"
SCRIPT="$REPO_ROOT/scripts/aim_full_diagnostic.py"

# Persistent report path — easy to bookmark / git diff.
REPORT_DIR="$REPO_ROOT/docs/operational"
TS="$(/usr/bin/date +%Y-%m-%dT%H%M%S)"
REPORT_MD="$REPORT_DIR/diagnostic_${TS}.md"
REPORT_LATEST="$REPORT_DIR/diagnostic_latest.md"

/usr/bin/mkdir -p "$REPORT_DIR"

/usr/bin/gnome-terminal --title="AIM full-system diagnostic" -- \
    /usr/bin/bash -lc "
        set +e;
        cd '${REPO_ROOT}' || exit 1;
        echo '════════════════════════════════════════════════════════════';
        echo '🩺 AIM full-system diagnostic + calibration';
        echo '════════════════════════════════════════════════════════════';
        echo '';
        '${VENV_PY}' '${SCRIPT}' --md --out '${REPORT_MD}';
        /usr/bin/cp '${REPORT_MD}' '${REPORT_LATEST}';
        '${VENV_PY}' '${SCRIPT}';
        rc=\$?;
        echo '';
        echo '═══════════════════════════════════════════════════════════';
        echo 'Markdown report saved:';
        echo '  ${REPORT_MD}';
        echo '  ${REPORT_LATEST}  (symlink-equivalent latest)';
        echo '';
        if [ \$rc -eq 0 ]; then
            echo '✓ exit 0 — no P0 findings; system healthy';
        else
            echo '⚠ exit '\$rc' — P0 findings present; see report';
        fi;
        echo;
        echo 'Press Enter to open report in default editor (or close window).';
        read;
        /usr/bin/xdg-open '${REPORT_LATEST}' >/dev/null 2>&1 &
    "
