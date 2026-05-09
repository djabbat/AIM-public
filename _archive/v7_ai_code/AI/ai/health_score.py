"""AI/ai/health_score.py — HS1 (2026-05-04).

Single 0–100 score for "is the AIM/AI subsystem healthy?".

Aggregates across the closed loop:
  - DR2 doctor (wiring crit/warn count) — heavy weight
  - DG1 ledger trend (avg compliance + avg crit)
  - RD1 regression (current state)
  - CV1 case validity
  - PV1 prompt drift age

Score breakdown is exposed so callers can see WHY the score is what
it is. 100 = every signal perfect; 0 = catastrophic failure.

Public API:
    score() -> Score
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from typing import Optional

log = logging.getLogger("ai.health_score")


@dataclasses.dataclass
class Score:
    total: int                  # 0–100
    components: dict[str, int]  # name → contribution to total
    notes: list[str]

    @property
    def grade(self) -> str:
        if self.total >= 90:
            return "A"
        if self.total >= 75:
            return "B"
        if self.total >= 60:
            return "C"
        if self.total >= 40:
            return "D"
        return "F"


# Component weights (must sum to 100).
_W_WIRING = 30      # DR2 — broken modules block everything
_W_REGRESSION = 25  # RD1 — most recent run vs prev
_W_COMPLIANCE = 20  # DG1 — average prompt compliance
_W_CASES = 15       # CV1 — schema-clean cases
_W_PROMPT_DRIFT = 10  # PV1 — recent revisions = active iteration


def _wiring_component() -> tuple[int, list[str]]:
    notes: list[str] = []
    try:
        from AI.ai.doctor import diagnose
        probes = diagnose()
    except Exception as e:
        notes.append(f"doctor unavailable: {e}")
        return (0, notes)
    crit = sum(1 for p in probes if not p.ok and p.severity == "crit")
    warn = sum(1 for p in probes if not p.ok and p.severity == "warn")
    if crit:
        notes.append(f"{crit} critical wiring failure(s)")
        return (0, notes)
    if warn:
        notes.append(f"{warn} warning(s)")
        return (max(0, _W_WIRING - 5 * warn), notes)
    return (_W_WIRING, notes)


def _regression_component() -> tuple[int, list[str]]:
    notes: list[str] = []
    try:
        from AI.ai.regression_detector import detect
        r = detect()
    except Exception as e:
        notes.append(f"regression check failed: {e}")
        return (_W_REGRESSION // 2, notes)
    if not r.have_baseline:
        notes.append("no regression baseline yet")
        return (_W_REGRESSION // 2, notes)
    if r.regressed:
        notes.append(f"REGRESSED: {len(r.new_findings)} new finding(s)")
        return (0, notes)
    if r.improved:
        return (_W_REGRESSION, notes)
    return (_W_REGRESSION, notes)


def _compliance_component() -> tuple[int, list[str]]:
    notes: list[str] = []
    try:
        from AI.ai.diagnostic_ledger import trend
        t = trend()
    except Exception as e:
        notes.append(f"ledger unavailable: {e}")
        return (0, notes)
    if t["n_runs"] == 0:
        notes.append("no diagnostic runs yet")
        return (_W_COMPLIANCE // 2, notes)
    avg = t["avg_compliance"]
    if avg >= 0.9:
        return (_W_COMPLIANCE, notes)
    if avg >= 0.6:
        return (int(_W_COMPLIANCE * 0.7), notes)
    if avg >= 0.3:
        notes.append(f"avg compliance only {avg:.0%}")
        return (int(_W_COMPLIANCE * 0.4), notes)
    notes.append(f"avg compliance critically low ({avg:.0%})")
    return (0, notes)


def _cases_component() -> tuple[int, list[str]]:
    notes: list[str] = []
    try:
        from AI.ai.case_validator import validate_dir
        rep = validate_dir()
    except Exception as e:
        notes.append(f"case validator failed: {e}")
        return (_W_CASES // 2, notes)
    if rep.n_cases == 0:
        return (_W_CASES, notes)
    if rep.n_failed == 0:
        return (_W_CASES, notes)
    notes.append(f"{rep.n_failed} invalid eval case(s)")
    ratio = rep.n_ok / max(1, rep.n_cases)
    return (int(_W_CASES * ratio), notes)


def _prompt_drift_component() -> tuple[int, list[str]]:
    notes: list[str] = []
    try:
        from AI.ai.prompt_versions import history, fingerprint
        h = history()
        cur = fingerprint()
    except Exception as e:
        notes.append(f"prompt versions failed: {e}")
        return (0, notes)
    if not h:
        notes.append("prompt never fingerprinted")
        return (_W_PROMPT_DRIFT // 2, notes)
    last = h[-1]
    if last.sha256 != cur.sha256:
        notes.append("prompt drifted since last record")
        return (_W_PROMPT_DRIFT // 2, notes)
    if last.ts:
        try:
            age_days = (dt.datetime.now()
                        - dt.datetime.fromisoformat(last.ts)).days
            if age_days > 30:
                notes.append(f"last prompt revision {age_days}d ago "
                             "— is it still the right shape?")
                return (int(_W_PROMPT_DRIFT * 0.7), notes)
        except ValueError:
            pass
    return (_W_PROMPT_DRIFT, notes)


def score() -> Score:
    components: dict[str, int] = {}
    notes: list[str] = []
    for name, fn in (
        ("wiring", _wiring_component),
        ("regression", _regression_component),
        ("compliance", _compliance_component),
        ("cases", _cases_component),
        ("prompt_drift", _prompt_drift_component),
    ):
        try:
            pts, n = fn()
        except Exception as e:
            log.debug("component %s failed: %s", name, e)
            pts, n = (0, [f"{name}: unexpected error: {e}"])
        components[name] = pts
        notes.extend(n)
    total = sum(components.values())
    return Score(total=total, components=components, notes=notes)


# ── persistence (sidecar in diagnostic_ledger.db) ───────────────


def _connect():
    import contextlib, sqlite3
    from AI.ai.diagnostic_ledger import db_path
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_scores (
            ts          TEXT NOT NULL,
            total       INTEGER NOT NULL,
            grade       TEXT NOT NULL,
            wiring      INTEGER NOT NULL,
            regression  INTEGER NOT NULL,
            compliance  INTEGER NOT NULL,
            cases       INTEGER NOT NULL,
            prompt_drift INTEGER NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_ts ON health_scores(ts)"
    )
    return conn


def record(*, ts: Optional[str] = None) -> Score:
    """Compute a score and persist it to the ledger DB."""
    import contextlib
    s = score()
    ts = ts or dt.datetime.now().isoformat()
    with contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO health_scores"
            "(ts, total, grade, wiring, regression, compliance, "
            "cases, prompt_drift) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, s.total, s.grade,
             s.components.get("wiring", 0),
             s.components.get("regression", 0),
             s.components.get("compliance", 0),
             s.components.get("cases", 0),
             s.components.get("prompt_drift", 0)),
        )
    return s


def history(limit: int = 30) -> list[dict]:
    """Last `limit` recorded health scores, oldest first."""
    import contextlib
    with contextlib.closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT ts, total, grade, wiring, regression, compliance, "
            "cases, prompt_drift FROM health_scores "
            "ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "ts": r[0], "total": r[1], "grade": r[2],
            "wiring": r[3], "regression": r[4],
            "compliance": r[5], "cases": r[6],
            "prompt_drift": r[7],
        })
    return list(reversed(out))


def trend() -> dict:
    h = history(limit=30)
    if not h:
        return {"n": 0}
    totals = [r["total"] for r in h]
    return {
        "n": len(h),
        "first_ts": h[0]["ts"],
        "last_ts": h[-1]["ts"],
        "first_total": totals[0],
        "last_total": totals[-1],
        "delta": totals[-1] - totals[0],
        "min": min(totals),
        "max": max(totals),
    }


def info_line() -> str:
    """Single-line summary for cron logs.

    Format:
        AIM/AI: 80/100 B  wir=30 reg=25 comp=0 cases=15 pd=10
    """
    s = score()
    parts = [
        f"AIM/AI: {s.total}/100 {s.grade}",
        f"wir={s.components.get('wiring', 0)}",
        f"reg={s.components.get('regression', 0)}",
        f"comp={s.components.get('compliance', 0)}",
        f"cases={s.components.get('cases', 0)}",
        f"pd={s.components.get('prompt_drift', 0)}",
    ]
    return "  ".join(parts)


def summary() -> str:
    s = score()
    parts = [f"💯 AIM/AI health: {s.total}/100 (grade {s.grade})"]
    for name, pts in s.components.items():
        parts.append(f"  • {name:14s}: {pts:>3d}")
    if s.notes:
        parts.append("\n notes:")
        for n in s.notes:
            parts.append(f"  - {n}")
    return "\n".join(parts)
