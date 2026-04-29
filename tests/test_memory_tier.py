"""Unit tests for memory tiering in db.py — hot/warm/cold ai_events."""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Изолированная DB для каждого теста — не трогаем production aim.db."""
    db_file = tmp_path / "test_aim.db"
    # Подмена DB_PATH ДО импорта db
    import config
    monkeypatch.setattr(config, "DB_PATH", db_file)

    # Перезагрузить db с новым путём
    import importlib
    import db as db_mod
    importlib.reload(db_mod)

    # Создать ai_events (kernel.py делает это лениво — мы тестируем эту lazy ситуацию)
    con = sqlite3.connect(db_file)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ai_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            patient_id TEXT,
            session_id TEXT,
            agent TEXT,
            decision_type TEXT,
            alternatives_json TEXT,
            chosen_id TEXT,
            laws_json TEXT,
            scoring_json TEXT,
            override_type TEXT,
            override_reason TEXT
        )
    """)
    con.commit()
    con.close()

    yield db_mod, db_file


def _insert_event(db_file, patient_id, ts, decision_type="dx"):
    con = sqlite3.connect(db_file)
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (?, ?, 'doctor', ?)",
        (ts, patient_id, decision_type)
    )
    con.commit()
    con.close()


def test_tier_stats_empty(tmp_db):
    db, _ = tmp_db
    stats = db.tier_stats()
    assert stats["hot"] == 0
    assert stats["warm"] == 0
    assert stats["cold"] == 0
    assert stats["hot_days"] == 7
    assert stats["warm_days"] == 90


def test_hot_warm_classification(tmp_db):
    db, db_file = tmp_db
    # Hot: 1 day ago
    _insert_event(db_file, "P1", "2099-01-01 00:00:00")  # реальный hot будет через "now"
    # Используем SQL datetime — вставить относительно now
    con = sqlite3.connect(db_file)
    con.execute("DELETE FROM ai_events")
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-1 day'), 'P1', 'doctor', 'dx')"
    )
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-30 days'), 'P1', 'doctor', 'dx')"
    )
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-200 days'), 'P1', 'doctor', 'dx')"
    )
    con.commit()
    con.close()

    hot = db.get_hot_events()
    warm = db.get_warm_events()
    assert len(hot) == 1                # -1 day → hot
    assert len(warm) == 1               # -30 days → warm (между HOT_DAYS=7 и WARM_DAYS=90)
    # -200 days в warm не попадает (старше WARM_DAYS), это cold candidate


def test_archive_cold_events(tmp_db):
    db, db_file = tmp_db
    con = sqlite3.connect(db_file)
    # Один свежий (не должен архивироваться)
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-1 day'), 'P1', 'doctor', 'dx')"
    )
    # Два старых (>90 дней)
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-100 days'), 'P1', 'doctor', 'dx')"
    )
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-200 days'), 'P2', 'lab', 'lab_panel')"
    )
    con.commit()
    con.close()

    moved = db.archive_old_events()
    assert moved == 2

    cold = db.get_cold_events()
    assert len(cold) == 2

    # Проверка идемпотентности: повторный вызов не должен ничего двигать
    moved2 = db.archive_old_events()
    assert moved2 == 0


def test_archive_handles_missing_ai_events(tmp_db):
    db, db_file = tmp_db
    con = sqlite3.connect(db_file)
    con.execute("DROP TABLE ai_events")
    con.commit()
    con.close()

    # Не должно падать
    assert db.archive_old_events() == 0
    assert db.get_hot_events() == []
    assert db.get_warm_events() == []


def test_filter_by_patient(tmp_db):
    db, db_file = tmp_db
    con = sqlite3.connect(db_file)
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-1 day'), 'Alice', 'doctor', 'dx')"
    )
    con.execute(
        "INSERT INTO ai_events (ts, patient_id, agent, decision_type) "
        "VALUES (datetime('now', '-1 day'), 'Bob', 'doctor', 'dx')"
    )
    con.commit()
    con.close()

    alice = db.get_hot_events(patient_id="Alice")
    bob = db.get_hot_events(patient_id="Bob")
    assert len(alice) == 1 and alice[0]["patient_id"] == "Alice"
    assert len(bob) == 1 and bob[0]["patient_id"] == "Bob"
