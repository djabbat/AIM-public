"""AI/ai/case_validator.py — thin Python shim over the
`aim-ai-cases` Rust binary (Phase 9 Tier 3 #15, 2026-05-07).

Validate every yaml case in AIM_EVAL_CASES_DIR. The Rust crate owns
schema rules + YAML parsing; Python keeps the same dataclass-shaped
public API.

Public API (preserved):
    CaseStatus / Report dataclasses (Report.all_ok property)
    validate_one(path) -> CaseStatus
    validate_dir(path=None) -> Report
    summary(path=None) -> str

Env: AIM_EVAL_CASES_DIR.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.case_validator")


@dataclasses.dataclass
class CaseStatus:
    path: Path
    ok: bool
    case_id: Optional[str]
    issues: list[str]


@dataclasses.dataclass
class Report:
    n_cases: int
    n_ok: int
    n_failed: int
    statuses: list[CaseStatus]

    @property
    def all_ok(self) -> bool:
        return self.n_failed == 0


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-cases"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-cases binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-cases {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _status_from_json(j: dict) -> CaseStatus:
    return CaseStatus(
        path=Path(j["path"]),
        ok=bool(j.get("ok")),
        case_id=j.get("case_id"),
        issues=list(j.get("issues", [])),
    )


def validate_one(path: Path) -> CaseStatus:
    out = _run(["validate-one", str(Path(path))])
    return _status_from_json(json.loads(out.strip()))


def validate_dir(path: Optional[Path] = None) -> Report:
    args = ["validate-dir"]
    if path is not None:
        args += ["--dir", str(Path(path))]
    j = json.loads(_run(args).strip())
    return Report(
        n_cases=int(j.get("n_cases", 0)),
        n_ok=int(j.get("n_ok", 0)),
        n_failed=int(j.get("n_failed", 0)),
        statuses=[_status_from_json(s) for s in j.get("statuses", [])],
    )


def summary(path: Optional[Path] = None) -> str:
    args = ["summary"]
    if path is not None:
        args += ["--dir", str(Path(path))]
    return _run(args).rstrip("\n")
