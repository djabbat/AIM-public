#!/usr/bin/env bash
# AIM v6.0 — start.sh
# Главный лаунчер системы.
# Активирует venv, запускает GUI (если есть) или CLI.

set -e

AIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$AIM_DIR/venv"
ENV_FILE="$HOME/.aim_env"

# ── Баннер ────────────────────────────────────────────────────────────────
echo ""
echo "  AIM v6.0 — Ассистент Интегративной Медицины"
echo "  drjaba.com"
echo ""

# ── Проверка venv ─────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv "$VENV_DIR"
fi

# ── Активация venv ────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── Проверка зависимостей ─────────────────────────────────────────────────
if ! python3 -c "import openai" 2>/dev/null; then
    echo "Установка зависимостей..."
    pip install -q -r "$AIM_DIR/requirements.txt"
fi

# ── Загрузка env ──────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
    echo "  Env: $ENV_FILE загружен"
else
    echo "  ! ~/.aim_env не найден — DeepSeek API недоступен"
    echo "    Создайте файл: echo 'DEEPSEEK_API_KEY=sk-...' > ~/.aim_env"
fi

# ── Переход в директорию AIM ──────────────────────────────────────────────
cd "$AIM_DIR"

# ── Запуск ────────────────────────────────────────────────────────────────
if [ "$1" = "--all" ]; then
    echo "Режим: обработка всех пациентов"
    python3 medical_system.py --all
elif [ -f "$AIM_DIR/aim_gui.py" ]; then
    echo "Режим: GUI"
    python3 aim_gui.py
else
    echo "Режим: CLI"
    python3 medical_system.py "$@"
fi
