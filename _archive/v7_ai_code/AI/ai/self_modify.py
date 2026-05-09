"""AI/ai/self_modify.py — thin Python shim over the
`aim-ai-self-modify` Rust binary (Phase 9 Tier 2 #3, 2026-05-07).

Code self-modification framework (S6). Gate closed by default.
All gate logic + proposal building in Rust crate
`rust-core/crates/aim-ai-self-modify`.

Public API (preserved):
    Verdict / Proposal / ApplyResult dataclasses
    can_self_modify() -> Verdict
    propose(finding_ref) -> Proposal
    apply(proposal, *, dry_run=True) -> ApplyResult
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

log = logging.getLogger("ai.self_modify")


@dataclasses.dataclass
class Verdict:
    allowed: bool
    reasons: list[str]
    n_baseline_runs: int
    baseline_age_days: float


@dataclasses.dataclass
class Proposal:
    finding_ref: str
    target_path: Path
    summary: str
    patch_unified: str
    eval_case_id: Optional[str] = None


@dataclasses.dataclass
class ApplyResult:
    proposal: Proposal
    applied: bool
    worktree_path: Optional[Path]
    pre_eval_score: Optional[float]
    post_eval_score: Optional[float]
    notes: list[str]


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-self-modify"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-self-modify binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-self-modify {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _verdict_from_json(j: dict) -> Verdict:
    return Verdict(
        allowed=bool(j["allowed"]),
        reasons=list(j.get("reasons") or []),
        n_baseline_runs=int(j["n_baseline_runs"]),
        baseline_age_days=float(j["baseline_age_days"]),
    )


def _proposal_from_json(j: dict) -> Proposal:
    return Proposal(
        finding_ref=str(j["finding_ref"]),
        target_path=Path(j["target_path"]),
        summary=str(j["summary"]),
        patch_unified=str(j.get("patch_unified", "")),
        eval_case_id=j.get("eval_case_id"),
    )


def can_self_modify() -> Verdict:
    out = _run(["can-self-modify"]).strip()
    return _verdict_from_json(json.loads(out))


def propose(finding_ref: str) -> Proposal:
    """Build a Proposal struct for `finding_ref`."""
    out = _run(["propose", finding_ref]).strip()
    return _proposal_from_json(json.loads(out))


def apply(proposal: Proposal, *, dry_run: bool = True) -> ApplyResult:
    """Apply a Proposal in an isolated worktree. Currently always dry_run
    until baseline matures."""
    args = ["apply", proposal.finding_ref]
    if not dry_run:
        args.append("--no-dry-run")
    out = _run(args).strip()
    j = json.loads(out)
    p_json = j["proposal"]
    return ApplyResult(
        proposal=_proposal_from_json(p_json),
        applied=bool(j["applied"]),
        worktree_path=Path(j["worktree_path"]) if j.get("worktree_path") else None,
        pre_eval_score=(
            float(j["pre_eval_score"]) if j.get("pre_eval_score") is not None else None
        ),
        post_eval_score=(
            float(j["post_eval_score"]) if j.get("post_eval_score") is not None else None
        ),
        notes=list(j.get("notes") or []),
    )


def summary() -> str:
    """Original Python format preserved."""
    v = can_self_modify()
    if v.allowed:
        return ("🟢 self-modify gate OPEN — baseline mature.\n"
                f"  runs={v.n_baseline_runs}  age={v.baseline_age_days:.1f}d")
    parts = ["🔒 self-modify gate CLOSED",
             f"  runs={v.n_baseline_runs}  age={v.baseline_age_days:.1f}d"]
    for r in v.reasons:
        parts.append(f"  - {r}")
    return "\n".join(parts)
