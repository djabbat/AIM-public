# -*- coding: utf-8 -*-
"""
AIM v6.0 — db.py
SQLite слой с полной схемой БД. В production заменяется на PostgreSQL.

All TEXT columns store Unicode natively in UTF-8 (SQLite default).
Georgian (ქართული), Kazakh (Қазақша), Arabic (العربية) names/notes
are fully supported. A custom GEORGIAN collation enables Unicode-aware
sorting for Georgian patient surnames.

Использование:
    from db import get_db, init_db
    db = get_db()
    db.execute("SELECT * FROM patients WHERE tenant_id = ?", [1])
"""

import sqlite3
import json
import logging
import unicodedata
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from config import cfg

logger = logging.getLogger(__name__)

# ============================================================================
# Georgian / Unicode collation
# ============================================================================

def georgian_collation(a: str, b: str) -> int:
    """
    Unicode-aware collation for Georgian (mkhedruli) and other non-Latin scripts.
    Normalises both strings to NFC before comparing so that precomposed and
    decomposed representations of the same character sort identically.
    Returns -1, 0, or 1 (as required by sqlite3.create_collation).
    """
    a_norm = unicodedata.normalize("NFC", a or "")
    b_norm = unicodedata.normalize("NFC", b or "")
    if a_norm < b_norm:
        return -1
    elif a_norm > b_norm:
        return 1
    return 0


# ============================================================================
# Схема БД
# ============================================================================

SCHEMA_SQL = """
-- ============================================================
-- AIM v6.0 Database Schema (SQLite)
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

-- ------------------------------------------------------------
-- Тенанты (клиники/организации)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,          -- 'drjaba', 'fclc', 'wlr_abastumani'
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',  -- free, basic, pro, enterprise
    max_patients INTEGER NOT NULL DEFAULT 50,
    max_doctors  INTEGER NOT NULL DEFAULT 2,
    storage_gb   INTEGER NOT NULL DEFAULT 1,
    api_calls_per_min INTEGER NOT NULL DEFAULT 30,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Пользователи (врачи, пациенты, персонал, партнёры)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email       TEXT,
    phone       TEXT,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'patient',
                -- patient | family_member | guardian | doctor | nurse |
                -- lab_technician | administrator | institution_admin |
                -- department_head | lab_partner | pharmacy_partner |
                -- insurance_partner | system_admin | auditor
    institution_id INTEGER,
    department_id  INTEGER,
    password_hash  TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    last_login  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_id, email),
    UNIQUE(tenant_id, phone)
);

-- ------------------------------------------------------------
-- Пациенты
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),          -- если пациент — пользователь системы
    folder_name TEXT,                                  -- имя папки в Patients/
    surname     TEXT NOT NULL,
    first_name  TEXT NOT NULL,
    birth_date  TEXT,
    sex         TEXT CHECK(sex IN ('M', 'F', 'X')),
    phone       TEXT,
    email       TEXT,
    address     TEXT,
    notes       TEXT,
    ze_status   REAL,                                  -- Ze-статус (0-100)
    biological_age REAL,                               -- биологический возраст
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Врачи (расширение users для медперсонала)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS doctors (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    speciality  TEXT,
    license_no  TEXT,
    bio         TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Записи на приём
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    doctor_id   INTEGER NOT NULL REFERENCES doctors(id),
    scheduled_at TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 30,
    status      TEXT NOT NULL DEFAULT 'scheduled',
                -- scheduled | confirmed | completed | cancelled | no_show
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Анализы и лабораторные данные
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyses (
    id          TEXT PRIMARY KEY,               -- UUID
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    doctor_id   INTEGER REFERENCES doctors(id),
    type        TEXT NOT NULL DEFAULT 'lab',    -- lab | ecg | eeg | hrv | mri | other
    source      TEXT,                           -- whatsapp | upload | lab_api | ocr
    raw_text    TEXT,                           -- оригинальный текст
    lab_values  TEXT,                           -- JSON: {"glucose": 5.4, "hba1c": 5.6}
    ai_analysis TEXT,                           -- AI-интерпретация
    status      TEXT NOT NULL DEFAULT 'pending',
                -- pending | processing | ready | approved | rejected
    file_path   TEXT,                           -- путь к исходному файлу
    file_hash   TEXT,                           -- SHA-256
    synced      INTEGER NOT NULL DEFAULT 1,     -- для офлайн-синхронизации
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Ze / HRV / EEG данные
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS biosense_readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    reading_type TEXT NOT NULL,                 -- hrv | eeg | ze_composite
    measured_at TEXT NOT NULL,
    -- HRV параметры
    sdnn        REAL,
    rmssd       REAL,
    lf_hf_ratio REAL,
    dfa_alpha1  REAL,
    -- EEG параметры
    alpha_power REAL,
    beta_power  REAL,
    theta_power REAL,
    delta_power REAL,
    -- Ze-статус
    ze_status   REAL,
    raw_data    TEXT,                           -- полный JSON с сырыми данными
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Рецепты и назначения
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prescriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    doctor_id   INTEGER NOT NULL REFERENCES doctors(id),
    items       TEXT NOT NULL,                  -- JSON: [{drug, dose, frequency, duration}]
    instructions TEXT,
    status      TEXT NOT NULL DEFAULT 'active', -- active | completed | cancelled
    issued_at   TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Диагнозы
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnoses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    doctor_id   INTEGER REFERENCES doctors(id),
    icd11_code  TEXT,                           -- МКБ-11 код
    name        TEXT NOT NULL,
    confidence  REAL,                           -- байесовская уверенность 0-1
    is_primary  INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    ze_context  TEXT,                           -- Ze-интерпретация диагноза
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Сообщения (чат врач-пациент)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,               -- UUID
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    from_user_id INTEGER NOT NULL REFERENCES users(id),
    to_user_id  INTEGER NOT NULL REFERENCES users(id),
    text        TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    synced      INTEGER NOT NULL DEFAULT 1,     -- для офлайн
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Push-токены (FCM/APNs)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS push_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    token       TEXT NOT NULL UNIQUE,
    platform    TEXT NOT NULL,                  -- android | ios | web
    device_id   TEXT,
    app_version TEXT,
    is_valid    INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Аудит лог (каждое действие)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER REFERENCES tenants(id),
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,                  -- login | view_patient | update_analysis | ...
    resource    TEXT,                           -- patient | analysis | prescription | ...
    resource_id TEXT,
    details     TEXT,                           -- JSON с деталями
    ip_address  TEXT,
    user_agent  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Биллинг и подписки
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS billing (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    plan        TEXT NOT NULL,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    status      TEXT NOT NULL DEFAULT 'active', -- active | past_due | cancelled | trialing
    current_period_start TEXT,
    current_period_end   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Накопленные медицинские знания (self-learning)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medical_knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type TEXT NOT NULL,                 -- symptom_diagnosis | lab_threshold | ze_correlation
    pattern_key  TEXT NOT NULL,
    pattern_data TEXT NOT NULL,                 -- JSON
    confidence   REAL NOT NULL DEFAULT 0.5,
    occurrences  INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(pattern_type, pattern_key)
);

-- ============================================================
-- Индексы
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_patients_tenant ON patients(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analyses_patient ON analyses(patient_id);
CREATE INDEX IF NOT EXISTS idx_analyses_tenant ON analyses(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_appointments_scheduled ON appointments(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_synced ON messages(synced);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_biosense_patient ON biosense_readings(patient_id);
CREATE INDEX IF NOT EXISTS idx_diagnoses_patient ON diagnoses(patient_id);
"""

# ============================================================================
# Соединение с БД
# ============================================================================

_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """Получить соединение с SQLite (singleton)"""
    global _connection
    if _connection is None:
        db_path = cfg.DB_PATH
        _connection = sqlite3.connect(
            str(db_path),
            timeout=cfg.DB_TIMEOUT,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        _connection.row_factory = sqlite3.Row

        # Enforce UTF-8 encoding at the SQLite level
        _connection.execute("PRAGMA encoding = 'UTF-8'")

        if cfg.DB_WAL_MODE:
            _connection.execute("PRAGMA journal_mode = WAL")
        _connection.execute("PRAGMA foreign_keys = ON")

        # Register Unicode-aware collation for Georgian and other scripts
        _connection.create_collation("GEORGIAN", georgian_collation)

    return _connection


@contextmanager
def get_db():
    """Context manager для работы с БД"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB ошибка: {e}")
        raise


def init_db():
    """Инициализировать схему БД"""
    try:
        conn = get_connection()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info(f"БД инициализирована: {cfg.DB_PATH}")
        _seed_default_tenant()
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        raise


def _seed_default_tenant():
    """Создать тенант по умолчанию (drjaba) если не существует"""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM tenants WHERE slug = ?", ["drjaba"]
    ).fetchone()

    if not existing:
        conn.execute(
            """INSERT INTO tenants (slug, name, plan, max_patients, max_doctors, storage_gb, api_calls_per_min)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["drjaba", "Dr. Jaba Tkemaladze Practice", "pro", 5000, 50, 100, 300]
        )
        conn.commit()
        logger.info("Создан тенант по умолчанию: drjaba")


# ============================================================================
# Вспомогательные функции
# ============================================================================

def row_to_dict(row) -> Optional[Dict]:
    """Конвертировать sqlite3.Row в dict"""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows) -> List[Dict]:
    """Конвертировать список sqlite3.Row в список dict"""
    return [dict(r) for r in rows]


def execute(sql: str, params: list = None) -> sqlite3.Cursor:
    """Выполнить SQL запрос"""
    conn = get_connection()
    return conn.execute(sql, params or [])


def fetchone(sql: str, params: list = None) -> Optional[Dict]:
    """Получить одну запись"""
    row = execute(sql, params).fetchone()
    return row_to_dict(row)


def fetchall(sql: str, params: list = None) -> List[Dict]:
    """Получить все записи"""
    rows = execute(sql, params).fetchall()
    return rows_to_list(rows)


def close():
    """Закрыть соединение с БД"""
    global _connection
    if _connection:
        _connection.close()
        _connection = None
        logger.info("Соединение с БД закрыто")


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    print(f"Инициализация БД: {cfg.DB_PATH}")
    init_db()

    # Проверка
    tenants = fetchall("SELECT * FROM tenants")
    print(f"Тенанты: {len(tenants)}")
    for t in tenants:
        print(f"  [{t['id']}] {t['slug']} — {t['name']} ({t['plan']})")

    close()
    print("db.py — OK")
