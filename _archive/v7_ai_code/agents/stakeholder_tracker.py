"""agents/stakeholder_tracker.py — contacts DB + email hooks (P3, 2026-05-02).

A small SQLite-backed tracker that augments the per-project YAML
stakeholder lists with cross-project, cross-session bookkeeping:

    contacts(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        role TEXT,
        project TEXT,                 -- comma-separated tags
        last_contact_at TEXT,         -- ISO datetime
        awaiting_reply INTEGER,       -- 0/1
        expected_response_by TEXT,    -- ISO date
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    UNIQUE(name, email)

Hooks (call these from email_agent / git push / Telegram):
    on_email_sent(name, email, project=None, expected_response_by=None)
    on_email_received(email)        -- clears awaiting_reply
    on_meeting(name, email=None)    -- bumps last_contact_at

Queries:
    overdue_followups(today=None)   -> list[Contact]
    silent_for(days, today=None)    -> list[Contact]   # last_contact > days
    by_project(project)             -> list[Contact]
    sync_from_yaml()                -> int             # imports project YAMLs

By default the DB lives at $AIM_HOME/contacts.db, falling back to
~/.cache/aim/contacts.db.
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

log = logging.getLogger("aim.stakeholders")


def db_path() -> Path:
    env = os.environ.get("AIM_CONTACTS_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("AIM_HOME")
    if base:
        return Path(base).expanduser() / "contacts.db"
    return Path.home() / ".cache" / "aim" / "contacts.db"


_LOCK = threading.RLock()


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _today() -> dt.date:
    return dt.date.today()


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            role TEXT,
            project TEXT,
            last_contact_at TEXT,
            awaiting_reply INTEGER NOT NULL DEFAULT 0,
            expected_response_by TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_name_email "
                 "ON contacts(name, IFNULL(email, ''))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email "
                 "ON contacts(email) WHERE email IS NOT NULL")
    return conn


# ── data classes ──────────────────────────────────────────────────


@dataclasses.dataclass
class Contact:
    id: int
    name: str
    email: Optional[str]
    role: Optional[str]
    project: Optional[str]
    last_contact_at: Optional[str]
    awaiting_reply: bool
    expected_response_by: Optional[str]
    notes: Optional[str]

    def days_silent(self, today: Optional[dt.date] = None) -> Optional[int]:
        if not self.last_contact_at:
            return None
        try:
            d = dt.date.fromisoformat(self.last_contact_at[:10])
        except ValueError:
            return None
        return ((today or _today()) - d).days

    def overdue(self, today: Optional[dt.date] = None) -> bool:
        if not self.awaiting_reply or not self.expected_response_by:
            return False
        try:
            exp = dt.date.fromisoformat(self.expected_response_by[:10])
        except ValueError:
            return False
        return (today or _today()) > exp


def _row(r: sqlite3.Row) -> Contact:
    return Contact(
        id=r["id"], name=r["name"], email=r["email"], role=r["role"],
        project=r["project"], last_contact_at=r["last_contact_at"],
        awaiting_reply=bool(r["awaiting_reply"]),
        expected_response_by=r["expected_response_by"], notes=r["notes"],
    )


# ── upsert & queries ─────────────────────────────────────────────


def upsert(name: str, email: Optional[str] = None,
           role: Optional[str] = None, project: Optional[str] = None,
           notes: Optional[str] = None) -> int:
    """Create or update a contact by (name, email). Returns row id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("upsert: name is required")
    email_norm = (email or "").strip().lower() or None
    with _LOCK, _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM contacts WHERE name=? AND IFNULL(email,'')=?",
            (name, email_norm or "")).fetchone()
        if existing:
            cid = existing["id"]
            conn.execute("""
                UPDATE contacts SET role=COALESCE(?, role),
                                    project=COALESCE(?, project),
                                    notes=COALESCE(?, notes),
                                    updated_at=?
                WHERE id=?
            """, (role, project, notes, _now(), cid))
            return cid
        cur = conn.execute("""
            INSERT INTO contacts(name, email, role, project, notes,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email_norm, role, project, notes, _now(), _now()))
        return cur.lastrowid


def get_by_email(email: str) -> Optional[Contact]:
    em = (email or "").strip().lower()
    if not em:
        return None
    with _LOCK, _connect() as conn:
        r = conn.execute("SELECT * FROM contacts WHERE email=?",
                         (em,)).fetchone()
    return _row(r) if r else None


def get_by_name(name: str) -> list[Contact]:
    with _LOCK, _connect() as conn:
        rs = conn.execute("SELECT * FROM contacts WHERE name=?",
                          (name,)).fetchall()
    return [_row(r) for r in rs]


def by_project(project: str) -> list[Contact]:
    with _LOCK, _connect() as conn:
        rs = conn.execute(
            "SELECT * FROM contacts WHERE project LIKE ? ORDER BY name",
            (f"%{project}%",)).fetchall()
    return [_row(r) for r in rs]


def all_contacts() -> list[Contact]:
    with _LOCK, _connect() as conn:
        rs = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    return [_row(r) for r in rs]


# ── lifecycle hooks ──────────────────────────────────────────────


def on_email_sent(name: Optional[str] = None, email: Optional[str] = None,
                  project: Optional[str] = None,
                  expected_response_by: Optional[str] = None,
                  role: Optional[str] = None) -> int:
    """Mark contact as just-emailed, awaiting reply.

    Either name or email must be given. If the contact doesn't exist,
    upsert one. Returns row id.
    """
    if not (name or email):
        raise ValueError("on_email_sent: need name or email")
    cid = upsert(name=name or (email or "").split("@", 1)[0],
                 email=email, project=project, role=role)
    with _LOCK, _connect() as conn:
        conn.execute("""
            UPDATE contacts SET last_contact_at=?, awaiting_reply=1,
                                expected_response_by=?, updated_at=?
            WHERE id=?
        """, (_now(), expected_response_by, _now(), cid))
    return cid


def on_email_received(email: str) -> bool:
    """Clear awaiting_reply for the matched contact (if any)."""
    em = (email or "").strip().lower()
    if not em:
        return False
    with _LOCK, _connect() as conn:
        cur = conn.execute("""
            UPDATE contacts SET awaiting_reply=0, last_contact_at=?,
                                expected_response_by=NULL, updated_at=?
            WHERE email=?
        """, (_now(), _now(), em))
        return cur.rowcount > 0


def on_meeting(name: Optional[str] = None, email: Optional[str] = None) -> int:
    """Bump last_contact_at without changing awaiting_reply."""
    if not (name or email):
        raise ValueError("on_meeting: need name or email")
    cid = upsert(name=name or (email or "").split("@", 1)[0], email=email)
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE contacts SET last_contact_at=?, updated_at=? "
                     "WHERE id=?", (_now(), _now(), cid))
    return cid


# ── queries ───────────────────────────────────────────────────────


def overdue_followups(today: Optional[dt.date] = None) -> list[Contact]:
    today = today or _today()
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT * FROM contacts
            WHERE awaiting_reply=1
              AND expected_response_by IS NOT NULL
              AND date(expected_response_by) < date(?)
            ORDER BY expected_response_by
        """, (today.isoformat(),)).fetchall()
    return [_row(r) for r in rs]


def silent_for(days: int, today: Optional[dt.date] = None) -> list[Contact]:
    """Contacts whose last_contact_at is more than `days` days old."""
    today = today or _today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT * FROM contacts
            WHERE last_contact_at IS NOT NULL
              AND date(last_contact_at) < date(?)
            ORDER BY last_contact_at
        """, (cutoff,)).fetchall()
    return [_row(r) for r in rs]


def awaiting_reply() -> list[Contact]:
    with _LOCK, _connect() as conn:
        rs = conn.execute("SELECT * FROM contacts WHERE awaiting_reply=1 "
                          "ORDER BY expected_response_by").fetchall()
    return [_row(r) for r in rs]


# ── sync from YAML ────────────────────────────────────────────────


def sync_from_yaml() -> int:
    """Import every YAML stakeholder into the DB. Returns imported count.

    Idempotent: running it twice doesn't double-add. Names + emails from
    YAML overwrite empty DB fields but never overwrite richer data.
    """
    from agents import project_owner as po
    n = 0
    for proj in po.list_projects():
        try:
            state = po.load(proj)
        except (FileNotFoundError, ValueError):
            continue
        for s in state.stakeholders:
            cid = upsert(name=s.name,
                         role=s.role or None,
                         project=state.name,
                         notes=s.notes or None)
            with _LOCK, _connect() as conn:
                conn.execute("""
                    UPDATE contacts SET awaiting_reply=?,
                                        expected_response_by=?,
                                        last_contact_at=COALESCE(?, last_contact_at),
                                        updated_at=?
                    WHERE id=?
                """, (
                    1 if s.awaiting_reply else 0,
                    s.expected_response_by.isoformat() if s.expected_response_by else None,
                    s.last_contact.isoformat() if s.last_contact else None,
                    _now(), cid,
                ))
            n += 1
    return n


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse, json
    ap = argparse.ArgumentParser(description="Stakeholder tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="import all YAML stakeholders")
    sub.add_parser("overdue", help="list overdue follow-ups")
    g = sub.add_parser("silent")
    g.add_argument("--days", type=int, default=14)
    sub.add_parser("awaiting", help="list contacts awaiting reply")
    sub.add_parser("list", help="list everyone")
    args = ap.parse_args()

    if args.cmd == "sync":
        n = sync_from_yaml()
        print(f"synced {n} stakeholders into {db_path()}")
        return 0
    if args.cmd == "overdue":
        rows = overdue_followups()
    elif args.cmd == "silent":
        rows = silent_for(args.days)
    elif args.cmd == "awaiting":
        rows = awaiting_reply()
    else:
        rows = all_contacts()
    for r in rows:
        print(json.dumps(dataclasses.asdict(r), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
