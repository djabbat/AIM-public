"""agents/smart_fallback.py — multi-tier fallback chain across providers.

Used as the last line of defence after circuit_breaker / rate_limiter /
resilient_llm have already exhausted retries on the primary path. Walks
through a configurable provider chain and returns the first successful
response, recording per-tier failures for analytics.

Default chain (top → bottom):
    1. deepseek-chat        (primary)
    2. deepseek-reasoner    (better quality, more expensive)
    3. groq-llama-70b       (different network)
    4. groq-llama-8b        (cheapest, last resort)

Override via env:
    AIM_FALLBACK_CHAIN=deepseek-chat,groq-llama-70b,groq-llama-8b
    AIM_FALLBACK_DISABLED=1   (skip entirely)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("aim.fallback")

DB_PATH = Path("~/.claude/smart_fallback.db").expanduser()

DEFAULT_CHAIN = [
    ("deepseek", "deepseek-chat"),
    ("deepseek", "deepseek-reasoner"),
    ("groq",     "llama-3.3-70b-versatile"),
    ("groq",     "llama-3.1-8b-instant"),
]


def _load_chain() -> list[tuple[str, str]]:
    raw = os.getenv("AIM_FALLBACK_CHAIN", "")
    if not raw:
        return DEFAULT_CHAIN
    out: list[tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("groq-") or entry.startswith("llama"):
            out.append(("groq", entry.replace("groq-", "")))
        else:
            out.append(("deepseek", entry))
    return out or DEFAULT_CHAIN


_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, provider TEXT, model TEXT,
            ok INTEGER, error TEXT, latency_s REAL
        )
    """)
    return conn


def _record(provider: str, model: str, ok: bool, error: str = "", latency: float = 0.0) -> None:
    try:
        with _LOCK:
            _db().execute(
                "INSERT INTO attempts (ts, provider, model, ok, error, latency_s) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 provider, model, 1 if ok else 0, error[:300], round(latency, 3)),
            )
    except Exception as e:
        log.debug(f"fallback record failed: {e}")


def call_with_fallback(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Try each tier in the chain; return the first successful content."""
    if os.getenv("AIM_FALLBACK_DISABLED", "").lower() in ("1", "true", "yes"):
        from llm import ask
        return ask(prompt, system=system, temperature=temperature, max_tokens=max_tokens)

    last_err: Exception | None = None
    chain = _load_chain()
    for i, (provider, model) in enumerate(chain):
        t0 = time.time()
        try:
            content = _call_one(provider, model, prompt, system, temperature, max_tokens)
            _record(provider, model, True, latency=time.time() - t0)
            if i > 0:
                log.warning(f"fallback succeeded at tier {i+1} ({provider}/{model})")
            return content
        except Exception as e:
            _record(provider, model, False, error=str(e), latency=time.time() - t0)
            last_err = e
            log.warning(f"fallback tier {i+1} ({provider}/{model}) failed: {e}")
            continue
    raise RuntimeError(f"all fallback tiers exhausted; last error: {last_err}")


def _call_one(provider: str, model: str, prompt: str, system: str,
              temperature: float, max_tokens: int) -> str:
    from llm import _deepseek, _groq, DEEPSEEK_API_KEY, GROQ_API_KEY
    if provider == "deepseek":
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("no deepseek key")
        client = _deepseek()
    else:
        if not GROQ_API_KEY:
            raise RuntimeError("no groq key")
        client = _groq()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def stats() -> dict:
    if not DB_PATH.exists():
        return {"chain": _load_chain(), "rows": 0}
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        by_model = {f"{r[0]}/{r[1]}": {"attempts": r[2], "successes": r[3], "fail_rate": round(1 - r[3] / r[2], 3)}
                    for r in c.execute(
            "SELECT provider, model, COUNT(*), SUM(ok) FROM attempts GROUP BY provider, model"
        ).fetchall() if r[2] > 0}
    return {"chain": _load_chain(), "rows": rows, "by_model": by_model}


def _main():
    import argparse, json
    p = argparse.ArgumentParser(prog="aim-fallback")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("chain")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "chain":
        for i, (p_, m) in enumerate(_load_chain(), 1):
            print(f"  {i}. {p_}/{m}")


if __name__ == "__main__":
    _main()
