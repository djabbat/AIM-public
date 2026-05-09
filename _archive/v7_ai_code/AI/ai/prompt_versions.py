"""AI/ai/prompt_versions.py — PV1 (2026-05-04).

Track changes to `AI/docs/SELF_DIAGNOSTIC_PROMPT.md` over time so we
can correlate prompt revisions with diagnostic-quality metrics in the
ledger. Each row records (sha256, mtime, line_count, byte_count) so
later we can ask "did metric X improve after prompt rev R?".

The DG1 ledger doesn't currently store prompt sha — so we keep this
in a sidecar table inside the same DB.

Public API:
    fingerprint() -> Fingerprint
    record_current() -> None
    history() -> list[Fingerprint]
    drift_since_last() -> dict
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.prompt_versions")

_LOCK = threading.RLock()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def prompt_path() -> Path:
    env = os.environ.get("AI_DIAGNOSTIC_PROMPT")
    if env:
        return Path(env)
    return project_root() / "AI" / "docs" / "SELF_DIAGNOSTIC_PROMPT.md"


def db_path() -> Path:
    """Re-use the diagnostic ledger DB so prompt history lives next to
    the metrics it explains."""
    env = os.environ.get("AI_DIAGNOSTIC_DB")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "aim" / "diagnostic_ledger.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            ts          TEXT NOT NULL,
            sha256      TEXT NOT NULL,
            byte_count  INTEGER NOT NULL,
            line_count  INTEGER NOT NULL
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_sha "
        "ON prompt_versions(sha256)"
    )
    return conn


@dataclasses.dataclass
class Fingerprint:
    sha256: str
    byte_count: int
    line_count: int
    ts: Optional[str] = None    # filled when read from DB


def fingerprint(path: Optional[Path] = None) -> Fingerprint:
    """Hash + size of the current prompt content."""
    p = path or prompt_path()
    if not p.exists():
        raise FileNotFoundError(p)
    blob = p.read_bytes()
    return Fingerprint(
        sha256=hashlib.sha256(blob).hexdigest(),
        byte_count=len(blob),
        line_count=blob.count(b"\n") + (0 if blob.endswith(b"\n") else 1),
    )


def record_current(path: Optional[Path] = None,
                    *, ts: Optional[str] = None) -> Fingerprint:
    """Record the current prompt fingerprint. Idempotent on sha256
    (same content twice → no duplicate row, returns existing)."""
    fp = fingerprint(path)
    ts = ts or dt.datetime.now().isoformat()
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO prompt_versions"
            "(ts, sha256, byte_count, line_count) "
            "VALUES (?, ?, ?, ?)",
            (ts, fp.sha256, fp.byte_count, fp.line_count),
        )
    fp.ts = ts
    return fp


def history() -> list[Fingerprint]:
    with _LOCK, contextlib.closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT ts, sha256, byte_count, line_count "
            "FROM prompt_versions ORDER BY ts ASC"
        ).fetchall()
    return [Fingerprint(sha256=r[1], byte_count=r[2],
                          line_count=r[3], ts=r[0])
            for r in rows]


def drift_since_last() -> dict:
    """Compare current prompt to the most recently recorded one."""
    h = history()
    try:
        cur = fingerprint()
    except FileNotFoundError:
        return {"have_baseline": False, "prompt_present": False}
    if not h:
        return {
            "have_baseline": False,
            "prompt_present": True,
            "current_sha": cur.sha256,
            "current_bytes": cur.byte_count,
            "current_lines": cur.line_count,
        }
    last = h[-1]
    return {
        "have_baseline": True,
        "prompt_present": True,
        "changed": cur.sha256 != last.sha256,
        "last_sha": last.sha256,
        "current_sha": cur.sha256,
        "delta_bytes": cur.byte_count - last.byte_count,
        "delta_lines": cur.line_count - last.line_count,
        "last_ts": last.ts,
    }


def summary() -> str:
    d = drift_since_last()
    if not d.get("prompt_present"):
        return "(prompt file missing)"
    if not d.get("have_baseline"):
        return (f"📝 Prompt fingerprinted for the first time:\n"
                f"  sha256={d['current_sha'][:12]}…  "
                f"{d['current_bytes']}b  {d['current_lines']}l")
    parts = [f"📝 Prompt drift since {d['last_ts'][:19]}:"]
    if not d["changed"]:
        parts.append("  = unchanged")
    else:
        parts.append(f"  sha {d['last_sha'][:8]} → {d['current_sha'][:8]}")
        parts.append(
            f"  bytes Δ {d['delta_bytes']:+d}  lines Δ {d['delta_lines']:+d}"
        )
    return "\n".join(parts)
