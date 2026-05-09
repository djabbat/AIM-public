"""AI/ai/safety_gate.py — SG1 (2026-05-04).

Pre-flight gates for triggering an actual self-diagnostic run. Cron
schedules can fire even when conditions are wrong — this module
checks them and returns a verdict (allow / deny + reason).

Two gates:
  - Cooldown: don't re-run if last ledger entry is within `min_age_h`
    hours.
  - Budget: don't run if today's spent exceeds the daily cap.

Public API:
    can_run() -> Verdict
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
from typing import Optional

log = logging.getLogger("ai.safety_gate")


@dataclasses.dataclass
class Verdict:
    allowed: bool
    reasons: list[str]
    cooldown_ok: bool
    budget_ok: bool
    last_run_age_h: Optional[float]
    daily_cost_usd: Optional[float]
    daily_budget_usd: Optional[float]


def _min_cooldown_hours() -> float:
    raw = os.environ.get("AI_DIAG_COOLDOWN_HOURS", "23")
    try:
        return float(raw)
    except ValueError:
        return 23.0


def _last_run_age_hours() -> Optional[float]:
    """Return hours since the most recent ledger row, or None if empty."""
    try:
        from AI.ai.diagnostic_ledger import recent
    except Exception as e:
        log.debug("ledger unavailable: %s", e)
        return None
    rows = recent(n=1)
    if not rows:
        return None
    try:
        last = dt.datetime.fromisoformat(rows[0].ts)
    except (ValueError, TypeError):
        return None
    return (dt.datetime.now() - last).total_seconds() / 3600.0


def _daily_budget_state() -> tuple[Optional[float], Optional[float]]:
    """Return (today_cost, daily_budget). Either may be None if the
    budget module is not available."""
    try:
        from agents.cost_ledger import daily_cost, daily_budget
    except Exception as e:
        log.debug("cost_ledger unavailable: %s", e)
        return (None, None)
    try:
        return (float(daily_cost()), float(daily_budget()))
    except Exception as e:
        log.debug("budget read failed: %s", e)
        return (None, None)


def can_run() -> Verdict:
    reasons: list[str] = []

    # Cooldown
    age = _last_run_age_hours()
    cooldown_min = _min_cooldown_hours()
    if age is None:
        cooldown_ok = True
    else:
        cooldown_ok = age >= cooldown_min
        if not cooldown_ok:
            reasons.append(
                f"cooldown not met: last run {age:.1f}h ago "
                f"(min {cooldown_min:.1f}h)"
            )

    # Budget
    cost, budget = _daily_budget_state()
    if cost is None or budget is None:
        budget_ok = True   # missing budget module → don't block
    elif budget <= 0:
        budget_ok = True   # explicitly unlimited
    else:
        budget_ok = cost < budget
        if not budget_ok:
            reasons.append(
                f"daily budget exceeded: ${cost:.2f} ≥ ${budget:.2f}"
            )

    return Verdict(
        allowed=cooldown_ok and budget_ok,
        reasons=reasons,
        cooldown_ok=cooldown_ok,
        budget_ok=budget_ok,
        last_run_age_h=age,
        daily_cost_usd=cost,
        daily_budget_usd=budget,
    )


def summary() -> str:
    v = can_run()
    if v.allowed:
        head = "🟢 safety gate: OK to run"
    else:
        head = "🔴 safety gate: BLOCKED"
    parts = [head]
    if v.last_run_age_h is None:
        parts.append("  cooldown: no prior run")
    else:
        mark = "✅" if v.cooldown_ok else "❌"
        parts.append(f"  {mark} cooldown: last run {v.last_run_age_h:.1f}h "
                      f"ago (min {_min_cooldown_hours():.1f}h)")
    if v.daily_cost_usd is None or v.daily_budget_usd is None:
        parts.append("  budget: (unavailable)")
    elif v.daily_budget_usd <= 0:
        parts.append("  budget: unlimited")
    else:
        mark = "✅" if v.budget_ok else "❌"
        parts.append(f"  {mark} budget: ${v.daily_cost_usd:.2f} / "
                      f"${v.daily_budget_usd:.2f} today")
    if v.reasons:
        parts.append("\n notes:")
        for r in v.reasons:
            parts.append(f"  - {r}")
    return "\n".join(parts)
