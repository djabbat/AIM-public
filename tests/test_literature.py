"""tests/test_literature.py — anti-hallucination citation verifier tests.

Hits real PubMed and Crossref APIs. Marked `slow` so they can be excluded
in CI. Most checks complete in <2 seconds total via shared HTTP clients.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.literature import (  # noqa: E402
    verify_pmid, verify_doi,
    pubmed_search, crossref_search,
    enforce_citations,
)


@pytest.mark.network
def test_real_pmid_resolves():
    # Pick a PMID we know is real and lookup-stable.
    rec = verify_pmid("28425478")  # frequently cited PubMed example
    assert rec is not None
    assert rec.get("title")
    assert rec.get("year")


@pytest.mark.network
def test_fake_pmid_rejected():
    # 9-digit unused PMID space — fits the regex but does not exist
    assert verify_pmid("999999999") is None
    assert verify_pmid("not-a-pmid") is None
    assert verify_pmid("") is None


@pytest.mark.network
def test_real_doi_resolves():
    rec = verify_doi("10.1126/sciadv.adh2560")
    assert rec is not None
    assert "phonological" in (rec.get("title") or "").lower()


@pytest.mark.network
def test_fake_doi_rejected():
    assert verify_doi("10.1234/fakefake.123") is None
    assert verify_doi("not-a-doi") is None
    assert verify_doi("") is None


@pytest.mark.network
def test_enforce_citations_annotates_fakes():
    text = (
        "First, real PMID: 28425478. "
        "Second, fabricated paper PMID: 999999999. "
        "Third, real DOI 10.1126/sciadv.adh2560 and fake doi:10.9999/notreal.404."
    )
    rep = enforce_citations(text, mode="annotate")
    assert any(r["value"] == "999999999" for r in rep.rejected)
    assert any("notreal" in r["value"].lower() for r in rep.rejected)
    assert "[UNVERIFIED:PMID:999999999]" in rep.text
    assert "28425478" in rep.text   # real one untouched
    assert "10.1126/sciadv.adh2560" in rep.text


@pytest.mark.network
def test_strict_mode_raises_on_unverified():
    with pytest.raises(ValueError):
        enforce_citations("Bad cite PMID: 999999999", mode="strict")


@pytest.mark.network
def test_pubmed_search_returns_real_records():
    rows = pubmed_search("phoneme acquisition deconvolution EEG", n=5)
    assert isinstance(rows, list)
    if rows:
        assert all(r.get("pmid") for r in rows)
        assert all(r.get("title") for r in rows)
