"""agents/cost_monitor.py — token-cost tracking with daily/monthly caps + alerts.

Auto-records every successful llm.ask call (wired in llm._record_token_usage).
Persists to ~/.claude/cost_monitor.db (SQLite); raises alert when daily or
monthly cap is exceeded; alerts go to:
    • stderr (always)
    • Telegram if AIM_TELEGRAM_CHAT_ID + bot token configured
    • Webhook if AIM_ALERT_WEBHOOK is set

Limits via env (defaults shown):
    AIM_COST_LIMIT_DAILY=5.0          # USD
    AIM_COST_LIMIT_MONTHLY=50.0       # USD
    AIM_COST_HARD_STOP=0              # 1 = raise CostLimitExceeded once exceeded

CLI:
    aim-cost stats
    aim-cost alerts                    # unacknowledged
    aim-cost ack <id>
    aim-cost reset                     # truncate all rows
    aim-cost limits set --daily 10 --monthly 100
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.cost")

DB_PATH = Path("~/.claude/cost_monitor.db").expanduser()

# DeepSeek pricing as of 2026-Q1, USD per 1M tokens.
# Override per-deploy via AIM_COST_PRICES JSON env.
PRICES: dict[str, dict[str, float]] = {
    "deepseek-chat":     {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},   # R1 pricing
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant":    {"input": 0.05, "output": 0.08},
    "mixtral-8x7b-32768":      {"input": 0.24, "output": 0.24},
}
try:
    PRICES.update(json.loads(os.getenv("AIM_COST_PRICES", "{}")))
except Exception:
    pass

DAILY_LIMIT   = float(os.getenv("AIM_COST_LIMIT_DAILY",   "5.0"))
MONTHLY_LIMIT = float(os.getenv("AIM_COST_LIMIT_MONTHLY", "50.0"))
HARD_STOP     = os.getenv("AIM_COST_HARD_STOP", "").lower() in ("1", "true", "yes")


class CostLimitExceeded(RuntimeError):
    pass


_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, model TEXT, provider TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            input_cost REAL, output_cost REAL, total_cost REAL,
            task_id TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_costs_ts ON costs(ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, kind TEXT, message TEXT, acknowledged INTEGER DEFAULT 0
        )
    """)
    return conn


# ── price lookup ────────────────────────────────────────────────────────────


def _price_for(model: str) -> dict[str, float]:
    if model in PRICES:
        return PRICES[model]
    # Fuzzy: strip provider prefix / suffix
    for k, v in PRICES.items():
        if k in model or model in k:
            return v
    return {"input": 1.0, "output": 2.0}   # generic fallback


# ── core API ───────────────────────────────────────────────────────────────


def record(model: str, input_tokens: int, output_tokens: int,
           provider: str = "", task_id: Optional[str] = None) -> dict:
    """Record one call. Auto-fires alerts/hard-stop on cap exceedance."""
    p = _price_for(model)
    icost = input_tokens  * p["input"]  / 1_000_000
    ocost = output_tokens * p["output"] / 1_000_000
    total = icost + ocost
    ts = datetime.now().isoformat(timespec="seconds")

    with _LOCK:
        c = _db()
        c.execute(
            "INSERT INTO costs (ts,model,provider,input_tokens,output_tokens,"
            "input_cost,output_cost,total_cost,task_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, model, provider, input_tokens, output_tokens,
             round(icost, 6), round(ocost, 6), round(total, 6), task_id),
        )

    daily = daily_cost()
    monthly = monthly_cost()
    if daily > DAILY_LIMIT:
        _alert("DAILY_CAP", f"daily ${daily:.2f} > limit ${DAILY_LIMIT:.2f}")
        if HARD_STOP:
            raise CostLimitExceeded(f"daily cap exceeded: ${daily:.2f}")
    if monthly > MONTHLY_LIMIT:
        _alert("MONTHLY_CAP", f"monthly ${monthly:.2f} > limit ${MONTHLY_LIMIT:.2f}")
        if HARD_STOP:
            raise CostLimitExceeded(f"monthly cap exceeded: ${monthly:.2f}")

    return {"input_cost": icost, "output_cost": ocost, "total_cost": total,
            "daily": daily, "monthly": monthly}


def daily_cost(date: Optional[datetime] = None) -> float:
    date = date or datetime.now()
    prefix = date.strftime("%Y-%m-%d")
    with _LOCK:
        cur = _db().execute(
            "SELECT COALESCE(SUM(total_cost),0) FROM costs WHERE ts LIKE ?",
            (prefix + "%",),
        )
        return float(cur.fetchone()[0])


def monthly_cost(date: Optional[datetime] = None) -> float:
    date = date or datetime.now()
    prefix = date.strftime("%Y-%m")
    with _LOCK:
        cur = _db().execute(
            "SELECT COALESCE(SUM(total_cost),0) FROM costs WHERE ts LIKE ?",
            (prefix + "%",),
        )
        return float(cur.fetchone()[0])


def stats() -> dict:
    with _LOCK:
        c = _db()
        total_calls, total_cost, in_tok, out_tok = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_cost),0), "
            "COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM costs"
        ).fetchone()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        by_model = {
            r[0]: round(r[1], 4)
            for r in c.execute(
                "SELECT model, SUM(total_cost) FROM costs WHERE ts >= ? "
                "GROUP BY model ORDER BY 2 DESC", (week_ago,)
            ).fetchall()
        }
    d = daily_cost()
    m = monthly_cost()
    return {
        "daily_cost":          round(d, 4),
        "monthly_cost":        round(m, 4),
        "total_calls":         total_calls,
        "total_cost":          round(total_cost, 4),
        "total_input_tokens":  int(in_tok),
        "total_output_tokens": int(out_tok),
        "cost_by_model_7d":    by_model,
        "daily_limit":         DAILY_LIMIT,
        "monthly_limit":       MONTHLY_LIMIT,
        "remaining_daily":     round(max(0.0, DAILY_LIMIT - d), 4),
        "remaining_monthly":   round(max(0.0, MONTHLY_LIMIT - m), 4),
        "hard_stop":           HARD_STOP,
    }


# ── alerts ─────────────────────────────────────────────────────────────────


def _alert(kind: str, message: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        _db().execute(
            "INSERT INTO alerts (ts,kind,message) VALUES (?,?,?)",
            (ts, kind, message),
        )
    print(f"⚠️  COST ALERT [{kind}] {message}", file=sys.stderr)
    _notify_external(kind, message)


def _notify_external(kind: str, message: str) -> None:
    # Webhook
    url = os.getenv("AIM_ALERT_WEBHOOK")
    if url:
        try:
            import httpx
            with httpx.Client(timeout=5) as cl:
                cl.post(url, json={"kind": kind, "message": message,
                                   "ts": datetime.now().isoformat(timespec="seconds")})
        except Exception as e:
            log.debug(f"webhook alert failed: {e}")
    # Telegram (best-effort, only if token + chat present)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("AIM_TG_BOT_TOKEN")
    chat  = os.getenv("AIM_TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            import httpx
            with httpx.Client(timeout=5) as cl:
                cl.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat, "text": f"⚠️ {kind}\n{message}"})
        except Exception as e:
            log.debug(f"telegram alert failed: {e}")


def alerts(limit: int = 50, only_unacked: bool = True) -> list[dict]:
    with _LOCK:
        sql = "SELECT id,ts,kind,message,acknowledged FROM alerts"
        if only_unacked:
            sql += " WHERE acknowledged=0"
        sql += " ORDER BY ts DESC LIMIT ?"
        rows = _db().execute(sql, (limit,)).fetchall()
    return [dict(zip(["id","ts","kind","message","acknowledged"], r)) for r in rows]


def acknowledge(alert_id: int) -> bool:
    with _LOCK:
        cur = _db().execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
    return cur.rowcount > 0


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-cost")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    a = sub.add_parser("alerts");  a.add_argument("--all", action="store_true")
    ack = sub.add_parser("ack");   ack.add_argument("alert_id", type=int)
    sub.add_parser("reset")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "alerts":
        for a in alerts(only_unacked=not args.all):
            print(f"  [{a['id']}] {a['ts']}  {a['kind']:<14}  {a['message']}")
    elif args.cmd == "ack":
        print("ok" if acknowledge(args.alert_id) else "not found")
    elif args.cmd == "reset":
        with _LOCK:
            _db().execute("DELETE FROM costs")
            _db().execute("DELETE FROM alerts")
        print("reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
