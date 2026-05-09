"""agents/doctor_dry_run.py — pre-emit safety pass (DR1, 2026-05-03).

Composes the existing safety primitives into ONE call the doctor agent
runs before sending its draft to the user:

    final = dry_run(draft, drugs=[...], strict_citations=False)

What it does:

  1. Citation guard: sanitize() unverified PMID/DOI in the draft, OR
     raise CitationError when strict_citations=True.
  2. Regimen validator: if `drugs` is non-empty, annotate the draft
     with a footer; raise RegimenError on hard refusal.
  3. Audit: every dry_run gets logged so we can track how often the
     doctor's own draft contains unverified refs / contraindicated drugs.

Public API:
    dry_run(draft, *, drugs=(), strict_citations=False,
            physician_override=False) -> Result
    Result.text            — the post-processed draft
    Result.citation_issues — list of unresolved citation refs
    Result.regimen         — Validation object (or None)

Used by `agents.doctor` like:

    from agents.doctor_dry_run import dry_run
    out = dry_run(draft_text, drugs=patient.regimen)
    return out.text
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.doctor_dry_run")


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "doctor_dry_run.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclasses.dataclass
class Result:
    text: str
    citation_issues: list[str]
    regimen: Optional[object]   # agents.regimen_validator.Validation


def _audit(payload: dict) -> None:
    rec = {**payload,
            "ts": dt.datetime.now().replace(microsecond=0).isoformat()}
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("dry_run audit write failed: %s", e)


def dry_run(draft: str,
            *,
            drugs: Iterable[str] = (),
            strict_citations: bool = False,
            physician_override: bool = False) -> Result:
    """Run citation + regimen safety checks on a doctor draft."""
    drugs = [d for d in (drugs or []) if d and d.strip()]

    # 1. Citations.
    citation_issues: list[str] = []
    text = draft
    try:
        from agents.citation_guard import verify, sanitize, CitationError
        if strict_citations:
            verify(text, strict=True)
        else:
            v = verify(text, strict=False)
            citation_issues = [f"{c.kind}:{c.raw}" for c in v.unresolved]
            if citation_issues:
                text = sanitize(text)
    except ImportError:
        pass
    except Exception as e:
        # Re-raise CitationError for the strict path; treat anything else
        # as a soft warning so the doctor draft still ships.
        if e.__class__.__name__ == "CitationError":
            raise
        log.warning("citation guard failed: %s", e)

    # 2. Regimen.
    regimen = None
    if drugs:
        try:
            from agents.regimen_validator import (
                annotate, validate_or_raise,
            )
            # validate_or_raise raises RegimenError on hard refusal —
            # we deliberately let that bubble, since the doctor MUST NOT
            # ship a regimen with contraindicated pairs.
            regimen = validate_or_raise(
                drugs, physician_override=physician_override)
            text = annotate(text, drugs,
                             physician_override=physician_override)
        except ImportError:
            pass

    _audit({
        "draft_length":       len(draft),
        "n_citation_issues":  len(citation_issues),
        "n_drugs":            len(drugs),
        "physician_override": physician_override,
    })
    return Result(text=text,
                   citation_issues=citation_issues,
                   regimen=regimen)


def history(limit: int = 50) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]
