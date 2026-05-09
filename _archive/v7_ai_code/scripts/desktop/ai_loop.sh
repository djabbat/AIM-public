#!/usr/bin/env bash
# AIM AI free-form ReAct loop launcher.
# Загружает ~/.aim_env (для DEEPSEEK/GROQ/ANTHROPIC keys),
# активирует venv, запускает REPL.
set -u

AIM_ROOT="/home/oem/Desktop/LongevityCommon/AIM"

if [ -f "$HOME/.aim_env" ]; then
    set -a
    # shellcheck disable=SC1090,SC1091
    . "$HOME/.aim_env" 2>/dev/null || true
    set +a
fi

# Снимаем path-sandbox для interactive REPL: пользователь работает у себя
# на машине, ему нужны service-файлы в ~/Desktop/AIM-service/, проекты в
# ~/Desktop/<Project>/ и т.д. Sandbox оправдан в multi-user/server режиме,
# не в личном desktop launcher'е.
export AIM_NO_PATH_SANDBOX=1

cd "$AIM_ROOT" || exit 1
if [ -f venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

python3 "$AIM_ROOT/scripts/desktop/ai_loop_repl.py"
rc=$?

echo
echo "=== REPL exited (rc=$rc) — press Enter to close window ==="
read -r _
