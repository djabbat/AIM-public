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

CREATE TABLE IF NOT EXISTS ai_events_archive (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id     INTEGER,
    archived_at     TEXT NOT NULL,
    ts              TEXT,
    patient_id      TEXT,
    session_id      TEXT,
    agent           TEXT,
    decision_type   TEXT,
    alternatives_json TEXT,
    chosen_id       TEXT,
    laws_json       TEXT,
    scoring_json    TEXT,
    override_type   TEXT,
    override_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_patients_folder ON patients(folder);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_cache_hash ON llm_cache(hash);
CREATE INDEX IF NOT EXISTS idx_archive_patient ON ai_events_archive(patient_id);
CREATE INDEX IF NOT EXISTS idx_archive_ts ON ai_events_archive(ts);
"""

def init_db():
    """Создать таблицы если не существуют."""
    with _conn() as con:
        con.executescript(SCHEMA)

# ── Пациенты ──────────────────────────────────────────────────────────────────

DOB_PLACEHOLDER = "2000_01_01"
"""Placeholder для неизвестной/сомнительной даты рождения. См. CLAUDE.md."""


def format_patient_folder(name: str, dob: str | None = None) -> str:
    """Сформировать имя папки пациента: SURNAME_NAME_YYYY_MM_DD.

    Per CLAUDE.md: YYYY_MM_DD = дата рождения. Если неизвестна → placeholder
    `2000_01_01`. НЕ использовать `date.today()` — это была багa intake/UI.

    Args:
        name: "Фамилия Имя" (свободная форма, регистр любой)
        dob: "YYYY-MM-DD" / "YYYY_MM_DD" / "DD.MM.YYYY" / None
    """
    safe_name = name.strip().replace(" ", "_")

    if not dob:
        dob_part = DOB_PLACEHOLDER
    else:
        # Нормализуем популярные форматы → YYYY_MM_DD
        d = dob.strip().replace("-", "_").replace(".", "_").replace("/", "_")
        parts = d.split("_")
        if len(parts) == 3 and len(parts[0]) == 4:
            dob_part = f"{parts[0]}_{parts[1].zfill(2)}_{parts[2].zfill(2)}"
        elif len(parts) == 3 and len(parts[2]) == 4:
            # DD_MM_YYYY → YYYY_MM_DD
            dob_part = f"{parts[2]}_{parts[1].zfill(2)}_{parts[0].zfill(2)}"
        else:
            dob_part = DOB_PLACEHOLDER

    return f"{safe_name}_{dob_part}"


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

# ── Memory tiering (hot / warm / cold) для ai_events ──────────────────────────
#
# Policy:
#   HOT  — последние 7 дней (запрашиваются часто, оставлять в `ai_events`)
#   WARM — 7-90 дней (доступны, но не индексируются агрессивно — `ai_events`)
#   COLD — старше 90 дней → перенос в `ai_events_archive`, удаление из hot
#
# Закрывает TODO из README_AI_KERNEL.md §12: "ai_events retention policy не
# определена (будет расти вечно)".

HOT_DAYS  = 7
WARM_DAYS = 90  # warm cutoff = всё, что старше → cold


def _ai_events_exists(con) -> bool:
    """ai_events создаётся в kernel.py лениво — не падать, если её ещё нет."""
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_events'"
    ).fetchone()
    return row is not None


def get_hot_events(patient_id: str | None = None, limit: int = 100) -> list[dict]:
    """Последние HOT_DAYS дней. Если patient_id=None — глобально."""
    with _conn() as con:
        if not _ai_events_exists(con):
            return []
        cutoff = f"datetime('now', '-{HOT_DAYS} days')"
        sql = f"SELECT * FROM ai_events WHERE ts >= {cutoff}"
        params: tuple = ()
        if patient_id:
            sql += " AND patient_id=?"
            params = (patient_id,)
        sql += " ORDER BY ts DESC LIMIT ?"
        rows = con.execute(sql, params + (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_warm_events(patient_id: str | None = None, limit: int = 500) -> list[dict]:
    """От HOT_DAYS до WARM_DAYS дней назад."""
    with _conn() as con:
        if not _ai_events_exists(con):
            return []
        sql = (
            f"SELECT * FROM ai_events "
            f"WHERE ts < datetime('now', '-{HOT_DAYS} days') "
            f"  AND ts >= datetime('now', '-{WARM_DAYS} days')"
        )
        params: tuple = ()
        if patient_id:
            sql += " AND patient_id=?"
            params = (patient_id,)
        sql += " ORDER BY ts DESC LIMIT ?"
        rows = con.execute(sql, params + (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_cold_events(patient_id: str | None = None, limit: int = 1000) -> list[dict]:
    """Архивные события (старше WARM_DAYS дней). Из ai_events_archive."""
    with _conn() as con:
        sql = "SELECT * FROM ai_events_archive"
        params: tuple = ()
        if patient_id:
            sql += " WHERE patient_id=?"
            params = (patient_id,)
        sql += " ORDER BY ts DESC LIMIT ?"
        rows = con.execute(sql, params + (limit,)).fetchall()
        return [dict(r) for r in rows]


def archive_old_events(cutoff_days: int = WARM_DAYS) -> int:
    """Перенести события старше cutoff_days в archive. Вернуть число перенесённых.

    Идемпотентно: при повторном вызове не дублирует (use original_id + ts).
    Безопасно: не падает при отсутствии ai_events.
    """
    with _conn() as con:
        if not _ai_events_exists(con):
            return 0
        cutoff_sql = f"datetime('now', '-{cutoff_days} days')"
        old = con.execute(
            f"SELECT * FROM ai_events WHERE ts < {cutoff_sql}"
        ).fetchall()
        if not old:
            return 0

        archived_at = datetime.now().isoformat()
        moved = 0
        for row in old:
            # Идемпотентность: пропустить, если уже в архиве
            existing = con.execute(
                "SELECT id FROM ai_events_archive WHERE original_id=? AND ts=?",
                (row["id"], row["ts"])
            ).fetchone()
            if existing:
                continue
            con.execute(
                "INSERT INTO ai_events_archive "
                "(original_id, archived_at, ts, patient_id, session_id, agent, "
                " decision_type, alternatives_json, chosen_id, laws_json, "
                " scoring_json, override_type, override_reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], archived_at, row["ts"], row["patient_id"],
                 row["session_id"], row["agent"], row["decision_type"],
                 row["alternatives_json"], row["chosen_id"], row["laws_json"],
                 row["scoring_json"], row["override_type"], row["override_reason"])
            )
            con.execute("DELETE FROM ai_events WHERE id=?", (row["id"],))
            moved += 1
        return moved


def tier_stats() -> dict:
    """Diagnostic: размеры hot/warm/cold ярусов."""
    with _conn() as con:
        if not _ai_events_exists(con):
            hot = warm = 0
        else:
            hot = con.execute(
                f"SELECT COUNT(*) FROM ai_events "
                f"WHERE ts >= datetime('now', '-{HOT_DAYS} days')"
            ).fetchone()[0]
            warm = con.execute(
                f"SELECT COUNT(*) FROM ai_events "
                f"WHERE ts < datetime('now', '-{HOT_DAYS} days')"
            ).fetchone()[0]
        cold = con.execute("SELECT COUNT(*) FROM ai_events_archive").fetchone()[0]
        return {"hot": hot, "warm": warm, "cold": cold,
                "hot_days": HOT_DAYS, "warm_days": WARM_DAYS}

# ── Инициализация при импорте ─────────────────────────────────────────────────

init_db()
