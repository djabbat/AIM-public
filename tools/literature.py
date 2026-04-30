"""tools/literature.py — hard PubMed / Crossref / OpenAlex verification.

Per memory rule `feedback_deepseek_no_citations`: DeepSeek (and other LLMs)
hallucinate DOIs and PMIDs. Every citation surfaced by AIM Researcher /
Writer agents MUST pass through this module before being emitted.

If a PMID/DOI does not resolve at the authoritative source — the citation
is REJECTED. The agent must then either drop the claim or find a real
reference via search().

Public API:
    verify_pmid(pmid)              → dict | None
    verify_doi(doi)                → dict | None
    pubmed_search(query, n=10)     → list[dict]
    crossref_search(query, n=10)   → list[dict]
    enforce_citations(text, mode)  → (clean_text, report)

No third-party deps — urllib + json only.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Optional

log = logging.getLogger("aim.literature")

# ── Endpoints ──────────────────────────────────────────────────────────────

PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_ESEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CROSSREF_WORKS  = "https://api.crossref.org/works"

USER_AGENT = "AIM-literature/7.0 (contact: jaba@longevity.ge)"

# Rate-limit: PubMed = 3 req/s without API key, 10 with. Crossref polite = 1/s.
_LAST_CALL: dict[str, float] = {}


def _throttle(provider: str, min_interval: float = 0.4) -> None:
    last = _LAST_CALL.get(provider, 0)
    delta = time.time() - last
    if delta < min_interval:
        time.sleep(min_interval - delta)
    _LAST_CALL[provider] = time.time()


def _http_get(url: str, *, timeout: float = 8.0) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 300:
                return None
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning(f"GET failed: {url}  ({e})")
        return None


# ── PMID verification ──────────────────────────────────────────────────────


def verify_pmid(pmid: str | int) -> Optional[dict]:
    """Return {'pmid', 'title', 'authors', 'journal', 'year', 'doi'} if PMID
    exists at PubMed; None otherwise.  Idempotent + cached implicitly via
    upstream HTTP cache when one is configured."""
    pmid = str(pmid).strip().lstrip("PMID:").strip()
    if not pmid.isdigit():
        return None
    _throttle("pubmed")
    url = f"{PUBMED_ESUMMARY}?db=pubmed&id={pmid}&retmode=json"
    data = _http_get(url)
    if not data:
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    rec = payload.get("result", {}).get(pmid)
    if not rec or rec.get("error"):
        return None
    authors = [a.get("name") for a in rec.get("authors", []) if a.get("name")]
    doi = next((aid["value"] for aid in rec.get("articleids", [])
                if aid.get("idtype") == "doi"), None)
    return {
        "pmid":    pmid,
        "title":   rec.get("title", "").strip().rstrip(".") or None,
        "authors": authors,
        "journal": rec.get("source"),
        "year":    (rec.get("pubdate") or "")[:4] or None,
        "doi":     doi,
    }


# ── DOI verification (Crossref) ────────────────────────────────────────────


def verify_doi(doi: str) -> Optional[dict]:
    """Return Crossref metadata dict if DOI resolves, None otherwise."""
    doi = doi.strip().lstrip("doi:").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi).rstrip(".)")
    if not doi or "/" not in doi:
        return None
    _throttle("crossref", 1.0)
    url = f"{CROSSREF_WORKS}/{urllib.parse.quote(doi, safe='/')}"
    data = _http_get(url)
    if not data:
        return None
    try:
        msg = json.loads(data).get("message", {})
    except json.JSONDecodeError:
        return None
    if not msg.get("DOI"):
        return None
    title = (msg.get("title") or [""])[0].strip().rstrip(".")
    authors = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in msg.get("author", []) if a.get("family")
    ]
    year = ((msg.get("issued", {}).get("date-parts") or [[None]])[0] + [None, None])[0]
    return {
        "doi":     msg["DOI"],
        "title":   title or None,
        "authors": authors,
        "journal": (msg.get("container-title") or [None])[0],
        "year":    str(year) if year else None,
        "type":    msg.get("type"),
        "publisher": msg.get("publisher"),
    }


# ── Search ─────────────────────────────────────────────────────────────────


def pubmed_search(query: str, n: int = 10) -> list[dict]:
    """ESearch → ESummary; returns list of verified records."""
    _throttle("pubmed")
    q = urllib.parse.quote(query)
    url = f"{PUBMED_ESEARCH}?db=pubmed&term={q}&retmode=json&retmax={n}"
    data = _http_get(url)
    if not data:
        return []
    try:
        ids = json.loads(data).get("esearchresult", {}).get("idlist", [])
    except json.JSONDecodeError:
        return []
    out = []
    for pmid in ids[:n]:
        rec = verify_pmid(pmid)
        if rec:
            out.append(rec)
    return out


def crossref_search(query: str, n: int = 10) -> list[dict]:
    _throttle("crossref", 1.0)
    q = urllib.parse.quote(query)
    url = f"{CROSSREF_WORKS}?query={q}&rows={n}"
    data = _http_get(url)
    if not data:
        return []
    try:
        items = json.loads(data).get("message", {}).get("items", [])
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        if not it.get("DOI"):
            continue
        out.append({
            "doi": it["DOI"],
            "title": (it.get("title") or [""])[0].strip().rstrip("."),
            "authors": [
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in it.get("author", []) if a.get("family")
            ],
            "journal": (it.get("container-title") or [None])[0],
            "year": (((it.get("issued", {}).get("date-parts") or [[None]])[0] +
                      [None, None])[0]),
        })
    return out


# ── Citation enforcement ───────────────────────────────────────────────────


@dataclass
class CitationReport:
    verified: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    text:     str = ""

    @property
    def ok(self) -> bool:
        return len(self.rejected) == 0

    def summary(self) -> str:
        lines = [f"verified: {len(self.verified)}",
                 f"rejected: {len(self.rejected)}"]
        for r in self.rejected:
            lines.append(f"  ✗ {r['kind']}: {r['value']}  — does not resolve")
        return "\n".join(lines)


_PMID_RE = re.compile(r"\bPMID[:\s]*(\d{4,9})\b", re.IGNORECASE)
_DOI_RE  = re.compile(r"\b10\.\d{4,9}/[^\s\)\]\}\,;]+", re.IGNORECASE)


def enforce_citations(text: str, mode: str = "annotate") -> CitationReport:
    """Walk every PMID/DOI in `text`. Verify each.

    mode='annotate' — replace failed citations with `[UNVERIFIED: <value>]` markers.
    mode='strict'   — raise on any failure (caller catches; suitable for kernel).
    mode='strip'    — silently delete failed citations.
    """
    rep = CitationReport()
    found_pmids = set(_PMID_RE.findall(text))
    found_dois  = set(m.lower() for m in _DOI_RE.findall(text))

    for pmid in sorted(found_pmids):
        rec = verify_pmid(pmid)
        if rec:
            rep.verified.append({"kind": "pmid", "value": pmid, "rec": rec})
        else:
            rep.rejected.append({"kind": "pmid", "value": pmid})

    for doi in sorted(found_dois):
        rec = verify_doi(doi)
        if rec:
            rep.verified.append({"kind": "doi", "value": doi, "rec": rec})
        else:
            rep.rejected.append({"kind": "doi", "value": doi})

    if mode == "strict" and rep.rejected:
        raise ValueError("unverified citations:\n" + rep.summary())

    out = text
    for r in rep.rejected:
        if r["kind"] == "pmid":
            pat = re.compile(rf"\bPMID[:\s]*{r['value']}\b", re.IGNORECASE)
        else:
            pat = re.compile(re.escape(r["value"]), re.IGNORECASE)
        if mode == "annotate":
            out = pat.sub(f"[UNVERIFIED:{r['kind'].upper()}:{r['value']}]", out)
        elif mode == "strip":
            out = pat.sub("", out)
    rep.text = out
    return rep


# ── Quick CLI ──────────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="aim-lit-verify")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pmid"); s.add_argument("pmid")
    s = sub.add_parser("doi");  s.add_argument("doi")
    s = sub.add_parser("search-pubmed"); s.add_argument("query"); s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("search-crossref"); s.add_argument("query"); s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("scan");  s.add_argument("file"); s.add_argument("--mode", default="annotate",
                                                                          choices=["annotate", "strip", "strict"])
    a = ap.parse_args()
    if a.cmd == "pmid":
        print(json.dumps(verify_pmid(a.pmid) or {"error": "not found"},
                         indent=2, ensure_ascii=False))
    elif a.cmd == "doi":
        print(json.dumps(verify_doi(a.doi) or {"error": "not found"},
                         indent=2, ensure_ascii=False))
    elif a.cmd == "search-pubmed":
        print(json.dumps(pubmed_search(a.query, n=a.n), indent=2, ensure_ascii=False))
    elif a.cmd == "search-crossref":
        print(json.dumps(crossref_search(a.query, n=a.n), indent=2, ensure_ascii=False))
    elif a.cmd == "scan":
        from pathlib import Path
        rep = enforce_citations(Path(a.file).read_text(encoding="utf-8"), mode=a.mode)
        print(rep.summary())
        if a.mode != "strict":
            print("\n--- annotated ---")
            print(rep.text[:2000] + ("..." if len(rep.text) > 2000 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
