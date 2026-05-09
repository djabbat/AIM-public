"""AI/ai/morning_brief.py — thin Python shim over the
`aim-ai-brief` Rust binary (Phase 9 Tier 3 #14, 2026-05-07).

Single-shot wake-up briefing for AIM/AI subproject state. The Rust
crate `aim-ai-morning-brief` owns regression / ledger / archive /
deadlines sections; Python only overlays the wiring probe section
(still Python, since `AI/ai/doctor.py` calls `agents/*` modules).

Public API (preserved):
    render() -> str
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.morning_brief")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-brief"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-brief binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-brief failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _section_doctor() -> tuple[str, bool]:
    """Wiring probe — still in Python until `agents/doctor.py` is ported."""
    try:
        from AI.ai.doctor import diagnose
    except Exception as e:
        return (f"(wiring probe unavailable: {e})", False)
    try:
        probes = diagnose()
    except Exception as e:
        return (f"(wiring probe failed: {e})", False)
    crit = [p for p in probes if not p.ok and p.severity == "crit"]
    warn = [p for p in probes if not p.ok and p.severity == "warn"]
    if not crit and not warn:
        return ("✅ wiring clean — all probes ok", False)
    parts: list[str] = []
    if crit:
        parts.append(f"❌ {len(crit)} critical wiring issue(s):")
        for p in crit:
            parts.append(f"   • {p.name}: {p.detail.splitlines()[0]}")
    if warn:
        parts.append(f"⚠ {len(warn)} warning(s):")
        for p in warn:
            parts.append(f"   • {p.name}: {p.detail.splitlines()[0]}")
    return ("\n".join(parts), bool(crit))


def render() -> str:
    """Render the morning brief.

    Strategy: ask the Rust binary for the structured Brief, then
    overlay the wiring section using the Python doctor probe (which
    still depends on `agents/*` modules), recompute the headline, and
    serialise the same Markdown layout.
    """
    raw = _run(["--json"])
    b = json.loads(raw)

    wiring_text, doctor_crit = _section_doctor()
    overall_bad = bool(b.get("overall_bad")) or doctor_crit
    headline = ("⚠ AIM/AI needs attention this morning"
                if overall_bad
                else "🟢 AIM/AI is healthy this morning")

    parts = [
        f"# {headline}",
        "",
        "## High-criticality deadlines",
        b.get("deadlines", "(unavailable)"),
        "",
        "## Wiring",
        wiring_text,
        "",
        "## Regression check",
        b.get("regression", "(unavailable)"),
        "",
        "## Diagnostic trend",
        b.get("ledger", "(unavailable)"),
        "",
        "## Case archive",
        b.get("archive", "(unavailable)"),
    ]
    return "\n".join(parts)
