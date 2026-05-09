"""AI/ai/regression_alert.py — thin Python shim over the
`aim-ai-regression-alert` Rust binary (Phase 9 Tier 2 #6, 2026-05-07).

When `regression_detector.detect()` flags regression, format the
notification payload via the Rust `build` subcommand, then dispatch
through the Python `agents.notify` mux.

Direction rule preserved: AI/ → agents/ allowed; agents/ ↛ AI/.

Public API:
    Alert dataclass
    check_and_alert(*, dry_run: bool = False) -> Alert | None
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.regression_alert")


@dataclasses.dataclass
class Alert:
    fired: bool
    title: str
    body: str
    channels: list[str]


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-regression-alert"
    )


def _build_alert_json(regression) -> Optional[dict]:
    """Pipe the (suppression-filtered) Regression to the Rust binary."""
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-regression-alert binary not built at {bin_path}"
        )
    payload = {
        "have_baseline": regression.have_baseline,
        "prev_ts": regression.prev_ts,
        "curr_ts": regression.curr_ts,
        "prev_grade": regression.prev_grade,
        "curr_grade": regression.curr_grade,
        "prev_crit": regression.prev_crit,
        "curr_crit": regression.curr_crit,
        "prev_findings": sorted(regression.prev_findings),
        "curr_findings": sorted(regression.curr_findings),
        "new_findings": sorted(regression.new_findings),
        "fixed_findings": sorted(regression.fixed_findings),
    }
    proc = subprocess.run(
        [str(bin_path), "build"],
        input=json.dumps(payload),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-regression-alert build failed: {proc.stderr.strip()}"
        )
    out = proc.stdout.strip()
    if not out or out == "null":
        return None
    return json.loads(out)


def check_and_alert(*, dry_run: bool = False) -> Optional[Alert]:
    """Detect regression (Python — applies suppression) → format via Rust
    → dispatch via `agents.notify` (Python).

    Returns the Alert struct (with `fired` boolean) on regression, or
    None if no baseline / not regressed. With `dry_run=True`, the alert
    is built but the notification side-effect is skipped.
    """
    from AI.ai.regression_detector import detect
    r = detect()
    if not r.have_baseline or not r.regressed:
        return None
    a = _build_alert_json(r)
    if a is None:
        return None
    title = a["title"]
    body = a["body"]
    dedup_key = a["dedup_key"]
    dedup_window_minutes = float(a["dedup_window_minutes"])

    if dry_run:
        return Alert(fired=False, title=title, body=body, channels=[])

    channels: list[str] = []
    try:
        from agents.notify import notify as _notify
        full = f"{title}\n\n{body}"
        res = _notify(full, subject=title, level="high",
                      source="ai.regression_alert",
                      dedup_key=dedup_key,
                      dedup_window_minutes=dedup_window_minutes)
        if getattr(res, "delivered_via", None):
            channels = [res.delivered_via]
    except Exception as e:
        log.warning("notify unavailable: %s", e)
    return Alert(fired=bool(channels), title=title, body=body,
                 channels=channels)
