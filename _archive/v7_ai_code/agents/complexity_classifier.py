"""agents/complexity_classifier.py — heuristic task-complexity classifier.

Used by graph._planner to auto-decide whether to use Tree-of-Thoughts (#37),
flat planning, or skip planning entirely (single-step direct execution).

Classes:
    direct    — short factual / lookup, len < 80 chars, no reasoning markers
                → executor runs the task as-is, no planner LLM call
    simple    — len < 200, no markers
                → flat planner, 1–2 steps
    medium    — default; flat planner, 3 steps
    complex   — has reasoning markers OR ≥3 entities OR len ≥ 1200
                → tree-plan suggested

Wire-in: graph._suggest_plan_size() calls `suggest_plan_type()`. If the user
explicitly passes `--tree-plan`, that wins.

CLI:
    aim-complexity classify "сравни препарат A и препарат B"
"""

from __future__ import annotations

import argparse
import json
import logging
import re

log = logging.getLogger("aim.complexity")

_REASONING_RE = re.compile(
    r"\b(?:почему|объясни|обоснуй|проанализируй|сравни|оцени|"
    r"why|explain|analy[sz]e|compare|reason|prove|justify|"
    r"докажи|выведи|разложи|обсуди)\b",
    re.IGNORECASE,
)
_LOOKUP_RE = re.compile(
    r"^(?:что|кто|когда|где|сколько|when|who|where|how many|what is|какой|какая|какое)\s",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(
    r"\b(?:[A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}|[A-ZА-Я]{3,}|\d{4})\b"
)


def classify(task: str) -> dict:
    """Return {complexity, reasoning_markers, entity_count, length, suggestion}."""
    task = (task or "").strip()
    n = len(task)
    has_reasoning = bool(_REASONING_RE.search(task))
    is_lookup     = bool(_LOOKUP_RE.match(task))
    entities      = _ENTITY_RE.findall(task)
    n_entities    = len({e for e in entities if e.lower() not in
                         ("the", "this", "that", "что", "это", "todo")})

    if has_reasoning or n_entities >= 3 or n >= 1200:
        complexity = "complex"
    elif is_lookup or n < 80:
        complexity = "direct"
    elif n < 200:
        complexity = "simple"
    else:
        complexity = "medium"

    suggestion = {
        "direct":  {"plan_type": "direct",     "plan_size": 1,  "tree_plan": False},
        "simple":  {"plan_type": "flat",       "plan_size": 2,  "tree_plan": False},
        "medium":  {"plan_type": "flat",       "plan_size": 3,  "tree_plan": False},
        "complex": {"plan_type": "tree-plan",  "plan_size": 4,  "tree_plan": True},
    }[complexity]

    return {
        "complexity":         complexity,
        "reasoning_markers":  has_reasoning,
        "lookup_pattern":     is_lookup,
        "entity_count":       n_entities,
        "length":             n,
        **suggestion,
    }


def suggest_plan_type(task: str) -> str:
    """Convenience: just return 'direct' | 'flat' | 'tree-plan'."""
    return classify(task)["plan_type"]


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-complexity")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify")
    c.add_argument("task")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "classify":
        print(json.dumps(classify(args.task), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
