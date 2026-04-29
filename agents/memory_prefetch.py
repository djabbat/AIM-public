"""agents/memory_prefetch.py — predictive prefetching of related memory.

Spawns a background thread that pre-warms the LanceDB / GraphRAG path for
likely-next entities while the main task is running. Subsequent retrievals
hit the LRU embed cache.

Strategy:
    1. Cheap regex NER over the task (people / acronyms / years / IDs)
    2. For each entity, kick off `memory_index.retrieve` + `graphrag.query`
       in a ThreadPool — results are discarded; we only want the cache
       warmth side-effect.
    3. Optional: keep last K results in a small in-memory dict for direct
       reads via `cached_for(query)`.

Use:
    from agents.memory_prefetch import prefetch_for_task
    prefetch_for_task(task)   # fire-and-forget; returns immediately
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("aim.prefetch")

ENABLED = os.getenv("AIM_PREFETCH", "1").lower() in ("1", "true", "yes")
WORKERS = int(os.getenv("AIM_PREFETCH_WORKERS", "3"))
MAX_ENTITIES = int(os.getenv("AIM_PREFETCH_MAX_ENTITIES", "5"))

_POOL = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="aim-prefetch")
_CACHE: "OrderedDict[str, tuple[float, list[dict]]]" = OrderedDict()
_CACHE_TTL = 300.0  # 5 minutes
_CACHE_MAX = 64
_CACHE_LOCK = threading.Lock()

_ENT_RE = re.compile(
    r"\b(?:[A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}(?:[-\s][A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}){0,3}"
    r"|[A-ZА-Я]{3,}"
    r"|\b\d{4}\b"
    r"|PMID[:\s]*\d+|DOI[:\s]*[\w./-]+|ORCID[:\s]*[\w-]+)"
)
_STOP = {"The", "This", "That", "Что", "Это", "TODO", "DONE", "READ", "OPEN"}


def _extract_entities(text: str, k: int = MAX_ENTITIES) -> list[str]:
    seen: list[str] = []
    seen_lower: set[str] = set()
    for m in _ENT_RE.finditer(text or ""):
        ent = m.group(0).strip()
        low = ent.lower()
        if ent in _STOP or low in seen_lower:
            continue
        seen_lower.add(low)
        seen.append(ent)
        if len(seen) >= k:
            break
    return seen


def _cache_set(key: str, value: list[dict]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _cache_get(key: str) -> list[dict] | None:
    with _CACHE_LOCK:
        ent = _CACHE.get(key)
        if not ent:
            return None
        ts, val = ent
        if time.time() - ts > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return val


# ── public API ──────────────────────────────────────────────────────────────


def prefetch_for_task(task: str) -> None:
    """Fire-and-forget. Returns immediately; warming happens in background."""
    if not ENABLED or not task:
        return
    entities = _extract_entities(task)
    if not entities:
        return
    log.debug(f"prefetching {len(entities)} entities: {entities!r}")
    for ent in entities:
        _POOL.submit(_warm_entity, ent)


def _warm_entity(entity: str) -> None:
    try:
        from agents.memory_index import retrieve as _retrieve
        hits = _retrieve(entity, k=6)
        _cache_set(f"flat:{entity.lower()}", hits)
    except Exception as e:
        log.debug(f"flat retrieve failed for {entity!r}: {e}")
    try:
        from agents.graphrag import query as _gquery
        ghits = _gquery(entity, k=6, hops=1)
        _cache_set(f"graph:{entity.lower()}", ghits)
    except Exception as e:
        log.debug(f"graph retrieve failed for {entity!r}: {e}")


def cached_for(query: str, mode: str = "flat") -> list[dict] | None:
    return _cache_get(f"{mode}:{query.lower()}")


def stats() -> dict:
    with _CACHE_LOCK:
        return {
            "enabled":  ENABLED,
            "entries":  len(_CACHE),
            "workers":  WORKERS,
            "ttl_s":    _CACHE_TTL,
            "keys":     list(_CACHE.keys())[:20],
        }
