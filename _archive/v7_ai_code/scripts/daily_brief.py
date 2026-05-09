#!/usr/bin/env python3
"""scripts/daily_brief.py — Daily morning brief (P4, 2026-05-02).

Run from systemd timer or cron at 09:00. Renders all project briefs +
the cross-project deadline summary, then sends to Telegram (or stdout
if AIM_TG_DRYRUN=1 / no token).

Usage:
    python -m scripts.daily_brief                    # send to Telegram
    AIM_TG_DRYRUN=1 python -m scripts.daily_brief    # stdout only

Env vars consumed:
    TELEGRAM_BOT_TOKEN   (or AIM_TG_BOT_TOKEN)
    AIM_TELEGRAM_CHAT_ID — chat id for the brief; if absent, stdout only.
    AIM_BRIEF_HEAD       — optional preamble line.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Make AIM importable when invoked via systemd (cwd is /).
HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

logging.basicConfig(level=os.environ.get("AIM_LOGLEVEL", "INFO"))
log = logging.getLogger("aim.daily_brief")


def _rust_bin(name: str) -> Optional[Path]:
    """Locate a built Rust binary in rust-core/target/{release,debug}.
    Returns None when not built — bridge gracefully skips."""
    here = Path(__file__).resolve().parent.parent
    for sub in ("release", "debug"):
        p = here / "rust-core" / "target" / sub / name
        if p.exists():
            return p
    return None


def _run_rust(name: str, args: list, env_extra: dict | None = None,
              timeout: float = 10.0) -> str:
    """Run a Rust subprocess and return stdout, or '' on error."""
    bin_path = _rust_bin(name)
    if bin_path is None:
        log.debug("%s binary not built; skipping", name)
        return ""
    import subprocess
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        out = subprocess.run(
            [str(bin_path)] + args,
            capture_output=True, text=True, timeout=timeout, env=env, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("%s subprocess failed: %s", name, e)
        return ""
    if out.returncode != 0:
        log.warning("%s exit %d: %s", name, out.returncode,
                    (out.stderr or "")[:200])
        return ""
    return (out.stdout or "").strip()


def _patient_brief_block(today: dt.date) -> str:
    """Phase A bridge — call Rust `aim-patient-owner` binary."""
    from config import PATIENTS_DIR
    body = _run_rust(
        "aim-patient-owner",
        ["all", today.isoformat()],
        env_extra={"AIM_PATIENTS_DIR": str(PATIENTS_DIR)},
    )
    if not body or "no patients" in body.lower():
        return ""
    return body


def _experiment_brief_block(today: dt.date) -> str:
    """Phase B bridge (HW1, 2026-05-06) — call Rust `aim-experiment-owner`."""
    here = Path(__file__).resolve().parent.parent
    exp_dir = here / "USER" / "experiments"
    if not exp_dir.exists():
        return ""
    body = _run_rust(
        "aim-experiment-owner",
        ["all", today.isoformat()],
        env_extra={"AIM_EXPERIMENTS_DIR": str(exp_dir)},
    )
    if not body or "no experiments" in body.lower():
        return ""
    return body


def _patient_overdue_followups_block(today: dt.date) -> str:
    """Phase D bridge (HW1, 2026-05-06) — surface overdue patient
    follow-ups from the comms tracker SQLite.

    Each line: `<pid> | <topic> | <N>d past expected`.
    """
    body = _run_rust(
        "aim-patient-comms",
        ["overdue", today.isoformat()],
    )
    if not body:
        return ""
    return "📮 overdue patient follow-ups:\n" + "\n".join(
        f"  • {ln}" for ln in body.splitlines() if ln.strip()
    )


def render_brief(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    from agents import project_owner as po
    from agents import deadline_scanner as ds
    parts: list[str] = []

    head = os.environ.get("AIM_BRIEF_HEAD")
    if head is None:
        # B1 (2026-05-03): auto-generate a smart preamble unless the env
        # var was set explicitly. Empty string still wins (suppresses).
        try:
            from agents.brief_preamble import compose as _compose
            head = _compose(today=today)
        except Exception:
            head = ""
    if head:
        parts.append(head)

    parts.append(f"☀️ AIM daily brief — {today.isoformat()}")
    parts.append("")
    parts.append(po.all_briefs(today=today))

    # Phase A (HW1, 2026-05-06): patient briefs via Rust aim-patient-owner.
    patients_block = _patient_brief_block(today)
    if patients_block:
        parts.append("")
        parts.append("———")
        parts.append("")
        parts.append(patients_block)

    # Phase B (HW1, 2026-05-06): experiment briefs via aim-experiment-owner.
    experiments_block = _experiment_brief_block(today)
    if experiments_block:
        parts.append("")
        parts.append("———")
        parts.append("")
        parts.append(experiments_block)

    # Phase D (HW1, 2026-05-06): overdue patient comms via aim-patient-comms.
    comms_block = _patient_overdue_followups_block(today)
    if comms_block:
        parts.append("")
        parts.append("———")
        parts.append("")
        parts.append(comms_block)

    parts.append("")
    parts.append("———")
    parts.append("")
    parts.append(ds.summary(today=today))
    return "\n".join(parts)


def send_telegram(text: str) -> bool:
    """Backwards-compat re-export. Canonical impl: agents/telegram_sender.py.

    Existing `from scripts.daily_brief import send_telegram` callers
    keep working during gradual deprecation (HW1, 2026-05-06).
    New code should `from agents.telegram_sender import send_telegram`.
    """
    from agents.telegram_sender import send_telegram as _send
    return _send(text)


def main() -> int:
    text = render_brief()
    if os.environ.get("AIM_TG_DRYRUN") == "1":
        print(text)
        return 0
    # B2 (2026-05-03): respect quiet_hours + delivery channels from prefs.
    try:
        from agents import brief_preferences as bp
        prefs = bp.load()
        if bp.in_quiet_hours(prefs=prefs):
            log.info("inside quiet hours; brief suppressed")
            return 0
        channels = bp.daily_channels(prefs)
    except Exception:
        channels = ["telegram", "stdout"]
    try:
        from agents.notify import notify
        result = notify(text, channels=tuple(channels),
                         subject="AIM daily brief",
                         level="info", source="daily_brief",
                         dedup_key=f"daily:{__import__('datetime').date.today()}",
                         dedup_window_minutes=18 * 60)
        if result.delivered_via:
            log.info("daily brief sent via %s (%d chars)",
                     result.delivered_via, len(text))
            return 0
    except Exception as e:
        log.warning("notify-based delivery failed: %s", e)
    # Final fallback: legacy single-channel telegram, then stdout.
    if send_telegram(text):
        log.info("daily brief sent (%d chars)", len(text))
        return 0
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
