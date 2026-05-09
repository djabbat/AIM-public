"""tests/test_doctor_dry_run.py — DR1 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path))
    import importlib, sys
    if "agents.doctor_dry_run" in sys.modules:
        importlib.reload(sys.modules["agents.doctor_dry_run"])
    return tmp_path


def _ix(a, b, severity, recommendation="watch out"):
    from agents.interactions import Interaction
    return Interaction(drug_a=a, drug_b=b, severity=severity,
                       mechanism="test", recommendation=recommendation,
                       source="test")


# ── happy path ───────────────────────────────────────────────────


def test_clean_draft_passes_through(isolated, monkeypatch):
    """No citations, no drugs → text unchanged."""
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setattr(lit, "verify_doi",  lambda d: None)
    from agents.doctor_dry_run import dry_run
    out = dry_run("Drink water and rest.")
    assert out.text == "Drink water and rest."
    assert out.citation_issues == []
    assert out.regimen is None


def test_unresolved_citation_replaced(isolated, monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setattr(lit, "verify_doi", lambda d: None)
    from agents.doctor_dry_run import dry_run
    out = dry_run("See PMID: 99999 for evidence.")
    assert "99999" not in out.text
    assert "[ref unverified]" in out.text
    assert "pmid:99999" in out.citation_issues


def test_resolved_citation_kept(isolated, monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid",
                        lambda p: {"title": "Real", "year": 2024})
    from agents.doctor_dry_run import dry_run
    out = dry_run("See PMID: 12345 for evidence.")
    assert "12345" in out.text
    assert out.citation_issues == []


# ── strict mode ──────────────────────────────────────────────────


def test_strict_citations_raises(isolated, monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    from agents.doctor_dry_run import dry_run
    from agents.citation_guard import CitationError
    with pytest.raises(CitationError):
        dry_run("PMID: 99999", strict_citations=True)


# ── regimen ──────────────────────────────────────────────────────


def test_regimen_clean_appends_no_footer(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [])
    from agents.doctor_dry_run import dry_run
    out = dry_run("Plan: vitamin C.", drugs=["vitamin-c"])
    assert "Regimen safety review" not in out.text
    assert out.regimen is not None
    assert not out.regimen.refused


def test_regimen_moderate_annotates(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("a", "b", "moderate")])
    from agents.doctor_dry_run import dry_run
    out = dry_run("Plan: a + b.", drugs=["a", "b"])
    assert "MODERATE" in out.text
    assert "Regimen safety review" in out.text


def test_regimen_contraindicated_raises(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("warfarin", "aspirin",
                                            "contraindicated")])
    from agents.doctor_dry_run import dry_run
    from agents.regimen_validator import RegimenError
    with pytest.raises(RegimenError):
        dry_run("Plan", drugs=["warfarin", "aspirin"])


def test_regimen_major_blocked_without_override(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    from agents.doctor_dry_run import dry_run
    from agents.regimen_validator import RegimenError
    with pytest.raises(RegimenError):
        dry_run("Plan", drugs=["ssri", "maoi"])


def test_regimen_major_passes_with_override(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    from agents.doctor_dry_run import dry_run
    out = dry_run("Plan", drugs=["ssri", "maoi"],
                   physician_override=True)
    assert "MAJOR (override active)" in out.text
    assert not out.regimen.refused


def test_no_drugs_no_regimen_check(isolated, monkeypatch):
    """Empty drugs list → regimen field stays None and check_regimen never called."""
    from agents import regimen_validator as rv
    seen = []
    monkeypatch.setattr(rv, "check_regimen",
                        lambda d: seen.append(d) or [])
    from agents.doctor_dry_run import dry_run
    out = dry_run("clean", drugs=[])
    assert out.regimen is None
    assert seen == []


def test_blank_drugs_filtered(isolated, monkeypatch):
    from agents import regimen_validator as rv
    seen = []
    def stub(drugs):
        seen.append(list(drugs))
        return []
    monkeypatch.setattr(rv, "check_regimen", stub)
    from agents.doctor_dry_run import dry_run
    dry_run("plan", drugs=["", "  ", "real"])
    # validate_or_raise + annotate each call check_regimen separately;
    # the important property is that blanks were dropped before either.
    assert seen and all(c == ["real"] for c in seen)


# ── audit log ────────────────────────────────────────────────────


def test_audit_records_each_call(isolated, monkeypatch):
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen", lambda _: [])
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    from agents.doctor_dry_run import dry_run, history
    dry_run("PMID: 11111 OK")
    dry_run("clean", drugs=["x"])
    h = history()
    assert len(h) == 2
    assert h[0]["n_citation_issues"] == 1
    assert h[1]["n_drugs"] == 1
