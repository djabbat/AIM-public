"""agents/tree_planner.py — Tree-of-Thoughts planner for hard tasks.

Generates `branching` candidate approaches, scores them via DeepSeek-reasoner
as judge, expands the top-2 into concrete steps. Returns a flat plan that
LangGraph's executor can consume.

Used when state['tree_plan'] is True or via direct call:

    from agents.tree_planner import tree_plan
    steps = tree_plan("Спроектируй FCLC migration roadmap до Jan 2027",
                      branching=4, depth=2)
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from llm import ask, ask_deep

log = logging.getLogger("aim.tree_planner")


SYSTEM_PROMPT = (
    "Ты планировщик многошаговых задач. Отвечаешь на русском языке."
    " Без преамбул, без воды."
)


@dataclass
class Thought:
    text:     str
    score:    float = 0.0
    children: list["Thought"] = field(default_factory=list)
    rationale: str = ""


# ── stages ──────────────────────────────────────────────────────────────────


def _generate(task: str, n: int) -> list[str]:
    prompt = (
        f"ЗАДАЧА:\n{task}\n\n"
        f"Сгенерируй {n} принципиально РАЗНЫХ подходов к решению.\n"
        f"Каждый подход = одна строка, ≤140 символов. Без нумерации."
    )
    raw = ask_deep(prompt, system=SYSTEM_PROMPT, lang="ru")
    candidates = [
        line.strip("-•* \t").strip()
        for line in raw.splitlines()
        if line.strip() and len(line.strip()) > 10
    ]
    return candidates[:n]


_SCORE_RE = re.compile(r"(?:идея|approach|вариант)\s*(\d+)\s*[:=]\s*([\d.]+)", re.I)


def _evaluate(task: str, ideas: list[str]) -> list[Thought]:
    listed = "\n".join(f"{i + 1}. {idea}" for i, idea in enumerate(ideas))
    prompt = (
        f"ЗАДАЧА:\n{task}\n\n"
        f"Оцени каждый подход 0–10 по критериям: feasibility, completeness, risk.\n\n"
        f"ПОДХОДЫ:\n{listed}\n\n"
        f"ВЫХОД: одна строка на подход, формат «Идея N: X.X» (число — итог 0–10).\n"
        f"После списка — одна строка обоснования победителя ≤2 предложений."
    )
    raw = ask_deep(prompt, system=SYSTEM_PROMPT, lang="ru")
    scores: dict[int, float] = {}
    for m in _SCORE_RE.finditer(raw):
        try:
            idx = int(m.group(1)) - 1
            scores[idx] = float(m.group(2))
        except ValueError:
            continue
    rationale = "\n".join(line for line in raw.splitlines() if not _SCORE_RE.search(line)).strip()[:400]

    out = []
    for i, idea in enumerate(ideas):
        out.append(Thought(text=idea, score=scores.get(i, 5.0), rationale=rationale))
    return out


def _expand(task: str, thought: Thought, depth: int) -> list[str]:
    if depth <= 0:
        return [thought.text]
    prompt = (
        f"ЗАДАЧА:\n{task}\n\n"
        f"Развивай выбранный подход в КОНКРЕТНЫЕ исполняемые шаги.\n"
        f"ПОДХОД: {thought.text}\n\n"
        f"Дай ≤{max(depth, 1) * 2} шагов, по одному в строку, в повелительном наклонении, "
        f"≤120 символов, без нумерации, без преамбул."
    )
    raw = ask(prompt, system=SYSTEM_PROMPT, lang="ru")
    steps = [
        line.strip("-•* \t").strip()
        for line in raw.splitlines()
        if line.strip() and len(line.strip()) > 5
    ]
    return steps[:max(depth, 1) * 2]


# ── public ──────────────────────────────────────────────────────────────────


def tree_plan(
    task: str,
    branching: int = 4,
    depth: int = 2,
    keep_top: int = 2,
    parallel: bool = True,
) -> dict:
    """Return a flat list of executable steps from the top-`keep_top` ideas.

    parallel=True spawns the expansion of each kept idea concurrently.
    """
    log.info(f"tree-plan: branching={branching} depth={depth} keep={keep_top}")
    ideas = _generate(task, branching)
    if not ideas:
        return {"plan": [task], "thoughts": []}
    scored = _evaluate(task, ideas)
    scored.sort(key=lambda t: -t.score)
    top = scored[:keep_top]

    if parallel:
        with ThreadPoolExecutor(max_workers=keep_top) as pool:
            futures = [pool.submit(_expand, task, t, depth) for t in top]
            for t, fut in zip(top, futures):
                t.children = [Thought(text=s) for s in fut.result()]
    else:
        for t in top:
            t.children = [Thought(text=s) for s in _expand(task, t, depth)]

    plan: list[str] = []
    for t in top:
        plan.extend([c.text for c in t.children])
    plan = list(dict.fromkeys(plan))[:branching * depth]   # dedup, cap

    return {
        "plan": plan,
        "thoughts": [
            {"text": t.text, "score": t.score, "children": [c.text for c in t.children]}
            for t in scored
        ],
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main() -> int:
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("task")
    p.add_argument("--branching", type=int, default=4)
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--keep-top", type=int, default=2)
    p.add_argument("--no-parallel", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    res = tree_plan(args.task, branching=args.branching, depth=args.depth,
                    keep_top=args.keep_top, parallel=not args.no_parallel)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"\n━━━ THOUGHTS (scored) ━━━")
        for t in res["thoughts"]:
            print(f"  [{t['score']:.1f}]  {t['text']}")
        print(f"\n━━━ FLAT PLAN ━━━")
        for i, s in enumerate(res["plan"], 1):
            print(f"  {i}. {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
