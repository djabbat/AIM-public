"""AI/ai/fix_planner.py — turn shared-findings into actionable patches (S14, 2026-05-03).

Closes the SD1 → S12 → S13 → ACTION loop:

  * stable_run produces shared_findings — file:line refs the model
    flagged in ≥2 runs (high-confidence signal)
  * fix_planner groups them by file, reads the actual lines, and
    emits a punch-list with concrete recommended fixes

The recommendations are heuristic, not LLM-generated, so we don't
introduce another stochastic layer. The point is to give the human
ONE list of "open file X, look at line N, do thing Y" instead of
N independent findings.

Public API:
    plan(shared_findings: Iterable[str]) -> FixPlan
    summary(plan) -> str
    write_plan(plan, *, dest=None) -> Path
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ai.fix_planner")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def ai_root() -> Path:
    return project_root() / "AI"


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class FileFix:
    path: str            # repo-relative
    line_refs: list[int] # sorted unique line numbers
    snippets: dict[int, str]  # {line: source line, no \n}
    suggestion: str      # heuristic fix recommendation


@dataclasses.dataclass
class FixPlan:
    n_files: int
    n_lines: int
    files: list[FileFix]


# ── parse ────────────────────────────────────────────────────────


_REF_RE = re.compile(r"^([\w./_-]+\.\w+)(?::(\d+))?$")


def _parse_ref(ref: str) -> Optional[tuple[str, Optional[int]]]:
    m = _REF_RE.match(ref.strip().strip("`"))
    if not m:
        return None
    path = m.group(1).lstrip("./")
    line = int(m.group(2)) if m.group(2) else None
    return (path, line)


# ── fix-recommendation heuristics ──────────────────────────────


_PATH_HINTS: tuple[tuple[str, str], ...] = (
    ("distillation_tracker",
     "DB hardening: WAL + UNIQUE index + contextlib.closing(conn) + "
     "INSERT OR REPLACE — see CRIT-2 fix pattern."),
    ("eval_synthesiser",
     "L_VERIFIABILITY: route persisted spec through "
     "citation_guard.extract — reject if fabricated PMID/DOI present."),
    ("gap_detector",
     "Iterator safety: materialise surrender_list with list(...) "
     "before second pass — CRIT-3 generator-safe pattern."),
    ("citation_guard",
     "Verifiability: pipe through citation_guard.verify(strict=True) "
     "before emit; reject fabricated refs."),
    ("patient",
     "Privacy: confirm Patients/ scope is gated; ensure L_PRIVACY "
     "check fires before any persist."),
    ("worktree",
     "Worktree isolation: ensure agents.worktree.isolate() wraps any "
     "code-modification flow before mutation."),
    ("self_modify",
     "Eval-gate: any self-modification must run through S1 evals "
     "(Δscore≥0.05, p≤0.05) before merging into main."),
    ("orchestrator",
     "Decision kernel: confirm L0–L3 + L_PRIVACY/CONSENT/VERIFIABILITY "
     "all fire on the path; do not bypass."),
)


def _suggestion_for(path: str, snippets: dict[int, str]) -> str:
    """Heuristic recommendation based on path + the actual source line.

    Path patterns are checked first (cheap, deterministic), then
    snippet content. Test/doc paths are last because they're catch-alls.
    """
    plow = path.lower()
    body = " ".join(snippets.values()).lower()

    for key, advice in _PATH_HINTS:
        if key in plow:
            return advice

    if "patients/" in body:
        return ("Privacy: confirm Patients/ scope is gated; ensure "
                "L_PRIVACY check fires before any persist.")
    if "pmid" in body or "doi" in body or "citation" in body:
        return ("Verifiability: pipe through citation_guard.verify("
                "strict=True) before emit; reject fabricated refs.")
    if "subprocess" in body or "shell=true" in body or "os.system" in body:
        return ("Bash sandbox: route through agents.generalist._validate_bash "
                "or agents.worktree.isolate.")
    if "sqlite" in body or "execute(" in body or "insert " in body:
        return ("DB hardening: use contextlib.closing(conn); WAL mode; "
                "INSERT OR REPLACE for idempotency.")
    if "open(" in body or "write_text" in body or "file.write" in body:
        return ("Path sandbox: validate target path against AIM_GENERALIST_ROOT "
                "and refuse secret-path patterns.")
    if "except" in body and "pass" in body:
        return ("Silent failure: swap `except: pass` for at least "
                "log.warning(...); preserve traceback.")
    if "todo" in body or "fixme" in body or "xxx" in body:
        return ("Stale TODO/FIXME — convert to GitHub issue or remove.")
    if path.endswith("_test.py") or path.startswith("tests/") or "/tests/" in path:
        return ("Test quality: add pytest.raises for negative path; "
                "freeze datetime.now() with monkeypatch.")
    if "magic" in body or any(re.search(r"\b\d{2,}\b", l)
                                for l in snippets.values()):
        return ("Magic number — extract to module-level CONSTANT.")
    if path.endswith(".md"):
        return ("Documentation: cross-check claim against source code.")
    return ("Read the file at the cited line and decide if the model's "
            "concern is real before patching.")


# ── plan() ───────────────────────────────────────────────────────


def plan(shared_findings: Iterable[str],
         *,
         root: Optional[Path] = None,
         context_lines: int = 0) -> FixPlan:
    """Group shared findings by file; read each cited line; suggest fix.

    `root` defaults to the repo root (parent of AI/). `context_lines`
    pulls additional surrounding lines into the snippet for richer
    suggestions.
    """
    root = root or project_root()
    by_file: dict[str, set[int]] = {}
    no_line: dict[str, bool] = {}

    for ref in shared_findings:
        parsed = _parse_ref(ref)
        if parsed is None:
            continue
        path, line = parsed
        if line is None:
            no_line[path] = True
            by_file.setdefault(path, set())
        else:
            by_file.setdefault(path, set()).add(line)

    files: list[FileFix] = []
    for path, lines in sorted(by_file.items()):
        full = (root / path) if not Path(path).is_absolute() else Path(path)
        snippets: dict[int, str] = {}
        if full.exists() and full.is_file():
            try:
                source = full.read_text(encoding="utf-8",
                                         errors="replace").splitlines()
            except OSError:
                source = []
            for ln in sorted(lines):
                start = max(1, ln - context_lines)
                end = min(len(source), ln + context_lines)
                for j in range(start, end + 1):
                    if 1 <= j <= len(source):
                        snippets[j] = source[j - 1]
        suggestion = _suggestion_for(path, snippets)
        files.append(FileFix(
            path=path,
            line_refs=sorted(lines),
            snippets=snippets,
            suggestion=suggestion,
        ))

    return FixPlan(
        n_files=len(files),
        n_lines=sum(len(f.line_refs) for f in files),
        files=files,
    )


# ── render ───────────────────────────────────────────────────────


def summary(plan_obj: FixPlan) -> str:
    if plan_obj.n_files == 0:
        return "(no shared findings to plan around)"
    lines = [f"🛠 Fix plan — {plan_obj.n_files} files, "
             f"{plan_obj.n_lines} cited lines"]
    for f in plan_obj.files:
        line_str = (", ".join(str(l) for l in f.line_refs)
                     if f.line_refs else "—")
        lines.append(f"  • {f.path}  [L {line_str}]")
        lines.append(f"      → {f.suggestion}")
    return "\n".join(lines)


def render_markdown(plan_obj: FixPlan) -> str:
    parts: list[str] = []
    parts.append("# AIM/AI Fix Plan (from shared findings)")
    parts.append("")
    parts.append(f"**Files:** {plan_obj.n_files}  ")
    parts.append(f"**Cited lines:** {plan_obj.n_lines}  ")
    parts.append("")
    if plan_obj.n_files == 0:
        parts.append("_(no shared findings — nothing to plan)_")
        return "\n".join(parts)

    for f in plan_obj.files:
        parts.append(f"## `{f.path}`")
        parts.append("")
        if f.line_refs:
            parts.append(f"Lines: {', '.join(str(l) for l in f.line_refs)}")
        parts.append("")
        parts.append(f"**Suggestion:** {f.suggestion}")
        parts.append("")
        if f.snippets:
            parts.append("```python")
            for ln in sorted(f.snippets):
                parts.append(f"{ln:4d}: {f.snippets[ln]}")
            parts.append("```")
            parts.append("")
    return "\n".join(parts)


def write_plan(plan_obj: FixPlan,
                *, dest: Optional[Path] = None) -> Path:
    if dest is None:
        dest = (ai_root() / "artifacts"
                / f"fix_plan_{dt.date.today():%Y-%m-%d}.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_markdown(plan_obj), encoding="utf-8")
    return dest
