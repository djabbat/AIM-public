"""agents/literature_watch.py — PubMed RSS dedup + new-paper digest (L2, 2026-05-03).

Runs daily / weekly. For each configured query (in
USER/preferences/literature.yaml or env var), pulls the PubMed
esearch+esummary endpoint, deduplicates against:
  * already-seen PMIDs (~/.cache/aim/literature_seen.json)
  * the user's own publications.md so we don't surface own work
…then produces a short digest of NEW papers. The watch list is small
(20-50 items) so we don't hammer NCBI; default cooldown 6h between
identical-query refreshes.

Schema (USER/preferences/literature.yaml):

    queries:
      - name: centriole-aging
        term: 'centriole AND aging'
        max_results: 10
      - name: longevity-biomarkers
        term: 'longevity biomarker[Title]'
        max_results: 8
    cooldown_hours: 6

Public API:
    queries() -> list[Query]
    fetch(query) -> list[Paper]    # raw esummary call
    new_for(query, *, today=None) -> list[Paper]    # dedup'd
    summary(today=None) -> str
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

log = logging.getLogger("aim.literature_watch")


def prefs_path() -> Path:
    env = os.environ.get("AIM_LITERATURE_PREFS")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "USER" / "preferences" / "literature.yaml"


def seen_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "literature_seen.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Query:
    name: str
    term: str
    max_results: int = 10


@dataclasses.dataclass
class Paper:
    pmid: str
    title: str
    year: Optional[int]
    journal: str = ""
    first_author: str = ""

    def to_line(self) -> str:
        bits = [self.pmid]
        if self.year:
            bits.append(str(self.year))
        if self.first_author:
            bits.append(self.first_author + " et al.")
        if self.journal:
            bits.append(self.journal)
        return f"  • {self.title[:120]} — {' / '.join(bits)}"


# ── prefs ────────────────────────────────────────────────────────


def queries() -> list[Query]:
    p = prefs_path()
    if not p.exists():
        return []
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("literature prefs parse failed: %s", e)
        return []
    if not isinstance(raw, dict):
        return []
    out: list[Query] = []
    for q in raw.get("queries") or []:
        if not isinstance(q, dict):
            continue
        term = str(q.get("term") or "").strip()
        if not term:
            continue
        out.append(Query(
            name=str(q.get("name") or term[:30]),
            term=term,
            max_results=int(q.get("max_results", 10)),
        ))
    return out


# ── seen-set persistence ─────────────────────────────────────────


def _load_seen() -> dict:
    p = seen_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(state: dict) -> None:
    p = seen_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError as e:
        log.warning("save seen failed: %s", e)


# ── own-publications scan (so we don't surface own work) ─────────


_PMID_RE = re.compile(r"\bPMID[:\s]*([0-9]{4,9})", re.IGNORECASE)


def _own_pmids() -> set[str]:
    """Pull PMIDs out of memory/publications.md + ~/Desktop/PhD/publications/."""
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
        for m in _PMID_RE.finditer(text):
            out.add(m.group(1))
    return out


# ── PubMed fetch ────────────────────────────────────────────────


def fetch(query: Query) -> list[Paper]:
    """Hit NCBI esearch + esummary. Empty list on any failure."""
    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed; literature_watch disabled")
        return []
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        with httpx.Client(timeout=20.0) as cli:
            r = cli.get(f"{base}/esearch.fcgi", params={
                "db": "pubmed", "term": query.term, "retmode": "json",
                "retmax": query.max_results,
            })
            r.raise_for_status()
            ids = r.json().get("esearchresult", {}).get("idlist", []) or []
            if not ids:
                return []
            r = cli.get(f"{base}/esummary.fcgi", params={
                "db": "pubmed", "id": ",".join(ids), "retmode": "json",
            })
            r.raise_for_status()
            data = r.json().get("result", {}) or {}
    except Exception as e:
        log.warning("PubMed fetch failed for %r: %s", query.term, e)
        return []

    papers: list[Paper] = []
    for pmid in ids:
        rec = data.get(pmid)
        if not isinstance(rec, dict):
            continue
        title = str(rec.get("title", "")).strip()
        journal = str(rec.get("fulljournalname", "")).strip()
        year = None
        date_str = rec.get("pubdate") or rec.get("epubdate") or ""
        m = re.match(r"(\d{4})", str(date_str))
        if m:
            try:
                year = int(m.group(1))
            except ValueError:
                pass
        first_author = ""
        authors = rec.get("authors") or []
        if isinstance(authors, list) and authors:
            first_author = str(authors[0].get("name", "")).strip()
        papers.append(Paper(pmid=str(pmid), title=title, year=year,
                            journal=journal, first_author=first_author))
    return papers


# ── dedup ────────────────────────────────────────────────────────


def _cooldown_hours() -> float:
    p = prefs_path()
    if not p.exists():
        return 6.0
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return float(raw.get("cooldown_hours", 6.0))
    except Exception:
        return 6.0


def new_for(query: Query, *, today: Optional[dt.date] = None,
            fetch_fn=None) -> list[Paper]:
    """Return papers that are (a) currently in the PubMed result set and
    (b) NOT in our seen-set OR own-publications. Updates seen-set.

    `fetch_fn` defaults to module-level `fetch`; tests can monkeypatch
    `agents.literature_watch.fetch` to intercept calls."""
    seen = _load_seen()
    bucket = seen.setdefault(query.name, {"pmids": [], "last_fetched": 0})
    now = time.time()
    if now - bucket.get("last_fetched", 0) < _cooldown_hours() * 3600:
        # Cooldown active — skip the network and return [].
        return []

    if fetch_fn is None:
        fetch_fn = globals()["fetch"]
    papers = fetch_fn(query)
    own = _own_pmids()
    seen_set = set(bucket.get("pmids", []))
    new_papers = [p for p in papers
                  if p.pmid not in seen_set and p.pmid not in own]

    bucket["pmids"] = sorted(set(seen_set | {p.pmid for p in papers}))[-500:]
    bucket["last_fetched"] = int(now)
    _save_seen(seen)
    return new_papers


def summary(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    qs = queries()
    if not qs:
        return "(no literature queries configured)"
    parts = [f"📚 Literature watch — {today.isoformat()}"]
    any_new = False
    for q in qs:
        new = new_for(q, today=today)
        if not new:
            continue
        any_new = True
        parts.append(f"  «{q.name}» — {len(new)} new")
        for p in new[:5]:
            parts.append(p.to_line())
    if not any_new:
        parts.append("  (no new papers across watched queries)")
    return "\n".join(parts)
