"""AI/ai/case_archiver.py — thin Python shim over the
`aim-ai-case-archiver` Rust binary (Phase 9 Tier 2 #7, 2026-05-07).

When FE1 generates a regression eval case (`regr-*.yaml`) and the
underlying finding never reappears in subsequent diagnostic reports,
the case is just noise. This module moves such "resolved" cases into
`_archived/`. All slug normalisation, ledger-report scanning, and
filesystem moves now live in the Rust crate `aim-ai-case-archiver`.

Public API (preserved):
    Candidate, ArchiveResult dataclasses
    candidates(*, lookback=7, min_age_days=3) -> list[Candidate]
    archive(*, lookback=7, min_age_days=3, dry_run=False) -> ArchiveResult
    summary() -> str

Env: AI_DIAGNOSTIC_DB, AIM_EVAL_CASES_DIR, AIM_EVAL_ARCHIVE_DIR.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.case_archiver")


@dataclasses.dataclass
class Candidate:
    case_id: str
    case_path: Path
    inferred_ref_path: str
    inferred_ref_line: Optional[int]
    age_days: float


@dataclasses.dataclass
class ArchiveResult:
    n_candidates: int
    n_moved: int
    moved: list[Path]
    archive_dir: Path


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-case-archiver"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-case-archiver binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-case-archiver {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _opts_args(lookback: int, min_age_days: float) -> list[str]:
    return [
        "--lookback", str(int(lookback)),
        "--min-age-days", str(float(min_age_days)),
    ]


def candidates(*, lookback: int = 7,
               min_age_days: float = 3.0) -> list[Candidate]:
    """Return the regression cases that look ready to archive."""
    out = _run(["candidates", *_opts_args(lookback, min_age_days)])
    res: list[Candidate] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        res.append(Candidate(
            case_id=j["case_id"],
            case_path=Path(j["case_path"]),
            inferred_ref_path=j["inferred_ref_path"],
            inferred_ref_line=j.get("inferred_ref_line"),
            age_days=float(j["age_days"]),
        ))
    return res


def archive(*, lookback: int = 7,
            min_age_days: float = 3.0,
            dry_run: bool = False) -> ArchiveResult:
    args = ["archive", *_opts_args(lookback, min_age_days)]
    if not dry_run:
        args.append("--apply")
    j = json.loads(_run(args).strip())
    return ArchiveResult(
        n_candidates=int(j["n_candidates"]),
        n_moved=int(j["n_moved"]),
        moved=[Path(p) for p in j.get("moved", [])],
        archive_dir=Path(j["archive_dir"]),
    )


def summary() -> str:
    """Prefer the binary's own summary so the format stays a single
    source of truth."""
    return _run(["summary"]).rstrip("\n")
