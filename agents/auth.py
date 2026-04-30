"""agents/auth.py — Hub-side authentication core for AIM multi-user system.

Architecture:
    AIM Hub  (one instance)        →  manages users, issues tokens, audit log
    AIM Node (per-user, local)     →  validates token via hub_client, runs LLM
                                       with the user's own DeepSeek/Groq keys

This module is loaded ONLY when AIM_ROLE=hub. Node processes never touch it.

Cross-platform:
    Hub DB path  →  config.HUB_DB_PATH  (default: ROOT_DIR/aim_hub.db)
    Secrets      →  ~/.aim_env via dotenv (Linux/macOS/Windows)

Public API:
    init_hub_db()
    create_user(username, password, role='user', email=None)
    set_password(user_id, new_password)
    disable_user(user_id)
    verify_password(username, password)         → user dict | None
    get_user(user_id) / get_user_by_username(u) / get_user_by_token(t)
    list_users()
    issue_jwt(user_id, ttl_days=7)              → str
    verify_jwt(token)                            → user dict | None
    issue_api_token(user_id)                    → str (long-lived, opaque)
    revoke_api_token(user_id)
    create_link_code(user_id, ttl_min=10)       → str (6-digit)
    consume_link_code(code, telegram_id)        → user dict | None
    audit(user_id, action, target=None, ip=None, ua=None)
    record_node_heartbeat(user_id, node_id, host, version)
    list_nodes(user_id=None)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# ── Config ──────────────────────────────────────────────────────────────────

# Hub DB lives next to the regular aim.db unless overridden.
_DEFAULT_HUB_DB = Path(__file__).resolve().parent.parent / "aim_hub.db"
HUB_DB_PATH = Path(os.getenv("AIM_HUB_DB", str(_DEFAULT_HUB_DB)))

# JWT secret. Generated and persisted on first hub start.
_SECRET_FILE = HUB_DB_PATH.with_suffix(".secret")


def _load_or_create_secret() -> bytes:
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_bytes()
    HUB_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    s = secrets.token_bytes(64)
    _SECRET_FILE.write_bytes(s)
    try:
        os.chmod(_SECRET_FILE, 0o600)  # no-op on Windows, fine
    except OSError:
        pass
    return s


_SECRET = _load_or_create_secret()
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


# ── DB connection ───────────────────────────────────────────────────────────


@contextmanager
def _conn():
    HUB_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(HUB_DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',  -- 'admin' | 'user'
    api_token     TEXT UNIQUE,
    telegram_id   INTEGER UNIQUE,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS jwt_revocations (
    jti          TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    revoked_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_codes (
    code         TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    expires_at   TEXT NOT NULL,
    used         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    user_id   INTEGER,
    action    TEXT NOT NULL,
    target    TEXT,
    ip        TEXT,
    ua        TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    user_id      INTEGER NOT NULL REFERENCES users(id),
    node_id      TEXT NOT NULL,
    host         TEXT,
    version      TEXT,
    last_seen    TEXT NOT NULL,
    PRIMARY KEY (user_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_nodes_seen ON nodes(last_seen);
"""


def init_hub_db() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["disabled"] = bool(d.get("disabled", 0))
    d.pop("password_hash", None)
    return d


# ── User CRUD ───────────────────────────────────────────────────────────────


def create_user(username: str, password: str, role: str = "user",
                email: Optional[str] = None) -> dict:
    if role not in ("admin", "user"):
        raise ValueError("role must be 'admin' or 'user'")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    pw_hash = _HASHER.hash(password)
    with _conn() as con:
        try:
            cur = con.execute(
                "INSERT INTO users (username, email, password_hash, role, created_at) "
                "VALUES (?,?,?,?,?) RETURNING *",
                (username, email, pw_hash, role, _now()),
            )
            return _row_to_user(cur.fetchone())
        except sqlite3.IntegrityError as e:
            raise ValueError(f"username '{username}' already exists") from e


def set_password(user_id: int, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("password must be at least 8 characters")
    with _conn() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?",
                    (_HASHER.hash(new_password), user_id))


def disable_user(user_id: int) -> None:
    with _conn() as con:
        con.execute("UPDATE users SET disabled=1, api_token=NULL WHERE id=?", (user_id,))


def enable_user(user_id: int) -> None:
    with _conn() as con:
        con.execute("UPDATE users SET disabled=0 WHERE id=?", (user_id,))


def get_user(user_id: int) -> dict | None:
    with _conn() as con:
        return _row_to_user(con.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def get_user_by_username(username: str) -> dict | None:
    with _conn() as con:
        return _row_to_user(con.execute(
            "SELECT * FROM users WHERE username=?", (username,)).fetchone())


def get_user_by_token(api_token: str) -> dict | None:
    if not api_token:
        return None
    with _conn() as con:
        return _row_to_user(con.execute(
            "SELECT * FROM users WHERE api_token=? AND disabled=0",
            (api_token,)).fetchone())


def get_user_by_telegram(telegram_id: int) -> dict | None:
    with _conn() as con:
        return _row_to_user(con.execute(
            "SELECT * FROM users WHERE telegram_id=? AND disabled=0",
            (telegram_id,)).fetchone())


def list_users() -> list[dict]:
    with _conn() as con:
        return [_row_to_user(r) for r in con.execute(
            "SELECT * FROM users ORDER BY id").fetchall()]


def verify_password(username: str, password: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE username=? AND disabled=0",
                          (username,)).fetchone()
    if row is None:
        # constant-time-ish: still hash to avoid user-enumeration timing
        try:
            _HASHER.verify("$argon2id$v=19$m=65536,t=3,p=2$" + "A" * 22 + "$" + "A" * 43,
                           password)
        except Exception:
            pass
        return None
    try:
        _HASHER.verify(row["password_hash"], password)
    except (VerifyMismatchError, InvalidHashError):
        return None
    # Auto-rehash if params changed
    if _HASHER.check_needs_rehash(row["password_hash"]):
        with _conn() as con:
            con.execute("UPDATE users SET password_hash=? WHERE id=?",
                        (_HASHER.hash(password), row["id"]))
    with _conn() as con:
        con.execute("UPDATE users SET last_login_at=? WHERE id=?", (_now(), row["id"]))
    return _row_to_user(row)


# ── JWT (HMAC-SHA256, dependency-free) ──────────────────────────────────────


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    import base64
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_jwt(user_id: int, ttl_days: int = 7) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_days * 86400,
        "jti": secrets.token_hex(8),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(_SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def verify_jwt(token: str) -> dict | None:
    if not token or token.count(".") != 2:
        return None
    h, p, sig = token.split(".")
    expected = _b64url(hmac.new(_SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64url_decode(p))
    except Exception:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    # Revocation check
    with _conn() as con:
        rev = con.execute("SELECT 1 FROM jwt_revocations WHERE jti=?",
                          (payload.get("jti"),)).fetchone()
    if rev:
        return None
    user = get_user(payload["sub"])
    if user is None or user.get("disabled"):
        return None
    return user


def revoke_jwt(token: str) -> bool:
    if not token or token.count(".") != 2:
        return False
    try:
        _, p, _ = token.split(".")
        payload = json.loads(_b64url_decode(p))
    except Exception:
        return False
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO jwt_revocations (jti, user_id, revoked_at) VALUES (?,?,?)",
            (payload.get("jti"), payload.get("sub"), _now()))
    return True


# ── Long-lived API token (for nodes / CLI / GUI) ────────────────────────────


def issue_api_token(user_id: int) -> str:
    """Generate a fresh opaque token; replaces any previous token for this user."""
    tok = "aim_" + secrets.token_urlsafe(32)
    with _conn() as con:
        con.execute("UPDATE users SET api_token=? WHERE id=?", (tok, user_id))
    return tok


def revoke_api_token(user_id: int) -> None:
    with _conn() as con:
        con.execute("UPDATE users SET api_token=NULL WHERE id=?", (user_id,))


# ── Telegram link codes ─────────────────────────────────────────────────────


def create_link_code(user_id: int, ttl_min: int = 10) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_min)).isoformat()
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO link_codes (code, user_id, expires_at, used) "
                    "VALUES (?,?,?,0)", (code, user_id, expires))
    return code


def consume_link_code(code: str, telegram_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM link_codes WHERE code=? AND used=0",
                          (code,)).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        con.execute("UPDATE link_codes SET used=1 WHERE code=?", (code,))
        try:
            con.execute("UPDATE users SET telegram_id=? WHERE id=?",
                        (telegram_id, row["user_id"]))
        except sqlite3.IntegrityError:
            return None  # telegram_id already bound to another user
    return get_user(row["user_id"])


# ── Audit log ───────────────────────────────────────────────────────────────


def audit(user_id: Optional[int], action: str,
          target: Optional[str] = None,
          ip: Optional[str] = None, ua: Optional[str] = None) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO audit_log (ts, user_id, action, target, ip, ua) VALUES (?,?,?,?,?,?)",
            (_now(), user_id, action, target, ip, ua))


def list_audit(user_id: Optional[int] = None, limit: int = 200) -> list[dict]:
    with _conn() as con:
        if user_id is None:
            rows = con.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ── Nodes (heartbeat registry) ──────────────────────────────────────────────


def record_node_heartbeat(user_id: int, node_id: str,
                          host: str = "", version: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO nodes (user_id, node_id, host, version, last_seen) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id, node_id) DO UPDATE SET "
            "host=excluded.host, version=excluded.version, last_seen=excluded.last_seen",
            (user_id, node_id, host, version, _now()))


def list_nodes(user_id: Optional[int] = None) -> list[dict]:
    with _conn() as con:
        if user_id is None:
            rows = con.execute(
                "SELECT n.*, u.username FROM nodes n JOIN users u ON u.id=n.user_id "
                "ORDER BY n.last_seen DESC").fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM nodes WHERE user_id=? ORDER BY last_seen DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]


# Auto-init on import (cheap, idempotent).
init_hub_db()
