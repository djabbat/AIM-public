#!/usr/bin/env bash
cd "/home/oem/Desktop/AIM"
[ -d venv ] && source venv/bin/activate
python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/oem/Desktop/AIM")
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
