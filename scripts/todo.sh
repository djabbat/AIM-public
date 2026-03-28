#!/bin/bash
cd ~/AI
source venv/bin/activate
python3 todo_analyzer.py "$1"
deactivate
