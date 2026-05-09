"""agents/debate.py — multi-agent debate for high-stakes decisions.

Three personas argue, then a synthesiser picks the strongest synthesis.
Used when state['debate'] is True or via direct call:

    from agents.debate import debate
    answer = debate("Стоит ли публиковать в DOAJ сейчас или ждать?")
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from llm import ask, ask_deep

log = logging.getLogger("aim.debate")


PERSONAS = {
    "Оптимист":  "Ты ищешь возможности и плюсы. Аргументируй за «да», но честно (не рекламируй).",
    "Пессимист": "Ты ищешь риски и слабости. Аргументируй за «нет» / «осторожно», но честно (не запугивай).",
    "Реалист":   "Ты взвешиваешь факты, числа, временные ограничения. Делай ставку на вероятности.",
}


def _opinion(name: str, role: str, question: str, prior: dict[str, str]) -> tuple[str, str]:
    prior_block = "\n".join(f"  {k}: {v}" for k, v in prior.items() if k != name) or "  (это первый раунд)"
    prompt = (
        f"ВОПРОС:\n{question}\n\n"
        f"━━━ ИНСТРУКЦИЯ ━━━\n"
        f"Твоя роль: {role}\n"
        f"Высказывания других участников:\n{prior_block}\n\n"
        f"Дай свой ответ за 2–4 предложения. Кратко. Без преамбул. Без воды."
    )
    return name, ask(prompt, system="Ты участник дебатов. Отвечай по существу, на русском.", lang="ru")


def debate(question: str, rounds: int = 2, parallel: bool = True) -> dict:
    """Return {opinions, synthesis, votes} after `rounds` rounds.

    parallel=True runs the three personas concurrently per round (3× faster).
    """
    opinions: dict[str, str] = {name: "" for name in PERSONAS}
    history: list[dict[str, str]] = []

    for r in range(rounds):
        log.info(f"[debate] round {r+1}/{rounds}")
        if parallel:
            with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
                futures = [
                    pool.submit(_opinion, name, role, question, dict(opinions))
                    for name, role in PERSONAS.items()
                ]
                for fut in futures:
                    name, text = fut.result()
                    opinions[name] = text
        else:
            for name, role in PERSONAS.items():
                _, text = _opinion(name, role, question, dict(opinions))
                opinions[name] = text
        history.append(dict(opinions))

    # Synthesis with the reasoner
    synth_prompt = (
        f"ВОПРОС:\n{question}\n\n"
        f"━━━ МНЕНИЯ ━━━\n"
        + "\n".join(f"{n}: {t}" for n, t in opinions.items())
        + "\n\n━━━ ИНСТРУКЦИЯ (СИНТЕЗ) ━━━\n"
          "Учти все три позиции. Найди реальную точку согласия (если есть) и реальные расхождения. "
          "Дай взвешенное решение в 4–7 предложений: рекомендация + 1 ключевой аргумент + 1 ключевой риск."
    )
    synthesis = ask_deep(synth_prompt, system="Ты модератор дебатов. Отвечай на русском.", lang="ru")

    return {
        "question": question,
        "rounds": rounds,
        "opinions": opinions,
        "history": history,
        "synthesis": synthesis,
    }


def _main():
    import argparse, json, logging as _log, sys
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--no-parallel", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    _log.basicConfig(level=_log.INFO, format="[%(name)s] %(message)s")
    res = debate(args.question, rounds=args.rounds, parallel=not args.no_parallel)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for name, text in res["opinions"].items():
            print(f"\n━━━ {name} ━━━\n{text}")
        print(f"\n━━━ СИНТЕЗ ━━━\n{res['synthesis']}")


if __name__ == "__main__":
    _main()
