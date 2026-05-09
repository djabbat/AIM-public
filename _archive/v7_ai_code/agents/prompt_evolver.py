"""agents/prompt_evolver.py — eval-gated prompt self-improvement (S3, 2026-05-02).

Closes the loop reflexion → mutate → measure → ship that the existing
modules build the pieces for:

    agents/reflexion.py        — captures verbal "what went wrong" notes
    agents/prompt_optimizer.py — LLM-mediated mutation of base prompts
    agents/evals.py            — measures aggregate score
    agents/ab_router.py        — decides if challenger > baseline

The evolver:

  1. Reads the current baseline prompt from `~/.aim/prompts/<key>/v<n>.md`
     (highest n wins). Falls back to a sentinel "v0" if no patch exists.
  2. Aggregates the most recent reflexion notes for that prompt key — if
     fewer than `min_reflections` accumulated, refuses to evolve (we
     don't mutate based on noise).
  3. Asks `prompt_optimizer.mutate` for K candidate revisions seeded by
     those reflections.
  4. Calls a user-supplied `runner(prompt) -> (score: float, cost: float)`
     to score baseline + each candidate against the eval harness.
  5. Picks the best candidate. If it beats baseline by ≥ `min_delta` and
     Welch p ≤ `min_p`, persist it as v<n+1> and write a decision row
     into the audit log. Otherwise: keep baseline.

Every committed patch is reversible: rollback with `revert(key)` drops
the highest version.

Public API:
    baseline_path(key) -> Path
    current_version(key) -> int
    load_baseline(key) -> str
    propose(key, runner, repeats=3, k_candidates=4) -> dict
    revert(key) -> Optional[int]
    history(key=None, limit=20) -> list[dict]
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("aim.prompt_evolver")


def prompts_root() -> Path:
    env = os.environ.get("AIM_PROMPTS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".aim" / "prompts"


def history_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "prompt_evolver.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── dataclasses ──────────────────────────────────────────────────


@dataclasses.dataclass
class CandidateResult:
    text: str
    score: float
    cost: float


@dataclasses.dataclass
class ProposalResult:
    key: str
    baseline_version: int
    new_version: Optional[int]
    verdict: str          # promoted | rejected | insufficient_reflections | no_change
    delta: float
    p_value: Optional[float]
    note: str


# ── persistence ──────────────────────────────────────────────────


def baseline_path(key: str, version: Optional[int] = None) -> Path:
    """Return path to a specific version, or to the current baseline."""
    root = prompts_root() / key
    root.mkdir(parents=True, exist_ok=True)
    if version is not None:
        return root / f"v{version}.md"
    cur = current_version(key)
    return root / f"v{cur}.md"


def current_version(key: str) -> int:
    root = prompts_root() / key
    if not root.exists():
        return 0
    nums = []
    for p in root.glob("v*.md"):
        try:
            nums.append(int(p.stem[1:]))
        except ValueError:
            continue
    return max(nums) if nums else 0


def load_baseline(key: str) -> str:
    p = baseline_path(key)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _persist_patch(key: str, text: str) -> int:
    n = current_version(key) + 1
    path = baseline_path(key, n)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return n


def _audit(record: dict) -> None:
    try:
        with history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("evolver audit write failed: %s", e)


def history(key: Optional[str] = None, limit: int = 20) -> list[dict]:
    p = history_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if key and row.get("key") != key:
                continue
            out.append(row)
    return out[-limit:]


def revert(key: str) -> Optional[int]:
    """Drop the latest patch. Returns the version reverted, or None."""
    n = current_version(key)
    if n == 0:
        return None
    p = baseline_path(key, n)
    if p.exists():
        p.unlink()
    _audit({"ts": _now(), "key": key, "verdict": "reverted",
            "from_version": n, "to_version": n - 1})
    return n


# ── reflexion aggregation ────────────────────────────────────────


def _gather_reflections(key: str, n: int = 8) -> list[str]:
    try:
        from agents import reflexion as rfx
    except ImportError:
        return []
    fn = getattr(rfx, "recent_reflections", None)
    if fn is None:
        return []
    try:
        return list(fn(key, n=n)) or []
    except TypeError:
        return list(fn(key)) or []
    except Exception as e:
        log.debug("reflexion gather failed: %s", e)
        return []


def _mutate_candidates(base: str, reflections: list[str],
                        k: int) -> list[str]:
    try:
        from agents import prompt_optimizer as po
    except ImportError:
        return []
    fn = getattr(po, "mutate", None) or getattr(po, "generate_candidates", None)
    if fn is None:
        return []
    try:
        return list(fn(base, reflections=reflections, k=k)) or []
    except TypeError:
        try:
            return list(fn(base, k))[:k]
        except Exception as e:
            log.debug("prompt_optimizer call failed: %s", e)
            return []


# ── statistics ───────────────────────────────────────────────────


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ── main flow ────────────────────────────────────────────────────


def propose(key: str,
            runner: Callable[[str], tuple[float, float]],
            *,
            repeats: int = 3,
            k_candidates: int = 4,
            min_reflections: int = 3,
            min_delta: float = 0.01,
            min_p: float = 0.05,
            mutate_fn: Optional[Callable[[str, list[str], int], list[str]]] = None,
            ) -> ProposalResult:
    """Try to evolve the baseline prompt for `key`.

    `runner(prompt)` is called `repeats` times per candidate (so we have
    a sample for the t-test). It must return (score: float [0,1], cost_usd).

    `mutate_fn(base, reflections, k)` is an optional override; default
    routes through agents.prompt_optimizer.

    Returns a ProposalResult; if verdict == "promoted", the new patch is
    on disk under ~/.aim/prompts/<key>/v<n+1>.md.
    """
    from agents import ab_router as ar
    base = load_baseline(key)
    base_version = current_version(key)
    reflections = _gather_reflections(key, n=8)

    if len(reflections) < min_reflections:
        result = ProposalResult(
            key=key, baseline_version=base_version, new_version=None,
            verdict="insufficient_reflections",
            delta=0.0, p_value=None,
            note=f"have {len(reflections)} reflections, need {min_reflections}",
        )
        _audit({"ts": _now(), **dataclasses.asdict(result)})
        return result

    mutate = mutate_fn or _mutate_candidates
    candidates = mutate(base, reflections, k_candidates)
    if not candidates:
        result = ProposalResult(
            key=key, baseline_version=base_version, new_version=None,
            verdict="no_change", delta=0.0, p_value=None,
            note="no mutation candidates produced",
        )
        _audit({"ts": _now(), **dataclasses.asdict(result)})
        return result

    def _evaluate(prompt: str) -> list[CandidateResult]:
        runs: list[CandidateResult] = []
        for _ in range(max(2, repeats)):
            try:
                score, cost = runner(prompt)
            except Exception as e:
                log.warning("runner failed: %s", e)
                score, cost = 0.0, 0.0
            runs.append(CandidateResult(prompt, float(score), float(cost)))
        return runs

    base_runs = _evaluate(base)
    best: Optional[tuple[str, list[CandidateResult]]] = None
    for cand in candidates:
        if not isinstance(cand, str) or not cand.strip():
            continue
        cand_runs = _evaluate(cand)
        if best is None:
            best = (cand, cand_runs)
            continue
        if (sum(r.score for r in cand_runs) / len(cand_runs)
                > sum(r.score for r in best[1]) / len(best[1])):
            best = (cand, cand_runs)

    if best is None:
        result = ProposalResult(
            key=key, baseline_version=base_version, new_version=None,
            verdict="no_change", delta=0.0, p_value=None,
            note="no evaluable candidate",
        )
        _audit({"ts": _now(), **dataclasses.asdict(result)})
        return result

    cand_text, cand_runs = best
    base_scores = [r.score for r in base_runs]
    cand_scores = [r.score for r in cand_runs]
    delta = (sum(cand_scores) / len(cand_scores)
             - sum(base_scores) / len(base_scores))
    p_value = ar.welch_t_p(base_scores, cand_scores)
    cost_delta = (sum(r.cost for r in cand_runs) / len(cand_runs)
                  - sum(r.cost for r in base_runs) / len(base_runs))

    if delta >= min_delta and p_value is not None and p_value <= min_p:
        new_v = _persist_patch(key, cand_text)
        result = ProposalResult(
            key=key, baseline_version=base_version, new_version=new_v,
            verdict="promoted", delta=delta, p_value=p_value,
            note=f"Δ={delta:.3f} p={p_value:.3f} cost_Δ={cost_delta:.4f}",
        )
    else:
        result = ProposalResult(
            key=key, baseline_version=base_version, new_version=None,
            verdict="rejected", delta=delta, p_value=p_value,
            note=(f"Δ={delta:.3f} p="
                  + (f"{p_value:.3f}" if p_value is not None else "n/a")),
        )
    _audit({"ts": _now(), **dataclasses.asdict(result)})
    return result


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Prompt evolver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("show", help="print current baseline for a key")
    g.add_argument("key")
    g = sub.add_parser("revert", help="drop the latest patch")
    g.add_argument("key")
    g = sub.add_parser("history", help="show audit history")
    g.add_argument("--key", default=None)
    args = ap.parse_args()
    if args.cmd == "show":
        print(load_baseline(args.key) or "(no patch yet)")
    elif args.cmd == "revert":
        v = revert(args.key)
        print(f"reverted v{v}" if v else "(nothing to revert)")
    elif args.cmd == "history":
        for h in history(args.key):
            print(json.dumps(h, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
