"""agents/regimen_validator.py — strict regimen validator (D1, 2026-05-03;
Phase 8 hybrid 2026-05-07).

Wraps `agents.interactions.check_regimen` (now a Rust-backed shim) with
a hard-refusal layer:

  1. Contraindicated pair → ALWAYS refuse, no override.
  2. Major pair → refuse unless ``physician_override=True``.
  3. Moderate pair → warn (returned), do not refuse.
  4. Minor / no_known → silent.

The drug-pair table + canonicalization live entirely in Rust
(`rust-core/crates/aim-interactions`). The bucketing / refusal
classification (this file) stays in Python because it's small (~50
LoC), unit-tested via `tests/test_regimen_validator.py` with
`monkeypatch.setattr(rv, "check_regimen", ...)`, and is mirrored in the
Rust crate `aim-regimen-validator` for contexts where Python is not
available (e.g., Phoenix LiveView calling the binary directly).

Public API:
    validate(drugs, *, physician_override=False) -> Validation
    validate_or_raise(...)                                  → raises RegimenError
    annotate(report_text, drugs, ...)                       → str
    RegimenError
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Iterable

log = logging.getLogger("aim.regimen")

try:
    from agents.interactions import (
        Interaction,
        check_regimen,
        SEVERITY_ORDER,  # type: ignore
    )
except ImportError:  # pragma: no cover
    Interaction = object  # type: ignore
    SEVERITY_ORDER = {"contraindicated": 0, "major": 1, "moderate": 2,
                      "minor": 3, "no_known": 4}
    def check_regimen(_drugs):  # type: ignore
        return []


class RegimenError(Exception):
    pass


@dataclasses.dataclass
class Validation:
    interactions: list
    contraindicated: list
    major: list
    moderate: list
    safe_drugs: list[str]
    must_drop: list[str]
    monitoring_required: list[str]
    refused: bool
    summary: str

    def to_dict(self) -> dict:
        return {
            "refused": self.refused,
            "summary": self.summary,
            "must_drop": self.must_drop,
            "monitoring_required": self.monitoring_required,
            "safe_drugs": self.safe_drugs,
            "contraindicated_pairs": [(i.drug_a, i.drug_b) for i in self.contraindicated],
            "major_pairs": [(i.drug_a, i.drug_b) for i in self.major],
            "moderate_pairs": [(i.drug_a, i.drug_b) for i in self.moderate],
        }


def _bucket(interactions: Iterable) -> tuple[list, list, list]:
    contraindicated, major, moderate = [], [], []
    for ix in interactions:
        sev = getattr(ix, "severity", "no_known")
        if sev == "contraindicated":
            contraindicated.append(ix)
        elif sev == "major":
            major.append(ix)
        elif sev == "moderate":
            moderate.append(ix)
    return contraindicated, major, moderate


def validate(drugs: list[str], *,
             physician_override: bool = False) -> Validation:
    """Run check_regimen and classify the outcome.

    `physician_override=True` allows MAJOR pairs through (still warned)
    but NEVER allows contraindicated pairs — those are absolute.
    """
    drugs = [d for d in (drugs or []) if d and d.strip()]
    interactions = check_regimen(drugs)
    contraindicated, major, moderate = _bucket(interactions)

    must_drop: set[str] = set()
    monitoring_required: set[str] = set()
    for ix in contraindicated:
        must_drop.add(ix.drug_a)
        must_drop.add(ix.drug_b)
    if not physician_override:
        for ix in major:
            must_drop.add(ix.drug_a)
            must_drop.add(ix.drug_b)
    else:
        for ix in major:
            monitoring_required.add(ix.drug_a)
            monitoring_required.add(ix.drug_b)
    for ix in moderate:
        monitoring_required.add(ix.drug_a)
        monitoring_required.add(ix.drug_b)

    refused = bool(contraindicated) or (bool(major) and not physician_override)
    safe_drugs = sorted(set(drugs) - must_drop)

    pieces: list[str] = []
    if contraindicated:
        pieces.append(f"{len(contraindicated)} CONTRAINDICATED")
    if major:
        pieces.append(f"{len(major)} major")
    if moderate:
        pieces.append(f"{len(moderate)} moderate")
    if not pieces:
        pieces.append("no flagged pairs")
    summary = "regimen review: " + ", ".join(pieces)

    return Validation(
        interactions=list(interactions),
        contraindicated=contraindicated,
        major=major,
        moderate=moderate,
        safe_drugs=safe_drugs,
        must_drop=sorted(must_drop),
        monitoring_required=sorted(monitoring_required - must_drop),
        refused=refused,
        summary=summary,
    )


def validate_or_raise(drugs: list[str], *,
                      physician_override: bool = False) -> Validation:
    """Same as validate() but raises RegimenError on hard refusal."""
    v = validate(drugs, physician_override=physician_override)
    if v.refused:
        first = (v.contraindicated + v.major)[0]
        raise RegimenError(
            f"{v.summary} — refusing regimen. "
            f"Offending pair: {first.drug_a} + {first.drug_b} "
            f"({first.severity}): {getattr(first, 'recommendation', '')}"
        )
    return v


def annotate(draft_text: str, drugs: list[str], *,
             physician_override: bool = False) -> str:
    """Append a regimen-validation footer to a doctor's draft.

    Used by `agents.doctor` to attach a machine-readable validation
    block so the user can audit any prescription advice.
    """
    v = validate(drugs, physician_override=physician_override)
    if not (v.contraindicated or v.major or v.moderate):
        return draft_text
    bits = [draft_text.rstrip(), "", "─── Regimen safety review ───"]
    if v.contraindicated:
        bits.append("⛔ CONTRAINDICATED — must not co-administer:")
        for ix in v.contraindicated:
            bits.append(f"   • {ix.drug_a} + {ix.drug_b} — "
                        f"{getattr(ix, 'recommendation', '')}")
    if v.major:
        marker = ("⚠️ MAJOR (override active)" if physician_override
                  else "⛔ MAJOR — refused without physician_override")
        bits.append(f"{marker}:")
        for ix in v.major:
            bits.append(f"   • {ix.drug_a} + {ix.drug_b} — "
                        f"{getattr(ix, 'recommendation', '')}")
    if v.moderate:
        bits.append("🟡 MODERATE — monitoring required:")
        for ix in v.moderate:
            bits.append(f"   • {ix.drug_a} + {ix.drug_b} — "
                        f"{getattr(ix, 'recommendation', '')}")
    if v.must_drop:
        bits.append("")
        bits.append("must drop: " + ", ".join(v.must_drop))
    if v.monitoring_required:
        bits.append("monitoring: " + ", ".join(v.monitoring_required))
    return "\n".join(bits)
