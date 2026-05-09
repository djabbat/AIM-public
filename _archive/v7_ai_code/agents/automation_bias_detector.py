"""agents/automation_bias_detector.py — thin Python shim over the
`aim-disagreement` Rust binary (Blumenthal-Lee 4-zone classifier).

All zone logic lives in Rust (`rust-core/crates/aim-disagreement`).
This module exists only to give Python callers a typed dataclass and
named constants for thresholds.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AI_HIGH = 0.80
DEFAULT_CLINICIAN_HIGH = 0.75


@dataclass(frozen=True)
class ZoneThresholds:
    ai_high: float = DEFAULT_AI_HIGH
    clinician_high: float = DEFAULT_CLINICIAN_HIGH


@dataclass(frozen=True)
class DisagreementOutcome:
    zone: str
    ui_action: str
    ai_conf: float
    clinician_conf: float
    agree: bool
    summary: str


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-disagreement"
    )


def classify(
    ai_conf: float,
    clinician_conf: float,
    agree: bool,
    thresholds: ZoneThresholds | None = None,
) -> DisagreementOutcome:
    if not 0.0 <= ai_conf <= 1.0:
        raise ValueError(f"ai_conf {ai_conf} out of range 0..=1")
    if not 0.0 <= clinician_conf <= 1.0:
        raise ValueError(f"clinician_conf {clinician_conf} out of range 0..=1")
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-disagreement binary not built at {bin_path}; "
            "run `cargo build -p aim-disagreement --release` in rust-core/"
        )
    args = [str(bin_path), "classify",
            f"{ai_conf}", f"{clinician_conf}",
            "true" if agree else "false"]
    if thresholds is not None:
        args += ["--ai-high", f"{thresholds.ai_high}",
                 "--clinician-high", f"{thresholds.clinician_high}"]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"aim-disagreement classify failed: {proc.stderr.strip()}")
    j = json.loads(proc.stdout)
    return DisagreementOutcome(
        zone=str(j["zone"]),
        ui_action=str(j["ui_action"]),
        ai_conf=float(j["ai_conf"]),
        clinician_conf=float(j["clinician_conf"]),
        agree=bool(j["agree"]),
        summary=str(j["summary"]),
    )
