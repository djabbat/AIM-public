"""agents/own_pubs_tracker.py — Crossref author watcher (PV1, 2026-05-03).

Polls Crossref for new publications under a configured author name,
de-duplicates against the existing `publications.md`, and surfaces
new entries in the daily / weekly digest.

Configured via env or defaults:
    AIM_AUTHOR_NAME (default: "Tkemaladze")
    AIM_AUTHOR_ORCID (optional — enables stricter querying)

Cache lives at $AIM_HOME/own_pubs_seen.json so a 6-hour cooldown
prevents hammering Crossref. We never overwrite publications.md —
we only suggest entries to add.

Public API:
    fetch() -> list[Publication]
    new_pubs(today=None) -> list[Publication]
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.own_pubs_tracker")


def author_name() -> str:
    return os.environ.get("AIM_AUTHOR_NAME", "Tkemaladze")


def author_orcid() -> Optional[str]:
    return os.environ.get("AIM_AUTHOR_ORCID") or None


def cooldown_hours() -> float:
    try:
        return float(os.environ.get("AIM_OWN_PUBS_COOLDOWN_HOURS", "6"))
    except ValueError:
        return 6.0


def state_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "own_pubs_seen.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Publication:
    doi: str
    title: str
    year: Optional[int]
    journal: str = ""
    pmid: str = ""

    def to_line(self) -> str:
        bits = []
        if self.year:
            bits.append(str(self.year))
        if self.journal:
            bits.append(self.journal)
        if self.doi:
            bits.append(f"doi:{self.doi}")
        return f"  • {self.title[:120]} — {' / '.join(bits)}"


# ── seen ─────────────────────────────────────────────────────────


def _load_seen() -> dict:
    p = state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(state: dict) -> None:
    p = state_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError as e:
        log.warning("save own_pubs seen failed: %s", e)


# ── publications.md scan ─────────────────────────────────────────


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;)]+)", re.IGNORECASE)


def _publications_md_dois() -> set[str]:
    out: set[str] = set()
    candidates = [
        Path.home() / ".claude" / "projects" / "-home-oem" / "memory" / "publications.md",
        Path.home() / "Desktop" / "PhD" / "publications.md",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _DOI_RE.finditer(text):
            out.add(m.group(1).rstrip(".,;)").lower())
    return out


# ── Crossref ────────────────────────────────────────────────────


_CROSSREF_URL = "https://api.crossref.org/works"


def fetch() -> list[Publication]:
    """Return up to 30 most recent works for the configured author."""
    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed; own_pubs disabled")
        return []
    params = {
        "rows": "30",
        "sort": "issued",
        "order": "desc",
    }
    orcid = author_orcid()
    if orcid:
        params["query.author"] = author_name()
        params["filter"] = f"orcid:{orcid}"
    else:
        params["query.author"] = author_name()
    try:
        with httpx.Client(timeout=30.0,
                           headers={"User-Agent": "AIM/1.0 (research)"}) as cli:
            r = cli.get(_CROSSREF_URL, params=params)
            r.raise_for_status()
            items = r.json().get("message", {}).get("items", []) or []
    except Exception as e:
        log.warning("Crossref fetch failed: %s", e)
        return []
    out: list[Publication] = []
    for it in items:
        doi = str(it.get("DOI", "")).lower()
        if not doi:
            continue
        title_arr = it.get("title") or []
        title = title_arr[0] if title_arr else "(no title)"
        journal_arr = (it.get("container-title") or [])
        journal = journal_arr[0] if journal_arr else ""
        year = None
        issued = it.get("issued", {}).get("date-parts") or []
        if issued and issued[0]:
            try:
                year = int(issued[0][0])
            except (TypeError, ValueError):
                year = None
        out.append(Publication(
            doi=doi, title=str(title).strip()[:300],
            year=year, journal=str(journal).strip()[:120],
        ))
    return out


# ── new_pubs ─────────────────────────────────────────────────────


def new_pubs(today: Optional[dt.date] = None,
             *, fetch_fn=None) -> list[Publication]:
    """Return Publications absent from publications.md AND from the seen-set."""
    state = _load_seen()
    last = state.get("last_fetched", 0)
    now = time.time()
    if now - last < cooldown_hours() * 3600:
        return []

    fn = fetch_fn or globals()["fetch"]
    pubs = fn()
    own_dois = _publications_md_dois()
    seen_set = set(state.get("dois", []))

    new = [p for p in pubs
            if p.doi not in own_dois and p.doi not in seen_set]

    state["dois"] = sorted(set(seen_set | {p.doi for p in pubs}))[-500:]
    state["last_fetched"] = int(now)
    _save_seen(state)
    return new


# ── summary ──────────────────────────────────────────────────────


def summary(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    new = new_pubs(today=today)
    if not new:
        return "(no new own publications since last poll)"
    parts = [f"📄 New publications ({len(new)}) for author={author_name()!r}"]
    for p in new[:8]:
        parts.append(p.to_line())
    return "\n".join(parts)
