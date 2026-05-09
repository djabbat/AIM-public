"""agents/cost_ledger.py — budget alerts on top of cost_monitor (L1, 2026-05-03).

`agents/cost_monitor.py` already records every LLM call into SQLite and
exposes `daily_cost`, `monthly_cost`, `stats`. L1 adds:

  * `weekly_cost(date)`               — last 7 days
  * `breakdown(window)`               — per-provider $ for window
  * `check_budgets(today=None)`       — fire alerts when daily/weekly/monthly
                                         budget thresholds are crossed
  * audit log compatible with notify.py + the weekly digest

Budgets read from env (or .aim_env):
    AIM_BUDGET_DAILY_USD     (default 5.0)
    AIM_BUDGET_WEEKLY_USD    (default 25.0)
    AIM_BUDGET_MONTHLY_USD   (default 80.0)

Each budget has a soft threshold at 80% (warn) and a hard threshold at
100% (alert). Crossing fires through `agents.notify` once per day.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.cost_ledger")


# ── budget config ────────────────────────────────────────────────


def _budget(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, default))
    except ValueError:
        return default


def daily_budget() -> float:
    return _budget("AIM_BUDGET_DAILY_USD", 5.0)


def weekly_budget() -> float:
    return _budget("AIM_BUDGET_WEEKLY_USD", 25.0)


def monthly_budget() -> float:
    return _budget("AIM_BUDGET_MONTHLY_USD", 80.0)


# ── DB access (re-uses cost_monitor's DB) ────────────────────────


def _db_path() -> Path:
    """Resolve the SQLite path the cost_monitor wrote into."""
    try:
        from agents.cost_monitor import _db
        conn = _db()
        path = conn.execute("PRAGMA database_list").fetchone()[2]
        conn.close()
        return Path(path)
    except Exception as e:
        log.debug("cost_monitor _db unavailable: %s", e)
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    return Path(base).expanduser() / "cost.db"


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


# ── window aggregations ──────────────────────────────────────────


def _sum_cost(start: dt.date, end: dt.date) -> float:
    """Total $ across [start, end] inclusive. Returns 0 if table absent."""
    try:
        conn = _connect()
        cur = conn.execute("""
            SELECT COALESCE(SUM(cost_usd), 0.0) AS total
            FROM calls
            WHERE date(ts) BETWEEN date(?) AND date(?)
        """, (start.isoformat(), end.isoformat()))
        row = cur.fetchone()
        conn.close()
        return float(row["total"]) if row else 0.0
    except sqlite3.OperationalError as e:
        log.debug("cost table missing: %s", e)
        return 0.0


def daily_cost(today: Optional[dt.date] = None) -> float:
    today = today or dt.date.today()
    return _sum_cost(today, today)


def weekly_cost(today: Optional[dt.date] = None) -> float:
    today = today or dt.date.today()
    return _sum_cost(today - dt.timedelta(days=7), today)


def monthly_cost(today: Optional[dt.date] = None) -> float:
    today = today or dt.date.today()
    return _sum_cost(today - dt.timedelta(days=30), today)


def breakdown(window: str = "weekly",
              today: Optional[dt.date] = None) -> list[tuple[str, float]]:
    """Per-provider $ breakdown for the given window."""
    today = today or dt.date.today()
    if window == "daily":
        start = today
    elif window == "weekly":
        start = today - dt.timedelta(days=7)
    elif window == "monthly":
        start = today - dt.timedelta(days=30)
    else:
        raise ValueError(f"unknown window {window!r}")
    try:
        conn = _connect()
        rows = conn.execute("""
            SELECT provider, COALESCE(SUM(cost_usd), 0.0) AS total
            FROM calls
            WHERE date(ts) BETWEEN date(?) AND date(?)
            GROUP BY provider
            ORDER BY total DESC, provider ASC
        """, (start.isoformat(), today.isoformat())).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []
    return [(r["provider"] or "unknown", float(r["total"])) for r in rows]


# ── budget alerts ────────────────────────────────────────────────


@dataclasses.dataclass
class BudgetCheck:
    window: str         # daily | weekly | monthly
    spent: float
    budget: float
    pct: float          # spent / budget
    severity: str       # ok | warn | breach

    def message(self) -> str:
        return (f"{self.window.title()} cost ${self.spent:.2f} / "
                f"${self.budget:.2f} budget ({self.pct:.0%}) — {self.severity}")


def check_budgets(today: Optional[dt.date] = None) -> list[BudgetCheck]:
    today = today or dt.date.today()
    out: list[BudgetCheck] = []
    for window, spent_fn, budget_fn in (
        ("daily",   daily_cost,   daily_budget),
        ("weekly",  weekly_cost,  weekly_budget),
        ("monthly", monthly_cost, monthly_budget),
    ):
        spent = spent_fn(today)
        budget = budget_fn()
        if budget <= 0:
            continue
        pct = spent / budget
        if pct >= 1.0:
            sev = "breach"
        elif pct >= 0.80:
            sev = "warn"
        else:
            sev = "ok"
        out.append(BudgetCheck(window=window, spent=spent, budget=budget,
                                pct=pct, severity=sev))
    return out


def alert_breaches(today: Optional[dt.date] = None,
                    *, dispatch=None) -> list[BudgetCheck]:
    """Run the budget check and route warn/breach to notify.py.

    `dispatch` is an optional override (`callable(BudgetCheck)`) for tests.
    """
    checks = check_budgets(today=today)
    interesting = [c for c in checks if c.severity in ("warn", "breach")]
    if not interesting:
        return checks

    if dispatch is None:
        try:
            from agents.notify import notify
        except ImportError:
            return checks

        def dispatch(c: BudgetCheck) -> None:  # type: ignore
            notify(c.message(),
                   channels=("telegram", "stdout"),
                   subject=f"💸 budget {c.severity}",
                   level="warn" if c.severity == "warn" else "high",
                   source="cost_ledger",
                   dedup_key=f"budget:{c.window}:{c.severity}",
                   dedup_window_minutes=24 * 60)

    for c in interesting:
        try:
            dispatch(c)
        except Exception as e:  # noqa: BLE001
            log.warning("budget dispatch failed: %s", e)
    return checks


# ── digest helper ────────────────────────────────────────────────


def summary(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    checks = check_budgets(today=today)
    if not checks:
        return "(no LLM cost data yet)"
    parts = ["💸 Cost ledger:"]
    for c in checks:
        marker = ("⛔" if c.severity == "breach"
                   else "⚠️" if c.severity == "warn"
                   else "✅")
        parts.append(f"  {marker} {c.message()}")
    bk = breakdown("weekly", today=today)
    if bk:
        parts.append("  by provider (last 7d):")
        for prov, total in bk[:5]:
            parts.append(f"    • {prov}: ${total:.3f}")
    return "\n".join(parts)


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Cost ledger / budget alerts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary")
    g = sub.add_parser("breakdown")
    g.add_argument("window", nargs="?", default="weekly",
                    choices=("daily", "weekly", "monthly"))
    sub.add_parser("alert", help="run budget check + notify on breach")
    args = ap.parse_args()
    if args.cmd == "summary":
        print(summary())
    elif args.cmd == "breakdown":
        for prov, total in breakdown(args.window):
            print(f"{prov:30s}  ${total:.3f}")
    elif args.cmd == "alert":
        for c in alert_breaches():
            print(c.message())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
