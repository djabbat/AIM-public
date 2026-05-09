"""agents/recall_perf.py — slow-query detector + LRU cache (SL1, 2026-05-03).

Wraps `agents.memory_index.retrieve` (and the public `agents.recall_cli.recall`)
with two non-invasive layers:

  1. Per-call latency log: anything over `slow_threshold_ms` (default 500)
     gets recorded into JSONL for the weekly digest.
  2. Hot-query LRU cache: if the same `(query, k)` is asked more than
     once within `cache_ttl_seconds`, return the cached result.

Activation is opt-in via `install()` (called from main CLI / serve daemon).
A test-only `uninstall()` restores the original retrieve.

Public API:
    install()       — patch memory_index.retrieve with the wrapper
    uninstall()     — restore the original
    stats()         — {n_calls, n_cache_hits, n_slow, top_slow}
    history(limit)  — recent slow-query log entries
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aim.recall_perf")


# ── config ───────────────────────────────────────────────────────


def slow_threshold_ms() -> int:
    try:
        return int(os.environ.get("AIM_RECALL_SLOW_MS", "500"))
    except ValueError:
        return 500


def cache_ttl_seconds() -> float:
    try:
        return float(os.environ.get("AIM_RECALL_CACHE_TTL", "60"))
    except ValueError:
        return 60.0


def cache_max_entries() -> int:
    try:
        return int(os.environ.get("AIM_RECALL_CACHE_MAX", "32"))
    except ValueError:
        return 32


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "recall_slow.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── state ────────────────────────────────────────────────────────


_LOCK = threading.RLock()
_CACHE: "OrderedDict[tuple[str, int], tuple[float, Any]]" = OrderedDict()
_STATS = {"n_calls": 0, "n_cache_hits": 0, "n_slow": 0,
          "slow_queries": []}   # list[(query, ms)]
_INSTALLED = {"original": None}


def reset_state_for_tests() -> None:
    with _LOCK:
        _CACHE.clear()
        _STATS["n_calls"] = 0
        _STATS["n_cache_hits"] = 0
        _STATS["n_slow"] = 0
        _STATS["slow_queries"] = []


# ── wrapper ──────────────────────────────────────────────────────


def _audit_slow(query: str, latency_ms: int, k: int) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "query": query[:200],
        "latency_ms": latency_ms,
        "k": k,
    }
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("recall_perf audit write failed: %s", e)


def make_wrapper(original):
    def wrapper(query: str, k: int = 12, max_chars_per_file: int = 4000):
        key = (str(query), int(k))
        ttl = cache_ttl_seconds()
        slow_ms = slow_threshold_ms()
        max_n = cache_max_entries()

        with _LOCK:
            _STATS["n_calls"] += 1
            cached = _CACHE.get(key)
            if cached and (time.time() - cached[0]) <= ttl:
                _CACHE.move_to_end(key)
                _STATS["n_cache_hits"] += 1
                return cached[1]

        t0 = time.time()
        result = original(query, k=k, max_chars_per_file=max_chars_per_file)
        latency_ms = int((time.time() - t0) * 1000)

        with _LOCK:
            _CACHE[key] = (time.time(), result)
            while len(_CACHE) > max_n:
                _CACHE.popitem(last=False)
            if latency_ms >= slow_ms:
                _STATS["n_slow"] += 1
                _STATS["slow_queries"].append((str(query)[:120], latency_ms))
                _STATS["slow_queries"] = _STATS["slow_queries"][-20:]
                _audit_slow(str(query), latency_ms, k)

        return result
    return wrapper


# ── lifecycle ────────────────────────────────────────────────────


def install() -> bool:
    """Replace memory_index.retrieve with our wrapper. Idempotent."""
    try:
        from agents import memory_index as mi
    except ImportError:
        return False
    if _INSTALLED["original"] is not None:
        return True
    _INSTALLED["original"] = mi.retrieve
    mi.retrieve = make_wrapper(mi.retrieve)
    log.info("recall_perf wrapper installed (slow=%dms, ttl=%.0fs)",
             slow_threshold_ms(), cache_ttl_seconds())
    return True


def uninstall() -> bool:
    if _INSTALLED["original"] is None:
        return False
    try:
        from agents import memory_index as mi
        mi.retrieve = _INSTALLED["original"]
    except ImportError:
        pass
    _INSTALLED["original"] = None
    return True


# ── reporting ────────────────────────────────────────────────────


def stats() -> dict:
    with _LOCK:
        return {
            "n_calls":       _STATS["n_calls"],
            "n_cache_hits":  _STATS["n_cache_hits"],
            "n_slow":        _STATS["n_slow"],
            "cache_size":    len(_CACHE),
            "top_slow":      list(_STATS["slow_queries"]),
        }


def history(limit: int = 50) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]
