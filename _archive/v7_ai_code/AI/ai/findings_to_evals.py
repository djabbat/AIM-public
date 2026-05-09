"""AI/ai/findings_to_evals.py — thin Python shim over the
`aim-ai-findings-to-evals` Rust binary (Phase 9 Tier 3 #16, 2026-05-07).

Convert shared findings (file:line refs) from the diagnostic pipeline
into eval cases that codify those concerns as regression checks. Rust
crate owns slug/regex/YAML emit + filesystem I/O; Python keeps the same
public dataclass-shaped API.

Public API (preserved):
    CaseSpec dataclass
    case_from_finding(ref) -> CaseSpec | None
    generate_cases(refs) -> list[CaseSpec]
    write_cases(refs, *, dest=None, overwrite=False) -> list[Path]
    summary(refs) -> str

Env: AIM_EVAL_CASES_DIR.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ai.findings_to_evals")


@dataclasses.dataclass
class CaseSpec:
    id: str
    task: str
    rubrics: dict
    tags: list[str]


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-findings-to-evals"
    )


def _run(args: list[str], *, stdin: Optional[str] = None) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-findings-to-evals binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-findings-to-evals {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _spec_from_json(j: dict) -> CaseSpec:
    rub = j.get("rubrics", {})
    return CaseSpec(
        id=j["id"],
        task=j["task"],
        rubrics={
            "contains_all": list(rub.get("contains_all", [])),
            "min_length": int(rub.get("min_length", 0)),
            "forbid_any": list(rub.get("forbid_any", [])),
        },
        tags=list(j.get("tags", [])),
    )


def case_from_finding(ref: str) -> Optional[CaseSpec]:
    out = _run(["case-from-finding", ref]).strip()
    if not out or out == "null":
        return None
    return _spec_from_json(json.loads(out))


def generate_cases(refs: Iterable[str]) -> list[CaseSpec]:
    refs_list = [r for r in refs if r and r.strip()]
    if not refs_list:
        return []
    out = _run(["generate"], stdin="\n".join(refs_list))
    return [_spec_from_json(json.loads(line))
            for line in out.splitlines() if line.strip()]


def write_cases(refs: Iterable[str], *,
                 dest: Optional[Path] = None,
                 overwrite: bool = False) -> list[Path]:
    refs_list = [r for r in refs if r and r.strip()]
    if not refs_list:
        return []
    args = ["write"]
    if dest is not None:
        args += ["--dest", str(Path(dest))]
    if overwrite:
        args.append("--overwrite")
    out = _run(args, stdin="\n".join(refs_list)).strip()
    if not out:
        return []
    j = json.loads(out)
    return [Path(p) for p in j.get("written", [])]


def summary(refs: Iterable[str]) -> str:
    refs_list = [r for r in refs if r and r.strip()]
    if not refs_list:
        return "(no eval cases generated — refs were unparseable)"
    return _run(["summary"], stdin="\n".join(refs_list)).rstrip("\n")
