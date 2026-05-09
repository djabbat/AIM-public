"""tests/test_doctor_calibration.py — D2 (2026-05-03)."""
from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_CALIBRATION_DB", str(tmp_path / "calib.db"))
    import importlib, sys
    if "agents.doctor_calibration" in sys.modules:
        importlib.reload(sys.modules["agents.doctor_calibration"])
    return tmp_path


# ── record() ──────────────────────────────────────────────────────


def test_record_creates_row(isolated):
    from agents.doctor_calibration import record, pending
    rid = record("STEMI", 0.7, case_id="case-1", domain="diagnosis")
    assert rid > 0
    rows = pending()
    assert len(rows) == 1
    assert rows[0].label == "STEMI"
    assert rows[0].confidence == 0.7
    assert rows[0].domain == "diagnosis"


def test_record_rejects_invalid_confidence(isolated):
    from agents.doctor_calibration import record
    with pytest.raises(ValueError):
        record("X", 1.5)
    with pytest.raises(ValueError):
        record("X", -0.1)


def test_record_rejects_blank_label(isolated):
    from agents.doctor_calibration import record
    with pytest.raises(ValueError):
        record("", 0.5)


# ── resolve() ────────────────────────────────────────────────────


def test_resolve_updates_outcome(isolated):
    from agents.doctor_calibration import record, resolve, pending, all_resolved
    rid = record("STEMI", 0.7)
    assert resolve(rid, outcome=True, source="ECG follow-up")
    assert pending() == []
    rows = all_resolved()
    assert len(rows) == 1
    assert rows[0].outcome == 1


def test_resolve_unknown_returns_false(isolated):
    from agents.doctor_calibration import resolve
    assert resolve(9999, outcome=True) is False


def test_resolve_idempotent(isolated):
    from agents.doctor_calibration import record, resolve
    rid = record("X", 0.5)
    assert resolve(rid, outcome=True)
    # Already resolved → next attempt does nothing.
    assert resolve(rid, outcome=False) is False


# ── metrics() ────────────────────────────────────────────────────


def test_metrics_empty_window(isolated):
    from agents.doctor_calibration import metrics
    m = metrics()
    assert m["n"] == 0
    assert m["accuracy"] is None


def test_metrics_overconfident_set(isolated):
    """5 predictions @ 0.9 confidence, only 50% correct → strong bias."""
    from agents.doctor_calibration import record, resolve, metrics
    for i in range(10):
        rid = record(f"label-{i}", 0.9)
        resolve(rid, outcome=(i < 5))
    m = metrics()
    assert m["n"] == 10
    assert m["accuracy"] == 0.5
    assert m["mean_confidence"] == pytest.approx(0.9)
    assert m["bias"] == pytest.approx(0.4)
    assert m["brier"] == pytest.approx(0.41, abs=0.05)


def test_metrics_well_calibrated(isolated):
    from agents.doctor_calibration import record, resolve, metrics
    for i in range(10):
        rid = record("x", 0.5)
        resolve(rid, outcome=(i < 5))
    m = metrics()
    assert m["accuracy"] == 0.5
    assert abs(m["bias"]) < 0.01


def test_metrics_per_bucket(isolated):
    from agents.doctor_calibration import record, resolve, metrics
    # 4 predictions @ 0.85 (3 correct), 4 predictions @ 0.25 (1 correct)
    for i in range(4):
        resolve(record("hi", 0.85), outcome=(i < 3))
    for i in range(4):
        resolve(record("lo", 0.25), outcome=(i < 1))
    m = metrics()
    bucket_ranges = {b["range"] for b in m["buckets"]}
    assert "[0.8,1.0)" in bucket_ranges
    assert "[0.2,0.4)" in bucket_ranges


def test_metrics_filters_by_domain(isolated):
    from agents.doctor_calibration import record, resolve, metrics
    resolve(record("dx-x", 0.8, domain="diagnosis"), outcome=True)
    resolve(record("rx-x", 0.4, domain="treatment"), outcome=False)
    m_dx = metrics(domain="diagnosis")
    assert m_dx["n"] == 1
    assert m_dx["accuracy"] == 1.0


# ── summary string ──────────────────────────────────────────────


def test_summary_calm_when_empty(isolated):
    from agents.doctor_calibration import summary
    s = summary()
    assert "no resolved" in s


def test_summary_renders_metrics(isolated):
    from agents.doctor_calibration import record, resolve, summary
    for i in range(10):
        resolve(record("x", 0.9), outcome=(i < 5))
    s = summary()
    assert "Calibration" in s
    assert "n=10" in s
    assert "overconfident" in s


def test_summary_well_calibrated_marker(isolated):
    from agents.doctor_calibration import record, resolve, summary
    for i in range(10):
        resolve(record("x", 0.5), outcome=(i < 5))
    s = summary()
    assert "well-calibrated" in s


# ── window filter ───────────────────────────────────────────────


def test_window_filter_excludes_old_resolutions(isolated):
    from agents.doctor_calibration import record, resolve, all_resolved, _connect
    rid = record("X", 0.5)
    resolve(rid, outcome=True)
    # Backdate the prediction by 60 days.
    with _connect() as conn:
        old_ts = (dt.date.today() - dt.timedelta(days=60)).isoformat()
        conn.execute("UPDATE predictions SET ts=? WHERE id=?",
                     (old_ts + "T00:00:00", rid))
    assert all_resolved(window_days=30) == []
    assert len(all_resolved(window_days=120)) == 1
