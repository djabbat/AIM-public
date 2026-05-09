"""AI/ai/diagnostic_ledger.py — DG1 (2026-05-03).

Tiny SQLite ledger of every self-diagnostic run.

Why: with the auto-retry on `run_self_diagnostic.run()`, we want to
know whether the corrective suffix is actually pulling compliance up
over time, AND whether prompt-tightening (e.g. the SELF_DIAGNOSTIC_PROMPT
update on 2026-05-03) is moving the average grade.

One row per saved report; no PII (only metric counts + grade).
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ai.diagnostic_ledger")

_LOCK = threading.RLock()


def db_path() -> Path:
    env = os.environ.get("AI_DIAGNOSTIC_DB")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "aim" / "diagnostic_ledger.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            ts          TEXT NOT NULL,
            model       TEXT NOT NULL,
            grade       TEXT,
            n_refs      INTEGER NOT NULL,
            n_with_line INTEGER NOT NULL,
            compliance  REAL NOT NULL,
            crit        INTEGER,
            high        INTEGER,
            med         INTEGER,
            low         INTEGER,
            retry_used  INTEGER NOT NULL DEFAULT 0,
            report_path TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts)")
    return conn


@dataclasses.dataclass
class Row:
    ts: str
    model: str
    grade: Optional[str]
    n_refs: int
    n_with_line: int
    compliance: float
    crit: Optional[int]
    high: Optional[int]
    med: Optional[int]
    low: Optional[int]
    retry_used: bool
    report_path: Optional[str]


def record(*,
           model: str,
           grade: Optional[str],
           n_refs: int,
           n_with_line: int,
           crit: Optional[int] = None,
           high: Optional[int] = None,
           med: Optional[int] = None,
           low: Optional[int] = None,
           retry_used: bool = False,
           report_path: Optional[str] = None,
           ts: Optional[str] = None) -> None:
    """Append a new row. Compliance is computed from n_refs + n_with_line."""
    if n_refs < 0 or n_with_line < 0:
        raise ValueError("counts must be non-negative")
    if n_with_line > n_refs:
        raise ValueError("n_with_line cannot exceed n_refs")
    compliance = (n_with_line / n_refs) if n_refs else 0.0
    ts = ts or dt.datetime.now().isoformat()
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO runs(ts, model, grade, n_refs, n_with_line, "
            "compliance, crit, high, med, low, retry_used, report_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, model, grade, n_refs, n_with_line, compliance,
             crit, high, med, low, int(retry_used), report_path),
        )


def record_from_report(report: str, *,
                        model: str,
                        retry_used: bool = False,
                        report_path: Optional[str] = None,
                        ts: Optional[str] = None) -> None:
    """Convenience: parse a report string and record the metrics."""
    from AI.ai.meta_evaluator import parse_report
    p = parse_report(report)
    n_refs = len(p.findings)
    n_with_line = sum(1 for r in p.findings
                       if ":" in r and r.rsplit(":", 1)[-1].isdigit())
    record(
        model=model,
        grade=p.grade,
        n_refs=n_refs,
        n_with_line=n_with_line,
        crit=p.totals.get("crit"),
        high=p.totals.get("high"),
        med=p.totals.get("med"),
        low=p.totals.get("low"),
        retry_used=retry_used,
        report_path=report_path,
        ts=ts,
    )


def all_rows() -> list[Row]:
    with _LOCK, contextlib.closing(_connect()) as conn:
        cur = conn.execute(
            "SELECT ts, model, grade, n_refs, n_with_line, compliance, "
            "crit, high, med, low, retry_used, report_path "
            "FROM runs ORDER BY ts ASC"
        )
        return [
            Row(ts=r[0], model=r[1], grade=r[2], n_refs=r[3],
                n_with_line=r[4], compliance=r[5],
                crit=r[6], high=r[7], med=r[8], low=r[9],
                retry_used=bool(r[10]), report_path=r[11])
            for r in cur.fetchall()
        ]


def prune_phantom(*, dry_run: bool = True) -> dict:
    """Remove rows whose `report_path` was set but the file no longer
    exists — almost certainly test fixtures whose tmp_path got cleaned
    up. Returns counts (kept, removed). Safe by default (dry_run=True)."""
    rows = all_rows()
    phantom_ts: list[str] = []
    real_ts: list[str] = []
    for r in rows:
        if r.report_path:
            from pathlib import Path
            if not Path(r.report_path).exists():
                phantom_ts.append(r.ts)
            else:
                real_ts.append(r.ts)
        else:
            real_ts.append(r.ts)   # rows without report_path stay
    if dry_run or not phantom_ts:
        return {
            "removed": 0 if dry_run else 0,
            "would_remove": len(phantom_ts),
            "kept": len(real_ts),
            "dry_run": dry_run,
        }
    with _LOCK, contextlib.closing(_connect()) as conn:
        # Batch delete by ts (in chunks to keep SQL parameter limit safe).
        for i in range(0, len(phantom_ts), 500):
            batch = phantom_ts[i:i + 500]
            placeholders = ",".join("?" * len(batch))
            conn.execute(
                f"DELETE FROM runs WHERE ts IN ({placeholders})",
                batch,
            )
    return {
        "removed": len(phantom_ts),
        "would_remove": 0,
        "kept": len(real_ts),
        "dry_run": False,
    }


def recent(n: int = 10) -> list[Row]:
    rows = all_rows()
    return rows[-n:]


def trend() -> dict:
    """Return aggregate trend stats across all runs."""
    rows = all_rows()
    if not rows:
        return {"n_runs": 0}
    n = len(rows)
    avg_comp = sum(r.compliance for r in rows) / n
    avg_crit = (sum(r.crit for r in rows if r.crit is not None)
                / max(1, sum(1 for r in rows if r.crit is not None)))
    grades = [r.grade for r in rows if r.grade]
    grade_dist = {g: grades.count(g) for g in sorted(set(grades))}
    retry_share = sum(1 for r in rows if r.retry_used) / n
    return {
        "n_runs": n,
        "avg_compliance": avg_comp,
        "avg_crit": avg_crit,
        "grade_dist": grade_dist,
        "retry_share": retry_share,
        "first_ts": rows[0].ts,
        "last_ts": rows[-1].ts,
    }


def summary() -> str:
    t = trend()
    if t["n_runs"] == 0:
        return "(no diagnostic runs recorded)"
    parts = [
        f"📈 Diagnostic ledger — {t['n_runs']} runs "
        f"(first {t['first_ts'][:10]} → last {t['last_ts'][:10]})",
        f"  avg compliance:  {t['avg_compliance']:.0%}",
        f"  avg crit count:  {t['avg_crit']:.1f}",
        f"  grade dist:      {t['grade_dist']}",
        f"  retry share:     {t['retry_share']:.0%}",
    ]
    if t["avg_compliance"] < 0.6:
        parts.append("  ⚠ avg compliance under 60% — consider tightening "
                      "prompt or switching model.")
    return "\n".join(parts)
