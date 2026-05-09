"""agents/feature_flags.py — in-flight flag/experiment tracker (FX1, 2026-05-03).

A small SQLite registry for the kind of "remove-once-X" tags that
otherwise rot quietly: feature flags, staged rollouts, A/B experiments,
TODO("ремуви после миграции 2026-06"), сon-call workarounds.

Each flag has:
  * id       — short slug
  * project  — optional owning project (matches projects/<name>.yaml)
  * owner    — person responsible (free text)
  * status   — "active" | "ramping" | "ready_to_remove" | "retired"
  * cleanup_by — optional ISO date — when this flag should be gone
  * notes    — free text

The brief picks up flags whose cleanup_by ≤ today + N days and surfaces
them as "remove me" reminders.

Public API:
    add(id, *, project=None, owner=None, status="active",
        cleanup_by=None, notes=None) -> int
    update(id, **fields) -> bool
    list_flags(status=None, project=None) -> list[Flag]
    overdue(today=None, horizon_days=14) -> list[Flag]
    summary(today=None) -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.feature_flags")

_LOCK = threading.RLock()


def db_path() -> Path:
    env = os.environ.get("AIM_FLAGS_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    return Path(base).expanduser() / "feature_flags.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flags (
            id TEXT PRIMARY KEY,
            project TEXT,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            cleanup_by TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flags_status "
                 "ON flags(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flags_cleanup "
                 "ON flags(cleanup_by)")
    return conn


_VALID_STATUSES = {"active", "ramping", "ready_to_remove", "retired"}


@dataclasses.dataclass
class Flag:
    id: str
    project: Optional[str]
    owner: Optional[str]
    status: str
    cleanup_by: Optional[str]
    notes: Optional[str]

    def overdue(self, today: Optional[dt.date] = None) -> bool:
        if not self.cleanup_by or self.status == "retired":
            return False
        try:
            d = dt.date.fromisoformat(self.cleanup_by[:10])
        except ValueError:
            return False
        return (today or dt.date.today()) > d


def _row(r: sqlite3.Row) -> Flag:
    return Flag(id=r["id"], project=r["project"], owner=r["owner"],
                 status=r["status"], cleanup_by=r["cleanup_by"],
                 notes=r["notes"])


# ── CRUD ─────────────────────────────────────────────────────────


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def add(flag_id: str, *, project: Optional[str] = None,
        owner: Optional[str] = None, status: str = "active",
        cleanup_by: Optional[str] = None,
        notes: Optional[str] = None) -> str:
    if not flag_id or not flag_id.strip():
        raise ValueError("flag id required")
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {_VALID_STATUSES}")
    with _LOCK, _connect() as conn:
        conn.execute("""
            INSERT INTO flags(id, project, owner, status, cleanup_by, notes,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project    = excluded.project,
                owner      = excluded.owner,
                status     = excluded.status,
                cleanup_by = excluded.cleanup_by,
                notes      = excluded.notes,
                updated_at = excluded.updated_at
        """, (flag_id.strip(), project, owner, status, cleanup_by, notes,
              _now(), _now()))
    return flag_id.strip()


def update(flag_id: str, **fields) -> bool:
    if not fields:
        return False
    if "status" in fields and fields["status"] not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {_VALID_STATUSES}")
    sets = ", ".join(f"{k}=?" for k in fields)
    params = list(fields.values()) + [_now(), flag_id]
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            f"UPDATE flags SET {sets}, updated_at=? WHERE id=?",
            params,
        )
        return cur.rowcount > 0


def get(flag_id: str) -> Optional[Flag]:
    with _LOCK, _connect() as conn:
        r = conn.execute("SELECT * FROM flags WHERE id=?",
                          (flag_id,)).fetchone()
    return _row(r) if r else None


def list_flags(*, status: Optional[str] = None,
                project: Optional[str] = None) -> list[Flag]:
    sql = "SELECT * FROM flags WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if project:
        sql += " AND project=?"
        params.append(project)
    sql += " ORDER BY id"
    with _LOCK, _connect() as conn:
        rs = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rs]


def remove(flag_id: str) -> bool:
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM flags WHERE id=?", (flag_id,))
        return cur.rowcount > 0


# ── reporting ────────────────────────────────────────────────────


def overdue(today: Optional[dt.date] = None,
            horizon_days: int = 14) -> list[Flag]:
    """Return flags whose cleanup_by is ≤ today + horizon_days AND
    status != 'retired'."""
    today = today or dt.date.today()
    cutoff = (today + dt.timedelta(days=horizon_days)).isoformat()
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT * FROM flags
            WHERE status != 'retired'
              AND cleanup_by IS NOT NULL
              AND date(cleanup_by) <= date(?)
            ORDER BY cleanup_by ASC
        """, (cutoff,)).fetchall()
    return [_row(r) for r in rs]


def summary(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    flags = list_flags()
    if not flags:
        return "(no feature flags tracked)"
    by_status: dict[str, int] = {}
    for f in flags:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    lines = ["🚩 Feature flags:"]
    for status, n in sorted(by_status.items()):
        lines.append(f"  • {status}: {n}")
    over = overdue(today=today)
    if over:
        lines.append(f"  ⚠ overdue/cleanup-soon ({len(over)}):")
        for f in over[:8]:
            cb = (f.cleanup_by or "")[:10]
            lines.append(f"    - {f.id}  (cleanup_by={cb}, "
                         f"owner={f.owner or '?'}, project={f.project or '?'})")
    return "\n".join(lines)
