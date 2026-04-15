"""
AIM v7.0 — SQLite layer
Пациенты · Сессии · Кэш LLM
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from config import DB_PATH

# ── Соединение ────────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
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

# ── Схема ─────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder      TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    lang        TEXT DEFAULT 'ru',
    notes       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER REFERENCES patients(id),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    lang        TEXT DEFAULT 'ru',
    summary     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER REFERENCES sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    model       TEXT DEFAULT '',
    provider    TEXT DEFAULT '',
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    hash        TEXT PRIMARY KEY,
    prompt_hash TEXT NOT NULL,
    response    TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_patients_folder ON patients(folder);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_cache_hash ON llm_cache(hash);
"""

def init_db():
    """Создать таблицы если не существуют."""
    with _conn() as con:
        con.executescript(SCHEMA)

# ── Пациенты ──────────────────────────────────────────────────────────────────

def upsert_patient(folder: str, name: str, lang: str = "ru") -> int:
    """Добавить или обновить пациента. Вернуть id."""
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO patients (folder, name, created_at, lang) VALUES (?,?,?,?) "
            "ON CONFLICT(folder) DO UPDATE SET name=excluded.name, lang=excluded.lang "
            "RETURNING id",
            (folder, name, datetime.now().isoformat(), lang)
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur2 = con.execute("SELECT id FROM patients WHERE folder=?", (folder,))
        return cur2.fetchone()[0]

def get_patient(folder: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM patients WHERE folder=?", (folder,)
        ).fetchone()
        return dict(row) if row else None

def list_patients() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM patients ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

def search_patients(query: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM patients WHERE name LIKE ? OR folder LIKE ? ORDER BY name",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
        return [dict(r) for r in rows]

# ── Сессии ────────────────────────────────────────────────────────────────────

def new_session(patient_id: int | None, lang: str = "ru") -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO sessions (patient_id, started_at, lang) VALUES (?,?,?) RETURNING id",
            (patient_id, datetime.now().isoformat(), lang)
        )
        return cur.fetchone()[0]

def close_session(session_id: int, summary: str = ""):
    with _conn() as con:
        con.execute(
            "UPDATE sessions SET ended_at=?, summary=? WHERE id=?",
            (datetime.now().isoformat(), summary, session_id)
        )

# ── Сообщения ─────────────────────────────────────────────────────────────────

def save_message(session_id: int, role: str, content: str,
                 model: str = "", provider: str = ""):
    with _conn() as con:
        con.execute(
            "INSERT INTO messages (session_id, role, content, model, provider, ts) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, role, content, model, provider, datetime.now().isoformat())
        )

def get_history(session_id: int, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT role, content, model, ts FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

# ── LLM-кэш ──────────────────────────────────────────────────────────────────

def _make_hash(prompt: str, model: str) -> str:
    s = f"{model}::{prompt}"
    return hashlib.sha256(s.encode()).hexdigest()[:32]

def cache_get(prompt: str, model: str) -> str | None:
    h = _make_hash(prompt, model)
    with _conn() as con:
        row = con.execute(
            "SELECT response FROM llm_cache WHERE hash=?", (h,)
        ).fetchone()
        return row[0] if row else None

def cache_set(prompt: str, model: str, response: str):
    h = _make_hash(prompt, model)
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO llm_cache (hash, prompt_hash, response, model, created_at) "
            "VALUES (?,?,?,?,?)",
            (h, h, response, model, datetime.now().isoformat())
        )

# ── Инициализация при импорте ─────────────────────────────────────────────────

init_db()
