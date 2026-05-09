"""agents/evals.py — Eval harness foundation (S1, 2026-05-02).

The keystone of closed-loop self-improvement: nothing automatic in S2-S7
is allowed to ship without a measured improvement on this harness.

Anatomy:

    EvalCase     — a single task with input + scoring rubric (regex/JSON/
                   keyword/exact). Stored as YAML in tests/evals/cases/.
    score_case   — runs the rubric against an output string, returns float [0,1].
    run_case     — invokes a callable with the case input, scores result,
                   logs latency + cost.
    run_all      — runs every case, returns EvalRun summary.
    DB           — SQLite at $AIM_HOME/eval_runs.db storing every run for
                   week-over-week regression detection.
    compare      — compares two version strings; emits {improved, regressed, neutral}.

The harness deliberately knows nothing about LLMs — it takes a callable
`(prompt: str) -> str`. That means S3 (prompt patches), S5 (router A/B),
S2 (synthesised tools) all plug in by passing different callables.

Scoring rubrics (declarative, in YAML):

    regex:        "must match this pattern"
    contains_all: ["term-1", "term-2"]    # case-insensitive
    contains_any: ["alt-1", "alt-2"]
    forbids:      ["gpt-4", "as an AI"]   # case-insensitive negative match
    exact:        "expected verbatim"
    json_keys:    ["a", "b.c"]            # response must be JSON containing all keys
    min_length:   80
    max_length:   2000

A case can have multiple rubrics; final score = average of per-rubric
scores.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import re
import sqlite3
import textwrap
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("aim.evals")


def cases_dir() -> Path:
    env = os.environ.get("AIM_EVAL_CASES_DIR")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "tests" / "evals" / "cases"


def db_path() -> Path:
    env = os.environ.get("AIM_EVAL_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    return Path(base).expanduser() / "eval_runs.db"


# ── data classes ─────────────────────────────────────────────────


@dataclasses.dataclass
class EvalCase:
    id: str
    task: str
    rubrics: dict
    tags: list[str] = dataclasses.field(default_factory=list)
    weight: float = 1.0


@dataclasses.dataclass
class CaseResult:
    case_id: str
    score: float            # [0, 1]
    latency_ms: int
    cost_usd: float
    output: str
    rubric_scores: dict     # {rubric_name: score_float}
    error: Optional[str] = None


@dataclasses.dataclass
class EvalRun:
    version: str
    run_at: str
    cases: list[CaseResult]

    @property
    def aggregate_score(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.score for c in self.cases) / len(self.cases)


# ── case loading ─────────────────────────────────────────────────


def load_cases() -> list[EvalCase]:
    """Read every YAML in cases_dir() and return EvalCase list."""
    import yaml
    out: list[EvalCase] = []
    d = cases_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            log.warning("skip %s: %s", p, e)
            continue
        if not isinstance(raw, dict):
            log.warning("skip %s: not a mapping", p)
            continue
        out.append(EvalCase(
            id=str(raw.get("id") or p.stem),
            task=str(raw.get("task", "")),
            rubrics=dict(raw.get("rubrics") or {}),
            tags=list(raw.get("tags") or []),
            weight=float(raw.get("weight", 1.0)),
        ))
    return out


# ── scoring rubrics ──────────────────────────────────────────────


def _score_regex(output: str, pattern: str) -> float:
    return 1.0 if re.search(pattern, output) else 0.0


def _score_contains_all(output: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lo = output.lower()
    hits = sum(1 for t in terms if str(t).lower() in lo)
    return hits / len(terms)


def _score_contains_any(output: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lo = output.lower()
    return 1.0 if any(str(t).lower() in lo for t in terms) else 0.0


def _score_forbids(output: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lo = output.lower()
    return 0.0 if any(str(t).lower() in lo for t in terms) else 1.0


def _score_exact(output: str, expected: str) -> float:
    return 1.0 if output.strip() == expected.strip() else 0.0


def _score_json_keys(output: str, keys: list[str]) -> float:
    try:
        obj = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return 0.0
    hits = 0
    for k in keys:
        cur: Any = obj
        for part in str(k).split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur is not None:
            hits += 1
    return hits / max(len(keys), 1)


def _score_min_length(output: str, n: int) -> float:
    return 1.0 if len(output) >= int(n) else 0.0


def _score_max_length(output: str, n: int) -> float:
    return 1.0 if len(output) <= int(n) else 0.0


_RUBRIC_FNS: dict[str, Callable[[str, Any], float]] = {
    "regex": _score_regex,
    "contains_all": _score_contains_all,
    "contains_any": _score_contains_any,
    "forbids": _score_forbids,
    "exact": _score_exact,
    "json_keys": _score_json_keys,
    "min_length": _score_min_length,
    "max_length": _score_max_length,
}


def score_case(output: str, rubrics: dict) -> tuple[float, dict]:
    """Score a single output. Returns (overall, per-rubric scores dict)."""
    if not rubrics:
        return 1.0, {}
    per: dict = {}
    for name, val in rubrics.items():
        fn = _RUBRIC_FNS.get(name)
        if fn is None:
            log.warning("unknown rubric %r — ignored", name)
            continue
        per[name] = fn(output, val)
    if not per:
        return 1.0, per
    return sum(per.values()) / len(per), per


# ── DB ───────────────────────────────────────────────────────────


_DB_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            run_at TEXT NOT NULL,
            case_id TEXT NOT NULL,
            score REAL NOT NULL,
            latency_ms INTEGER NOT NULL,
            cost_usd REAL NOT NULL DEFAULT 0,
            error TEXT,
            rubric_scores TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_version "
                 "ON eval_runs(version, run_at)")
    return conn


def persist(run: EvalRun) -> None:
    with _DB_LOCK, _connect() as conn:
        for c in run.cases:
            conn.execute("""
                INSERT INTO eval_runs(version, run_at, case_id, score,
                                      latency_ms, cost_usd, error, rubric_scores)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (run.version, run.run_at, c.case_id, c.score,
                  c.latency_ms, c.cost_usd, c.error,
                  json.dumps(c.rubric_scores, ensure_ascii=False)))


def latest_score(version: str) -> Optional[float]:
    with _DB_LOCK, _connect() as conn:
        r = conn.execute("""
            SELECT AVG(score) AS s
            FROM eval_runs
            WHERE version=? AND run_at=(
                SELECT MAX(run_at) FROM eval_runs WHERE version=?
            )
        """, (version, version)).fetchone()
    return r["s"] if r and r["s"] is not None else None


def compare(version_a: str, version_b: str) -> dict:
    """Aggregate score delta between two versions' latest runs.

    Returns {a, b, delta, verdict} where verdict ∈ {improved, regressed, neutral}.
    """
    a = latest_score(version_a) or 0.0
    b = latest_score(version_b) or 0.0
    delta = b - a
    verdict = ("improved" if delta > 0.01 else
               "regressed" if delta < -0.01 else "neutral")
    return {"a": a, "b": b, "delta": delta, "verdict": verdict}


# ── runner ───────────────────────────────────────────────────────


def run_case(case: EvalCase, fn: Callable[[str], str],
             *, cost_per_call: float = 0.0) -> CaseResult:
    """Run `fn(case.task)` and score the output."""
    t0 = time.time()
    try:
        out = fn(case.task)
        err = None
    except Exception as e:
        out = ""
        err = f"{type(e).__name__}: {e}"
    latency_ms = int((time.time() - t0) * 1000)
    score, per = score_case(out or "", case.rubrics) if err is None else (0.0, {})
    return CaseResult(
        case_id=case.id, score=score, latency_ms=latency_ms,
        cost_usd=cost_per_call, output=(out or "")[:4000],
        rubric_scores=per, error=err,
    )


def run_all(fn: Callable[[str], str], *, version: str,
            cost_per_call: float = 0.0,
            persist_results: bool = True,
            tag_filter: Optional[str] = None) -> EvalRun:
    """Run every case (optionally filtered by tag) and persist."""
    cases = load_cases()
    if tag_filter:
        cases = [c for c in cases if tag_filter in c.tags]
    results = [run_case(c, fn, cost_per_call=cost_per_call) for c in cases]
    run = EvalRun(
        version=version,
        run_at=dt.datetime.now().replace(microsecond=0).isoformat(),
        cases=results,
    )
    if persist_results:
        persist(run)
    return run


# ── builtin sample cases (so tests don't need the YAML directory) ──


_BUILTIN_CASES_YAML = textwrap.dedent("""\
    # Built-in starter cases for the AIM eval harness. Add real ones as
    # tests/evals/cases/<id>.yaml — they will be picked up automatically.
    id: smoke-greeting
    task: "Say hello in one short sentence."
    tags: [smoke, sanity]
    rubrics:
      contains_any: ["hello", "привет", "hi", "hey"]
      max_length: 200
""")


def _ensure_cases_dir() -> None:
    d = cases_dir()
    if d.exists() and any(d.glob("*.yaml")):
        return
    d.mkdir(parents=True, exist_ok=True)
    (d / "smoke-greeting.yaml").write_text(_BUILTIN_CASES_YAML, encoding="utf-8")


_ensure_cases_dir()


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AIM eval harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list available cases")
    g = sub.add_parser("run", help="run all cases via llm.ask")
    g.add_argument("--version", required=True)
    g.add_argument("--tag", default=None)
    g = sub.add_parser("compare", help="compare two versions")
    g.add_argument("a")
    g.add_argument("b")
    args = ap.parse_args()
    if args.cmd == "list":
        for c in load_cases():
            print(f"{c.id:30s}  tags={c.tags}  weight={c.weight}")
    elif args.cmd == "run":
        from llm import ask
        run = run_all(ask, version=args.version, tag_filter=args.tag)
        print(json.dumps({
            "version": run.version,
            "run_at": run.run_at,
            "score": run.aggregate_score,
            "n": len(run.cases),
        }, indent=2))
    elif args.cmd == "compare":
        print(json.dumps(compare(args.a, args.b), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
