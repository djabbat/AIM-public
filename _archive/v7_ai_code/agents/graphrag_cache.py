"""agents/graphrag_cache.py — in-process LRU cache for GraphRAG queries.

The graphrag.query() walk is O(k × hops × entity-fan-out) — fast on small
graphs (<10k nodes) but adds up when invoked repeatedly with paraphrased
queries during a single session. This wraps it with a TTL-aware LRU
keyed on (query, k, hops).

Opt-in: AIM_GRAPHRAG_CACHE=1
TTL:    AIM_GRAPHRAG_CACHE_TTL_S=600        (10 min)
SIZE:   AIM_GRAPHRAG_CACHE_MAX=128

Wire-in is automatic: agents.graphrag.query checks `cached_query` first
when this module is loaded.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("aim.graphrag_cache")

ENABLED = os.getenv("AIM_GRAPHRAG_CACHE", "").lower() in ("1", "true", "yes")
TTL_S   = int(os.getenv("AIM_GRAPHRAG_CACHE_TTL_S", "600"))
MAX     = int(os.getenv("AIM_GRAPHRAG_CACHE_MAX",   "128"))


_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, tuple[float, list]]" = OrderedDict()


class _Stats:
    hits = 0
    misses = 0


def _key(query: str, k: int, hops: int) -> str:
    return f"{(query or '').strip().lower()}::k={k}::h={hops}"


def cached_query(query: str, k: int, hops: int) -> Optional[list]:
    if not ENABLED:
        return None
    key = _key(query, k, hops)
    cutoff = time.time() - TTL_S
    with _LOCK:
        ent = _CACHE.get(key)
        if not ent:
            _Stats.misses += 1
            return None
        ts, value = ent
        if ts < cutoff:
            _CACHE.pop(key, None)
            _Stats.misses += 1
            return None
        _CACHE.move_to_end(key)
        _Stats.hits += 1
        return value


def store(query: str, k: int, hops: int, value: list) -> None:
    if not ENABLED:
        return
    key = _key(query, k, hops)
    with _LOCK:
        _CACHE[key] = (time.time(), value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > MAX:
            _CACHE.popitem(last=False)


def stats() -> dict:
    total = _Stats.hits + _Stats.misses
    return {
        "enabled":  ENABLED,
        "ttl_s":    TTL_S,
        "max":      MAX,
        "size":     len(_CACHE),
        "hits":     _Stats.hits,
        "misses":   _Stats.misses,
        "hit_rate": round(_Stats.hits / total, 3) if total else 0.0,
    }


def clear() -> int:
    with _LOCK:
        n = len(_CACHE)
        _CACHE.clear()
    return n


def _main():
    import argparse, json
    p = argparse.ArgumentParser(prog="aim-graphrag-cache")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("clear")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "clear":
        print(f"cleared: {clear()}")


if __name__ == "__main__":
    _main()
