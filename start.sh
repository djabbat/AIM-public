#!/bin/bash
cd /home/oem/AIM
[ -d "venv" ] && source venv/bin/activate
python3 -c "import psutil" 2>/dev/null || pip install psutil >/dev/null 2>&1
python3 ai_system.py
deactivate 2>/dev/null
