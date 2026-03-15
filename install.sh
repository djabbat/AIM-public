#!/bin/bash
# Скрипт установки AI системы

echo "🚀 Установка AI системы..."

# Создаем виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем пакеты
pip install --upgrade pip
pip install -r requirements.txt

# Устанавливаем Ollama
if ! command -v ollama &> /dev/null; then
    echo "📦 Установка Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Скачиваем модель
ollama pull llama3.2

# Создаем ярлык на рабочем столе
cp AI.desktop ~/Desktop/ 2>/dev/null || true
chmod +x ~/Desktop/AI.desktop

echo "✅ Установка завершена!"
echo "🚀 Запуск: ./start.sh"
