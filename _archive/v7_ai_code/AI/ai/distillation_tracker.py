"""AI/ai/distillation_tracker.py — per-tier model comparison (S9, 2026-05-03).

Run the same eval suite against 3-4 model tiers and ask:
  * On which cases has the cheaper tier caught up to the expensive one?
  * Which cases STILL need the high-tier model — i.e. the irreducible
    "premium" cost surface?

Result: a "downgrade safety" matrix. Surface in weekly digest so we
can route specific task classes to the cheapest model that still solves
them, saving cost without sacrificing accuracy.

Inputs:
  * `agents.evals.run_all` — runs cases against a callable runner
  * a list of (tier_name, runner_fn, cost_per_call) tuples — the
    caller supplies these (we don't import llm.py to keep AI/ pure)

Outputs:
  * SQLite table `tier_runs(case_id, tier, score, cost_usd, ts)` in
    `~/.cache/aim/distillation.db`
  * `compare_tiers(today)` → matrix of {(case_id, tier): score}
  * `downgrade_candidates(min_safe_score=0.85, ratio=0.95)` → list of
    cases where a cheaper tier reaches ≥ ratio of premium tier's score
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger("ai.distillation_tracker")

_LOCK = threading.RLock()


def db_path() -> Path:
    env = os.environ.get("AI_DISTILL_DB")
    if env:
        return Path(env).expanduser()
    base = (os.environ.get("AIM_HOME") or
            str(Path.home() / ".cache" / "aim"))
    return Path(base).expanduser() / "distillation.db"


def _connect() -> sqlite3.Connection:
    """Return a fresh SQLite connection. Caller MUST close it
    (use `contextlib.closing(_connect())` to be safe).

    CRIT-2 fix (2026-05-03):
      * WAL mode enables concurrent readers while a writer holds the lock.
      * UNIQUE index on (tier, case_id, ts) prevents accidental dupes
        from two near-simultaneous record() calls in the same second.
    """
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tier_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            tier TEXT NOT NULL,
            case_id TEXT NOT NULL,
            score REAL NOT NULL,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tier_runs_case "
                 "ON tier_runs(case_id, tier, ts)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_tier_runs "
                 "ON tier_runs(tier, case_id, ts)")
    return conn


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Tier:
    name: str
    runner: Callable[[str], str]
    cost_per_call: float = 0.0


@dataclasses.dataclass
class DowngradeRecommendation:
    case_id: str
    safe_tier: str
    premium_tier: str
    safe_score: float
    premium_score: float
    cost_saved_per_call: float


# ── recording ────────────────────────────────────────────────────


def record(tier: str, case_id: str, score: float, *,
           latency_ms: int = 0, cost_usd: float = 0.0) -> None:
    """Persist a (tier, case_id, score) row. Thread-safe under _LOCK.

    Uses microsecond-precision timestamps so concurrent record() calls
    within the same second don't collide on the UNIQUE index. INSERT OR
    REPLACE keeps the row idempotent if (tier, case_id, ts) repeats.
    """
    import contextlib
    ts = dt.datetime.now().isoformat()  # microsecond precision (CRIT-2)
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO tier_runs(
                ts, tier, case_id, score, latency_ms, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ts, tier, case_id, score, latency_ms, cost_usd))


def run_tier(tier: Tier, *, persist: bool = True) -> dict:
    """Execute the eval suite against one tier; record per-case scores.
    Returns aggregate stats."""
    from agents.evals import run_all
    run = run_all(tier.runner,
                  version=f"distill:{tier.name}",
                  cost_per_call=tier.cost_per_call,
                  persist_results=False)
    if persist:
        for r in run.cases:
            record(tier.name, r.case_id, r.score,
                   latency_ms=r.latency_ms,
                   cost_usd=tier.cost_per_call)
    return {
        "tier": tier.name,
        "n_cases": len(run.cases),
        "score": run.aggregate_score,
        "ran_at": run.run_at,
    }


def run_all_tiers(tiers: Iterable[Tier], *,
                  persist: bool = True) -> list[dict]:
    return [run_tier(t, persist=persist) for t in tiers]


# ── comparison ───────────────────────────────────────────────────


def latest_per_tier_per_case() -> dict[tuple[str, str], dict]:
    """Map (case_id, tier) -> {score, cost, ts} for the most recent run
    of each pair."""
    import contextlib
    with _LOCK, contextlib.closing(_connect()) as conn:
        rs = conn.execute("""
            SELECT t1.case_id, t1.tier, t1.score, t1.cost_usd, t1.ts
            FROM tier_runs t1
            WHERE t1.id = (
                SELECT MAX(id) FROM tier_runs t2
                WHERE t2.case_id = t1.case_id AND t2.tier = t1.tier
            )
        """).fetchall()
    return {(r["case_id"], r["tier"]): dict(r) for r in rs}


def compare_tiers(*, tier_order: Optional[list[str]] = None
                  ) -> dict[str, dict[str, float]]:
    """Return {case_id: {tier: score, ...}} using the latest run per pair."""
    raw = latest_per_tier_per_case()
    out: dict[str, dict[str, float]] = {}
    for (case_id, tier), info in raw.items():
        out.setdefault(case_id, {})[tier] = info["score"]
    return out


def downgrade_candidates(*,
                         premium_tier: str,
                         budget_tiers: list[str],
                         min_safe_score: float = 0.85,
                         ratio: float = 0.95,
                         ) -> list[DowngradeRecommendation]:
    """Find (case, cheaper-tier) pairs where cheaper reaches ≥ratio
    of premium's score AND is itself ≥ min_safe_score absolute.

    Caller passes a `premium_tier` (most expensive baseline) and
    `budget_tiers` ordered cheapest-first. We walk the matrix and pick
    the cheapest tier that still passes the safety threshold.
    """
    raw = latest_per_tier_per_case()
    matrix: dict[str, dict[str, dict]] = {}
    for (case_id, tier), info in raw.items():
        matrix.setdefault(case_id, {})[tier] = info

    out: list[DowngradeRecommendation] = []
    for case_id, by_tier in matrix.items():
        prem = by_tier.get(premium_tier)
        if prem is None:
            continue
        for budget_name in budget_tiers:
            row = by_tier.get(budget_name)
            if row is None:
                continue
            if (row["score"] >= min_safe_score and
                    row["score"] >= ratio * prem["score"]):
                cost_saved = max(0.0, prem["cost_usd"] - row["cost_usd"])
                out.append(DowngradeRecommendation(
                    case_id=case_id,
                    safe_tier=budget_name,
                    premium_tier=premium_tier,
                    safe_score=row["score"],
                    premium_score=prem["score"],
                    cost_saved_per_call=cost_saved,
                ))
                break  # cheapest first; stop after first match
    return out


# ── reporting ────────────────────────────────────────────────────


def summary(*, premium_tier: str = "premium",
            budget_tiers: Optional[list[str]] = None) -> str:
    matrix = compare_tiers()
    if not matrix:
        return "(no distillation runs yet)"
    tiers = sorted({t for row in matrix.values() for t in row})
    lines = [f"🧪 Distillation matrix — {len(matrix)} cases × {len(tiers)} tiers"]
    for case_id, by_tier in sorted(matrix.items()):
        cells = "  ".join(f"{t}={by_tier.get(t, 0):.2f}" for t in tiers)
        lines.append(f"  • {case_id:30s}  {cells}")
    if budget_tiers:
        recs = downgrade_candidates(premium_tier=premium_tier,
                                     budget_tiers=budget_tiers)
        if recs:
            lines.append("")
            lines.append(f"💸 downgrade-safe ({len(recs)})")
            for r in recs[:8]:
                lines.append(f"  • {r.case_id} → {r.safe_tier} "
                             f"(safe={r.safe_score:.2f}, "
                             f"prem={r.premium_score:.2f}, "
                             f"−${r.cost_saved_per_call:.4f}/call)")
    return "\n".join(lines)
