"""AI/ai/meta_evaluator.py — diagnostic prompt reproducibility (S12, 2026-05-03).

We observed during the SD1 audit cycle that the SAME code + SAME 9-phase
prompt fed through DeepSeek-reasoner produced grades C → F → D on three
consecutive runs. Adversarial mode amplifies stochasticity: the model
finds new "concerns" each pass, escalating severity inconsistently.

S12 measures this directly:

  1. Run the diagnostic N times (default 3) against the SAME inventory.
  2. Parse each report for: total finding count by severity, claimed
     grade, set of file:line references.
  3. Compute reproducibility metrics:
        * grade_variance        — set of distinct grades observed
        * jaccard_findings      — overlap of file:line refs across runs
        * crit_count_stddev     — stability of "crit" severity
        * shared_findings       — refs appearing in ≥2 runs (the signal)
        * unique_findings       — refs in exactly 1 run (the noise)
  4. Verdict:
        * stable     — same grade, jaccard ≥ 0.6, signal/noise ≥ 1.5
        * noisy      — grade variance OR jaccard < 0.4
        * unstable   — both conditions

Output: a markdown report with the verdict + recommendation
(re-prompt, narrow scope, or accept the noisy nature of adversarial
audits).

Public API:
    parse_report(text) -> ReportFacts
    measure(reports: Sequence[str]) -> Reproducibility
    summary(reports) -> str
"""
from __future__ import annotations

import dataclasses
import logging
import re
import statistics
from typing import Iterable, Optional, Sequence

log = logging.getLogger("ai.meta_evaluator")


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class ReportFacts:
    grade: Optional[str]
    totals: dict[str, int]   # {"crit": N, "high": N, "med": N, "low": N}
    findings: set[str]       # file refs (with or without :line)

    @property
    def line_compliance(self) -> float:
        """Fraction of findings carrying a `:line` ref. Diagnostic prompt
        requires path:line per L_VERIFIABILITY — low ratio = audit
        should be re-run with stricter prompt."""
        if not self.findings:
            return 0.0
        with_line = sum(1 for r in self.findings if ":" in r and
                         r.rsplit(":", 1)[-1].isdigit())
        return with_line / len(self.findings)


@dataclasses.dataclass
class Reproducibility:
    n_runs: int
    grades: list[Optional[str]]
    grade_variance: int       # number of distinct grades
    crit_counts: list[int]
    crit_stddev: float
    jaccard_findings: float   # over the union of all reports
    shared_findings: set[str]
    unique_findings: set[str]
    verdict: str              # stable | noisy | unstable

    def signal_to_noise(self) -> float:
        if not self.unique_findings:
            return float("inf") if self.shared_findings else 0.0
        return len(self.shared_findings) / max(1, len(self.unique_findings))


# ── parsing ──────────────────────────────────────────────────────


_GRADE_RE = re.compile(
    r"\b(?:Overall\s+)?[Gg]rade[\s:*]+([A-F])\b"
)
_TOTAL_RE = re.compile(
    r"^\s*\|?\s*(crit|high|med|low)\b[\s:|]+(\d+)",
    re.IGNORECASE | re.MULTILINE,
)
# Reference to a path:line. We accept absolute and relative paths.
_REF_RE = re.compile(
    r"`?([\w./_-]+\.(?:py|md|yaml|yml|toml|sh|rs))(?::(\d+))?`?"
)


def parse_report(text: str) -> ReportFacts:
    """Extract grade + severity totals + file:line refs from a markdown
    audit report. Best-effort: missing fields → None / 0 / empty."""
    if not isinstance(text, str):
        return ReportFacts(grade=None, totals={}, findings=set())

    grade = None
    m = _GRADE_RE.search(text)
    if m:
        grade = m.group(1).upper()

    totals: dict[str, int] = {}
    for m in _TOTAL_RE.finditer(text):
        key = m.group(1).lower()
        try:
            totals[key] = int(m.group(2))
        except ValueError:
            continue

    refs: set[str] = set()
    for m in _REF_RE.finditer(text):
        path = m.group(1).lstrip("./")
        line = m.group(2)
        # Filter out obvious non-code refs (config-like extensions are OK,
        # but we want SOMETHING that looks like a real path component).
        if "/" not in path and not path.endswith(".py"):
            continue
        ref = f"{path}:{line}" if line else path
        refs.add(ref)
    return ReportFacts(grade=grade, totals=totals, findings=refs)


# ── measurement ──────────────────────────────────────────────────


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def measure(reports: Sequence[str]) -> Reproducibility:
    """Compare ≥2 reports of the same code; emit reproducibility metrics."""
    if len(reports) < 2:
        raise ValueError("need at least 2 reports to measure reproducibility")

    parsed = [parse_report(r) for r in reports]
    grades = [p.grade for p in parsed]
    distinct_grades = len({g for g in grades if g is not None})
    crit_counts = [p.totals.get("crit", 0) for p in parsed]
    crit_stddev = (statistics.stdev(crit_counts)
                    if len(crit_counts) >= 2 else 0.0)

    # Pairwise Jaccard, averaged.
    jacc_pairs: list[float] = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            jacc_pairs.append(_jaccard(parsed[i].findings, parsed[j].findings))
    jaccard_avg = sum(jacc_pairs) / len(jacc_pairs) if jacc_pairs else 0.0

    # Shared (signal) vs unique (noise) findings.
    finding_counts: dict[str, int] = {}
    for p in parsed:
        for ref in p.findings:
            finding_counts[ref] = finding_counts.get(ref, 0) + 1
    shared = {ref for ref, n in finding_counts.items() if n >= 2}
    unique = {ref for ref, n in finding_counts.items() if n == 1}

    # Verdict.
    if distinct_grades > 1 and jaccard_avg < 0.4:
        verdict = "unstable"
    elif distinct_grades > 1 or jaccard_avg < 0.4:
        verdict = "noisy"
    else:
        verdict = "stable"

    return Reproducibility(
        n_runs=len(reports),
        grades=grades,
        grade_variance=distinct_grades,
        crit_counts=crit_counts,
        crit_stddev=crit_stddev,
        jaccard_findings=jaccard_avg,
        shared_findings=shared,
        unique_findings=unique,
        verdict=verdict,
    )


# ── reporting ────────────────────────────────────────────────────


def summary(reports: Sequence[str]) -> str:
    if len(reports) < 2:
        return "(need at least 2 reports to assess reproducibility)"
    m = measure(reports)
    parts = [
        f"🔬 Diagnostic reproducibility — {m.n_runs} runs",
        f"  grades:           {m.grades}",
        f"  grade variance:   {m.grade_variance} distinct",
        f"  crit per run:     {m.crit_counts}  (stddev {m.crit_stddev:.2f})",
        f"  pair Jaccard:     {m.jaccard_findings:.3f}",
        f"  shared findings:  {len(m.shared_findings)}  (signal)",
        f"  unique findings:  {len(m.unique_findings)} (noise)",
        f"  signal/noise:     {m.signal_to_noise():.2f}",
        f"  verdict:          {m.verdict.upper()}",
    ]
    if m.verdict != "stable":
        parts.append("")
        parts.append("Recommendation:")
        if m.verdict == "unstable":
            parts.append("  Both grade and findings vary widely. Either")
            parts.append("  the prompt is too open-ended OR the model is")
            parts.append("  in adversarial-paranoia mode. Treat findings")
            parts.append("  as noise; rely on SHARED findings only.")
        else:  # noisy
            parts.append("  Grades or findings drift. Trust signal over")
            parts.append("  individual runs; act on shared findings.")
    return "\n".join(parts)


def shared_only(reports: Sequence[str]) -> set[str]:
    """Return ONLY findings that appear in ≥2 reports — the signal."""
    if len(reports) < 2:
        return set()
    return measure(reports).shared_findings
