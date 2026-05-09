"""AI/ai/eval_synthesiser.py — synthesise eval cases from observed failures (S8, 2026-05-03).

Closes the pipeline:
  reflexion → pattern_miner → eval_synthesiser → S1 evals → S3 prompt evolver

Inputs:
  * `agents.pattern_miner.mine` findings (slow_tool, tool_failure_rate,
    error_type_frequency, sequential_pair, redundant_memory_query)
  * recent reflexion notes from
    `~/.claude/projects/-home-oem/memory/feedback_*.md` (per Reflexion's
    bucket layout) — short verbal "what to do differently" notes

Outputs:
  * YAML eval cases under `AI/cases/auto_<id>.yaml` (or env override).
    Each case probes one observed failure mode by giving the model a
    task that previously failed and a rubric that catches the failure
    signature (e.g. "if reply contains a fabricated PMID → fail").

Rubrics emitted per finding kind:
  * tool_failure_rate    → forbids: ["ERROR:"] + min_length: 10
  * slow_tool            → max_length: 4000  (force concise outputs)
  * error_type_frequency → forbids: [<error prefix>]
  * sequential_pair      → contains_all: [<tool_a>, <tool_b>] (probe synth)
  * reflexion (verbal)   → free-form contains_all key terms from note

Public API:
    synthesise(window_days=7, *, dry_run=False) -> list[CasePath]
    synthesise_from_reflexion(text, *, slug=None) -> CaseSpec
    audit() -> list[dict]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("ai.eval_synthesiser")


def cases_dir() -> Path:
    env = os.environ.get("AI_SYNTH_CASES_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "cases"


def audit_path() -> Path:
    base = (Path(os.environ.get("AIM_HOME") or
                  Path.home() / ".cache" / "aim").expanduser())
    p = base / "ai_eval_synth.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class CaseSpec:
    id: str
    task: str
    rubrics: dict
    tags: list[str]
    source: str          # "pattern:tool_failure_rate" | "reflexion:medical" | …
    weight: float = 1.0

    def to_yaml(self) -> str:
        # Hand-rolled YAML so we don't pull yaml.safe_dump's quoting decisions.
        lines = [f"id: {self.id}",
                 f"task: |\n  " + self.task.replace("\n", "\n  "),
                 f"tags: {self.tags}",
                 f"weight: {self.weight}",
                 "rubrics:"]
        for k, v in self.rubrics.items():
            if isinstance(v, str):
                lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
            elif isinstance(v, list):
                lines.append(f"  {k}: " + json.dumps(
                    list(v), ensure_ascii=False))
            else:
                lines.append(f"  {k}: {v}")
        lines.append(f"# auto-generated source: {self.source}")
        return "\n".join(lines) + "\n"


# ── pattern → CaseSpec ──────────────────────────────────────────


_REFLEXION_KEYTERM_RE = re.compile(
    r"\b([A-Za-zА-Яа-я][\w-]{4,30})\b"
)


def _slug(s: str, max_len: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:max_len] or hashlib.sha1(s.encode()).hexdigest()[:8]


def _from_finding(f) -> Optional[CaseSpec]:
    """Translate one pattern_miner.Finding into an eval case."""
    kind = f.kind
    sample = getattr(f, "sample", {}) or {}
    summary = getattr(f, "summary", "") or ""

    if kind == "tool_failure_rate":
        tool = sample.get("tool") or sample.get("name") or "the offending tool"
        return CaseSpec(
            id=f"auto-fail-{_slug(tool)}",
            task=(f"You must complete a task that previously caused "
                  f"`{tool}` to fail at least 30% of the time. Plan the "
                  f"call carefully; do NOT emit ERROR: prefixes or fall "
                  f"back to apology language."),
            rubrics={
                "forbids": ["ERROR:", "as an AI", "I cannot"],
                "min_length": 40,
            },
            tags=["auto", "tool_failure"],
            source=f"pattern:tool_failure_rate:{tool}",
        )

    if kind == "slow_tool":
        tool = sample.get("name") or "tool"
        return CaseSpec(
            id=f"auto-slow-{_slug(tool)}",
            task=(f"Reply concisely (≤120 words) on a topic where the "
                  f"underlying tool `{tool}` typically takes >2s. The eval "
                  f"penalises long verbose answers."),
            rubrics={
                "max_length": 1200,
                "forbids": ["as previously discussed", "in summary, in summary"],
            },
            tags=["auto", "slow_tool"],
            source=f"pattern:slow_tool:{tool}",
        )

    if kind == "error_type_frequency":
        prefix = sample.get("prefix") or "ERROR"
        return CaseSpec(
            id=f"auto-err-{_slug(prefix)}",
            task=(f"Produce an answer that does NOT trip the recurring "
                  f"error class {prefix!r}. Be specific and grounded."),
            rubrics={
                "forbids": [prefix, "ERROR:"],
                "min_length": 30,
            },
            tags=["auto", "error_class"],
            source=f"pattern:error_type_frequency:{prefix}",
        )

    if kind == "sequential_pair":
        a = sample.get("a", "")
        b = sample.get("b", "")
        if not (a and b):
            return None
        return CaseSpec(
            id=f"auto-pair-{_slug(a)}-{_slug(b)}",
            task=(f"Solve a multi-step problem that frequently chains "
                  f"`{a}` → `{b}`. Mention both steps explicitly so the "
                  f"reasoning is traceable."),
            rubrics={
                "contains_all": [a, b],
                "min_length": 60,
            },
            tags=["auto", "sequential_pair"],
            source=f"pattern:sequential_pair:{a}|{b}",
        )

    if kind == "redundant_memory_query":
        return CaseSpec(
            id=f"auto-cache-{hashlib.sha1(summary.encode()).hexdigest()[:8]}",
            task=("Answer using your existing context — do NOT request "
                  "memory recall again for facts already in the prompt."),
            rubrics={
                "forbids": ["recall", "let me check memory"],
                "min_length": 20,
            },
            tags=["auto", "cache_redundant"],
            source="pattern:redundant_memory_query",
        )

    return None


# ── reflexion → CaseSpec ────────────────────────────────────────


def synthesise_from_reflexion(text: str,
                              *, slug: Optional[str] = None) -> Optional[CaseSpec]:
    """Convert a verbal reflexion note into an eval case.

    Strategy: pull 2-3 substantive key terms out of the note; the
    rubric requires the answer to address them. This isn't perfect
    (a model could namedrop the terms without solving the problem),
    but combined with the existing forbids list it raises the bar.
    """
    if not isinstance(text, str) or len(text.strip()) < 20:
        return None
    # Drop obvious filler words.
    fillers = {"the", "and", "for", "with", "that", "this", "from",
                "they", "your", "their", "user", "model", "agent",
                "after", "когда", "если", "чтобы", "также", "может"}
    terms: list[str] = []
    seen: set[str] = set()
    for m in _REFLEXION_KEYTERM_RE.finditer(text):
        term = m.group(1)
        low = term.lower()
        if low in fillers or low in seen:
            continue
        seen.add(low)
        terms.append(term)
        if len(terms) >= 3:
            break
    if not terms:
        return None
    sid = slug or _slug(text[:60])
    return CaseSpec(
        id=f"auto-rfx-{sid}",
        task=(f"Address the lesson from a recent failure note: "
              f"{text.strip()[:300]}. Make sure your answer reflects it."),
        rubrics={
            "contains_all": terms,
            "forbids": ["as an AI", "I cannot help"],
            "min_length": 60,
        },
        tags=["auto", "reflexion"],
        source="reflexion",
    )


# ── orchestrate ─────────────────────────────────────────────────


def _gather_reflexion_texts(window_days: int = 30) -> list[str]:
    """Pull recent verbal reflexion notes from
    `~/.claude/projects/-home-oem/memory/feedback_*.md`.

    These are user-curated rules-of-thumb captured as feedback memories;
    using them as eval seeds turns the user's corrections into machine-
    enforceable cases.
    """
    base = (Path.home() / ".claude" / "projects" /
            "-home-oem" / "memory")
    if not base.exists():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=window_days)
    out: list[str] = []
    for p in base.glob("feedback_*.md"):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Strip frontmatter.
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4:]
        text = text.strip()
        if len(text) >= 20:
            out.append(text)
    return out


def _verify_no_fabricated_citations(spec: CaseSpec) -> Optional[str]:
    """L_VERIFIABILITY gate (CRIT-1 fix, 2026-05-03).

    Run citation_guard over the case YAML body. If unresolved citations
    found, refuse to persist — better an empty cases dir than fabricated
    science seeded into the eval suite.

    Returns None if clean, or an error string if blocked.
    """
    try:
        from agents.citation_guard import extract
    except ImportError:
        return None  # citation_guard unavailable → no enforcement
    blob = spec.task + " " + json.dumps(spec.rubrics, ensure_ascii=False)
    cites = extract(blob)
    if not cites:
        return None
    # We don't actually hit PubMed/Crossref here (cron-time) — just
    # extract suspicious refs. Auto-generated cases shouldn't carry
    # ANY PMIDs/DOIs, so non-empty list is the failure signal.
    raw_list = ", ".join(f"{c.kind}:{c.raw}" for c in cites[:5])
    return (f"refuse to persist {spec.id}: contains "
            f"{len(cites)} unverifiable refs ({raw_list})")


def _persist(spec: CaseSpec, dry_run: bool) -> Optional[Path]:
    err = _verify_no_fabricated_citations(spec)
    if err:
        log.warning("L_VERIFIABILITY blocked: %s", err)
        return None
    target = cases_dir() / f"{spec.id}.yaml"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.to_yaml(), encoding="utf-8")
    return target


def _audit(spec: CaseSpec, target: Path, dry_run: bool) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "case_id": spec.id,
        "source": spec.source,
        "tags": spec.tags,
        "target": str(target),
        "dry_run": dry_run,
    }
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("audit write failed: %s", e)


def synthesise(window_days: int = 7, *,
                dry_run: bool = False,
                pattern_findings: Optional[list] = None,
                reflexions: Optional[list[str]] = None,
                ) -> list[Path]:
    """Run the full pipeline. Returns the list of YAML paths produced.

    `pattern_findings` and `reflexions` may be passed in for testing;
    when None, we fetch from `agents.pattern_miner.mine` and the user's
    feedback memory directory respectively.
    """
    if pattern_findings is None:
        try:
            from agents.pattern_miner import mine
            pattern_findings = mine(window_days=window_days)
        except Exception as e:
            log.debug("pattern miner unavailable: %s", e)
            pattern_findings = []
    if reflexions is None:
        reflexions = _gather_reflexion_texts(window_days=window_days * 4)

    written: list[Path] = []
    seen_ids: set[str] = set()

    for f in pattern_findings or []:
        spec = _from_finding(f)
        if spec is None or spec.id in seen_ids:
            continue
        seen_ids.add(spec.id)
        target = _persist(spec, dry_run)
        if target is None:
            # Blocked by L_VERIFIABILITY — skip silently (logged in _persist).
            continue
        _audit(spec, target, dry_run)
        written.append(target)

    for text in reflexions or []:
        spec = synthesise_from_reflexion(text)
        if spec is None or spec.id in seen_ids:
            continue
        seen_ids.add(spec.id)
        target = _persist(spec, dry_run)
        if target is None:
            continue
        _audit(spec, target, dry_run)
        written.append(target)

    return written


def audit(limit: int = 50) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AI/eval_synthesiser")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = synthesise(window_days=args.window_days, dry_run=args.dry_run)
    print(f"synthesised {len(out)} cases:")
    for p in out:
        print(f"  • {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
