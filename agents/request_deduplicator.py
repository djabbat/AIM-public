"""agents/request_deduplicator.py — silently drop accidental duplicate
requests within a sliding TTL window.

Use case: someone hits Enter twice in the REPL, or a webhook re-fires after
network blip. We catch the duplicate before it reaches the LLM router (and
the cost monitor).

Wire-in: imported by graph.run_agent() — bypasses pipeline if duplicate.

Env:
    AIM_DEDUP_TTL_S=10                 # window in seconds (0 = disabled)
    AIM_DEDUP_MAX=100                  # max distinct hashes tracked
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict

log = logging.getLogger("aim.dedup")

TTL_S    = int(os.getenv("AIM_DEDUP_TTL_S",   "10"))
MAX_SIZE = int(os.getenv("AIM_DEDUP_MAX",    "100"))


_LOCK    = threading.Lock()
_CACHE:  "OrderedDict[str, float]" = OrderedDict()
_blocked = 0


def _hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def is_duplicate(text: str) -> tuple[bool, float]:
    """Return (is_dup, seconds_since_first_seen). is_dup=False also marks
    the request as seen (so subsequent identical calls within TTL hit)."""
    if TTL_S <= 0 or not text:
        return False, 0.0
    key = _hash(text)
    now = time.time()
    cutoff = now - TTL_S
    with _LOCK:
        # purge expired
        while _CACHE and next(iter(_CACHE.values())) < cutoff:
            _CACHE.popitem(last=False)
        if key in _CACHE:
            elapsed = now - _CACHE[key]
            global _blocked
            _blocked += 1
            return True, elapsed
        # mark as seen
        _CACHE[key] = now
        if len(_CACHE) > MAX_SIZE:
            _CACHE.popitem(last=False)
    return False, 0.0


def stats() -> dict:
    with _LOCK:
        active = len(_CACHE)
    return {
        "ttl_s":         TTL_S,
        "max_size":      MAX_SIZE,
        "tracked":       active,
        "blocked_total": _blocked,
    }


def clear() -> int:
    with _LOCK:
        n = len(_CACHE)
        _CACHE.clear()
    return n


def _main():
    import argparse, json
    p = argparse.ArgumentParser(prog="aim-dedup")
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
