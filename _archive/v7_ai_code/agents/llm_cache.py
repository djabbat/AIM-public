"""agents/llm_cache.py — semantic cache for LLM responses.

Stores (prompt+system) embeddings in SQLite. On lookup, computes similarity
against the most-recent N entries and returns the response if cosine ≥
threshold. Saves 30–50% tokens on workflows with repeated queries (peer
reviews, batch summarisation, repeated planner prompts).

Wire-in (opt-in via env):
    AIM_LLM_CACHE=1                 enable
    AIM_LLM_CACHE_THRESHOLD=0.95    cosine threshold (default 0.95)
    AIM_LLM_CACHE_TTL_HOURS=24      drop entries older than N hours

Code:
    from agents.llm_cache import maybe_cached, store
    cached = maybe_cached(prompt, system)
    if cached: return cached
    response = call_llm(...)
    store(prompt, system, response, model, provider)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.llm_cache")

DB_PATH = Path("~/.claude/llm_cache.db").expanduser()
ENABLED = os.getenv("AIM_LLM_CACHE", "").lower() in ("1", "true", "yes")
THRESHOLD = float(os.getenv("AIM_LLM_CACHE_THRESHOLD", "0.95"))
TTL_HOURS = float(os.getenv("AIM_LLM_CACHE_TTL_HOURS", "24"))
MAX_ENTRIES = int(os.getenv("AIM_LLM_CACHE_MAX", "5000"))
SCAN_LIMIT  = int(os.getenv("AIM_LLM_CACHE_SCAN_LIMIT", "1000"))

_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            prompt_preview TEXT,
            embedding TEXT,
            response TEXT,
            model TEXT,
            provider TEXT,
            created_at REAL,
            hits INTEGER DEFAULT 0,
            last_hit REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON cache(created_at)")
    return conn


def _embed(text: str) -> list[float] | None:
    """Use the running embed daemon to vectorise; fall back to None on error."""
    try:
        from agents.embed_daemon import encode_via_daemon
        vecs = encode_via_daemon([text], timeout_s=5.0)
        return vecs[0] if vecs else None
    except Exception as e:
        log.debug(f"embed failed: {e}")
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _key(prompt: str, system: str) -> str:
    import hashlib
    return hashlib.md5(f"{system}\n--\n{prompt}".encode("utf-8")).hexdigest()


# ── Public API ──────────────────────────────────────────────────────────────


def maybe_cached(prompt: str, system: str = "", threshold: float | None = None) -> Optional[str]:
    """Return a cached response if any prior entry exceeds the cosine threshold."""
    if not ENABLED:
        return None
    full = f"{system}\n{prompt}" if system else prompt
    qvec = _embed(full)
    if qvec is None:
        return None

    cutoff = time.time() - TTL_HOURS * 3600
    thr = threshold if threshold is not None else THRESHOLD

    with _LOCK:
        c = _db()
        cur = c.execute(
            "SELECT key, embedding, response FROM cache "
            "WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
            (cutoff, SCAN_LIMIT),
        )
        best = (0.0, None, None)
        for key, emb_blob, resp in cur:
            try:
                emb = json.loads(emb_blob)
            except Exception:
                continue
            sim = _cosine(qvec, emb)
            if sim > best[0]:
                best = (sim, key, resp)

        if best[0] >= thr and best[1]:
            c.execute(
                "UPDATE cache SET hits = hits + 1, last_hit = ? WHERE key = ?",
                (time.time(), best[1]),
            )
            log.info(f"hit: similarity={best[0]:.3f} key={best[1][:8]}")
            try:
                from agents.metrics import REQUESTS
                REQUESTS.labels(endpoint="llm_cache", status="hit").inc()
            except Exception:
                pass
            return best[2]

    try:
        from agents.metrics import REQUESTS
        REQUESTS.labels(endpoint="llm_cache", status="miss").inc()
    except Exception:
        pass
    return None


def store(prompt: str, system: str, response: str,
          model: str = "", provider: str = "") -> bool:
    if not ENABLED:
        return False
    full = f"{system}\n{prompt}" if system else prompt
    vec = _embed(full)
    if vec is None:
        return False
    key = _key(prompt, system)
    with _LOCK:
        c = _db()
        c.execute(
            "INSERT OR REPLACE INTO cache "
            "(key, prompt_preview, embedding, response, model, provider, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (key, full[:160], json.dumps(vec), response, model, provider, time.time()),
        )
        # cap table size
        c.execute(
            "DELETE FROM cache WHERE key NOT IN "
            "(SELECT key FROM cache ORDER BY created_at DESC LIMIT ?)",
            (MAX_ENTRIES,),
        )
    return True


def stats() -> dict:
    with _LOCK:
        c = _db()
        total = c.execute("SELECT COUNT(*), COALESCE(SUM(hits),0) FROM cache").fetchone()
        recent = c.execute(
            "SELECT COUNT(*) FROM cache WHERE created_at > ?",
            (time.time() - TTL_HOURS * 3600,),
        ).fetchone()[0]
    return {
        "enabled":   ENABLED,
        "threshold": THRESHOLD,
        "ttl_hours": TTL_HOURS,
        "entries":   total[0],
        "total_hits": total[1],
        "fresh":     recent,
    }


def clear() -> int:
    with _LOCK:
        c = _db()
        cur = c.execute("DELETE FROM cache")
        n = cur.rowcount
    return n


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(prog="aim-llm-cache")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("clear")
    args = p.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "clear":
        n = clear()
        print(f"deleted {n} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
