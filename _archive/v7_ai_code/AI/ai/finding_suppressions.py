"""AI/ai/finding_suppressions.py — thin Python shim over the
`aim-ai-suppressions` Rust binary (Phase 9 Tier 3 #18, 2026-05-07).

Some diagnostic findings are persistent false-positives or intentional
code (a TODO that is part of the design, a known limitation that has a
roadmap entry). RA1 alerts must not fire on those forever. The Rust
binary owns the SQLite mute list (sidecar table on the ledger DB) and
the active/expired logic; Python just shells out.

Public API (preserved):
    db_path() -> Path
    Suppression dataclass + active_now property
    suppress(ref, *, reason="", until=None) -> Suppression
    unsuppress(ref) -> bool
    is_suppressed(ref) -> bool
    active() -> list[Suppression]
    filter_findings(refs) -> list[str]
    summary() -> str
    prune_expired() -> int

Env: AI_DIAGNOSTIC_DB (override DB path).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ai.finding_suppressions")


def db_path() -> Path:
    """Reuse the diagnostic ledger DB so suppressions live next to the
    metrics they explain."""
    env = os.environ.get("AI_DIAGNOSTIC_DB")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "aim" / "diagnostic_ledger.db"


@dataclasses.dataclass
class Suppression:
    ref: str
    reason: str
    created_ts: str
    until_ts: Optional[str]

    @property
    def active_now(self) -> bool:
        if self.until_ts is None:
            return True
        try:
            until = dt.datetime.fromisoformat(self.until_ts)
        except (ValueError, TypeError):
            return True
        # Strip tz to match Python's naive datetime.now() behaviour.
        if until.tzinfo is not None:
            until = until.astimezone().replace(tzinfo=None)
        return dt.datetime.now() < until


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-suppressions"
    )


def _run(args: list[str], *, stdin: Optional[str] = None,
         allow_nonzero: bool = False) -> tuple[int, str]:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-suppressions binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 and not allow_nonzero:
        raise RuntimeError(
            f"aim-ai-suppressions {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.returncode, proc.stdout


def _row_from_json(j: dict) -> Suppression:
    return Suppression(
        ref=j["ref"],
        reason=j.get("reason", ""),
        created_ts=j["created_ts"],
        until_ts=j.get("until_ts"),
    )


def suppress(ref: str, *,
              reason: str = "",
              until: Optional[dt.datetime] = None) -> Suppression:
    if not ref or not ref.strip():
        raise ValueError("ref must be non-empty")
    args = ["suppress", "--ref", ref.strip()]
    if reason:
        args += ["--reason", reason]
    if until is not None:
        if until.tzinfo is None:
            until = until.astimezone()
        args += ["--until", until.isoformat()]
    _, out = _run(args)
    return _row_from_json(json.loads(out.strip()))


def unsuppress(ref: str) -> bool:
    """Remove a suppression. Returns True if a row was deleted."""
    code, out = _run(["unsuppress", "--ref", ref], allow_nonzero=True)
    return out.strip() == "true"


def active() -> list[Suppression]:
    """Suppressions that are currently in effect (not expired)."""
    _, out = _run(["active"])
    return [_row_from_json(json.loads(line))
            for line in out.splitlines() if line.strip()]


def is_suppressed(ref: str) -> bool:
    code, out = _run(["is-suppressed", "--ref", ref], allow_nonzero=True)
    return out.strip() == "true"


def filter_findings(refs: Iterable[str]) -> list[str]:
    """Return refs minus any currently-suppressed."""
    refs_list = [r for r in refs if r]
    if not refs_list:
        return []
    _, out = _run(["filter"], stdin="\n".join(refs_list))
    kept = {ln.strip() for ln in out.splitlines() if ln.strip()}
    # Preserve original input order.
    return [r for r in refs_list if r in kept]


def summary() -> str:
    _, out = _run(["summary"])
    return out.rstrip("\n")


def prune_expired() -> int:
    """Delete rows whose `until_ts` has passed. Returns count removed."""
    _, out = _run(["prune-expired"])
    return int(json.loads(out.strip()).get("removed", 0))
