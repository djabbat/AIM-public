"""AI/ai/dashboard.py — DB1 (2026-05-04).

One-button consolidated view of AIM/AI subproject state.

Pulls every available summary from sibling modules and stitches them
into a single text dashboard. Each module is invoked best-effort —
if one fails (missing data, missing dep), the dashboard still emits.

Public API:
    render() -> str
    sections() -> list[Section]      # for programmatic consumption
"""
from __future__ import annotations

import dataclasses
import logging
import traceback
from typing import Callable, Optional

log = logging.getLogger("ai.dashboard")


@dataclasses.dataclass
class Section:
    name: str
    title: str
    body: str
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _safe_call(fn: Callable[[], str]) -> tuple[str, Optional[str]]:
    try:
        out = fn()
        if not isinstance(out, str):
            out = str(out)
        return (out, None)
    except Exception as e:
        log.debug("dashboard section failed", exc_info=True)
        return ("(unavailable)", f"{type(e).__name__}: {e}")


def _diagnostic_ledger() -> str:
    from AI.ai.diagnostic_ledger import summary
    return summary()


def _regression_detector() -> str:
    from AI.ai.regression_detector import summary
    return summary()


def _distillation_tracker() -> str:
    from AI.ai.distillation_tracker import summary
    return summary()


def _gap_detector() -> str:
    from AI.ai.gap_detector import summary
    return summary()


def _reflexion_cluster() -> str:
    from AI.ai.reflexion_cluster import summary
    return summary()


def _prompt_versions() -> str:
    from AI.ai.prompt_versions import summary
    return summary()


def _prompt_impact() -> str:
    from AI.ai.prompt_impact import summary
    return summary()


def _health_score() -> str:
    from AI.ai.health_score import summary
    return summary()


def _safety_gate() -> str:
    from AI.ai.safety_gate import summary
    return summary()


def _suppressions() -> str:
    from AI.ai.finding_suppressions import summary
    return summary()


def _compliance_promoter() -> str:
    from AI.ai.compliance_promoter import summary
    return summary()


_REGISTRY: list[tuple[str, str, Callable[[], str]]] = [
    ("score",        "Health score",              _health_score),
    ("safety",       "Safety gate (cooldown + budget)", _safety_gate),
    ("ledger",       "Diagnostic ledger trend",   _diagnostic_ledger),
    ("regression",   "Regression check",          _regression_detector),
    ("suppressions", "Finding suppressions",      _suppressions),
    ("prompt",       "Diagnostic prompt drift",   _prompt_versions),
    ("prompt_impact","Prompt-impact analysis",    _prompt_impact),
    ("compliance",   "Compliance threshold tuner", _compliance_promoter),
    ("distillation", "Per-tier distillation matrix", _distillation_tracker),
    ("gaps",         "Capability gaps",           _gap_detector),
    ("reflexion",    "Reflexion themes",          _reflexion_cluster),
]


def sections() -> list[Section]:
    out: list[Section] = []
    for name, title, fn in _REGISTRY:
        body, err = _safe_call(fn)
        out.append(Section(name=name, title=title, body=body, error=err))
    return out


def render() -> str:
    parts: list[str] = ["# AIM/AI Dashboard\n"]
    for s in sections():
        parts.append(f"## {s.title}")
        parts.append("")
        parts.append(s.body)
        if s.error:
            parts.append(f"_section error: {s.error}_")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_json() -> str:
    """Machine-readable dashboard for downstream tools (Telegram bot,
    Grafana scrape, etc.)."""
    import json
    payload = []
    for s in sections():
        payload.append({
            "name": s.name,
            "title": s.title,
            "body": s.body,
            "ok": s.ok,
            "error": s.error,
        })
    return json.dumps({"sections": payload}, ensure_ascii=False, indent=2)


def render_compact() -> str:
    """Telegram-friendly: 1-3 lines per section. Strips verbose body
    down to the headline metric per module."""
    import re

    def first_line(body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                # Drop emoji prefix for tighter Telegram rendering
                return re.sub(r"^[^\w\d]*\s*", "", stripped)[:120]
        return "(empty)"

    parts = ["📡 AIM/AI compact"]
    for s in sections():
        head = first_line(s.body)
        mark = "✓" if s.ok else "✗"
        parts.append(f"{mark} {s.title}: {head}")
    return "\n".join(parts)
