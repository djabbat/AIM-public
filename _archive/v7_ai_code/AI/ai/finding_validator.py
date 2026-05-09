"""AI/ai/finding_validator.py — thin Python shim over the
`aim-ai-finding-validator` Rust binary (Phase 9 Tier 3 #17, 2026-05-07).

Heuristic auto-validator for diagnostic findings. The Rust crate owns
the 5 contradiction rules + markdown parsing; Python keeps the same
public dataclass-shaped API.

Public API (preserved):
    Verdict / FindingAudit / AuditReport dataclasses
    classify(claim_text, file_path) -> Verdict
    audit_report(report_text, *, repo_root=None) -> AuditReport
    summary(report_text, *, repo_root=None) -> str
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.finding_validator")


@dataclasses.dataclass
class Verdict:
    status: str          # "false_positive" | "unverified" | "true"
    rule: str
    evidence: str


@dataclasses.dataclass
class FindingAudit:
    excerpt: str
    file_ref: Optional[str]
    verdict: Verdict


@dataclasses.dataclass
class AuditReport:
    n_findings: int
    n_false: int
    n_unverified: int
    n_true: int
    audits: list[FindingAudit]


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-finding-validator"
    )


def _run(args: list[str], *, stdin: Optional[str] = None) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-finding-validator binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-finding-validator {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


# Rust returns PascalCase ("FalsePositive"); Python public API uses
# snake_case ("false_positive"), so map back.
_STATUS_FROM_RUST = {
    "FalsePositive": "false_positive",
    "Unverified": "unverified",
    "True": "true",
}


def _verdict_from_json(j: dict) -> Verdict:
    return Verdict(
        status=_STATUS_FROM_RUST.get(str(j.get("status")), "unverified"),
        rule=str(j.get("rule", "")),
        evidence=str(j.get("evidence", "")),
    )


def classify(claim_text: str, file_path: Path) -> Verdict:
    out = _run(["classify", "--file", str(file_path)], stdin=claim_text)
    return _verdict_from_json(json.loads(out.strip()))


def audit_report(report_text: str,
                  *, repo_root: Optional[Path] = None) -> AuditReport:
    if repo_root is None:
        from AI.ai.run_self_diagnostic import project_root
        repo_root = project_root()
    out = _run(
        ["audit-report", "--repo-root", str(Path(repo_root))],
        stdin=report_text,
    )
    j = json.loads(out.strip())
    audits: list[FindingAudit] = []
    for a in j.get("audits", []):
        audits.append(FindingAudit(
            excerpt=str(a.get("excerpt", "")),
            file_ref=a.get("file_ref"),
            verdict=_verdict_from_json(a.get("verdict", {})),
        ))
    return AuditReport(
        n_findings=int(j.get("n_findings", 0)),
        n_false=int(j.get("n_false", 0)),
        n_unverified=int(j.get("n_unverified", 0)),
        n_true=int(j.get("n_true", 0)),
        audits=audits,
    )


def summary(report_text: str,
             *, repo_root: Optional[Path] = None) -> str:
    if repo_root is None:
        from AI.ai.run_self_diagnostic import project_root
        repo_root = project_root()
    return _run(
        ["summary", "--repo-root", str(Path(repo_root))],
        stdin=report_text,
    ).rstrip("\n")
