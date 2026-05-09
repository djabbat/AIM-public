#!/bin/bash
# patient_intake/start.sh — запуск UI приёма пациента
cd "$(dirname "$0")"
echo "🏥 AIM Patient Intake — запуск..."
echo "   Браузер: http://localhost:5050"
echo "   Ctrl+C для остановки"
echo ""
python3 app.py
