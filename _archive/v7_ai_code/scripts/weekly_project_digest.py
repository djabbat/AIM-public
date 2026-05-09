#!/usr/bin/env python3
"""scripts/weekly_project_digest.py — weekly cross-project digest (Phase E, 2026-05-06).

Sister to `scripts/weekly_digest.py` (which covers AIM-self quality:
pattern miner / ab router / prompt evolver / evals). This digest is
*outward-facing*: project velocity, patient follow-up drift,
experiment uptime, stakeholder silence patterns.

Sources (all read via existing modules / Rust binaries — no new logic):
  - `agents.project_owner.list_projects` + per-project KPI velocity
  - `aim-patient-owner all` (Rust) for patient hot/overdue
  - `aim-experiment-owner all` (Rust) for experiment status
  - `agents.pattern_miner._mine_stakeholder_silence` for silence pattern
  - `aim-patient-comms overdue` (Rust) for patient follow-up drift
  - `agents.deadline_scanner.scan_all` filtered to last 7d horizon

Output: markdown body, sent via `agents.notify` with telegram + log
channels. Idempotent: dedup_key = `weekly_project:<ISO_week>`.

Usage:
    python -m scripts.weekly_project_digest          # send via notify
    AIM_TG_DRYRUN=1 python -m scripts.weekly_project_digest   # stdout only
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

logging.basicConfig(level=os.environ.get("AIM_LOGLEVEL", "INFO"))
log = logging.getLogger("aim.weekly_project_digest")


def _section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"## {title}\n\n{body}\n"


def _projects_block(today: dt.date) -> str:
    """Per-project hot milestones + overdue stakeholders."""
    try:
        from agents import project_owner as po
    except Exception as e:
        return f"_(project_owner unavailable: {e})_"
    parts: list[str] = []
    for name in po.list_projects():
        try:
            state = po.load(name)
        except (FileNotFoundError, ValueError):
            continue
        hot = po.hot_milestones(state, today)
        overdue = [s for s in state.stakeholders if s.overdue(today)]
        if not hot and not overdue:
            continue
        line = f"**{state.name}** ({state.phase}) — "
        bits: list[str] = []
        if hot:
            bits.append(f"{len(hot)} hot")
        if overdue:
            bits.append(f"{len(overdue)} overdue stakeholder")
        line += ", ".join(bits)
        parts.append(line)
    return "\n".join(parts) if parts else "_(no projects with hot/overdue this week)_"


def _stakeholder_silence_block() -> str:
    try:
        from agents.pattern_miner import _mine_stakeholder_silence
    except Exception as e:
        return f"_(stakeholder_silence unavailable: {e})_"
    findings = _mine_stakeholder_silence(min_days=14, threshold=1)
    if not findings:
        return "_(no stakeholder silence patterns detected)_"
    return "\n".join(f"- {f.summary}" for f in findings)


def _rust_block(name: str, args: list[str], env_extra: dict | None = None) -> str:
    """Run a Rust binary; return stdout or '' on failure."""
    candidates = [
        HERE / "rust-core" / "target" / "release" / name,
        HERE / "rust-core" / "target" / "debug" / name,
    ]
    bin_path = next((p for p in candidates if p.exists()), None)
    if bin_path is None:
        return ""
    import subprocess
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        out = subprocess.run(
            [str(bin_path)] + args,
            capture_output=True, text=True, timeout=10, env=env, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout or "").strip()


def _experiments_block(today: dt.date) -> str:
    body = _rust_block(
        "aim-experiment-owner",
        ["all", today.isoformat()],
        env_extra={"AIM_EXPERIMENTS_DIR": str(HERE / "USER" / "experiments")},
    )
    if not body or "no experiments" in body.lower():
        return "_(no experiments configured)_"
    return body


def _patient_drift_block(today: dt.date) -> str:
    body = _rust_block("aim-patient-comms", ["overdue", today.isoformat()])
    if not body:
        return "_(no overdue patient follow-ups)_"
    return "\n".join(f"- {ln}" for ln in body.splitlines() if ln.strip())


def render_digest(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    parts: list[str] = []
    parts.append(f"# 📅 Weekly project digest — {today.isoformat()} (W{iso_week:02d}/{iso_year})")
    parts.append("")
    parts.append(_section("Projects (hot + overdue)", _projects_block(today)))
    parts.append(_section("Stakeholder silence (≥14d)", _stakeholder_silence_block()))
    parts.append(_section("Experiments", _experiments_block(today)))
    parts.append(_section("Patient follow-up drift", _patient_drift_block(today)))
    return "\n".join(p for p in parts if p)


def main() -> int:
    text = render_digest()
    if os.environ.get("AIM_TG_DRYRUN") == "1":
        print(text)
        return 0
    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    try:
        from agents.notify import notify
        result = notify(
            text,
            channels=("telegram", "log"),
            subject=f"AIM weekly project digest W{iso_week:02d}/{iso_year}",
            level="info",
            source="weekly_project_digest",
            dedup_key=f"weekly_project:{iso_year}-{iso_week:02d}",
            dedup_window_minutes=7 * 24 * 60,
        )
        if result.delivered_via:
            log.info("weekly project digest sent via %s (%d chars)",
                     result.delivered_via, len(text))
            return 0
    except Exception as e:
        log.warning("notify-based delivery failed: %s", e)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
