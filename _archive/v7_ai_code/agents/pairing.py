"""agents/pairing.py — 6-digit device pairing codes (Tailscale-style).

Hub-side: `aim hub pair <username>` issues a short code valid for N minutes.
Node-side: `aim node setup` consumes the code via /api/auth/consume-pair-code,
receives a long-lived AIM_USER_TOKEN, and writes ~/.aim_env atomically.

Differs from existing `link_codes` in agents/auth.py — those bind a
Telegram account; these bind a *device* (issue an API token, not a TG_id).

Public API:
    issue_pair_code(user_id, ttl_min=10)  → (code, expires_at_iso)
    consume_pair_code(code, *, node_id, host="", version="")
                                          → dict {token, user} | None
"""
from __future__ import annotations

import logging
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from agents.auth import (
    HUB_DB_PATH, _row_to_user, get_user, issue_api_token,
    record_node_heartbeat, audit, _now,
)

log = logging.getLogger("aim.pairing")


# ── Schema (additive — does not touch existing tables) ────────────────────


SCHEMA = """
CREATE TABLE IF NOT EXISTS pair_codes (
    code         TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    expires_at   TEXT NOT NULL,
    used         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pair_expires ON pair_codes(expires_at);
"""


@contextmanager
def _conn():
    HUB_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(HUB_DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _ensure_schema() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)


_ensure_schema()


# ── Public API ─────────────────────────────────────────────────────────────


def issue_pair_code(user_id: int, ttl_min: int = 10) -> tuple[str, str]:
    """Generate a fresh 6-digit code bound to the user. Idempotent in the
    sense that re-issuing for the same user invalidates older codes."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_min)).isoformat()
    with _conn() as con:
        # Invalidate any non-used pending codes for this user
        con.execute("UPDATE pair_codes SET used=1 WHERE user_id=? AND used=0",
                    (user_id,))
        con.execute(
            "INSERT INTO pair_codes (code, user_id, expires_at, used, created_at) "
            "VALUES (?,?,?,0,?)",
            (code, user_id, expires, _now()),
        )
    audit(user_id, "pair.issue", target=code[:2] + "****")
    return code, expires


def consume_pair_code(code: str, *, node_id: str = "",
                       host: str = "", version: str = "") -> dict | None:
    """Atomically: validate code, mark used, issue an API token, record node.
    Returns {'token': <opaque>, 'user': <user_dict>} on success, None otherwise."""
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        return None
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM pair_codes WHERE code=? AND used=0", (code,)
        ).fetchone()
        if row is None:
            return None
        # Expiry check
        try:
            exp = datetime.fromisoformat(row["expires_at"])
        except Exception:
            return None
        if exp < datetime.now(timezone.utc):
            return None
        # Atomic mark-used
        cur = con.execute("UPDATE pair_codes SET used=1 WHERE code=? AND used=0",
                          (code,))
        if cur.rowcount != 1:
            return None
        user_id = row["user_id"]

    user = get_user(user_id)
    if user is None or user.get("disabled"):
        return None
    token = issue_api_token(user_id)
    if node_id:
        record_node_heartbeat(user_id, node_id, host=host, version=version)
    audit(user_id, "pair.consume", target=node_id or "?")
    return {"token": token, "user": user}


def cleanup_expired(older_than_min: int = 60) -> int:
    """Delete used / expired codes older than N minutes. Returns count."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=older_than_min)).isoformat()
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM pair_codes WHERE created_at < ? OR (used=1 AND created_at < ?)",
            (cutoff, cutoff))
        return cur.rowcount
