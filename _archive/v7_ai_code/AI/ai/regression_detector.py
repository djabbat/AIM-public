"""AI/ai/regression_detector.py — thin Python shim over the
`aim-ai-regression` Rust binary (Phase 9 Tier 2 #5, 2026-05-07).

Compare the two most recent self-diagnostic runs and flag NEW
critical findings. All logic + finding-set diff in Rust crate
`rust-core/crates/aim-ai-regression`.

Public API (preserved):
    Regression dataclass + grade_improved / grade_worsened /
                          regressed / improved properties
    detect() -> Regression
    summary() -> str

Env: AI_DIAGNOSTIC_DB.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.regression_detector")


@dataclasses.dataclass
class Regression:
    have_baseline: bool
    prev_ts: Optional[str]
    curr_ts: Optional[str]
    prev_grade: Optional[str]
    curr_grade: Optional[str]
    prev_crit: Optional[int]
    curr_crit: Optional[int]
    prev_findings: set[str]
    curr_findings: set[str]
    new_findings: set[str]
    fixed_findings: set[str]

    @property
    def grade_improved(self) -> bool:
        if self.prev_grade is None or self.curr_grade is None:
            return False
        return self.curr_grade < self.prev_grade

    @property
    def grade_worsened(self) -> bool:
        if self.prev_grade is None or self.curr_grade is None:
            return False
        return self.curr_grade > self.prev_grade

    @property
    def regressed(self) -> bool:
        if self.grade_improved:
            return False
        if self.new_findings:
            return True
        if (self.prev_crit is not None and self.curr_crit is not None
                and self.curr_crit > self.prev_crit):
            return True
        return False

    @property
    def improved(self) -> bool:
        return (
            (not self.regressed) and
            (self.grade_improved or
             bool(self.fixed_findings) or
             (self.prev_crit is not None and self.curr_crit is not None
              and self.curr_crit < self.prev_crit))
        )


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-regression"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-regression binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-regression {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def detect() -> Regression:
    """Pull the last two ledger rows; diff their finding sets via Rust."""
    out = _run(["detect"]).strip()
    j = json.loads(out)
    new_set = set(j.get("new_findings") or [])
    # Apply Python-side suppression filter (kept here because the
    # suppressions module is still pure Python until its own port).
    try:
        from AI.ai.finding_suppressions import filter_findings
        new_set = set(filter_findings(new_set))
    except Exception as e:
        log.debug("suppression filter skipped: %s", e)
    return Regression(
        have_baseline=bool(j["have_baseline"]),
        prev_ts=j.get("prev_ts"),
        curr_ts=j.get("curr_ts"),
        prev_grade=j.get("prev_grade"),
        curr_grade=j.get("curr_grade"),
        prev_crit=j.get("prev_crit"),
        curr_crit=j.get("curr_crit"),
        prev_findings=set(j.get("prev_findings") or []),
        curr_findings=set(j.get("curr_findings") or []),
        new_findings=new_set,
        fixed_findings=set(j.get("fixed_findings") or []),
    )


def summary() -> str:
    """Original Python format preserved (more verbose than Rust binary's
    plain `summary` subcommand) — supports suppression-filtered findings."""
    r = detect()
    if not r.have_baseline:
        return ("(no baseline — need at least 2 diagnostic runs in the "
                "ledger before regression detection works)")
    parts = [
        f"🔍 Regression check — {r.prev_ts[:19]} → {r.curr_ts[:19]}",
        f"  grade:  {r.prev_grade or '?'} → {r.curr_grade or '?'}",
        f"  crit:   {r.prev_crit if r.prev_crit is not None else '?'} → "
        f"{r.curr_crit if r.curr_crit is not None else '?'}",
        f"  new findings:   {len(r.new_findings)}",
        f"  fixed findings: {len(r.fixed_findings)}",
    ]
    if r.regressed:
        parts.append("  ⚠ REGRESSED — new critical issues this run:")
        for f in sorted(r.new_findings)[:10]:
            parts.append(f"    • {f}")
        if len(r.new_findings) > 10:
            parts.append(f"    (+{len(r.new_findings) - 10} more)")
    elif r.improved:
        parts.append("  ✅ IMPROVED")
        for f in sorted(r.fixed_findings)[:5]:
            parts.append(f"    • fixed: {f}")
    else:
        parts.append("  = stable (no new findings, no fixes)")
    return "\n".join(parts)
