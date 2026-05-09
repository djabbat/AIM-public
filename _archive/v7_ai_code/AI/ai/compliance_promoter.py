"""AI/ai/compliance_promoter.py — CP1 (2026-05-04).

When the rolling line_compliance is consistently high, suggest
tightening `min_compliance` on `run_self_diagnostic.run()` so the
auto-retry corrective loop kicks in earlier (e.g. raise from 0.5 →
0.7). Conversely, if a tightening overshot (consecutive runs below
threshold), suggest backing off.

This is *recommendation only* — no env var or config is mutated. The
proposal lands in the dashboard so the user can decide.

Public API:
    recommendation() -> Recommendation
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import logging
import os
from typing import Optional

log = logging.getLogger("ai.compliance_promoter")


@dataclasses.dataclass
class Recommendation:
    current_threshold: float
    proposed_threshold: Optional[float]
    direction: str               # "tighten" | "loosen" | "hold"
    streak_high: int
    streak_low: int
    avg_recent: float
    n_recent: int
    reason: str


def _current_threshold() -> float:
    """Current `min_compliance` the live system will use. We don't
    parse the function signature — the env override `AI_DIAG_MIN_COMPLIANCE`
    is the only knob that lives outside code."""
    env = os.environ.get("AI_DIAG_MIN_COMPLIANCE")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return 0.5   # matches run_self_diagnostic.run default


_HIGH = 0.85       # streak threshold for tightening
_LOW = 0.40        # streak threshold for loosening
_MIN_STREAK = 3    # consecutive runs needed to trigger
_WINDOW = 10       # how many recent runs we look at


def recommendation() -> Recommendation:
    try:
        from AI.ai.diagnostic_ledger import recent
        rows = recent(n=_WINDOW)
    except Exception as e:
        log.debug("ledger unavailable: %s", e)
        rows = []

    cur = _current_threshold()
    if not rows:
        return Recommendation(
            current_threshold=cur, proposed_threshold=None,
            direction="hold", streak_high=0, streak_low=0,
            avg_recent=0.0, n_recent=0,
            reason="no diagnostic runs yet — keep default",
        )

    avg_recent = sum(r.compliance for r in rows) / len(rows)

    # Compute trailing streaks (looking from the most recent backwards
    # until a row breaks the streak).
    streak_high = 0
    streak_low = 0
    for r in reversed(rows):
        if r.compliance >= _HIGH:
            streak_high += 1
            if streak_low > 0:
                break
        elif r.compliance < _LOW:
            streak_low += 1
            if streak_high > 0:
                break
        else:
            break

    if streak_high >= _MIN_STREAK and cur < 0.8:
        return Recommendation(
            current_threshold=cur,
            proposed_threshold=min(0.8, cur + 0.1),
            direction="tighten",
            streak_high=streak_high, streak_low=0,
            avg_recent=avg_recent, n_recent=len(rows),
            reason=(f"{streak_high} consecutive runs ≥{_HIGH:.0%} "
                     f"compliance; raise threshold to catch borderline "
                     f"runs earlier"),
        )
    if streak_low >= _MIN_STREAK and cur > 0.3:
        return Recommendation(
            current_threshold=cur,
            proposed_threshold=max(0.3, cur - 0.1),
            direction="loosen",
            streak_high=0, streak_low=streak_low,
            avg_recent=avg_recent, n_recent=len(rows),
            reason=(f"{streak_low} consecutive runs <{_LOW:.0%} "
                     f"compliance; threshold may be unrealistic — "
                     f"lower to reduce wasted retries"),
        )
    return Recommendation(
        current_threshold=cur, proposed_threshold=None,
        direction="hold", streak_high=streak_high, streak_low=streak_low,
        avg_recent=avg_recent, n_recent=len(rows),
        reason="metric in normal band — no change recommended",
    )


def summary() -> str:
    r = recommendation()
    parts = [
        f"⚖ Compliance threshold — current {r.current_threshold:.0%}",
        f"  recent avg: {r.avg_recent:.0%}  (n={r.n_recent})",
    ]
    if r.direction == "hold":
        parts.append(f"  → hold  ({r.reason})")
    elif r.direction == "tighten":
        parts.append(
            f"  ↑ tighten to {r.proposed_threshold:.0%}: {r.reason}"
        )
    elif r.direction == "loosen":
        parts.append(
            f"  ↓ loosen to {r.proposed_threshold:.0%}: {r.reason}"
        )
    return "\n".join(parts)
