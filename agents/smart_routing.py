"""agents/smart_routing.py — smarter than llm._route(): picks the cheapest
adequate model based on prompt complexity + estimated cost.

Routing tiers:
    fast       — Groq llama-3.1-8b-instant (cheapest, ≤200 chars or <50 toks)
    standard   — DeepSeek chat (default)
    reasoning  — DeepSeek-reasoner (only when reasoning markers detected
                 OR caller explicitly forces it)

Backwards-compatible: existing llm._route() keeps working. To opt in:
    AIM_SMART_ROUTING=1

CLI:
    aim-route classify "проанализируй данные..."     # show route+cost estimate
    aim-route stats                                   # routing stats
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

log = logging.getLogger("aim.smart_routing")

ENABLED = os.getenv("AIM_SMART_ROUTING", "").lower() in ("1", "true", "yes")
DB_PATH = Path("~/.claude/smart_routing.db").expanduser()


# Pricing — keep in sync with cost_monitor.PRICES (DeepSeek V4 series, 2026-04)
_PRICES = {
    "deepseek-v4-flash":          {"input": 0.14,  "output": 0.28},
    "deepseek-v4-pro":            {"input": 0.435, "output": 0.87},   # 75% off until 2026-05-31
    # legacy aliases (billed identically per DeepSeek docs)
    "deepseek-chat":              {"input": 0.14,  "output": 0.28},
    "deepseek-reasoner":          {"input": 0.435, "output": 0.87},
    "llama-3.1-8b-instant":       {"input": 0.05,  "output": 0.08},
    "llama-3.3-70b-versatile":    {"input": 0.59,  "output": 0.79},
}

# heuristic — Russian + English reasoning markers
_REASONING_RE = re.compile(
    r"\b(?:почему|объясни|обоснуй|проанализируй|сравни|оцени|"
    r"why|explain|analy[sz]e|compare|reason|prove|justify|"
    r"докажи|выведи|разложи|обсуди)\b",
    re.IGNORECASE,
)
# triage queries — almost always one-line answers, route to fast model
_FAST_RE = re.compile(
    r"^(?:что|кто|когда|где|сколько|when|who|where|how many|what is|какой|какая|какое)\s",
    re.IGNORECASE,
)


# ── DB for route stats ─────────────────────────────────────────────────────


_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            ts TEXT, model TEXT, tier TEXT,
            prompt_chars INTEGER, est_in_tokens INTEGER,
            est_cost REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_routes_ts ON routes(ts)")
    return conn


# ── classification ─────────────────────────────────────────────────────────


def classify(prompt: str, force_model: str | None = None) -> dict:
    if force_model:
        return {"model": force_model, "tier": "forced",
                "reason": "caller forced model",
                "est_in_tokens": len(prompt) // 4}

    n = len(prompt)
    est_tokens = max(1, n // 4)

    if _REASONING_RE.search(prompt):
        return {"model": "deepseek-reasoner",     "tier": "reasoning",
                "reason": "reasoning marker matched",
                "est_in_tokens": est_tokens}

    if n < 200 or _FAST_RE.match(prompt or ""):
        return {"model": "llama-3.1-8b-instant",  "tier": "fast",
                "reason": "short or simple-Q pattern",
                "est_in_tokens": est_tokens}

    return {"model": "deepseek-chat",             "tier": "standard",
            "reason": "default",
            "est_in_tokens": est_tokens}


def estimate_cost(model: str, in_tok: int, out_tok: int = 0) -> float:
    p = _PRICES.get(model, {"input": 1.0, "output": 2.0})
    return (in_tok * p["input"] + out_tok * p["output"]) / 1_000_000


def route(prompt: str, force_model: str | None = None,
          assume_output: int = 500) -> dict:
    """Public API: returns {model, tier, est_cost_usd, ...}."""
    info = classify(prompt, force_model)
    info["est_cost"] = round(
        estimate_cost(info["model"], info["est_in_tokens"], assume_output), 6)

    if ENABLED:
        try:
            with _LOCK:
                _db().execute(
                    "INSERT INTO routes (ts, model, tier, prompt_chars, "
                    "est_in_tokens, est_cost) VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"),
                     info["model"], info["tier"], len(prompt or ""),
                     info["est_in_tokens"], info["est_cost"]),
                )
        except Exception as e:
            log.debug(f"route log failed: {e}")
    return info


# ── stats ──────────────────────────────────────────────────────────────────


def stats() -> dict:
    if not DB_PATH.exists():
        return {"enabled": ENABLED, "rows": 0}
    with _LOCK:
        c = _db()
        n   = c.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        cost = c.execute("SELECT COALESCE(SUM(est_cost),0) FROM routes").fetchone()[0]
        by_tier = {r[0]: r[1] for r in c.execute(
            "SELECT tier, COUNT(*) FROM routes GROUP BY tier").fetchall()}
        by_model = {r[0]: r[1] for r in c.execute(
            "SELECT model, COUNT(*) FROM routes GROUP BY model").fetchall()}
    # also compute "savings" — cost if everything routed to deepseek-chat
    chat_avg_in = _PRICES["deepseek-chat"]["input"] / 1_000_000
    return {
        "enabled":         ENABLED,
        "rows":            n,
        "estimated_cost":  round(cost, 4),
        "by_tier":         by_tier,
        "by_model":        by_model,
    }


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-route")
    sub = p.add_subparsers(dest="cmd", required=True)
    cl = sub.add_parser("classify"); cl.add_argument("prompt")
    sub.add_parser("stats")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "classify":
        print(json.dumps(route(args.prompt), ensure_ascii=False, indent=2))
    elif args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
