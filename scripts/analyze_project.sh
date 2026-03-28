#!/bin/bash
cd ~/AI
source venv/bin/activate
python3 project_analyzer.py "$1"
deactivate
