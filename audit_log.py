#!/usr/bin/env python3
"""
AIM — Audit log.
Append-only JSONL log of who accessed what.
File: ~/Desktop/AIM/logs/audit.jsonl
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import AIM_DIR, get_logger

_log = get_logger("audit")
_LOGS_DIR = Path(AIM_DIR) / "logs"
_AUDIT_FILE = _LOGS_DIR / "audit.jsonl"
_lock = threading.Lock()


def _ensure_dir():
    _LOGS_DIR.mkdir(exist_ok=True)


def audit(action: str,
          details: str = "",
          user_id: str = "",
          source: str = "bot",
          patient: str = "") -> None:
    """
    Write one audit record.

    Args:
        action:  short verb — "view_patients", "download_pdf", "send_photo",
                              "send_voice", "send_text", "analyze_patient",
                              "view_labs", "gui_open_patient", etc.
        details: free-form extra info
        user_id: Telegram user_id or "gui"
        source:  "bot" | "gui" | "cli"
        patient: patient folder name or display name (if known)
    """
    entry = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "source":  source,
        "user_id": str(user_id),
        "action":  action,
        "patient": patient,
        "details": details,
    }
    try:
        _ensure_dir()
        with _lock:
            with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        _log.warning("audit write failed: %s", e)


def read_recent(n: int = 50) -> list[dict]:
    """Return last n audit entries (newest last)."""
    try:
        if not _AUDIT_FILE.exists():
            return []
        lines = _AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


def stats() -> dict:
    """Return basic counts from audit log."""
    entries = read_recent(10000)
    from collections import Counter
    actions = Counter(e["action"] for e in entries)
    users   = Counter(e["user_id"] for e in entries)
    return {
        "total":   len(entries),
        "actions": dict(actions.most_common(10)),
        "users":   dict(users.most_common(10)),
    }
