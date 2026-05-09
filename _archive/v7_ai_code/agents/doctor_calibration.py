"""agents/doctor_calibration.py — confidence calibration tracker (D2, 2026-05-03).

Whenever the doctor agent emits a probabilistic prediction (e.g. "70%
likely STEMI"), record it. When the actual outcome lands later, score
the prediction (Brier score, log loss). Aggregate to detect:

  * overconfidence — average confidence ≫ accuracy
  * miscalibration in specific buckets (e.g. cardio > derm)
  * trend drift week over week

Schema (SQLite at $AIM_HOME/calibration.db):

    predictions(
        id INTEGER PK,
        ts TEXT NOT NULL,
        case_id TEXT,                 -- optional patient/encounter id
        domain TEXT,                  -- diagnosis | treatment | prognosis
        label TEXT NOT NULL,          -- e.g. "STEMI" or "no-MI"
        confidence REAL NOT NULL,     -- [0, 1]
        rationale TEXT,
        outcome INTEGER DEFAULT NULL, -- 1=correct, 0=wrong, NULL=pending
        outcome_at TEXT,
        outcome_source TEXT
    )

Public API:
    record(label, confidence, *, case_id=..., domain="diagnosis", rationale="")
    resolve(prediction_id, outcome: bool, source="")
    pending() -> list[Prediction]
    metrics(window_days=30) -> dict
    summary() -> str
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

log = logging.getLogger("aim.doctor_calibration")

_LOCK = threading.RLock()


def db_path() -> Path:
    env = os.environ.get("AIM_CALIBRATION_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    return Path(base).expanduser() / "calibration.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            case_id TEXT,
            domain TEXT,
            label TEXT NOT NULL,
            confidence REAL NOT NULL,
            rationale TEXT,
            outcome INTEGER DEFAULT NULL,
            outcome_at TEXT,
            outcome_source TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_ts "
                 "ON predictions(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_outcome "
                 "ON predictions(outcome)")
    return conn


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Prediction:
    id: int
    ts: str
    case_id: Optional[str]
    domain: Optional[str]
    label: str
    confidence: float
    rationale: Optional[str]
    outcome: Optional[int]
    outcome_at: Optional[str]
    outcome_source: Optional[str]


def _row(r: sqlite3.Row) -> Prediction:
    return Prediction(
        id=r["id"], ts=r["ts"], case_id=r["case_id"], domain=r["domain"],
        label=r["label"], confidence=float(r["confidence"]),
        rationale=r["rationale"], outcome=r["outcome"],
        outcome_at=r["outcome_at"], outcome_source=r["outcome_source"],
    )


# ── core ─────────────────────────────────────────────────────────


def record(label: str, confidence: float, *,
           case_id: Optional[str] = None,
           domain: str = "diagnosis",
           rationale: str = "") -> int:
    """Persist a probabilistic prediction. Returns its row id."""
    if not label:
        raise ValueError("label is required")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0,1], got {confidence}")
    ts = dt.datetime.now().replace(microsecond=0).isoformat()
    with _LOCK, _connect() as conn:
        cur = conn.execute("""
            INSERT INTO predictions(ts, case_id, domain, label,
                                     confidence, rationale)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ts, case_id, domain, label, confidence, rationale))
        return cur.lastrowid


def resolve(prediction_id: int, outcome: bool, *,
            source: str = "") -> bool:
    """Mark a prediction as correct/incorrect. Returns True if updated."""
    ts = dt.datetime.now().replace(microsecond=0).isoformat()
    with _LOCK, _connect() as conn:
        cur = conn.execute("""
            UPDATE predictions
            SET outcome=?, outcome_at=?, outcome_source=?
            WHERE id=? AND outcome IS NULL
        """, (1 if outcome else 0, ts, source, prediction_id))
        return cur.rowcount > 0


def pending(limit: int = 50) -> list[Prediction]:
    with _LOCK, _connect() as conn:
        rs = conn.execute(
            "SELECT * FROM predictions WHERE outcome IS NULL "
            "ORDER BY ts ASC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rs]


def all_resolved(window_days: int = 30) -> list[Prediction]:
    cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT * FROM predictions
            WHERE outcome IS NOT NULL AND date(ts) >= date(?)
            ORDER BY ts DESC
        """, (cutoff,)).fetchall()
    return [_row(r) for r in rs]


# ── calibration metrics ──────────────────────────────────────────


def metrics(window_days: int = 30,
            domain: Optional[str] = None) -> dict:
    """Brier score, accuracy, mean confidence, and per-bucket calibration.

    Returns:
      {
        "n":                  int,
        "accuracy":           float,
        "mean_confidence":    float,
        "brier":              float,
        "bias":               mean_confidence - accuracy,
        "buckets":            list of {range, n, accuracy, mean_conf}
      }
    """
    rows = all_resolved(window_days=window_days)
    if domain:
        rows = [p for p in rows if p.domain == domain]
    n = len(rows)
    if n == 0:
        return {"n": 0, "accuracy": None, "mean_confidence": None,
                "brier": None, "bias": None, "buckets": []}

    accuracy = sum(p.outcome for p in rows) / n
    mean_conf = sum(p.confidence for p in rows) / n
    brier = sum((p.confidence - p.outcome) ** 2 for p in rows) / n

    buckets: list[dict] = []
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        chunk = [p for p in rows if lo <= p.confidence < hi]
        if not chunk:
            continue
        buckets.append({
            "range": f"[{lo:.1f},{min(hi, 1.0):.1f})",
            "n": len(chunk),
            "accuracy": sum(p.outcome for p in chunk) / len(chunk),
            "mean_conf": sum(p.confidence for p in chunk) / len(chunk),
        })

    return {
        "n": n,
        "accuracy": accuracy,
        "mean_confidence": mean_conf,
        "brier": brier,
        "bias": mean_conf - accuracy,
        "buckets": buckets,
    }


def summary(window_days: int = 30) -> str:
    m = metrics(window_days=window_days)
    if not m["n"]:
        return "(no resolved predictions in window)"
    lines = [
        f"📊 Calibration — last {window_days}d, n={m['n']}",
        f"  accuracy        = {m['accuracy']:.3f}",
        f"  mean confidence = {m['mean_confidence']:.3f}",
        f"  Brier score     = {m['brier']:.3f}",
        f"  bias            = {m['bias']:+.3f}  "
        f"({'overconfident' if m['bias'] > 0.05 else 'underconfident' if m['bias'] < -0.05 else 'well-calibrated'})",
    ]
    if m["buckets"]:
        lines.append("  per-bucket:")
        for b in m["buckets"]:
            lines.append(f"    {b['range']:11s}  n={b['n']:3d}  "
                         f"acc={b['accuracy']:.2f}  conf={b['mean_conf']:.2f}")
    return "\n".join(lines)
