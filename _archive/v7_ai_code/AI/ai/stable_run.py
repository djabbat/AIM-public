"""AI/ai/stable_run.py — repeatable diagnostic orchestrator (S13).

Phase 9 Tier 4 #24 (2026-05-07): Python orchestrates N invocations of
the Rust `aim-ai-diag` binary (no-save mode), then consolidates via
`aim-ai-meta-evaluator measure`. The Rust crate `aim-ai-stable-run`
exists but requires an injected closure; calling the binary N times
matches the original Python public-API shape and keeps tests easy to
mock.

Public API (preserved):
    StableResult dataclass (with avg_compliance / compliance_ok properties)
    stable_run(n=3, model="deepseek-reasoner", *, run_fn=None,
                save_individual=False) -> StableResult
    render_consolidated(result) -> str
    write_consolidated(result, *, dest=None) -> Path
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.stable_run")


@dataclasses.dataclass
class StableResult:
    n_runs: int
    raw_reports: list[str]
    grades: list[Optional[str]]
    verdict: str
    shared_findings: list[str]
    unique_findings: list[str]
    crit_counts: list[int]
    jaccard: float
    line_compliance: list[float] = dataclasses.field(default_factory=list)

    @property
    def avg_compliance(self) -> float:
        return (sum(self.line_compliance) / len(self.line_compliance)
                if self.line_compliance else 0.0)

    @property
    def compliance_ok(self) -> bool:
        return self.avg_compliance >= 0.8


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def ai_root() -> Path:
    return project_root() / "AI"


def _diag_binary() -> Path:
    return project_root() / "rust-core" / "target" / "release" / "aim-ai-diag"


def _default_run_one(model: str) -> str:
    """Default implementation: shell out to aim-ai-diag --no-save --quiet
    and capture the report from stdout."""
    bin_path = _diag_binary()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-diag binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), "--model", model, "--no-save", "--quiet"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise RuntimeError(f"aim-ai-diag failed: {msg}")
    return proc.stdout


def stable_run(n: int = 3,
                model: str = "deepseek-reasoner",
                *,
                run_fn=None,
                save_individual: bool = False,
                ) -> StableResult:
    """Run the diagnostic `n` times and consolidate."""
    if n < 2:
        raise ValueError("stable_run needs n >= 2 (otherwise no signal)")
    if run_fn is None:
        def run_fn(model: str = model) -> str:  # type: ignore
            return _default_run_one(model)
    reports: list[str] = []
    for i in range(n):
        log.info("stable_run pass %d/%d (model=%s)", i + 1, n, model)
        reports.append(run_fn(model=model))
    if save_individual:
        for i, r in enumerate(reports, 1):
            p = (ai_root() / "artifacts"
                 / f"stable_run_{dt.date.today():%Y-%m-%d}_pass{i}.md")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r, encoding="utf-8")
    from AI.ai.meta_evaluator import measure, parse_report
    m = measure(reports)
    compliance = [parse_report(r).line_compliance for r in reports]
    return StableResult(
        n_runs=n,
        raw_reports=reports,
        grades=m.grades,
        verdict=m.verdict,
        shared_findings=sorted(m.shared_findings),
        unique_findings=sorted(m.unique_findings),
        crit_counts=m.crit_counts,
        jaccard=m.jaccard_findings,
        line_compliance=compliance,
    )


def render_consolidated(result: StableResult) -> str:
    parts: list[str] = []
    parts.append("# AIM/AI Stable-Run Diagnostic")
    parts.append("")
    parts.append(f"**Runs:** {result.n_runs}  ")
    parts.append(f"**Grades observed:** {result.grades}  ")
    parts.append(f"**Crit counts:** {result.crit_counts}  ")
    parts.append(f"**Pair Jaccard (findings):** {result.jaccard:.3f}  ")
    parts.append(f"**Line compliance per run:** "
                 f"{[f'{c:.0%}' for c in result.line_compliance]} "
                 f"(avg {result.avg_compliance:.0%})  ")
    if not result.compliance_ok:
        parts.append("**⚠ Line compliance below 80%** — refs are not "
                     "trustworthy enough for fix_planner. Tighten prompt "
                     "or rerun.  ")
    parts.append(f"**Verdict:** **{result.verdict.upper()}**")
    parts.append("")
    parts.append("## Signal — findings reproduced across runs")
    parts.append("")
    if result.shared_findings:
        for ref in result.shared_findings:
            parts.append(f"- `{ref}`")
    else:
        parts.append("_(no findings reproduced across runs — every "
                     "concern raised was a one-off)_")
    parts.append("")
    parts.append(f"## Noise — findings raised in only one run "
                 f"({len(result.unique_findings)})")
    parts.append("")
    if result.unique_findings:
        for ref in result.unique_findings[:20]:
            parts.append(f"- `{ref}`")
        if len(result.unique_findings) > 20:
            parts.append(f"  _(+{len(result.unique_findings) - 20} more)_")
    else:
        parts.append("_(no one-off noise — clean signal)_")
    parts.append("")
    parts.append("## Recommendation")
    parts.append("")
    if result.verdict == "stable":
        parts.append("Findings are reproducible — act on the full list "
                     "above. Adversarial mode converged.")
    elif result.verdict == "noisy":
        parts.append("Either grade or finding set drifted. Trust SHARED "
                     "findings only; treat unique findings as noise. "
                     "Consider tightening the prompt's severity rubric.")
    else:
        parts.append("Both grade and findings vary widely. Either the "
                     "prompt is too open-ended or the model is in "
                     "paranoia mode. Either accept noise or rewrite "
                     "the prompt with stricter Phase 7 criteria.")
    parts.append("")
    return "\n".join(parts)


def write_consolidated(result: StableResult,
                       *, dest: Optional[Path] = None) -> Path:
    if dest is None:
        dest = (ai_root() / "artifacts"
                / f"stable_run_{dt.date.today():%Y-%m-%d}.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_consolidated(result), encoding="utf-8")
    return dest


def _main() -> int:
    import argparse, sys
    ap = argparse.ArgumentParser(description="Stable-run diagnostic")
    ap.add_argument("--n", type=int, default=3,
                    help="number of repeat runs (default 3)")
    ap.add_argument("--model", default="deepseek-reasoner")
    ap.add_argument("--save-individual", action="store_true",
                    help="also write each pass to disk")
    args = ap.parse_args()
    try:
        result = stable_run(n=args.n, model=args.model,
                            save_individual=args.save_individual)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    out = write_consolidated(result)
    print(f"verdict: {result.verdict}")
    print(f"grades:  {result.grades}")
    print(f"shared findings: {len(result.shared_findings)}")
    print(f"noise findings:  {len(result.unique_findings)}")
    print(f"report → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
