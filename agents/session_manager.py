"""agents/session_manager.py — session persistence: resume + auto-state-update.

Sessions live in db.py's `sessions` + `messages` tables. This module adds:

  list_recent(n=5)          — show recent sessions for resume picker
  resume(session_id)        — load history into a list[dict] for replay
  start_or_resume(prompt)   — interactive picker; returns (session_id, history)
  on_turn_end(session_id, role, content, model, provider)
                            — persist a single message (cheap)
  finalize(session_id, summary)
                            — close session + auto-update relevant project STATE.md

The auto-state-update path: if the session's last user message mentions a
known project (from ~/Desktop/*), append a one-line entry to that project's
STATE.md under '## Recent updates'.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from db import (_conn, new_session, close_session, save_message,
                get_history, list_patients)

log = logging.getLogger("aim.session")

DESKTOP = Path.home() / "Desktop"


def list_recent(n: int = 5) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT s.id, s.started_at, s.ended_at, s.lang, s.summary, "
            "       p.folder AS patient, "
            "       (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS n_msg "
            "FROM sessions s LEFT JOIN patients p ON p.id=s.patient_id "
            "ORDER BY s.id DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]


def resume(session_id: int, limit: int = 50) -> list[dict]:
    return get_history(session_id, limit=limit)


def start_or_resume(prompt: str = "Resume which session?") -> tuple[int, list[dict]]:
    """Interactive picker for CLI. Falls back to fresh session if user picks 0.
    Programmatic callers can use list_recent + resume directly."""
    rows = list_recent(n=5)
    if not rows:
        sid = new_session(None, "ru")
        return sid, []
    print(prompt)
    for i, r in enumerate(rows, 1):
        when = r["started_at"][:16].replace("T", " ")
        snippet = (r["summary"] or "")[:60]
        n = r["n_msg"]
        print(f"  {i}. [{when}]  {n} msgs  {snippet}")
    print("  0. start new session")
    try:
        choice = int(input("> ").strip())
    except (ValueError, EOFError, KeyboardInterrupt):
        choice = 0
    if choice == 0:
        return new_session(None, "ru"), []
    if 1 <= choice <= len(rows):
        sid = rows[choice - 1]["id"]
        return sid, resume(sid)
    return new_session(None, "ru"), []


def on_turn_end(session_id: int, role: str, content: str,
                model: str = "", provider: str = "") -> None:
    save_message(session_id, role, content, model=model, provider=provider)


# ── Auto-update project STATE.md ────────────────────────────────────────────


_PROJECT_NAMES = (
    "LongevityCommon", "FCLC", "MCOA", "Ze",
    "BioSense", "CDATA", "AIM", "Annals",
    "PhD", "Books", "GLA",
)


def _detect_projects(text: str) -> list[str]:
    text_low = text.lower()
    return [p for p in _PROJECT_NAMES if p.lower() in text_low]


def _append_to_state(project: str, line: str) -> Optional[Path]:
    state = DESKTOP / project / "STATE.md"
    if not state.exists():
        return None
    try:
        content = state.read_text(encoding="utf-8")
        marker = "## Recent updates"
        ts = datetime.now().strftime("%Y-%m-%d")
        entry = f"- {ts}: {line[:200]}"
        if marker in content:
            content = re.sub(rf"({re.escape(marker)}\s*\n)",
                             rf"\1{entry}\n", content, count=1)
        else:
            content = content.rstrip() + f"\n\n{marker}\n{entry}\n"
        state.write_text(content, encoding="utf-8")
        return state
    except Exception as e:
        log.warning(f"state update failed for {project}: {e}")
        return None


def finalize(session_id: int, summary: str = "") -> dict:
    """Close the session and propagate a one-line summary to relevant
    project STATE.md files (only when the summary names a project)."""
    close_session(session_id, summary=summary)
    updated: list[str] = []
    if summary:
        for project in _detect_projects(summary):
            p = _append_to_state(project, summary)
            if p:
                updated.append(str(p))
    return {"session_id": session_id, "summary": summary,
            "state_updates": updated}
