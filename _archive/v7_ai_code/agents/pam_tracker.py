"""agents/pam_tracker.py — thin Python shim over the `aim-pam` Rust binary.

All scoring, persistence, and delta classification live in Rust
(`rust-core/crates/aim-pam`). This module exists only to give Python
callers (medical_system, generalist tools, tests) a Pythonic API and
to centralise the binary path / `AIM_PATIENTS_DIR` resolution.

If you find yourself adding scoring or stats logic here — STOP and put
it in the Rust crate instead, then expose a new subcommand. See
`AUDIT_CORNERSTONE_COMPLIANCE_2026-05-07.md` for the rationale.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Mirrors aim_patient_memory::PAM_MCID and PAM_MDC. Kept as constants for
# Python callers that need MCID/MDC without invoking the binary.
PAM_MCID = 5.4
PAM_MDC = 7.2


@dataclass
class PamScore:
    raw_sum: int
    score: float
    level: int


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-pam"
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
            f"aim-pam binary not built at {bin_path}; "
            "run `cargo build -p aim-pam --release` in rust-core/"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aim-pam {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def score_responses(responses: list[int]) -> PamScore:
    """Score 13 Likert responses (1-4) without persisting."""
    if len(responses) != 13:
        raise ValueError(f"expected 13 responses, got {len(responses)}")
    out = _run(["score", *[str(r) for r in responses]])
    raw = score = level = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Raw sum:"):
            raw = int(line.split(":", 1)[1].strip())
        elif line.startswith("Score:"):
            score = float(line.split(":", 1)[1].strip().split("/", 1)[0])
        elif line.startswith("Level:"):
            level = int(line.split(":", 1)[1].strip().split(" ", 1)[0])
    if None in (raw, score, level):
        raise RuntimeError(f"aim-pam score: unparseable output:\n{out}")
    return PamScore(raw_sum=raw, score=score, level=level)


def record_administration(
    patient_id: str,
    responses: list[int],
    administered_at: date | None = None,  # accepted for API back-compat; binary uses today
) -> PamScore:
    """Score + persist into `Patients/<id>/_pam_history.jsonl` via the
    Rust binary. Raises FileNotFoundError if the patient directory is
    missing."""
    if len(responses) != 13:
        raise ValueError(f"expected 13 responses, got {len(responses)}")
    out = _run([
        "record", patient_id,
        *[str(r) for r in responses],
        "--patients-dir", str(_patients_dir()),
    ])
    point = json.loads(out)  # {"date": "...", "score": ..., "level": ...}
    raw = sum(responses)
    return PamScore(
        raw_sum=raw,
        score=float(point["score"]),
        level=int(point["level"]),
    )


def history(patient_id: str) -> list[dict]:
    out = _run(["history", patient_id, "--patients-dir", str(_patients_dir())])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def current_activation_level(patient_id: str) -> int:
    """0 if no history, else the level of the most recent administration."""
    out = _run(["level", patient_id, "--patients-dir", str(_patients_dir())]).strip()
    return int(out) if out else 0


def current_activation_score(patient_id: str) -> float | None:
    h = history(patient_id)
    return float(h[-1]["score"]) if h else None


def latest_delta(patient_id: str) -> tuple[float | None, str]:
    """(delta, label). label ∈ {"insufficient_data", "no_change",
    "below_mcid", "clinically_significant", "individually_significant"}."""
    out = _run(["latest-delta", patient_id, "--patients-dir", str(_patients_dir())])
    j = json.loads(out)
    label = str(j["label"])
    delta = float(j["delta"])
    if label == "insufficient_data":
        return None, label
    return delta, label


def via_rust_binary(responses: list[int]) -> PamScore:
    """Back-compat alias — every score now goes via the binary."""
    return score_responses(responses)
