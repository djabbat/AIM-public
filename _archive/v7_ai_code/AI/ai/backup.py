"""AI/ai/backup.py — thin Python shim over the
`aim-ai-backup` Rust binary (Phase 9 Tier 4 #26, 2026-05-07).

JSON snapshot / restore of every persistent DB AIM/AI uses. The Rust
crate owns SQLite I/O and JSON encoding; Python keeps the same public
dict-shaped API plus the legacy default-output-path heuristic
(`AI/artifacts/backup_*.json`).

Public API (preserved):
    snapshot() -> dict
    write_snapshot(path=None) -> Path
    restore(path, *, dry_run=False) -> dict
    summary() -> str

Env: AI_DIAGNOSTIC_DB.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.backup")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-backup"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-backup binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-backup {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def snapshot() -> dict:
    return json.loads(_run(["snapshot"]).strip())


def write_snapshot(path: Optional[Path] = None) -> Path:
    if path is None:
        try:
            from AI.ai.run_self_diagnostic import ai_root
            base = ai_root() / "artifacts"
        except Exception:
            base = Path.home() / ".cache" / "aim"
        base.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y-%m-%dT%H%M%S")
        path = base / f"backup_{ts}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    j = json.loads(_run(["write", "--out", str(path)]).strip())
    return Path(j.get("path", path))


def restore(path: Path, *, dry_run: bool = False) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    args = ["restore", "--in", str(p)]
    if not dry_run:
        args.append("--apply")
    try:
        out = _run(args).strip()
    except RuntimeError as e:
        if "unsupported snapshot version" in str(e).lower():
            raise ValueError(str(e))
        raise
    if not out:
        return {"diagnostic_db": {}, "distillation_db": {}, "dry_run": dry_run}
    return json.loads(out)


def summary() -> str:
    return _run(["summary"]).rstrip("\n")
