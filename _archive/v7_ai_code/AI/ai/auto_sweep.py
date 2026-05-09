"""AI/ai/auto_sweep.py — thin Python shim over the
`aim-ai-sweep` Rust binary (Phase 9 Tier 4 #23, 2026-05-07).

Periodic maintenance sweep: fingerprint prompt → validate cases →
archive stale cases → prompt impact → prune phantom ledger rows →
prune expired suppressions → snapshot health score.

The Rust crate `aim-ai-auto-sweep` owns the orchestration; Python
keeps the same `SweepResult` dataclass shape.

Public API (preserved):
    SweepResult dataclass (with `all_clean` property)
    sweep(*, dry_run=False) -> SweepResult
    summary(*, dry_run=False) -> str
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.auto_sweep")


@dataclasses.dataclass
class SweepResult:
    started_at: str
    finished_at: str
    prompt_recorded: bool
    prompt_changed: Optional[bool]
    n_cases_validated: int
    n_cases_invalid: int
    n_archived_candidates: int
    n_archived_moved: int
    n_prompt_revisions: int
    n_phantom_removed: int = 0
    notes: list[str] = dataclasses.field(default_factory=list)

    @property
    def all_clean(self) -> bool:
        return self.n_cases_invalid == 0


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-sweep"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-sweep binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-sweep failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def sweep(*, dry_run: bool = False) -> SweepResult:
    args = ["--json"]
    if dry_run:
        args.append("--dry-run")
    j = json.loads(_run(args).strip())
    return SweepResult(
        started_at=str(j.get("started_at", "")),
        finished_at=str(j.get("finished_at", "")),
        prompt_recorded=bool(j.get("prompt_recorded", False)),
        prompt_changed=j.get("prompt_changed"),
        n_cases_validated=int(j.get("n_cases_validated", 0)),
        n_cases_invalid=int(j.get("n_cases_invalid", 0)),
        n_archived_candidates=int(j.get("n_archived_candidates", 0)),
        n_archived_moved=int(j.get("n_archived_moved", 0)),
        n_prompt_revisions=int(j.get("n_prompt_revisions", 0)),
        n_phantom_removed=int(j.get("n_phantom_removed", 0)),
        notes=list(j.get("notes", [])),
    )


def summary(*, dry_run: bool = False) -> str:
    args: list[str] = []
    if dry_run:
        args.append("--dry-run")
    return _run(args).rstrip("\n")
