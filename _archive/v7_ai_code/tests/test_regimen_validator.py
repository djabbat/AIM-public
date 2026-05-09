"""tests/test_regimen_validator.py — D1 regimen validator (2026-05-03)."""
from __future__ import annotations

import pytest

from agents import regimen_validator as rv


def _ix(a, b, severity, recommendation="watch out"):
    """Lightweight stand-in for Interaction."""
    from agents.interactions import Interaction
    return Interaction(
        drug_a=a, drug_b=b, severity=severity,
        mechanism="test mechanism",
        recommendation=recommendation,
        source="test",
    )


# ── bucket / classification ──────────────────────────────────────


def test_validate_no_drugs_returns_clean():
    v = rv.validate([])
    assert not v.refused
    assert v.must_drop == [] and v.monitoring_required == []


def test_validate_no_known_pairs(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [])
    v = rv.validate(["paracetamol", "vitamin-c"])
    assert not v.refused
    assert v.safe_drugs == ["paracetamol", "vitamin-c"]


def test_contraindicated_always_refuses(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("warfarin", "aspirin", "contraindicated")])
    v = rv.validate(["warfarin", "aspirin"], physician_override=True)
    assert v.refused
    assert "warfarin" in v.must_drop and "aspirin" in v.must_drop


def test_major_refuses_without_override(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    v = rv.validate(["ssri", "maoi"])
    assert v.refused
    assert v.must_drop == ["maoi", "ssri"]


def test_major_allowed_with_override(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    v = rv.validate(["ssri", "maoi"], physician_override=True)
    assert not v.refused
    assert v.monitoring_required == ["maoi", "ssri"]


def test_moderate_warns_only(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("a", "b", "moderate")])
    v = rv.validate(["a", "b"])
    assert not v.refused
    assert v.monitoring_required == ["a", "b"]
    assert v.must_drop == []


def test_minor_and_no_known_silent(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [
        _ix("x", "y", "minor"), _ix("y", "z", "no_known"),
    ])
    v = rv.validate(["x", "y", "z"])
    assert not v.refused
    assert v.must_drop == [] and v.monitoring_required == []


def test_safe_drugs_excludes_dropped(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [
        _ix("dangerous-1", "dangerous-2", "contraindicated"),
        _ix("warn-1", "warn-2", "moderate"),
    ])
    v = rv.validate(["dangerous-1", "dangerous-2", "warn-1", "warn-2", "lone"])
    assert "dangerous-1" not in v.safe_drugs
    assert "dangerous-2" not in v.safe_drugs
    assert "warn-1" in v.safe_drugs    # moderate doesn't drop
    assert "lone" in v.safe_drugs


def test_summary_string(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [
        _ix("a", "b", "contraindicated"),
        _ix("c", "d", "major"),
    ])
    v = rv.validate(["a", "b", "c", "d"])
    assert "1 CONTRAINDICATED" in v.summary
    assert "1 major" in v.summary


# ── validate_or_raise ────────────────────────────────────────────


def test_validate_or_raise_lets_clean_through(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [])
    v = rv.validate_or_raise(["paracetamol"])
    assert not v.refused


def test_validate_or_raise_blocks_contraindicated(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("warfarin", "aspirin",
                                            "contraindicated",
                                            "Avoid combination.")])
    with pytest.raises(rv.RegimenError) as ei:
        rv.validate_or_raise(["warfarin", "aspirin"])
    assert "warfarin" in str(ei.value)
    assert "Avoid" in str(ei.value)


def test_validate_or_raise_respects_override(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    v = rv.validate_or_raise(["ssri", "maoi"], physician_override=True)
    assert not v.refused


# ── annotate ─────────────────────────────────────────────────────


def test_annotate_appends_review_footer(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [
        _ix("a", "b", "contraindicated", "do NOT mix"),
    ])
    out = rv.annotate("Take A 100mg + B 50mg.", ["a", "b"])
    assert "Take A 100mg" in out
    assert "Regimen safety review" in out
    assert "do NOT mix" in out
    assert "must drop" in out


def test_annotate_clean_returns_unchanged(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen", lambda _drugs: [])
    out = rv.annotate("Take vitamin C.", ["vitamin-c"])
    assert out == "Take vitamin C."


def test_annotate_marks_major_override(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major", "monitor BP")])
    out = rv.annotate("Combo regimen.", ["ssri", "maoi"],
                      physician_override=True)
    assert "override active" in out
    assert "monitor BP" in out


def test_annotate_no_override_blocks(monkeypatch):
    monkeypatch.setattr(rv, "check_regimen",
                        lambda _drugs: [_ix("ssri", "maoi", "major")])
    out = rv.annotate("Combo regimen.", ["ssri", "maoi"])
    assert "refused without physician_override" in out


# ── empty/edge inputs ────────────────────────────────────────────


def test_validate_strips_blanks(monkeypatch):
    seen = []
    def stub(drugs):
        seen.append(list(drugs))
        return []
    monkeypatch.setattr(rv, "check_regimen", stub)
    rv.validate(["", "  ", "real"])
    assert seen == [["real"]]


def test_to_dict_serialises():
    v = rv.Validation(
        interactions=[], contraindicated=[], major=[], moderate=[],
        safe_drugs=["x"], must_drop=[], monitoring_required=[],
        refused=False, summary="ok",
    )
    d = v.to_dict()
    assert d["refused"] is False
    assert d["safe_drugs"] == ["x"]
