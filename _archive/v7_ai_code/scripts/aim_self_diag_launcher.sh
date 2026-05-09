#!/usr/bin/env bash
# AIM/AI self-diagnostic launcher (DESK1, updated 2026-05-03).
# Runs the actual DeepSeek-driven 9-phase audit, saves report, opens it.

set -e

AIM_DIR="$HOME/Desktop/LongevityCommon/AIM"
PY="$AIM_DIR/venv/bin/python"
RUN_SCRIPT="$AIM_DIR/AI_run_self_diag.py"
ARTIFACTS_DIR="$AIM_DIR/AI/artifacts"

# Outer call: re-exec inside gnome-terminal so window stays open.
if [[ "${1:-}" != "--inner" ]]; then
    if command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal --title="AIM Self-Diagnostic (running)" -- \
            bash "$0" --inner
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -T "AIM Self-Diagnostic" -e bash "$0" --inner
    else
        exec bash "$0" --inner
    fi
fi

# Inner: load env (DeepSeek key), run, open result.
mkdir -p "$ARTIFACTS_DIR"
LOG_FILE="$ARTIFACTS_DIR/launcher_$(date +%Y%m%d-%H%M%S).log"

# Load ~/.aim_env so DEEPSEEK_API_KEY is available.
if [[ -f "$HOME/.aim_env" ]]; then
    set -a
    # shellcheck disable=SC1090,SC1091
    . "$HOME/.aim_env" 2>/dev/null || true
    set +a
fi

{
    echo "=== AIM Self-Diagnostic — RUNNING ==="
    echo "started: $(date -Iseconds)"
    echo "python:  $PY"
    echo "script:  $RUN_SCRIPT"
    if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
        echo "deepseek: ${DEEPSEEK_API_KEY:0:8}..."
    else
        echo "deepseek: NOT SET (will fail)"
    fi
    echo
    echo "Запрос отправляется в DeepSeek-reasoner. Это может занять"
    echo "несколько минут (модель проводит 9-фазный аудит)..."
    echo

    if [[ ! -x "$PY" ]]; then
        echo "ERROR: python not found at $PY"
        exit 1
    fi
    if [[ ! -f "$RUN_SCRIPT" ]]; then
        echo "ERROR: launcher not found at $RUN_SCRIPT"
        exit 1
    fi

    cd "$AIM_DIR"
    "$PY" "$RUN_SCRIPT"
    rc=$?
    echo
    echo "rc: $rc"
} 2>&1 | tee "$LOG_FILE"

REPORT="$ARTIFACTS_DIR/self_diag_$(date +%Y-%m-%d).md"
if [[ ! -f "$REPORT" ]]; then
    REPORT=$(ls -t "$ARTIFACTS_DIR"/self_diag_*.md 2>/dev/null \
              | grep -v request | head -1)
fi

if [[ -f "$REPORT" ]]; then
    SIZE=$(stat -c%s "$REPORT")
    echo
    echo "Отчёт: $REPORT"
    echo "Размер: $SIZE байт"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$REPORT" >/dev/null 2>&1 &
        echo "(открыт в редакторе)"
    fi
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "AIM Self-Diagnostic ✅" \
            "Отчёт готов: $(basename "$REPORT") ($SIZE байт)" \
            -i system-run -t 8000
    fi
else
    echo "ERROR: отчёт не сгенерирован — смотри лог $LOG_FILE"
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "AIM Self-Diagnostic ❌" \
            "Самодиагностика провалилась — смотри лог" \
            -u critical
    fi
fi

echo
echo "=== готово — нажми Enter чтобы закрыть окно ==="
read _
