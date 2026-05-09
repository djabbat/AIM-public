"""agents/researcher.py — literature search & verification.

Принцип: НИКОГДА не доверять LLM в части DOI/PMID. Все ссылки идут через
`tools.literature` (PubMed esummary + Crossref). LLM используется только
для query-formulation и summarisation; цитаты — only verified.

Public API:
    find(query, *, n=10, source="pubmed")    → list[dict]    # verified records
    summarise(records, focus, lang="en")     → str           # uses verified only
    verify_text(text, mode="annotate")       → CitationReport
    formulate_queries(topic, n=5)            → list[str]     # LLM-generated query strings
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from llm import ask_fast, ask_deep
from tools.literature import (
    pubmed_search, crossref_search,
    verify_pmid, verify_doi,
    enforce_citations, CitationReport,
)

log = logging.getLogger("aim.researcher")


def formulate_queries(topic: str, n: int = 5) -> list[str]:
    """Ask LLM for n distinct PubMed-friendly query strings; one per line."""
    prompt = (
        f"Topic: {topic}\n\n"
        f"Generate {n} distinct PubMed query strings that would surface the "
        f"most relevant peer-reviewed evidence on this topic. Output: one "
        f"query per line, no numbering, no explanation. Use MeSH terms and "
        f"Boolean operators where helpful."
    )
    raw = ask_fast(prompt)
    queries = [ln.strip("- *•\t ").strip()
               for ln in raw.splitlines() if ln.strip()][:n]
    return [q for q in queries if 3 < len(q) < 250]


def find(query: str, *, n: int = 10, source: str = "pubmed") -> list[dict]:
    """Hard-verified search. `source` ∈ {pubmed, crossref, both}."""
    out: list[dict] = []
    if source in ("pubmed", "both"):
        out.extend(pubmed_search(query, n=n))
    if source in ("crossref", "both"):
        out.extend(crossref_search(query, n=n))
    seen = set()
    dedup = []
    for r in out:
        key = (r.get("doi") or "").lower() or r.get("pmid")
        if key in seen:
            continue
        seen.add(key); dedup.append(r)
    return dedup


def summarise(records: list[dict], focus: str, *, lang: str = "en") -> str:
    """Summarise verified records around a focus question.
    Each record is rendered as `[author year, journal | DOI/PMID]`. The LLM
    is instructed to cite only the records given (no fabrications)."""
    if not records:
        return "No verified records to summarise."
    cards = []
    for i, r in enumerate(records, 1):
        idline = (f"PMID:{r['pmid']}" if r.get("pmid")
                  else f"doi:{r['doi']}" if r.get("doi") else "?")
        first_author = (r.get("authors") or ["?"])[0]
        cards.append(f"[{i}] {first_author} {r.get('year','')} | "
                     f"{r.get('journal','?')} | {idline}\n"
                     f"    Title: {r.get('title','?')}")
    block = "\n\n".join(cards)
    sys = ("You are an evidence synthesiser. Use ONLY the records below; "
           "do not introduce any new citations. Cite as [N] referring to the "
           "card numbers. Be precise about what each record actually shows "
           "vs what would be required to support the focus question.")
    prompt = f"=== RECORDS ===\n{block}\n=== END ===\n\nFocus: {focus}"
    out = ask_deep(prompt, system=sys, lang=lang)
    # Replace [N] with the card identifier so citations stay verifiable in text
    def _expand(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= len(records):
            r = records[n - 1]
            return f"[{r.get('pmid') and 'PMID:'+r['pmid'] or 'doi:'+r.get('doi','?')}]"
        return m.group(0)
    out = re.sub(r"\[(\d+)\]", _expand, out)
    return out


def verify_text(text: str, mode: str = "annotate") -> CitationReport:
    """Pass-through to tools.literature.enforce_citations."""
    return enforce_citations(text, mode=mode)
