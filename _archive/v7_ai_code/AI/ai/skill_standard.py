"""AI/ai/skill_standard.py — thin Python shim over the
`aim-ai-skill-standard` Rust binary (Phase 9 Tier 3 #19, 2026-05-07).

Bidirectional adapter between AIM's internal skill format and the
agentskills.io open standard. The Rust crate owns conversion + batch
I/O; Python keeps the same public dict-in-dict-out API.

Public API (preserved):
    to_agentskills(aim_skill) -> dict
    from_agentskills(external) -> dict
    round_trip_aim(aim_skill) -> dict
    export_dir(src_dir, dst_dir, *, overwrite=False) -> int
    import_dir(src_dir, dst_dir, *, overwrite=False) -> int
    summary() -> str
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.skill_standard")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-skill-standard"
    )


def _run(args: list[str], *, stdin: Optional[str] = None) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-skill-standard binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-skill-standard {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def to_agentskills(aim_skill: dict) -> dict:
    if not aim_skill.get("skill_id"):
        raise ValueError("aim skill missing skill_id")
    out = _run(["to-agentskills"], stdin=json.dumps(aim_skill))
    return json.loads(out)


def from_agentskills(external: dict) -> dict:
    if not external.get("name"):
        raise ValueError("external skill missing 'name'")
    out = _run(["from-agentskills"], stdin=json.dumps(external))
    return json.loads(out)


def round_trip_aim(aim_skill: dict) -> dict:
    """aim → agentskills → aim."""
    return from_agentskills(to_agentskills(aim_skill))


def export_dir(src_dir: Path, dst_dir: Path,
                *, overwrite: bool = False) -> int:
    args = ["export-dir", str(Path(src_dir)), str(Path(dst_dir))]
    if overwrite:
        args.append("--overwrite")
    j = json.loads(_run(args).strip())
    return int(j.get("written", 0))


def import_dir(src_dir: Path, dst_dir: Path,
                *, overwrite: bool = False) -> int:
    args = ["import-dir", str(Path(src_dir)), str(Path(dst_dir))]
    if overwrite:
        args.append("--overwrite")
    j = json.loads(_run(args).strip())
    return int(j.get("written", 0))


def summary() -> str:
    return _run(["summary"]).rstrip("\n")
