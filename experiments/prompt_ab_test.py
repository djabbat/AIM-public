"""experiments/prompt_ab_test.py — A/B test two system prompts on a task set.

Each iteration runs the AIM graph (or a single ask) with prompt A and prompt B
in randomised order, then scores the outputs via DeepSeek-reasoner as judge.
Result is appended to ~/.claude/aim_experiments/<test_name>.jsonl

Run:
    python -m experiments.prompt_ab_test \
        --name planner_v2 \
        --task "проведи peer review статьи X" \
        --prompt-a path/to/system_a.txt \
        --prompt-b path/to/system_b.txt \
        --iterations 10
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from llm import ask, ask_deep

log = logging.getLogger("aim.ab")

OUT_DIR = Path.home() / ".claude" / "aim_experiments"


@dataclass
class TrialResult:
    iteration: int
    variant: str        # "A" or "B"
    prompt_first: str   # which variant ran first this iteration
    response: str
    score: float
    judge_reason: str
    latency_s: float


def _score(task: str, response: str) -> tuple[float, str]:
    """Use DeepSeek-reasoner as judge. Score 0–10."""
    judge_prompt = (
        f"ОЦЕНИ ОТВЕТ НА ЗАДАЧУ.\n\n"
        f"ЗАДАЧА:\n{task}\n\n"
        f"ОТВЕТ:\n{response}\n\n"
        f"━━━ КРИТЕРИИ ━━━\n"
        f"1. Прямота (отвечает ли строго на задачу).\n"
        f"2. Точность (нет фабрикации, нет противоречий).\n"
        f"3. Конкретность (числа, имена, сроки — где уместно).\n"
        f"4. Краткость (нет воды).\n\n"
        f"━━━ ВЫХОД ━━━\n"
        f"Первая строка: ровно одно число от 0.0 до 10.0.\n"
        f"Вторая строка и далее — обоснование (≤2 предложений)."
    )
    raw = ask_deep(judge_prompt, system="Ты беспристрастный судья. Отвечай по-русски.", lang="ru")
    lines = raw.strip().splitlines()
    score = 5.0
    if lines:
        try:
            score = float(lines[0].strip().replace(",", "."))
        except ValueError:
            pass
    reason = "\n".join(lines[1:])[:300]
    return max(0.0, min(10.0, score)), reason


def _run_once(task: str, system_prompt: str) -> tuple[str, float]:
    t0 = time.time()
    response = ask(task, system=system_prompt)
    return response, time.time() - t0


def run_ab_test(
    name: str,
    task: str,
    prompt_a: str,
    prompt_b: str,
    iterations: int = 10,
) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f"{name}.jsonl"

    trials: list[TrialResult] = []
    for i in range(1, iterations + 1):
        first = "A" if random.random() > 0.5 else "B"
        order = ("A", "B") if first == "A" else ("B", "A")
        for variant in order:
            sp = prompt_a if variant == "A" else prompt_b
            response, latency = _run_once(task, sp)
            score, reason = _score(task, response)
            tr = TrialResult(i, variant, first, response, score, reason, latency)
            trials.append(tr)
            with out_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(tr), ensure_ascii=False) + "\n")
            log.info(f"iter {i} {variant}: score={score:.1f} latency={latency:.1f}s")

    by_variant = {"A": [], "B": []}
    lat_variant = {"A": [], "B": []}
    for t in trials:
        by_variant[t.variant].append(t.score)
        lat_variant[t.variant].append(t.latency_s)

    summary = {
        "name": name,
        "iterations": iterations,
        "task": task,
        "score_a_mean":   statistics.mean(by_variant["A"]),
        "score_a_stdev":  statistics.pstdev(by_variant["A"]) if len(by_variant["A"]) > 1 else 0.0,
        "score_b_mean":   statistics.mean(by_variant["B"]),
        "score_b_stdev":  statistics.pstdev(by_variant["B"]) if len(by_variant["B"]) > 1 else 0.0,
        "latency_a_mean": statistics.mean(lat_variant["A"]),
        "latency_b_mean": statistics.mean(lat_variant["B"]),
        "winner":         "A" if statistics.mean(by_variant["A"]) > statistics.mean(by_variant["B"]) else "B",
        "samples_each":   iterations,
        "out_file":       str(out_file),
    }
    (OUT_DIR / f"{name}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def _main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--prompt-a", required=True, help="path to system prompt A")
    p.add_argument("--prompt-b", required=True, help="path to system prompt B")
    p.add_argument("--iterations", type=int, default=10)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    sp_a = Path(args.prompt_a).read_text(encoding="utf-8")
    sp_b = Path(args.prompt_b).read_text(encoding="utf-8")

    summary = run_ab_test(args.name, args.task, sp_a, sp_b, iterations=args.iterations)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
