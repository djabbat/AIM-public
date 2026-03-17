#!/usr/bin/env python3
"""
db.py — AIM SQLite database layer.

Заменяет: processed_files.json, medical_knowledge.json,
          разрозненные _lab_results.json и _ai_analysis.txt в папках пациентов.

База данных: ~/AIM/aim.db
Чистый sqlite3 — без внешних зависимостей.

Схема:
  patients        — реестр пациентов
  lab_snapshots   — лабораторные данные (JSON params)
  diagnoses       — AI-диагнозы (байес + LLM)
  ze_hrv          — Ze-HRV метрики (из ze_ecg.py)
  knowledge       — медицинская база знаний (самообучение)
  processed_files — лог обработанных файлов
"""

from __future__ import annotations

import json
import sqlite3
import hashlib
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from config import AIM_DIR, DB_PATH as _CONFIG_DB_PATH, get_logger

log = get_logger("db")

DB_PATH = Path(_CONFIG_DB_PATH)

# ─────────────────────────────────────────────────────────────────────────────
# Схема
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS patients (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    surname      TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    dob          TEXT,                        -- YYYY-MM-DD или NULL
    sex          TEXT    CHECK(sex IN ('M','F','?')) DEFAULT '?',
    folder_path  TEXT    NOT NULL UNIQUE,
    notes        TEXT    DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_patients_name ON patients(surname, name);

CREATE TABLE IF NOT EXISTS lab_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    taken_at     TEXT,                        -- дата забора крови YYYY-MM-DD
    source_file  TEXT    DEFAULT '',
    params_json  TEXT    NOT NULL DEFAULT '{}',  -- {param: {value, unit, status}}
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_labs_patient ON lab_snapshots(patient_id);

CREATE TABLE IF NOT EXISTS diagnoses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    bayesian_json  TEXT    DEFAULT '{}',     -- {diagnosis: probability}
    llm_text       TEXT    DEFAULT '',       -- полный текст анализа LLM
    confidence     REAL    DEFAULT 0.0,      -- 0..1
    source         TEXT    DEFAULT ''        -- "intake" | "telegram" | "manual"
);

CREATE INDEX IF NOT EXISTS idx_diag_patient ON diagnoses(patient_id);

-- FTS по тексту диагнозов
CREATE VIRTUAL TABLE IF NOT EXISTS diagnoses_fts USING fts5(
    llm_text,
    content=diagnoses,
    content_rowid=id
);

CREATE TABLE IF NOT EXISTS ze_hrv (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    recorded_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    ze_v         REAL,
    ze_tau       INTEGER,
    ze_state     TEXT,
    rmssd        REAL,
    sdnn         REAL,
    pnn50        REAL,
    mean_hr      REAL,
    mean_rr      REAL,
    quality      TEXT,
    source       TEXT    DEFAULT '',
    raw_json     TEXT    DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ze_patient ON ze_hrv(patient_id);

CREATE TABLE IF NOT EXISTS knowledge (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    condition    TEXT    NOT NULL UNIQUE,
    evidence_json TEXT   NOT NULL DEFAULT '{}',
    pattern_count INTEGER DEFAULT 0,
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processed_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT    NOT NULL UNIQUE,
    hash_md5     TEXT    DEFAULT '',
    processed_at TEXT    NOT NULL DEFAULT (datetime('now')),
    status       TEXT    DEFAULT 'ok',       -- "ok" | "error" | "skipped"
    error_msg    TEXT    DEFAULT ''
);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Подключение
# ─────────────────────────────────────────────────────────────────────────────

_local = threading.local()


def _connect() -> sqlite3.Connection:
    """Возвращает thread-local соединение с БД."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def _tx():
    """Контекстный менеджер транзакции."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(path: Optional[Path] = None) -> None:
    """Создаёт БД и применяет схему (идемпотентно)."""
    global DB_PATH
    if path:
        DB_PATH = path
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.executescript(SCHEMA)
    conn.commit()
    log.info(f"DB ready: {DB_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Patients
# ─────────────────────────────────────────────────────────────────────────────

def upsert_patient(surname: str, name: str, folder_path: str,
                   dob: Optional[str] = None, sex: str = "?",
                   notes: str = "") -> int:
    """
    Добавляет или обновляет пациента. Возвращает patient_id.
    folder_path используется как уникальный ключ.
    """
    with _tx() as conn:
        existing = conn.execute(
            "SELECT id FROM patients WHERE folder_path = ?", (folder_path,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE patients SET surname=?, name=?, dob=?, sex=?, notes=? WHERE id=?",
                (surname, name, dob, sex, notes, existing["id"])
            )
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO patients (surname, name, dob, sex, folder_path, notes) VALUES (?,?,?,?,?,?)",
            (surname, name, dob, sex, folder_path, notes)
        )
        return cur.lastrowid


def get_patient_by_folder(folder_path: str) -> Optional[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM patients WHERE folder_path = ?", (folder_path,)
    ).fetchone()


def get_patient_by_id(patient_id: int) -> Optional[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()


def search_patients(query: str) -> list[sqlite3.Row]:
    """Поиск по фамилии или имени (LIKE)."""
    q = f"%{query}%"
    return _connect().execute(
        "SELECT * FROM patients WHERE surname LIKE ? OR name LIKE ? ORDER BY surname",
        (q, q)
    ).fetchall()


def list_patients() -> list[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM patients ORDER BY surname, name"
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Lab Snapshots
# ─────────────────────────────────────────────────────────────────────────────

def save_labs(patient_id: int, params: dict,
              taken_at: Optional[str] = None,
              source_file: str = "") -> int:
    """Сохраняет лабораторный снапшот. params = {param_id: {value, unit, status}}."""
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO lab_snapshots (patient_id, taken_at, source_file, params_json) VALUES (?,?,?,?)",
            (patient_id, taken_at, source_file, json.dumps(params, ensure_ascii=False))
        )
        return cur.lastrowid


def get_latest_labs(patient_id: int) -> Optional[dict]:
    """Последний лабораторный снапшот для пациента."""
    row = _connect().execute(
        "SELECT params_json FROM lab_snapshots WHERE patient_id=? ORDER BY created_at DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return json.loads(row["params_json"]) if row else None


def get_lab_history(patient_id: int) -> list[dict]:
    """Все снапшоты пациента по дате."""
    rows = _connect().execute(
        "SELECT taken_at, created_at, params_json FROM lab_snapshots WHERE patient_id=? ORDER BY taken_at",
        (patient_id,)
    ).fetchall()
    return [{"taken_at": r["taken_at"], "created_at": r["created_at"],
             "params": json.loads(r["params_json"])} for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Diagnoses
# ─────────────────────────────────────────────────────────────────────────────

def save_diagnosis(patient_id: int, llm_text: str,
                   bayesian: Optional[dict] = None,
                   confidence: float = 0.0,
                   source: str = "intake") -> int:
    with _tx() as conn:
        bayes_json = json.dumps(bayesian or {}, ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO diagnoses (patient_id, bayesian_json, llm_text, confidence, source) VALUES (?,?,?,?,?)",
            (patient_id, bayes_json, llm_text, confidence, source)
        )
        diag_id = cur.lastrowid
        # Обновить FTS индекс
        conn.execute(
            "INSERT INTO diagnoses_fts(rowid, llm_text) VALUES (?,?)",
            (diag_id, llm_text)
        )
        return diag_id


def get_latest_diagnosis(patient_id: int) -> Optional[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM diagnoses WHERE patient_id=? ORDER BY created_at DESC LIMIT 1",
        (patient_id,)
    ).fetchone()


def search_diagnoses(query: str, limit: int = 20) -> list[sqlite3.Row]:
    """Full-text поиск по тексту диагнозов."""
    return _connect().execute(
        """SELECT d.*, p.surname, p.name
           FROM diagnoses_fts f
           JOIN diagnoses d ON f.rowid = d.id
           JOIN patients p ON d.patient_id = p.id
           WHERE diagnoses_fts MATCH ?
           ORDER BY rank LIMIT ?""",
        (query, limit)
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Ze HRV
# ─────────────────────────────────────────────────────────────────────────────

def save_ze_hrv(patient_id: int, metrics: Any,
                source: str = "", recorded_at: Optional[str] = None) -> int:
    """
    Сохраняет Ze-HRV отчёт. metrics — ZeMetrics dataclass или dict.
    """
    from dataclasses import asdict
    if hasattr(metrics, "ze_v"):
        m = asdict(metrics) if hasattr(metrics, "__dataclass_fields__") else vars(metrics)
    else:
        m = metrics

    with _tx() as conn:
        cur = conn.execute(
            """INSERT INTO ze_hrv
               (patient_id, recorded_at, ze_v, ze_tau, ze_state,
                rmssd, sdnn, pnn50, mean_hr, mean_rr, quality, source, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                patient_id,
                recorded_at or datetime.now().isoformat(),
                m.get("ze_v"), m.get("ze_tau"), m.get("ze_state"),
                m.get("rmssd"), m.get("sdnn"), m.get("pnn50"),
                m.get("mean_hr"), m.get("mean_rr"), m.get("quality"),
                source,
                json.dumps(m, ensure_ascii=False),
            )
        )
        return cur.lastrowid


def get_ze_history(patient_id: int, limit: int = 100) -> list[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM ze_hrv WHERE patient_id=? ORDER BY recorded_at DESC LIMIT ?",
        (patient_id, limit)
    ).fetchall()


def get_latest_ze(patient_id: int) -> Optional[sqlite3.Row]:
    return _connect().execute(
        "SELECT * FROM ze_hrv WHERE patient_id=? ORDER BY recorded_at DESC LIMIT 1",
        (patient_id,)
    ).fetchone()


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Base
# ─────────────────────────────────────────────────────────────────────────────

def upsert_knowledge(condition: str, evidence: dict) -> None:
    """Обновляет или создаёт запись в базе знаний."""
    with _tx() as conn:
        existing = conn.execute(
            "SELECT id, evidence_json, pattern_count FROM knowledge WHERE condition=?",
            (condition,)
        ).fetchone()
        if existing:
            # Мёрдж: объединяем доказательную базу
            old_ev = json.loads(existing["evidence_json"])
            old_ev.update(evidence)
            conn.execute(
                "UPDATE knowledge SET evidence_json=?, pattern_count=pattern_count+1, updated_at=datetime('now') WHERE id=?",
                (json.dumps(old_ev, ensure_ascii=False), existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO knowledge (condition, evidence_json, pattern_count) VALUES (?,?,1)",
                (condition, json.dumps(evidence, ensure_ascii=False))
            )


def get_knowledge(condition: str) -> Optional[dict]:
    row = _connect().execute(
        "SELECT evidence_json FROM knowledge WHERE condition=?", (condition,)
    ).fetchone()
    return json.loads(row["evidence_json"]) if row else None


def list_knowledge() -> list[sqlite3.Row]:
    return _connect().execute(
        "SELECT condition, pattern_count, updated_at FROM knowledge ORDER BY pattern_count DESC"
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Processed Files
# ─────────────────────────────────────────────────────────────────────────────

def _md5(path: str) -> str:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def is_processed(path: str) -> bool:
    row = _connect().execute(
        "SELECT id FROM processed_files WHERE path=? AND status='ok'", (path,)
    ).fetchone()
    return row is not None


def mark_processed(path: str, status: str = "ok", error_msg: str = "") -> None:
    h = _md5(path)
    with _tx() as conn:
        conn.execute(
            """INSERT INTO processed_files (path, hash_md5, status, error_msg)
               VALUES (?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                 hash_md5=excluded.hash_md5,
                 processed_at=datetime('now'),
                 status=excluded.status,
                 error_msg=excluded.error_msg""",
            (path, h, status, error_msg)
        )


def unmark_processed(path: str) -> None:
    with _tx() as conn:
        conn.execute("DELETE FROM processed_files WHERE path=?", (path,))


# ─────────────────────────────────────────────────────────────────────────────
# Миграция из старых JSON файлов
# ─────────────────────────────────────────────────────────────────────────────

def migrate_from_json(
    knowledge_file: Optional[str] = None,
    processed_file: Optional[str] = None,
    patients_dir:   Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Мигрирует данные из старых JSON/файловых структур в SQLite.

    knowledge_file : путь к medical_knowledge.json
    processed_file : путь к processed_files.json
    patients_dir   : путь к ~/AIM/Patients/
    dry_run        : только подсчёт, без записи

    Возвращает статистику миграции.
    """
    from config import KNOWLEDGE_FILE, PROCESSED_LOG, PATIENTS_DIR
    import re as _re

    stats = {"patients": 0, "labs": 0, "diagnoses": 0, "knowledge": 0,
             "processed": 0, "errors": 0}

    kf = Path(knowledge_file or KNOWLEDGE_FILE)
    pf = Path(processed_file or PROCESSED_LOG)
    pd = Path(patients_dir or PATIENTS_DIR)

    log.info(f"Migration {'DRY RUN' if dry_run else 'START'}")

    # 1. medical_knowledge.json → knowledge table
    if kf.exists():
        try:
            data = json.loads(kf.read_text(encoding="utf-8"))
            for condition, evidence in data.items():
                if not dry_run:
                    upsert_knowledge(condition, evidence if isinstance(evidence, dict) else {"raw": evidence})
                stats["knowledge"] += 1
        except Exception as e:
            log.warning(f"knowledge migration error: {e}")
            stats["errors"] += 1

    # 2. processed_files.json → processed_files table
    if pf.exists():
        try:
            paths = json.loads(pf.read_text(encoding="utf-8"))
            for p in paths:
                if not dry_run:
                    with _tx() as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO processed_files (path, status) VALUES (?,?)",
                            (str(p), "ok")
                        )
                stats["processed"] += 1
        except Exception as e:
            log.warning(f"processed_files migration error: {e}")
            stats["errors"] += 1

    # 3. Папки пациентов → patients + diagnoses
    folder_re = _re.compile(
        r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)_([A-Za-zА-Яа-яЁёა-ჿ\-]+)_(\d{4})_(\d{2})_(\d{2})$'
    )
    if pd.exists():
        for folder in pd.iterdir():
            if not folder.is_dir():
                continue
            m = folder_re.match(folder.name)
            if not m:
                continue
            surname, name, y, mo, d = m.groups()
            dob_str = f"{y}-{mo}-{d}"
            folder_path = str(folder)

            if not dry_run:
                pid = upsert_patient(surname, name, folder_path, dob=dob_str)
            else:
                pid = -1
            stats["patients"] += 1

            # _ai_analysis.txt → diagnoses
            analysis_file = folder / "_ai_analysis.txt"
            if analysis_file.exists():
                try:
                    text = analysis_file.read_text(encoding="utf-8", errors="replace")
                    if text.strip() and not dry_run:
                        save_diagnosis(pid, text, source="migrated")
                    stats["diagnoses"] += 1
                except Exception as e:
                    log.warning(f"diagnosis migration {folder.name}: {e}")
                    stats["errors"] += 1

            # _lab_results.json → lab_snapshots
            lab_file = folder / "_lab_results.json"
            if lab_file.exists():
                try:
                    labs = json.loads(lab_file.read_text(encoding="utf-8"))
                    if labs and not dry_run:
                        save_labs(pid, labs, source_file=str(lab_file))
                    stats["labs"] += 1
                except Exception as e:
                    log.warning(f"labs migration {folder.name}: {e}")
                    stats["errors"] += 1

            # ze_hrv.json → ze_hrv table
            ze_file = folder / "ze_hrv.json"
            if ze_file.exists():
                try:
                    ze_data = json.loads(ze_file.read_text(encoding="utf-8"))
                    if ze_data and not dry_run:
                        save_ze_hrv(pid, ze_data.get("metrics", {}),
                                    source=ze_data.get("source", "migrated"))
                except Exception as e:
                    log.warning(f"ze_hrv migration {folder.name}: {e}")
                    stats["errors"] += 1

    log.info(f"Migration complete: {stats}")
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    init_db()

    if "--migrate" in sys.argv:
        dry = "--dry-run" in sys.argv
        stats = migrate_from_json(dry_run=dry)
        print(f"\nМиграция {'(DRY RUN) ' if dry else ''}завершена:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    elif "--stats" in sys.argv:
        conn = _connect()
        for table in ["patients", "lab_snapshots", "diagnoses", "ze_hrv", "knowledge", "processed_files"]:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {n} записей")

    elif "--search" in sys.argv:
        query = sys.argv[sys.argv.index("--search") + 1]
        results = search_patients(query)
        print(f"Пациенты '{query}':")
        for r in results:
            print(f"  [{r['id']}] {r['surname']} {r['name']}  {r['dob'] or '?'}  {r['folder_path']}")

    else:
        print(f"AIM DB: {DB_PATH}")
        print("Команды: --migrate [--dry-run] | --stats | --search ИМЯ")
