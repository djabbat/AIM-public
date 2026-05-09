"""agents/doctor_consult.py — structured diagnostic flow (DC1, 2026-05-03).

A higher-order doctor entry point that composes:

  * intake   — structured patient input (chief complaint, history, exam, labs)
  * differential — top-N hypotheses with confidence + rationale
  * regimen  — proposed treatment plan with drug list
  * dry_run  — citation_guard + regimen_validator
  * calibration log — record predictions for D2

The actual diagnosis logic still lives in `agents.doctor`; this module
is a contract that bundles the pre/post safety stack into a single
function so callers (CLI, Telegram bot, web API) get all guards "for
free".

Public API:
    consult(intake, *, doctor_fn=None, physician_override=False) -> Consult
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from typing import Any, Callable, Optional

log = logging.getLogger("aim.doctor_consult")


# ── input / output dataclasses ───────────────────────────────────


@dataclasses.dataclass
class Intake:
    chief_complaint: str
    age: Optional[int] = None
    sex: Optional[str] = None
    history: str = ""
    exam: str = ""
    labs: str = ""
    drugs: list[str] = dataclasses.field(default_factory=list)
    case_id: Optional[str] = None

    def as_prompt(self) -> str:
        bits: list[str] = [f"Chief complaint: {self.chief_complaint}"]
        if self.age is not None:
            bits.append(f"Age: {self.age}")
        if self.sex:
            bits.append(f"Sex: {self.sex}")
        if self.history:
            bits.append(f"History: {self.history}")
        if self.exam:
            bits.append(f"Exam: {self.exam}")
        if self.labs:
            bits.append(f"Labs: {self.labs}")
        if self.drugs:
            bits.append(f"Current regimen: {', '.join(self.drugs)}")
        return "\n".join(bits)


@dataclasses.dataclass
class Hypothesis:
    label: str
    confidence: float
    rationale: str


@dataclasses.dataclass
class Consult:
    intake: Intake
    differential: list[Hypothesis]
    regimen_text: str
    safety_text: str
    citation_issues: list[str]
    refused: bool
    refusal_reason: Optional[str] = None


# ── default doctor stub (deterministic — for tests / fallback) ───


def _default_doctor(intake: Intake) -> tuple[list[Hypothesis], str]:
    """Trivial fallback: returns a single low-confidence hypothesis based
    on the chief complaint. Replaced at runtime by agents.doctor.diagnose."""
    return (
        [Hypothesis(label=f"Symptomatic ({intake.chief_complaint[:40]})",
                    confidence=0.3,
                    rationale="No domain-specific reasoning available; "
                              "treat symptomatically pending workup.")],
        "Workup: see clinic for full evaluation. No regimen prescribed "
        "from this stub.",
    )


# ── consult() ────────────────────────────────────────────────────


def consult(intake: Intake,
            *,
            doctor_fn: Optional[Callable[[Intake],
                                          tuple[list[Hypothesis], str]]] = None,
            physician_override: bool = False,
            ) -> Consult:
    """Run the full diagnostic stack on the intake. Always returns a
    Consult; refused flag indicates the regimen layer hard-rejected
    a contraindicated combination — in that case `regimen_text` is
    blank and the refusal is in `refusal_reason`."""
    fn = doctor_fn or _default_doctor

    # 1. Get hypotheses + draft regimen.
    try:
        hypotheses, draft = fn(intake)
    except Exception as e:
        log.warning("doctor_fn raised: %s", e)
        hypotheses, draft = (
            [Hypothesis(label="(diagnostic engine failed)",
                         confidence=0.0,
                         rationale=str(e))],
            ""
        )

    # 2. Calibration log: persist each hypothesis as a Prediction (D2).
    try:
        from agents.doctor_calibration import record
        for h in hypotheses:
            record(label=h.label, confidence=h.confidence,
                   case_id=intake.case_id, domain="diagnosis",
                   rationale=h.rationale[:1000])
    except Exception as e:
        log.debug("calibration record failed: %s", e)

    # 3. Run draft through dry_run (citation_guard + regimen_validator).
    refused = False
    refusal_reason: Optional[str] = None
    citation_issues: list[str] = []
    safe_regimen = draft
    try:
        from agents.doctor_dry_run import dry_run
        from agents.regimen_validator import RegimenError
        result = dry_run(draft, drugs=intake.drugs,
                          physician_override=physician_override)
        safe_regimen = result.text
        citation_issues = list(result.citation_issues)
    except RegimenError as e:
        refused = True
        refusal_reason = str(e)
        safe_regimen = ""
    except Exception as e:
        log.warning("dry_run failed: %s", e)

    safety_text = ""
    if citation_issues:
        safety_text = ("Soft citation warnings: "
                        + ", ".join(citation_issues[:5]))

    return Consult(
        intake=intake,
        differential=hypotheses,
        regimen_text=safe_regimen,
        safety_text=safety_text,
        citation_issues=citation_issues,
        refused=refused,
        refusal_reason=refusal_reason,
    )


def consult_summary(c: Consult) -> str:
    """Pretty-print a Consult for CLI / Telegram."""
    parts: list[str] = []
    parts.append(f"🩺 Consult — chief complaint: "
                  f"{c.intake.chief_complaint[:80]}")
    if c.differential:
        parts.append("Differential:")
        for h in c.differential[:5]:
            parts.append(f"  • {h.label}  ({h.confidence:.0%}) — "
                         f"{h.rationale[:120]}")
    if c.refused:
        parts.append(f"❌ Regimen refused: {c.refusal_reason}")
    elif c.regimen_text:
        parts.append("Regimen:")
        for line in c.regimen_text.splitlines():
            parts.append(f"  {line}")
    if c.safety_text:
        parts.append(f"⚠ {c.safety_text}")
    return "\n".join(parts)
