"""AI/ai/hive_telemetry.py — thin Python shim over the
`aim-hive-telemetry` Rust binary (Phase 9 Tier 4 #29, 2026-05-07).

Each AIM worker periodically packages anonymized signals about its
operation and POSTs them to the queen for aggregation. L_PRIVACY +
DP-budget gates live in the Rust crate `aim-hive-worker`; Python
keeps the same public dict-shaped API.

Public API (preserved):
    ContributionResult dataclass
    contribution() -> dict
    preview() -> str
    contribute(*, dry_run=False, queen_url=None, eps_per_round=None) -> ContributionResult
    summary(*, dry_run=True) -> str

Env: AIM_HIVE_QUEEN_URL, AIM_USER_TOKEN, AIM_DP_BUDGET, AIM_HOME.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.hive_telemetry")


@dataclasses.dataclass
class ContributionResult:
    sent: bool
    payload: dict
    queen_response: Optional[dict]
    notes: list[str]


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-hive-telemetry"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-hive-telemetry binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-hive-telemetry {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def contribution() -> dict:
    return json.loads(_run(["contribution"]).strip())


def preview() -> str:
    return _run(["preview"]).rstrip("\n")


def contribute(*, dry_run: bool = False,
                queen_url: Optional[str] = None,
                eps_per_round: Optional[float] = None) -> ContributionResult:
    args = ["contribute"]
    if dry_run:
        args.append("--dry-run")
    if queen_url:
        args += ["--queen-url", queen_url]
    if eps_per_round is not None:
        args += ["--eps", str(float(eps_per_round))]
    j = json.loads(_run(args).strip())
    return ContributionResult(
        sent=bool(j.get("sent", False)),
        payload=j.get("payload") or {},
        queen_response=j.get("queen_response"),
        notes=list(j.get("notes", [])),
    )


def summary(*, dry_run: bool = True) -> str:
    """Single-line preview of what would be sent (or was sent in this run)."""
    res = contribute(dry_run=dry_run)
    bits: list[str] = []
    if res.sent:
        bits.append("✅ sent")
    elif dry_run:
        bits.append("(dry-run)")
    else:
        bits.append("⛔ not sent")
    payload = res.payload or {}
    ledger = payload.get("ledger", {})
    if isinstance(ledger, dict) and ledger.get("n_runs"):
        bits.append(f"runs={ledger['n_runs']}")
    skills = payload.get("skills", {})
    if isinstance(skills, dict):
        invs = skills.get("skill_invocations", {})
        if isinstance(invs, dict):
            bits.append(f"skills={len(invs)}")
    if res.notes:
        bits.append("; ".join(res.notes[:2]))
    return "📡 hive_telemetry: " + " · ".join(bits)
