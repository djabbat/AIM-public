"""agents/ab_router.py — automated A/B routing tournament (S5, 2026-05-02).

The existing `agents/router_ab_test.py` provides per-call A/B random
assignment. This module sits one layer above it: schedule a tournament,
run two strategies on the eval harness, and promote the winner if its
score advantage is statistically meaningful (Welch t-test p < 0.05) and
not destroyed by cost.

Workflow:
  1. `start_round(challenger, baseline, evals=...)` — register a round.
  2. Round runs ≥30 cases per strategy (default = full eval suite × 3
     repeats for stability).
  3. After each round, `decide(round_id)` compares scores + costs and
     either promotes the challenger as the new baseline or keeps the
     baseline.
  4. Audit log: every decision goes into `~/.cache/aim/ab_router.jsonl`
     so we can rewind: "what router were we running on 2026-05-15?".

State persistence: SQLite at $AIM_HOME/ab_router.db.

Public API:
    register_strategy(name, callable_path)
    start_round(challenger, baseline=None, repeats=3, tag=None) -> round_id
    record_run(round_id, strategy, eval_run)
    decide(round_id) -> dict   # {winner, p_value, delta, verdict, ...}
    current_baseline() -> Optional[str]
    history(limit=20) -> list[dict]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import math
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.ab_router")

_LOCK = threading.RLock()


def db_path() -> Path:
    env = os.environ.get("AIM_AB_ROUTER_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    return Path(base).expanduser() / "ab_router.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            challenger TEXT NOT NULL,
            baseline TEXT,
            repeats INTEGER NOT NULL DEFAULT 3,
            tag TEXT,
            status TEXT NOT NULL DEFAULT 'running'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS round_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            strategy TEXT NOT NULL,
            score REAL NOT NULL,
            cost_usd REAL NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            n_cases INTEGER NOT NULL,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            decided_at TEXT NOT NULL,
            winner TEXT NOT NULL,
            verdict TEXT NOT NULL,
            p_value REAL,
            delta REAL NOT NULL,
            cost_delta REAL NOT NULL DEFAULT 0,
            note TEXT
        )
    """)
    return conn


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ── core flow ────────────────────────────────────────────────────


def start_round(challenger: str, baseline: Optional[str] = None,
                repeats: int = 3, tag: Optional[str] = None) -> int:
    if not challenger:
        raise ValueError("start_round: challenger is required")
    with _LOCK, _connect() as conn:
        cur = conn.execute("""
            INSERT INTO rounds(started_at, challenger, baseline, repeats, tag)
            VALUES (?, ?, ?, ?, ?)
        """, (_now(), challenger, baseline, repeats, tag))
        return cur.lastrowid


def record_run(round_id: int, strategy: str, score: float,
               cost_usd: float = 0.0, latency_ms: int = 0,
               n_cases: int = 0) -> int:
    with _LOCK, _connect() as conn:
        cur = conn.execute("""
            INSERT INTO round_runs(round_id, strategy, score, cost_usd,
                                    latency_ms, n_cases, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (round_id, strategy, score, cost_usd, latency_ms, n_cases, _now()))
        return cur.lastrowid


def _runs_for(round_id: int, strategy: str) -> list[dict]:
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT score, cost_usd, latency_ms, n_cases
            FROM round_runs
            WHERE round_id=? AND strategy=?
            ORDER BY id
        """, (round_id, strategy)).fetchall()
    return [dict(r) for r in rs]


def _round(round_id: int) -> dict:
    with _LOCK, _connect() as conn:
        r = conn.execute("SELECT * FROM rounds WHERE id=?",
                         (round_id,)).fetchone()
    if r is None:
        raise ValueError(f"unknown round {round_id}")
    return dict(r)


# ── statistics ───────────────────────────────────────────────────


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs: list[float], mean: float) -> float:
    if len(xs) < 2:
        return 0.0
    return sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)


def welch_t_p(a: list[float], b: list[float]) -> Optional[float]:
    """Two-tailed Welch t-test p-value. None when not enough data.

    Uses the survival function of a Student-t with Welch–Satterthwaite df.
    Falls back to a normal approximation when scipy is not installed."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = _mean(a), _mean(b)
    va, vb = _var(a, ma), _var(b, mb)
    if va == 0 and vb == 0:
        return 0.0 if ma != mb else 1.0
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return 1.0
    t = (mb - ma) / se
    # Welch–Satterthwaite degrees of freedom.
    num = (va / len(a) + vb / len(b)) ** 2
    denom = ((va / len(a)) ** 2 / (len(a) - 1)
             + (vb / len(b)) ** 2 / (len(b) - 1))
    df = num / denom if denom else 1.0
    try:
        from scipy import stats  # type: ignore
        return float(2.0 * stats.t.sf(abs(t), df))
    except ImportError:
        # Normal approximation: erfc(|t|/√2). Reasonable when df ≥ 30.
        return math.erfc(abs(t) / math.sqrt(2))


# ── decision ─────────────────────────────────────────────────────


def decide(round_id: int, *,
           min_p: float = 0.05,
           min_delta: float = 0.01,
           cost_tolerance: float = 0.20) -> dict:
    """Compare baseline vs challenger and emit a verdict.

    verdict ∈ {promote_challenger, keep_baseline, neutral, insufficient}.
    Promotion requires:
      * challenger.mean - baseline.mean ≥ min_delta
      * p-value ≤ min_p
      * cost increase ≤ cost_tolerance × baseline_cost  (if baseline cost > 0)

    A `keep_baseline` verdict means the challenger lost (worse score).
    `neutral` means we can't tell statistically.
    `insufficient` means we lack runs.
    """
    rd = _round(round_id)
    challenger_runs = _runs_for(round_id, rd["challenger"])
    baseline_runs = (_runs_for(round_id, rd["baseline"])
                     if rd["baseline"] else [])
    if len(challenger_runs) < 2 or len(baseline_runs) < 2:
        return {"verdict": "insufficient", "winner": rd["baseline"] or rd["challenger"],
                "p_value": None, "delta": 0.0, "cost_delta": 0.0,
                "note": "need ≥2 runs per strategy"}

    cs = [r["score"] for r in challenger_runs]
    bs = [r["score"] for r in baseline_runs]
    mc, mb = _mean(cs), _mean(bs)
    delta = mc - mb
    p = welch_t_p(bs, cs)

    cost_c = _mean([r["cost_usd"] for r in challenger_runs])
    cost_b = _mean([r["cost_usd"] for r in baseline_runs])
    cost_delta = cost_c - cost_b
    cost_ok = (cost_b == 0) or (cost_delta <= cost_tolerance * cost_b)

    if delta >= min_delta and p is not None and p <= min_p and cost_ok:
        verdict = "promote_challenger"
        winner = rd["challenger"]
        note = f"Δ={delta:.3f} p={p:.3f} cost_Δ=${cost_delta:.4f} OK"
    elif delta < -min_delta and p is not None and p <= min_p:
        verdict = "keep_baseline"
        winner = rd["baseline"]
        note = f"challenger worse Δ={delta:.3f} p={p:.3f}"
    elif p is None or p > min_p:
        verdict = "neutral"
        winner = rd["baseline"]
        note = (f"Δ={delta:.3f} p="
                + (f"{p:.3f}" if p is not None else "n/a"))
    else:
        verdict = "keep_baseline"
        winner = rd["baseline"]
        note = f"cost guard: Δ${cost_delta:.4f} > tolerance"

    record = {
        "round_id": round_id, "decided_at": _now(),
        "winner": winner, "verdict": verdict,
        "p_value": p, "delta": delta, "cost_delta": cost_delta,
        "note": note,
    }
    with _LOCK, _connect() as conn:
        conn.execute("""
            INSERT INTO decisions(round_id, decided_at, winner, verdict,
                                   p_value, delta, cost_delta, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (round_id, record["decided_at"], winner, verdict,
              p, delta, cost_delta, record["note"]))
        conn.execute("UPDATE rounds SET status='decided' WHERE id=?",
                     (round_id,))
    return record


# ── queries ──────────────────────────────────────────────────────


def current_baseline() -> Optional[str]:
    with _LOCK, _connect() as conn:
        r = conn.execute("""
            SELECT winner FROM decisions
            WHERE verdict IN ('promote_challenger', 'keep_baseline')
            ORDER BY id DESC LIMIT 1
        """).fetchone()
    return r["winner"] if r else None


def history(limit: int = 20) -> list[dict]:
    with _LOCK, _connect() as conn:
        rs = conn.execute("""
            SELECT d.*, r.challenger, r.baseline
            FROM decisions d JOIN rounds r ON r.id = d.round_id
            ORDER BY d.id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rs]


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="A/B router tournament")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline", help="print current promoted baseline")
    g = sub.add_parser("history", help="show recent decisions")
    g.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    if args.cmd == "baseline":
        print(current_baseline() or "(none)")
    elif args.cmd == "history":
        for h in history(args.limit):
            print(json.dumps(h, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
