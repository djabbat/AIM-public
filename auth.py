"""
auth.py — AIM Authentication Module

Аутентификация пользователей AIM.
- Таблицы: users, sessions (в aim.db)
- Пароли: PBKDF2-HMAC-SHA256, случайная соль, 260 000 итераций
- Сессии: secrets.token_hex(32), хранятся в ~/.aim_session (remember_me)
- Роли: admin | doctor | readonly

Правило новых таблиц:
  Перед созданием новой таблицы в aim.db — ОБЯЗАТЕЛЬНО обсудить с пользователем.
  Причина: медицинская БД, структура влияет на клиническую работу и миграции.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import db as _db
import i18n

SESSION_FILE = Path.home() / ".aim_session"
SESSION_EXPIRE_DAYS = 30
PBKDF2_ITERS = 260_000

# ── Password hashing ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Returns 'salt$hash' string. Both hex-encoded."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERS
    ).hex()
    return f"{salt}${key}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time compare against stored 'salt$hash'."""
    try:
        salt, key = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERS
    ).hex()
    return hmac.compare_digest(candidate, key)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    return _db._connect()


def init_auth_tables() -> None:
    """Create users + sessions tables if not exist. Called from db.init_db()."""
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           TEXT PRIMARY KEY,
            email        TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'doctor',
            display_name TEXT,
            created_at   TEXT NOT NULL,
            created_by   TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            remember_me INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    conn.commit()


# ── User management ───────────────────────────────────────────────────────────

def create_user(
    email: str,
    password: str,
    role: str = "doctor",
    display_name: str = "",
    created_by: str = "system",
) -> str:
    """Create a new user. Returns user_id. Raises ValueError if email taken."""
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    if existing:
        raise ValueError(f"Пользователь с email '{email}' уже существует.")

    user_id = secrets.token_hex(8)
    conn.execute(
        """INSERT INTO users (id, email, password_hash, role, display_name, created_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, email, _hash_password(password), role,
         display_name or email.split("@")[0],
         datetime.now().isoformat(), created_by)
    )
    conn.commit()
    return user_id


def get_user_by_email(email: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    return dict(row) if row else None


def list_users() -> list:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, email, role, display_name, created_at FROM users ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def change_password(user_id: str, new_password: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (_hash_password(new_password), user_id)
    )
    conn.commit()


# ── Session management ────────────────────────────────────────────────────────

def _create_session(user_id: str, remember_me: bool) -> str:
    token = secrets.token_hex(32)
    expires = datetime.now() + timedelta(
        days=SESSION_EXPIRE_DAYS if remember_me else 1
    )
    _conn().execute(
        """INSERT INTO sessions (token, user_id, created_at, expires_at, remember_me)
           VALUES (?, ?, ?, ?, ?)""",
        (token, user_id, datetime.now().isoformat(),
         expires.isoformat(), int(remember_me))
    )
    _conn().commit()
    return token


def _validate_token(token: str) -> Optional[dict]:
    """Returns user dict if token is valid and not expired, else None."""
    conn = _conn()
    row = conn.execute(
        """SELECT u.*, s.token, s.expires_at, s.remember_me
           FROM sessions s JOIN users u ON s.user_id = u.id
           WHERE s.token = ?""",
        (token,)
    ).fetchone()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    return dict(row)


def _save_session_file(token: str) -> None:
    SESSION_FILE.write_text(token, encoding="utf-8")
    SESSION_FILE.chmod(0o600)


def _load_session_file() -> Optional[str]:
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text(encoding="utf-8").strip() or None
    return None


def logout() -> None:
    """Invalidate current session."""
    token = _load_session_file()
    if token:
        try:
            _conn().execute("DELETE FROM sessions WHERE token = ?", (token,))
            _conn().commit()
        except Exception:
            pass
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


# ── Main auth flow ────────────────────────────────────────────────────────────

def login(email: str, password: str, remember_me: bool = False) -> Optional[dict]:
    """
    Verify credentials, create session, return user dict.
    Returns None if credentials are invalid.
    """
    user = get_user_by_email(email)
    if not user:
        return None
    if not _verify_password(password, user["password_hash"]):
        return None
    token = _create_session(user["id"], remember_me)
    if remember_me:
        _save_session_file(token)
    user["_token"] = token
    return user


def require_auth() -> dict:
    """
    Ensure user is authenticated. Returns current user dict.

    Flow:
    1. Load language preference
    2. Check ~/.aim_session token → auto-login if valid
    3. Select language (if first run)
    4. Prompt for email/password
    5. Ask "remember me?"
    """
    init_auth_tables()
    _ensure_admin_exists()

    # Load saved language; if none — show selector
    i18n.load()
    if not i18n.LANG_FILE.exists():
        i18n.select_language()

    # Try saved session first
    token = _load_session_file()
    if token:
        user = _validate_token(token)
        if user:
            print(f"  ✓ {i18n.t('welcome_back', name=user['display_name'], role=user['role'])}")
            return user
        else:
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()

    # Prompt for credentials
    print("\n" + "═" * 44)
    print(f"  🔐  {i18n.t('login_header')}")
    print("═" * 44)

    for attempt in range(3):
        if attempt > 0:
            print(f"  ✗ {i18n.t('wrong_creds', n=attempt + 1)}")

        email = input(f"  {i18n.t('email_prompt')}").strip()
        import getpass
        password = getpass.getpass(f"  {i18n.t('password_prompt')}")

        user = login(email, password, remember_me=False)
        if user:
            break
    else:
        print(f"  ✗ {i18n.t('access_denied')}")
        raise SystemExit(1)

    # Remember me?
    remember = input(f"  {i18n.t('remember_me')}").strip()
    if i18n.is_yes(remember):
        token = _create_session(user["id"], remember_me=True)
        _save_session_file(token)
        print(f"  ✓ {i18n.t('session_saved')}")

    print(f"  ✓ {i18n.t('login_success', name=user['display_name'], role=user['role'])}")
    return user


# ── Admin functions ───────────────────────────────────────────────────────────

def register_user_interactive(admin_user: dict) -> None:
    """Interactive new user registration. Admin only."""
    if admin_user.get("role") != "admin":
        print(f"  ✗ {i18n.t('admin_only')}")
        return

    print(f"\n{i18n.t('reg_header')}")
    email = input(f"  {i18n.t('email_prompt')}").strip()
    import getpass
    pw  = getpass.getpass(f"  {i18n.t('password_prompt')}")
    pw2 = getpass.getpass(f"  {i18n.t('pw_confirm')}")
    if pw != pw2:
        print(f"  ✗ {i18n.t('pw_mismatch')}")
        return
    name = input(f"  {i18n.t('name_prompt')}").strip()
    role = input(f"  {i18n.t('role_prompt')}").strip() or "doctor"
    if role not in ("admin", "doctor", "readonly"):
        role = "doctor"
    try:
        uid = create_user(email, pw, role=role, display_name=name,
                          created_by=admin_user["id"])
        print(f"  ✓ {i18n.t('user_created', email=email, role=role, uid=uid)}")
    except ValueError as e:
        print(f"  ✗ {e}")


def show_users(admin_user: dict) -> None:
    """Print user list. Admin only."""
    if admin_user.get("role") != "admin":
        print(f"  ✗ {i18n.t('admin_only')}")
        return
    users = list_users()
    ci  = i18n.t("col_id")
    ce  = i18n.t("col_email")
    cr  = i18n.t("col_role")
    cn  = i18n.t("col_name")
    cct = i18n.t("col_created")
    print(f"\n{ci:8}  {ce:30}  {cr:10}  {cn:20}  {cct}")
    print("─" * 90)
    for u in users:
        print(f"{u['id']:8}  {u['email']:30}  {u['role']:10}  "
              f"{(u['display_name'] or ''):20}  {u['created_at'][:10]}")


# ── Bootstrap: ensure admin user exists ──────────────────────────────────────

def _ensure_admin_exists() -> None:
    """Seed admin user on first run. Credentials from ~/.aim_env."""
    conn = _conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return  # already seeded

    # Read from ~/.aim_env
    env_path = Path.home() / ".aim_env"
    email = "djabbat@gmail.com"
    password = "3.14dar100STOP"

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("AIM_ADMIN_EMAIL="):
                email = line.split("=", 1)[1].strip()
            elif line.startswith("AIM_ADMIN_PASSWORD="):
                password = line.split("=", 1)[1].strip()

    create_user(
        email=email,
        password=password,
        role="admin",
        display_name="Dr. Jaba Tkemaladze",
        created_by="bootstrap",
    )
    print(f"  ✓ {i18n.t('admin_created', email=email)}")


if __name__ == "__main__":
    # Quick test
    init_auth_tables()
    _ensure_admin_exists()
    users = list_users()
    print(f"Users in DB: {len(users)}")
    for u in users:
        print(f"  {u['email']} [{u['role']}]")
