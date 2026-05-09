"""tests/test_doctor_consult.py — DC1 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_CALIBRATION_DB", str(tmp_path / "calib.db"))
    import importlib, sys
    for m in ["agents.doctor_calibration", "agents.doctor_dry_run",
              "agents.doctor_consult"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def _ix(a, b, severity, recommendation="watch"):
    from agents.interactions import Interaction
    return Interaction(drug_a=a, drug_b=b, severity=severity,
                       mechanism="test", recommendation=recommendation,
                       source="test")


# ── Intake.as_prompt ─────────────────────────────────────────────


def test_intake_as_prompt(isolated):
    from agents.doctor_consult import Intake
    i = Intake(chief_complaint="chest pain", age=62, sex="M",
                history="HTN", exam="ECG ST-elev", labs="trop+",
                drugs=["aspirin"])
    s = i.as_prompt()
    assert "chest pain" in s
    assert "Age: 62" in s
    assert "Sex: M" in s
    assert "History: HTN" in s
    assert "aspirin" in s


def test_intake_omits_blank_fields(isolated):
    from agents.doctor_consult import Intake
    s = Intake(chief_complaint="cough").as_prompt()
    assert "Cough" in s.title() or "cough" in s
    assert "Age" not in s
    assert "Labs" not in s


# ── consult() default doctor ────────────────────────────────────


def test_default_doctor_returns_one_hypothesis(isolated):
    from agents.doctor_consult import Intake, consult
    res = consult(Intake(chief_complaint="headache"))
    assert len(res.differential) == 1
    assert res.differential[0].confidence == 0.3
    assert not res.refused


# ── consult() with custom doctor_fn ─────────────────────────────


def test_consult_dispatches_doctor_fn(isolated):
    from agents.doctor_consult import Intake, Hypothesis, consult

    def doctor(intake):
        return ([Hypothesis("STEMI", 0.7, "ST-elev II/III/aVF")],
                "Aspirin 325 mg + PCI within 90 min.")

    res = consult(Intake(chief_complaint="chest pain"),
                   doctor_fn=doctor)
    assert res.differential[0].label == "STEMI"
    assert "Aspirin" in res.regimen_text


def test_consult_handles_doctor_failure(isolated):
    from agents.doctor_consult import Intake, consult
    def boom(_intake):
        raise RuntimeError("model timeout")
    res = consult(Intake(chief_complaint="x"), doctor_fn=boom)
    assert "engine failed" in res.differential[0].label
    assert res.regimen_text == ""


# ── citation guard integration ──────────────────────────────────


def test_consult_sanitises_unverified_citations(isolated, monkeypatch):
    from agents.doctor_consult import Intake, Hypothesis, consult
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)

    def doctor(_):
        return ([Hypothesis("X", 0.5, "see PMID: 99999")],
                "Take aspirin. Reference PMID: 99999 supports.")

    res = consult(Intake(chief_complaint="x"), doctor_fn=doctor)
    assert "99999" not in res.regimen_text
    assert "[ref unverified]" in res.regimen_text
    assert res.citation_issues
    assert "Soft citation" in res.safety_text


# ── regimen refusal ─────────────────────────────────────────────


def test_consult_refuses_contraindicated_pair(isolated, monkeypatch):
    from agents.doctor_consult import Intake, Hypothesis, consult
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda d: [_ix("warfarin", "aspirin",
                                        "contraindicated")])

    def doctor(_):
        return ([Hypothesis("MI", 0.9, "...")],
                "Combine warfarin + aspirin daily.")

    res = consult(Intake(chief_complaint="MI",
                          drugs=["warfarin", "aspirin"]),
                   doctor_fn=doctor)
    assert res.refused
    assert "warfarin" in res.refusal_reason
    assert res.regimen_text == ""


def test_consult_major_blocked_without_override(isolated, monkeypatch):
    from agents.doctor_consult import Intake, Hypothesis, consult
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda d: [_ix("ssri", "maoi", "major")])

    def doctor(_):
        return ([Hypothesis("MDD", 0.7, "...")], "ssri + maoi")

    res = consult(Intake(chief_complaint="depression",
                          drugs=["ssri", "maoi"]),
                   doctor_fn=doctor,
                   physician_override=False)
    assert res.refused


def test_consult_major_passes_with_override(isolated, monkeypatch):
    from agents.doctor_consult import Intake, Hypothesis, consult
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda d: [_ix("ssri", "maoi", "major")])

    def doctor(_):
        return ([Hypothesis("MDD", 0.7, "...")], "ssri + maoi.")

    res = consult(Intake(chief_complaint="x", drugs=["ssri", "maoi"]),
                   doctor_fn=doctor, physician_override=True)
    assert not res.refused
    assert "MAJOR (override active)" in res.regimen_text


# ── calibration tracker hookup ──────────────────────────────────


def test_consult_records_calibration(isolated):
    from agents.doctor_consult import Intake, Hypothesis, consult
    from agents.doctor_calibration import pending

    def doctor(_):
        return ([Hypothesis("STEMI", 0.7, "ECG"),
                 Hypothesis("PE",    0.2, "differential")],
                "Aspirin + PCI.")

    consult(Intake(chief_complaint="chest pain", case_id="case-1"),
             doctor_fn=doctor)
    rows = pending()
    assert len(rows) == 2
    labels = {r.label for r in rows}
    assert labels == {"STEMI", "PE"}


# ── consult_summary ─────────────────────────────────────────────


def test_consult_summary_renders(isolated):
    from agents.doctor_consult import Intake, Hypothesis, consult, consult_summary

    def doctor(_):
        return ([Hypothesis("Migraine", 0.6, "no red flags")],
                "Sumatriptan 50mg PRN.")

    res = consult(Intake(chief_complaint="headache"), doctor_fn=doctor)
    s = consult_summary(res)
    assert "Migraine" in s
    assert "Sumatriptan" in s


def test_consult_summary_refused_flag(isolated, monkeypatch):
    from agents.doctor_consult import Intake, Hypothesis, consult, consult_summary
    from agents import regimen_validator as rv
    monkeypatch.setattr(rv, "check_regimen",
                        lambda d: [_ix("warfarin", "aspirin",
                                        "contraindicated")])

    def doctor(_):
        return ([Hypothesis("MI", 0.8, "x")], "warfarin + aspirin")

    res = consult(Intake(chief_complaint="x",
                          drugs=["warfarin", "aspirin"]),
                   doctor_fn=doctor)
    s = consult_summary(res)
    assert "refused" in s.lower()
