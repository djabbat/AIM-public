"""agents/speculative_prefetch.py — anticipatory tool execution.

While the generalist LLM is composing its next step, this module runs the
*most likely* upcoming tool calls in the background and caches their
results. When the LLM actually requests one of them, the result is
returned instantly; otherwise the cached result is discarded.

Heuristics anticipate, in priority order:
  1. read_file  — every absolute path mentioned in the latest user/tool turn
  2. memory_recall — every project name mentioned (FCLC, MCOA, Ze, …)
  3. verify_pmid / verify_doi — every PMID / DOI pattern in the text

Usage:
    pf = Prefetcher()
    pf.observe(history)            # kicks off background work
    res = pf.consume("read_file", {"path": "/foo"})  # → cached or None
    pf.shutdown()
"""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional

log = logging.getLogger("aim.prefetch")


_PATH_RE = re.compile(r"(?<![\w/])(/(?:home|tmp|var|etc|Users)/[^\s'\"`)\]]+)")
_PMID_RE = re.compile(r"\bPMID[:\s]*(\d{4,9})\b", re.IGNORECASE)
_DOI_RE  = re.compile(r"\b(10\.\d{4,9}/[^\s\)\]\}\,;]+)", re.IGNORECASE)
_PROJECTS = ("FCLC", "MCOA", "Ze", "BioSense", "CDATA", "AIM",
             "Annals", "PhD", "Books", "GLA", "LongevityCommon")


class Prefetcher:
    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="aim-prefetch")
        self._cache: dict[str, Future] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(tool: str, args: dict) -> str:
        # Stable, simple cache key
        items = sorted((k, str(v)[:120]) for k, v in (args or {}).items())
        return f"{tool}::" + "|".join(f"{k}={v}" for k, v in items)

    def _maybe_submit(self, tool: str, args: dict, fn) -> None:
        key = self._key(tool, args)
        with self._lock:
            if key in self._cache:
                return
            self._cache[key] = self._pool.submit(fn, **args)

    def observe(self, history: list[dict]) -> None:
        """Scan recent history; speculatively launch likely tools."""
        if not history:
            return
        # consider the last 3 turns
        text = "\n".join(str(m.get("content", "") or m.get("result", ""))
                         for m in history[-3:])
        # 1. Paths → read_file
        seen_paths: set[str] = set()
        for m in _PATH_RE.finditer(text):
            p = m.group(1).rstrip(".,);")
            if p in seen_paths:
                continue
            seen_paths.add(p)
            try:
                from agents.generalist import _t_read_file
            except Exception:
                return
            self._maybe_submit("read_file", {"path": p, "offset": 0,
                                              "limit": 200}, _t_read_file)
            if len(seen_paths) >= 3:
                break

        # 2. Project names → memory_recall
        for proj in _PROJECTS:
            if re.search(rf"\b{proj}\b", text):
                try:
                    from agents.generalist import _t_memory_recall
                except Exception:
                    return
                self._maybe_submit("memory_recall",
                                    {"query": proj, "k": 6},
                                    _t_memory_recall)

        # 3. PMID / DOI → verify
        for m in _PMID_RE.finditer(text):
            try:
                from agents.generalist import _t_verify_pmid
            except Exception:
                return
            self._maybe_submit("verify_pmid", {"pmid": m.group(1)},
                                _t_verify_pmid)
        for m in _DOI_RE.finditer(text):
            try:
                from agents.generalist import _t_verify_doi
            except Exception:
                return
            self._maybe_submit("verify_doi", {"doi": m.group(1)},
                                _t_verify_doi)

    def consume(self, tool: str, args: dict, *,
                wait: float = 0.05) -> Optional[str]:
        """Return cached result if speculative call already finished, else None.
        Short wait gives the prefetcher a small chance to finish in flight."""
        key = self._key(tool, args)
        with self._lock:
            fut = self._cache.pop(key, None)
        if fut is None:
            return None
        try:
            return str(fut.result(timeout=wait))
        except TimeoutError:
            # Not done yet; let the caller run it normally. We've thrown away
            # the future intentionally — it'll finish in the background, no
            # harm done (its result is just dropped).
            return None
        except Exception as e:
            log.debug(f"prefetch[{tool}] errored: {e}")
            return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
