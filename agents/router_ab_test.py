"""agents/router_ab_test.py — A/B testing для smart_routing решений.

Каждое route-решение (smart_routing.route()) дублируется записью в
~/.claude/router_ab.db. Пользователь может позже разметить trial как
'good'/'bad' через CLI, и мы получим аналитику по каждому tier.

Auto-attaches к smart_routing.route() при импорте модуля.

CLI:
    aim-router-ab list                     # последние 50 trials
    aim-router-ab feedback <id> good|bad   # пометить trial
    aim-router-ab stats                    # by-tier hit rate
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("aim.router_ab")

DB_PATH = Path("~/.claude/router_ab.db").expanduser()
_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, task_preview TEXT,
            tier_assigned TEXT, model_assigned TEXT,
            tier_actual TEXT, model_actual TEXT,
            latency_ms INTEGER, cost_usd REAL,
            user_feedback TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_ts ON trials(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_tier ON trials(tier_assigned)")
    return conn


def log_trial(task: str, tier_assigned: str, model_assigned: str,
              tier_actual: str = "", model_actual: str = "",
              latency_ms: int = 0, cost_usd: float = 0.0) -> int:
    with _LOCK:
        c = _db()
        cur = c.execute(
            "INSERT INTO trials (ts, task_preview, tier_assigned, model_assigned, "
            "tier_actual, model_actual, latency_ms, cost_usd) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"),
             (task or "")[:120], tier_assigned, model_assigned,
             tier_actual or tier_assigned,
             model_actual or model_assigned,
             latency_ms, round(cost_usd, 6)),
        )
        return cur.lastrowid


def feedback(trial_id: int, value: str) -> bool:
    if value not in ("good", "bad", "neutral"):
        return False
    with _LOCK:
        cur = _db().execute(
            "UPDATE trials SET user_feedback=? WHERE id=?",
            (value, trial_id),
        )
    return cur.rowcount > 0


def list_recent(limit: int = 50) -> list[dict]:
    with _LOCK:
        rows = _db().execute(
            "SELECT id, ts, tier_assigned, model_assigned, latency_ms, cost_usd, user_feedback, task_preview "
            "FROM trials ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    cols = ("id", "ts", "tier", "model", "latency_ms", "cost_usd", "feedback", "task")
    return [dict(zip(cols, r)) for r in rows]


def stats() -> dict:
    with _LOCK:
        c = _db()
        total = c.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        with_fb = c.execute(
            "SELECT COUNT(*) FROM trials WHERE user_feedback IS NOT NULL"
        ).fetchone()[0]
        by_tier = {}
        for row in c.execute("""
            SELECT tier_assigned,
                   COUNT(*) as n,
                   AVG(latency_ms) as lat,
                   AVG(cost_usd) as cost,
                   SUM(CASE WHEN user_feedback='good' THEN 1 ELSE 0 END) as good,
                   SUM(CASE WHEN user_feedback='bad'  THEN 1 ELSE 0 END) as bad
            FROM trials GROUP BY tier_assigned
        """).fetchall():
            tier, n, lat, cost, good, bad = row
            rated = (good or 0) + (bad or 0)
            by_tier[tier] = {
                "trials":         n,
                "avg_latency_ms": round(lat or 0, 1),
                "avg_cost_usd":   round(cost or 0, 6),
                "good":           good or 0,
                "bad":            bad  or 0,
                "good_rate":      round((good or 0) / rated, 3) if rated else None,
            }
    return {"total": total, "rated": with_fb, "by_tier": by_tier}


# ── auto-attach to smart_routing ────────────────────────────────────────────


def _patch_smart_routing() -> None:
    """Wrap smart_routing.route() so every call also logs to router_ab.db."""
    try:
        import agents.smart_routing as sr
    except Exception:
        return
    if getattr(sr, "_ab_patched", False):
        return
    original = sr.route

    def wrapped(prompt: str, force_model=None, assume_output: int = 500):
        info = original(prompt, force_model=force_model, assume_output=assume_output)
        try:
            log_trial(prompt, info.get("tier", "?"), info.get("model", "?"),
                      cost_usd=info.get("est_cost", 0.0))
        except Exception:
            pass
        return info
    sr.route = wrapped
    sr._ab_patched = True
    log.info("router_ab attached to smart_routing.route()")


_patch_smart_routing()


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-router-ab")
    sub = p.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("--limit", type=int, default=50)
    fb = sub.add_parser("feedback")
    fb.add_argument("trial_id", type=int)
    fb.add_argument("value", choices=["good", "bad", "neutral"])
    sub.add_parser("stats")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "list":
        for r in list_recent(args.limit):
            mark = {"good": "✓", "bad": "✗", "neutral": "·", None: " "}.get(r["feedback"], " ")
            print(f"  {r['id']:>4}  {mark}  {r['tier']:<10}  {r['cost_usd']:.5f}  {r['task'][:60]}")
    elif args.cmd == "feedback":
        ok = feedback(args.trial_id, args.value)
        print("ok" if ok else "not found")
    elif args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
