"""agents/prompt_optimizer.py — evolutionary prompt optimisation.

Treats prompt-engineering as black-box evolutionary search:
    1. Generate K candidate variants from a base prompt (LLM mutation)
    2. Score each on an `evaluator(prompt) -> float`
    3. Keep top-N, mutate further; iterate `generations` times

This is NOT the embedding-gradient approach (which can't be back-projected
reliably without a separate decoder). LLM-mediated mutation is robust and
language-agnostic.

CLI:
    python -m agents.prompt_optimizer optimize \\
        --base "Ты помощник врача..."  \\
        --task "Поставь предварительный диагноз: одышка, кашель"  \\
        --generations 4 --population 6
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from llm import ask, ask_deep

log = logging.getLogger("aim.prompt_optimizer")

JUDGE_SYSTEM = (
    "Ты беспристрастный судья оценки качества системного промпта по тому, "
    "насколько хорошо ответ агента покрывает задачу. Отвечай на русском."
)
MUTATE_SYSTEM = (
    "Ты редактор промптов. Производишь точечные мутации: меняешь формулировки, "
    "добавляешь конкретику, удаляешь воду. Сохраняешь общий смысл и формат. "
    "Возвращаешь ТОЛЬКО новый промпт без преамбулы."
)


@dataclass
class Candidate:
    prompt: str
    score:  float = 0.0
    rationale: str = ""


# ── core ───────────────────────────────────────────────────────────────────


def _mutate(base: str, mutation_kind: str = "tighten") -> str:
    instr = {
        "tighten":   "Сократи повторы и водные конструкции, сохрани все инструкции.",
        "explicate": "Сделай неявные ограничения явными (формат, длина, тон).",
        "soften":    "Сделай тон более вежливым, но не теряй точность инструкций.",
        "constrain": "Добавь жёсткие констрейнты на формат вывода (макс. длина, структура).",
        "examplify": "Добавь 1 короткий пример хорошего ответа в конце.",
    }.get(mutation_kind, "Перепиши промпт по-своему, сохраняя смысл.")
    user = f"━━━ ИСХОДНЫЙ ПРОМПТ ━━━\n{base}\n\n━━━ ИНСТРУКЦИЯ ━━━\n{instr}"
    return ask(user, system=MUTATE_SYSTEM, temperature=0.7)


def default_evaluator(prompt: str, task: str) -> Candidate:
    """Default judge: run the prompt-as-system on `task`, then score the answer 0–10."""
    answer = ask(task, system=prompt, temperature=0.0)
    judge_user = (
        f"━━━ ЗАДАЧА ━━━\n{task}\n\n"
        f"━━━ ОТВЕТ ━━━\n{answer}\n\n"
        f"━━━ КРИТЕРИИ ━━━\n"
        f"1. Прямота (отвечает ли строго на задачу).\n"
        f"2. Точность.\n"
        f"3. Конкретность.\n"
        f"4. Краткость.\n\n"
        f"Первая строка — число 0–10. Далее — обоснование (≤2 предложения)."
    )
    raw = ask_deep(judge_user, system=JUDGE_SYSTEM)
    lines = raw.strip().splitlines()
    score = 5.0
    if lines:
        try:
            score = float(lines[0].strip().replace(",", "."))
        except ValueError:
            pass
    rationale = "\n".join(lines[1:])[:300]
    return Candidate(prompt=prompt, score=max(0.0, min(10.0, score)), rationale=rationale)


def optimize(
    base_prompt: str,
    task: str,
    population: int = 6,
    generations: int = 3,
    keep_top: int = 2,
    mutation_kinds: tuple = ("tighten", "explicate", "constrain", "examplify", "soften"),
    evaluator: Optional[Callable[[str, str], Candidate]] = None,
) -> dict:
    """Run evolutionary search and return the winner + history."""
    evaluator = evaluator or default_evaluator
    log.info(f"optimize: pop={population} gen={generations} keep={keep_top}")

    pool: list[Candidate] = []
    pool.append(evaluator(base_prompt, task))
    for _ in range(population - 1):
        kind = random.choice(mutation_kinds)
        try:
            mutated = _mutate(base_prompt, kind)
        except Exception as e:
            log.warning(f"mutation failed: {e}")
            continue
        pool.append(evaluator(mutated, task))

    history = [{
        "generation": 0,
        "best": max(c.score for c in pool),
        "mean": statistics.mean(c.score for c in pool),
    }]

    for gen in range(1, generations + 1):
        pool.sort(key=lambda c: -c.score)
        survivors = pool[:keep_top]
        children: list[Candidate] = []
        while len(children) < population - keep_top:
            parent = random.choice(survivors)
            kind = random.choice(mutation_kinds)
            try:
                cp = _mutate(parent.prompt, kind)
            except Exception:
                continue
            children.append(evaluator(cp, task))
        pool = survivors + children
        history.append({
            "generation": gen,
            "best": max(c.score for c in pool),
            "mean": statistics.mean(c.score for c in pool),
        })
        log.info(f"gen {gen}: best={history[-1]['best']:.2f} mean={history[-1]['mean']:.2f}")

    pool.sort(key=lambda c: -c.score)
    winner = pool[0]
    return {
        "winner":    asdict(winner),
        "all":       [asdict(c) for c in pool],
        "history":   history,
        "base":      base_prompt,
        "task":      task,
    }


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-prompt-optimize")
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("optimize")
    o.add_argument("--base", required=True, help="path to file OR inline prompt text")
    o.add_argument("--task", required=True)
    o.add_argument("--population", type=int, default=6)
    o.add_argument("--generations", type=int, default=3)
    o.add_argument("--keep-top", type=int, default=2)
    o.add_argument("--out", default=None, help="write winner.txt + summary.json here")

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "optimize":
        from pathlib import Path
        base = Path(args.base).read_text(encoding="utf-8") if Path(args.base).exists() else args.base
        result = optimize(base, args.task,
                          population=args.population,
                          generations=args.generations,
                          keep_top=args.keep_top)
        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "winner.txt").write_text(result["winner"]["prompt"], encoding="utf-8")
            (out / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"saved → {out}")
        else:
            print(json.dumps({"winner_score": result["winner"]["score"],
                              "winner_prompt": result["winner"]["prompt"][:400] + "...",
                              "history": result["history"]},
                             ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
