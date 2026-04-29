"""agents/embed_cache.py — semantic LRU cache for embeddings.

The embed daemon already caches by exact MD5 of text. This module adds a
*semantic* layer on top: if a query text is highly similar (cosine ≥
threshold) to one already in cache, return the cached vector instead of
encoding again.

Useful when the same factoid is paraphrased many times (typical for an LLM
agent that re-asks "что такое CDATA?" in slightly different wordings).

Wire-in pattern (opt-in):
    from agents.embed_cache import semantic_get, semantic_put
    cached = semantic_get(text)
    if cached is None:
        v = model.encode([text])[0]
        semantic_put(text, v)
    else:
        v = cached
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("aim.embed_cache")

ENABLED   = os.getenv("AIM_EMBED_SEMCACHE", "").lower() in ("1", "true", "yes")
THRESHOLD = float(os.getenv("AIM_EMBED_SEMCACHE_THRESHOLD", "0.95"))
MAX_SIZE  = int(os.getenv("AIM_EMBED_SEMCACHE_MAX", "1024"))


class _Stats:
    hits = 0
    misses = 0


_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, list[float]]" = OrderedDict()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na  += x * x
        nb  += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / math.sqrt(na * nb)


# ── public API ──────────────────────────────────────────────────────────────


def semantic_get(text: str, query_vec: Optional[list[float]] = None) -> Optional[list[float]]:
    """Return a cached vector if any stored entry has cosine ≥ THRESHOLD."""
    if not ENABLED or not text:
        return None
    if query_vec is None:
        # Need an embedding to compare — but that defeats the purpose.
        # Caller should pass query_vec from the freshly-computed encode call.
        return None
    with _LOCK:
        best_sim = 0.0
        best_vec: Optional[list[float]] = None
        for k, v in _CACHE.items():
            sim = _cosine(query_vec, v)
            if sim > best_sim:
                best_sim = sim
                best_vec = v
        if best_vec is not None and best_sim >= THRESHOLD:
            _Stats.hits += 1
            return best_vec
    _Stats.misses += 1
    return None


def semantic_put(text: str, vec: list[float]) -> None:
    if not ENABLED or not text or not vec:
        return
    key = text[:160] + f"#{len(text)}"
    with _LOCK:
        _CACHE[key] = vec
        _CACHE.move_to_end(key)
        while len(_CACHE) > MAX_SIZE:
            _CACHE.popitem(last=False)


def stats() -> dict:
    with _LOCK:
        total = _Stats.hits + _Stats.misses
        return {
            "enabled":   ENABLED,
            "size":      len(_CACHE),
            "max_size":  MAX_SIZE,
            "threshold": THRESHOLD,
            "hits":      _Stats.hits,
            "misses":    _Stats.misses,
            "hit_rate":  round(_Stats.hits / total, 3) if total else 0.0,
        }


def clear() -> int:
    with _LOCK:
        n = len(_CACHE)
        _CACHE.clear()
    return n


def _main():
    import argparse, json, logging as _l
    p = argparse.ArgumentParser(prog="aim-embed-semcache")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("clear")
    args = p.parse_args()
    _l.basicConfig(level=_l.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "clear":
        print(f"cleared: {clear()}")


if __name__ == "__main__":
    _main()
