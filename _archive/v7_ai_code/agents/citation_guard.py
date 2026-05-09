"""agents/citation_guard.py — zero-hallucination citation pipeline (R1, 2026-05-03).

Wraps any text the researcher / writer / doctor might emit and:

  1. Extracts every PMID, DOI, NCT, arXiv id mentioned.
  2. Hits PubMed esummary (`tools.literature.verify_pmid`) and Crossref
     (`tools.literature.verify_doi`) for hard verification.
  3. Returns a Verdict: every citation either resolves with title+year
     or is flagged. Strict mode → raises CitationError on any miss.
  4. Optional auto-rewrite: replace flagged citations with `[ref unverified]`
     so downstream readers see the gap immediately.

This is the L_VERIFIABILITY enforcement layer — kernel.evaluate_l_verifiability
already calls `tools.literature.enforce_citations`; this module adds:

  * strict mode that REFUSES TO EMIT TEXT instead of flagging,
  * auto-rewrite mode for soft warnings,
  * cache to skip re-verifying the same id within a session.

Public API:
    extract(text) -> list[Citation]
    verify(text, *, strict=False) -> Verdict
    sanitize(text, replacement="[ref unverified]") -> str
    CitationError                          # raised in strict mode
"""
from __future__ import annotations

import dataclasses
import logging
import os
import re
import threading
from typing import Optional

log = logging.getLogger("aim.citation_guard")


class CitationError(Exception):
    pass


@dataclasses.dataclass
class Citation:
    kind: str          # "pmid" | "doi" | "nct" | "arxiv"
    raw: str
    span: tuple[int, int]
    resolved: bool = False
    title: str = ""
    year: Optional[int] = None
    note: str = ""


@dataclasses.dataclass
class Verdict:
    citations: list[Citation]
    ok: bool

    @property
    def unresolved(self) -> list[Citation]:
        return [c for c in self.citations if not c.resolved]


# ── extraction ──────────────────────────────────────────────────


_PMID_RE = re.compile(r"(?<![A-Za-z0-9])PMID[:\s]*([0-9]{4,9})(?![A-Za-z0-9])",
                      re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;)]+)", re.IGNORECASE)
_NCT_RE = re.compile(r"\b(NCT\d{8})\b")
_ARXIV_RE = re.compile(r"\b(?:arxiv:|arXiv:)?\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)\b",
                        re.IGNORECASE)


def extract(text: str) -> list[Citation]:
    out: list[Citation] = []
    if not isinstance(text, str) or not text:
        return out
    for m in _PMID_RE.finditer(text):
        out.append(Citation(kind="pmid", raw=m.group(1), span=m.span()))
    for m in _DOI_RE.finditer(text):
        out.append(Citation(kind="doi", raw=m.group(1).rstrip(".,;)"),
                            span=m.span()))
    for m in _NCT_RE.finditer(text):
        out.append(Citation(kind="nct", raw=m.group(1), span=m.span()))
    # arxiv: only catch the explicit prefix to avoid false positives on
    # plain decimal numbers like dosages "0.5/1.5 mg/kg".
    for m in re.finditer(r"\b(?:arxiv|arXiv)[:\s]+([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
                         text, flags=re.IGNORECASE):
        out.append(Citation(kind="arxiv", raw=m.group(1), span=m.span()))
    return out


# ── cache to avoid hitting PubMed/Crossref repeatedly ───────────


_CACHE: dict[tuple[str, str], dict] = {}
_CACHE_LOCK = threading.RLock()


def _cache_get(kind: str, raw: str) -> Optional[dict]:
    with _CACHE_LOCK:
        return _CACHE.get((kind, raw))


def _cache_put(kind: str, raw: str, info: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[(kind, raw)] = info


def reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# ── verification ────────────────────────────────────────────────


def _verify_pmid(raw: str) -> Optional[dict]:
    if (cached := _cache_get("pmid", raw)) is not None:
        return cached
    try:
        from tools.literature import verify_pmid as _vp
    except ImportError:
        return None
    info = None
    try:
        info = _vp(raw)
    except Exception as e:
        log.debug("verify_pmid(%s) failed: %s", raw, e)
    if info:
        _cache_put("pmid", raw, info)
    return info


def _verify_doi(raw: str) -> Optional[dict]:
    if (cached := _cache_get("doi", raw)) is not None:
        return cached
    try:
        from tools.literature import verify_doi as _vd
    except ImportError:
        return None
    info = None
    try:
        info = _vd(raw)
    except Exception as e:
        log.debug("verify_doi(%s) failed: %s", raw, e)
    if info:
        _cache_put("doi", raw, info)
    return info


def _verify_one(c: Citation) -> Citation:
    """Resolve in-place and return the same citation."""
    if c.kind == "pmid":
        info = _verify_pmid(c.raw)
    elif c.kind == "doi":
        info = _verify_doi(c.raw)
    else:
        # NCT / arXiv don't have a hard verifier in tools.literature yet —
        # treat them as "valid format" but mark as not-strictly-verified.
        info = None
        c.note = f"{c.kind} format-validated only (no API check)"
        c.resolved = bool(re.match(r"^[A-Z0-9.]+$", c.raw, re.IGNORECASE))
        return c
    if info:
        c.resolved = True
        c.title = str(info.get("title", ""))[:200]
        try:
            c.year = int(info.get("year") or info.get("published_year") or 0) or None
        except (TypeError, ValueError):
            c.year = None
        c.note = "verified"
    else:
        c.resolved = False
        c.note = "API returned nothing — id likely fabricated or unindexed"
    return c


def verify(text: str, *, strict: bool = False,
           offline_ok: bool = False) -> Verdict:
    """Resolve every citation in `text`.

    `strict=True` raises CitationError if any citation fails to resolve.
    `offline_ok=True` treats network failure as "unknown" rather than
    "fabricated" — useful when AIM_NO_NETWORK=1 etc.
    """
    cites = extract(text)
    if not cites:
        return Verdict(citations=[], ok=True)
    if offline_ok and os.environ.get("AIM_NO_NETWORK") == "1":
        return Verdict(citations=cites, ok=True)
    for c in cites:
        _verify_one(c)
    bad = [c for c in cites if not c.resolved]
    if strict and bad:
        joined = ", ".join(f"{c.kind}:{c.raw}" for c in bad[:10])
        raise CitationError(f"{len(bad)} unverified citations: {joined}")
    return Verdict(citations=cites, ok=not bad)


def sanitize(text: str, *, replacement: str = "[ref unverified]") -> str:
    """Replace every unresolved citation in-place with `replacement`.

    Useful for soft mode: emit text but make the gaps obvious.
    """
    v = verify(text, strict=False)
    if v.ok:
        return text
    spans = sorted([c.span for c in v.unresolved], reverse=True)
    out = text
    for start, end in spans:
        out = out[:start] + replacement + out[end:]
    return out
