"""AI/ai/explainer.py — EX1 (2026-05-04).

When `aim diag --score` says 67/100 grade C, the user needs to know
WHAT to fix. This module produces an actionable explanation: per
component, why points were deducted and what concrete step recovers
them.

Public API:
    explain() -> Explanation
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Optional

log = logging.getLogger("ai.explainer")


@dataclasses.dataclass
class Recovery:
    component: str       # "wiring" | "regression" | "compliance" | "cases" | "prompt_drift"
    pts_lost: int
    why: str             # short cause
    action: str          # one-line concrete step


@dataclasses.dataclass
class Explanation:
    total: int
    grade: str
    recoveries: list[Recovery]


def explain() -> Explanation:
    """Build per-component recovery suggestions for the current score."""
    from AI.ai.health_score import score, _W_WIRING, _W_REGRESSION
    from AI.ai.health_score import _W_COMPLIANCE, _W_CASES, _W_PROMPT_DRIFT

    s = score()
    weights = {
        "wiring": _W_WIRING,
        "regression": _W_REGRESSION,
        "compliance": _W_COMPLIANCE,
        "cases": _W_CASES,
        "prompt_drift": _W_PROMPT_DRIFT,
    }
    recoveries: list[Recovery] = []
    for name, full in weights.items():
        got = s.components.get(name, 0)
        if got >= full:
            continue
        lost = full - got
        why, action = _diagnose(name, got, full)
        recoveries.append(Recovery(
            component=name, pts_lost=lost, why=why, action=action,
        ))
    # Sort: biggest pts_lost first (highest leverage to fix).
    recoveries.sort(key=lambda r: r.pts_lost, reverse=True)
    return Explanation(total=s.total, grade=s.grade, recoveries=recoveries)


def _diagnose(component: str, got: int, full: int) -> tuple[str, str]:
    """Map (component, got) → (why, action)."""
    if component == "wiring":
        try:
            from AI.ai.doctor import diagnose
            probes = diagnose()
            crit = [p for p in probes
                    if not p.ok and p.severity == "crit"]
            if crit:
                names = ", ".join(p.name for p in crit)
                return (
                    f"{len(crit)} critical wiring probe(s) failed: {names}",
                    f"run `aim diag --doctor` and fix the crit failures",
                )
            warn = [p for p in probes
                    if not p.ok and p.severity == "warn"]
            if warn:
                names = ", ".join(p.name for p in warn)
                return (
                    f"{len(warn)} warning(s): {names}",
                    "address warnings (e.g. set DEEPSEEK_API_KEY in ~/.aim_env)",
                )
        except Exception:
            pass
        return ("wiring not fully passing",
                "run `aim diag --doctor` for detail")

    if component == "regression":
        try:
            from AI.ai.regression_detector import detect
            r = detect()
            if not r.have_baseline:
                return (
                    "no baseline yet (need ≥2 diagnostic runs)",
                    "let the daily cron accumulate runs OR run "
                    "`aim diag --run` (cost: ~$0.01)",
                )
            if r.regressed:
                n = len(r.new_findings)
                return (
                    f"REGRESSED: {n} new finding(s) since previous run",
                    f"run `aim diag --regress` to inspect; suppress "
                    "false-positives via `aim diag --suppress REF`",
                )
        except Exception:
            pass
        return ("regression check incomplete",
                "ensure ledger has 2+ runs with grades + report paths")

    if component == "compliance":
        try:
            from AI.ai.diagnostic_ledger import trend
            t = trend()
            if t["n_runs"] == 0:
                return ("no diagnostic runs",
                         "run `aim diag --run` to accumulate baseline")
            avg = t["avg_compliance"]
            if avg < 0.3:
                return (
                    f"avg compliance {avg:.0%} (model ignores path:line rule)",
                    "tighten SELF_DIAGNOSTIC_PROMPT.md or switch to a "
                    "stricter model (e.g. claude-sonnet-4-6)",
                )
            if avg < 0.6:
                return (
                    f"avg compliance {avg:.0%} — borderline",
                    "let CP1 recommend threshold tuning: "
                    "`aim diag --dashboard` shows the recommendation",
                )
        except Exception:
            pass
        return ("compliance below full credit",
                "run `aim diag --trend` for breakdown")

    if component == "cases":
        try:
            from AI.ai.case_validator import validate_dir
            rep = validate_dir()
            if rep.n_failed:
                return (
                    f"{rep.n_failed} invalid eval case(s)",
                    "run `aim diag --validate-cases` and fix the listed "
                    "yaml schemas",
                )
        except Exception:
            pass
        return ("eval cases not fully clean",
                "run `aim diag --validate-cases`")

    if component == "prompt_drift":
        try:
            from AI.ai.prompt_versions import history, fingerprint
            h = history()
            cur = fingerprint()
            if not h:
                return (
                    "prompt never fingerprinted",
                    "run `aim diag --sweep` once to fingerprint",
                )
            if h[-1].sha256 != cur.sha256:
                return (
                    "prompt drifted since last record",
                    "run `aim diag --sweep` to record the new revision",
                )
        except Exception:
            pass
        return ("prompt drift not at full credit",
                "run `aim diag --dashboard` for the prompt section")

    return ("(unrecognised component)", "(no specific action)")


def summary() -> str:
    e = explain()
    parts = [f"📋 Score breakdown — {e.total}/100 (grade {e.grade})"]
    if not e.recoveries:
        parts.append("  ✅ all components at full credit — nothing to fix")
        return "\n".join(parts)
    parts.append("")
    parts.append("Recoverable points (largest leverage first):")
    for r in e.recoveries:
        parts.append(f"\n  [{r.component}] −{r.pts_lost}")
        parts.append(f"    why:    {r.why}")
        parts.append(f"    action: {r.action}")
    return "\n".join(parts)
