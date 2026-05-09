"""agents/codesign_log.py — thin Python shim over the `aim-codesign`
Rust binary (patient co-design event log).

All persistence logic lives in Rust (`rust-core/crates/aim-codesign`).
This module exists only to give Python callers a Pythonic API and to
expose `mark_codesigned()` as the L_AGENCY hand-off sentinel.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

VALID_KINDS = {"consulted", "agreed", "modified", "refused", "alternative"}
CODESIGNED_KINDS = {"agreed", "modified"}


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-codesign"
    )


def _patients_dir() -> Path:
    return Path(os.environ.get(
        "AIM_PATIENTS_DIR",
        str(Path(__file__).resolve().parent.parent / "Patients"),
    ))


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-codesign binary not built at {bin_path}; "
            "run `cargo build -p aim-codesign --release` in rust-core/"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip()
        # Translate the Rust error message into the same exception types the
        # previous pure-Python implementation raised, so existing callers
        # don't need to change.
        if "patient directory missing" in msg:
            raise FileNotFoundError(msg)
        if "unknown event kind" in msg or "expected one of" in msg \
                or "must be 'patient'" in msg:
            raise ValueError(msg)
        raise RuntimeError(f"aim-codesign {args[0]} failed: {msg}")
    return proc.stdout


def record(
    patient_id: str,
    kind: str,
    topic: str,
    *,
    decision_id: str | None = None,
    by: str = "patient",
    notes: str = "",
) -> dict:
    """Append a co-design event. Returns the recorded dict (parsed JSON
    from the Rust binary)."""
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(VALID_KINDS)}")
    if by not in {"patient", "caregiver"}:
        raise ValueError(f"by={by!r} must be 'patient' or 'caregiver'")
    args = ["record", patient_id, kind, topic, "--by", by,
            "--patients-dir", str(_patients_dir())]
    if decision_id is not None:
        args += ["--decision-id", decision_id]
    if notes:
        args += ["--notes", notes]
    out = _run(args)
    return json.loads(out)


def events(patient_id: str) -> list[dict]:
    out = _run(["events", patient_id, "--patients-dir", str(_patients_dir())])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def mark_codesigned(patient_id: str, decision_id: str) -> bool:
    """True iff there's an `agreed` or `modified` event for `decision_id`."""
    out = _run(["mark", patient_id, decision_id,
                "--patients-dir", str(_patients_dir())]).strip()
    return out.lower() == "true"


def filter_by_kind(patient_id: str, kinds: Iterable[str]) -> list[dict]:
    target = ",".join(sorted(set(kinds)))
    out = _run(["filter", patient_id, target,
                "--patients-dir", str(_patients_dir())])
    return [json.loads(line) for line in out.splitlines() if line.strip()]
