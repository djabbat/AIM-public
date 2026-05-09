"""tests/test_citation_guard.py — R1 (2026-05-03)."""
from __future__ import annotations

import pytest

from agents import citation_guard as cg


@pytest.fixture(autouse=True)
def _clean_cache():
    cg.reset_cache()
    yield
    cg.reset_cache()


# ── extraction ────────────────────────────────────────────────────


def test_extract_pmid():
    cites = cg.extract("See PMID: 12345678 and PMID 9999.")
    kinds = [c.kind for c in cites]
    raws = [c.raw for c in cites]
    assert kinds == ["pmid", "pmid"]
    assert raws == ["12345678", "9999"]


def test_extract_doi():
    cites = cg.extract("doi 10.1073/pnas.2537697123 — see also")
    assert len(cites) == 1
    assert cites[0].kind == "doi"
    assert cites[0].raw == "10.1073/pnas.2537697123"


def test_extract_doi_strips_trailing_punct():
    cites = cg.extract("Use 10.1038/nrm.2024.5, please.")
    assert cites[0].raw == "10.1038/nrm.2024.5"


def test_extract_nct():
    cites = cg.extract("Trial NCT01234567 enrolled.")
    assert cites[0].kind == "nct"
    assert cites[0].raw == "NCT01234567"


def test_extract_arxiv_with_prefix():
    cites = cg.extract("arXiv: 2401.12345v2 paper.")
    assert cites[0].kind == "arxiv"


def test_extract_no_arxiv_on_plain_decimal():
    """0.5/1.5 mg/kg dosage shouldn't be flagged as an arXiv id."""
    cites = cg.extract("Dose 0.5/1.5 mg/kg body weight.")
    assert all(c.kind != "arxiv" for c in cites)


def test_extract_empty_input():
    assert cg.extract("") == []
    assert cg.extract(None) == []  # type: ignore


# ── verification (with mocked tools.literature) ──────────────────


def test_verify_pmid_resolves(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid",
                        lambda p: {"title": "Foo", "year": 2024})
    text = "Cite PMID: 11111."
    v = cg.verify(text)
    assert v.ok
    assert v.citations[0].resolved is True
    assert v.citations[0].title == "Foo"
    assert v.citations[0].year == 2024


def test_verify_pmid_fails(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    v = cg.verify("Cite PMID: 99999.")
    assert not v.ok
    assert "fabricated" in v.unresolved[0].note


def test_verify_doi_resolves(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_doi",
                        lambda d: {"title": "Bar", "year": 2025})
    v = cg.verify("Use 10.1234/foo.bar")
    assert v.ok
    assert v.citations[0].title == "Bar"


def test_verify_strict_raises(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setattr(lit, "verify_doi", lambda d: None)
    with pytest.raises(cg.CitationError) as ei:
        cg.verify("PMID: 99999 and 10.1234/x", strict=True)
    assert "unverified" in str(ei.value)


def test_verify_no_citations_returns_ok():
    v = cg.verify("Just a paragraph with no refs.")
    assert v.ok
    assert v.citations == []


def test_verify_offline_safe(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setenv("AIM_NO_NETWORK", "1")
    v = cg.verify("PMID: 123", offline_ok=True)
    assert v.ok   # treated as unknown, not failure


def test_verify_caches_results(monkeypatch):
    import tools.literature as lit
    calls = {"n": 0}
    def stub(p):
        calls["n"] += 1
        return {"title": "T", "year": 2020}
    monkeypatch.setattr(lit, "verify_pmid", stub)
    cg.verify("PMID: 55555")
    cg.verify("PMID: 55555")
    assert calls["n"] == 1   # second call hit the cache


# ── sanitize ─────────────────────────────────────────────────────


def test_sanitize_replaces_unresolved(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    out = cg.sanitize("See PMID: 99999 for details.")
    assert "99999" not in out
    assert "[ref unverified]" in out


def test_sanitize_keeps_resolved(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid",
                        lambda p: {"title": "X", "year": 2024})
    out = cg.sanitize("See PMID: 12345 for details.")
    assert "12345" in out
    assert "unverified" not in out


def test_sanitize_handles_multiple_unresolved(monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setattr(lit, "verify_doi", lambda d: None)
    out = cg.sanitize("PMID: 11111 and 10.1234/foo are bad.")
    assert "11111" not in out
    assert out.count("[ref unverified]") == 2


# ── nct & arxiv: format-only validation ─────────────────────────


def test_nct_treated_as_format_only(monkeypatch):
    v = cg.verify("Trial NCT12345678 enrolled.")
    assert v.ok
    assert v.citations[0].resolved is True
    assert "format-validated" in v.citations[0].note


def test_arxiv_treated_as_format_only():
    v = cg.verify("arXiv: 2401.12345 paper.")
    assert v.ok
    assert v.citations[0].resolved is True
