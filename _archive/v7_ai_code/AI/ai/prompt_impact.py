"""AI/ai/prompt_impact.py — thin Python shim over the
`aim-ai-prompt-impact` Rust binary (Phase 9 Tier 2 #4, 2026-05-07).

Did tightening the diagnostic prompt actually move metrics?
Joins prompt-version history with ledger runs by ts; computes
before/after compliance + avg-crit deltas around each revision.

All logic in Rust. Public API preserved:
    ImpactRow dataclass + compliance_delta / crit_delta properties
    impact_per_revision() -> list[ImpactRow]
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.prompt_impact")


@dataclasses.dataclass
class ImpactRow:
    revision_ts: str
    sha_prefix: str
    n_runs_before: int
    n_runs_after: int
    avg_compliance_before: Optional[float]
    avg_compliance_after: Optional[float]
    avg_crit_before: Optional[float]
    avg_crit_after: Optional[float]

    @property
    def compliance_delta(self) -> Optional[float]:
        if (self.avg_compliance_before is None
                or self.avg_compliance_after is None):
            return None
        return self.avg_compliance_after - self.avg_compliance_before

    @property
    def crit_delta(self) -> Optional[float]:
        if (self.avg_crit_before is None
                or self.avg_crit_after is None):
            return None
        return self.avg_crit_after - self.avg_crit_before


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-prompt-impact"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-prompt-impact binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-prompt-impact {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _row_from_json(j: dict) -> ImpactRow:
    return ImpactRow(
        revision_ts=str(j.get("revision_ts", "?")),
        sha_prefix=str(j.get("sha_prefix", "")),
        n_runs_before=int(j.get("n_runs_before", 0)),
        n_runs_after=int(j.get("n_runs_after", 0)),
        avg_compliance_before=(
            float(j["avg_compliance_before"])
            if j.get("avg_compliance_before") is not None else None
        ),
        avg_compliance_after=(
            float(j["avg_compliance_after"])
            if j.get("avg_compliance_after") is not None else None
        ),
        avg_crit_before=(
            float(j["avg_crit_before"])
            if j.get("avg_crit_before") is not None else None
        ),
        avg_crit_after=(
            float(j["avg_crit_after"])
            if j.get("avg_crit_after") is not None else None
        ),
    )


def impact_per_revision() -> list[ImpactRow]:
    out = _run(["per-revision"])
    return [_row_from_json(json.loads(line))
            for line in out.splitlines() if line.strip()]


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.0%}" if v is not None else "—"


def _fmt_float(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else "—"


def _fmt_delta_pct(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"  ({v:+.0%})"


def _fmt_delta_float(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"  ({v:+.1f})"


def summary() -> str:
    rows = impact_per_revision()
    if not rows:
        return "(no prompt revisions recorded — run record_current first)"
    parts = ["📊 Prompt-impact analysis"]
    for r in rows:
        ts = r.revision_ts[:19] if r.revision_ts != "?" else "?"
        parts.append(f"\nrev {r.sha_prefix}  {ts}")
        parts.append(f"  runs: {r.n_runs_before} before / "
                      f"{r.n_runs_after} after")
        parts.append(
            f"  compliance: {_fmt_pct(r.avg_compliance_before)} → "
            f"{_fmt_pct(r.avg_compliance_after)}"
            f"{_fmt_delta_pct(r.compliance_delta)}"
        )
        parts.append(
            f"  avg crit:   {_fmt_float(r.avg_crit_before)} → "
            f"{_fmt_float(r.avg_crit_after)}"
            f"{_fmt_delta_float(r.crit_delta)}"
        )
    return "\n".join(parts)
