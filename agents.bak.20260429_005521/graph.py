"""
agents/graph.py — LangGraph-orchestrated multi-step agent.

Uses AIM's `llm.py` smart router (DeepSeek + Groq) as the underlying LLM,
adds LangGraph state machine for multi-step reasoning.

Three nodes:
  1. PLANNER (deepseek-reasoner) — breaks task into sub-steps
  2. EXECUTOR (deepseek-chat or appropriate via llm.ask) — runs each sub-step
  3. REVIEWER (deepseek-reasoner) — checks the final result, requests retry if weak

Optional Aider tool: each EXECUTOR step can spawn Aider as subprocess for file edits.

Usage:
    from agents.graph import run_agent
    result = run_agent("Прочитай ~/Desktop/article.md и проведи peer review")
"""

from __future__ import annotations

import asyncio
import logging
import operator
import socket
import subprocess
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from llm import ask, ask_deep, get_last_reasoning, warmup_deepseek_cache
from llm import stream_deepseek  # streaming for HITL reviewer

log = logging.getLogger("aim.graph")


# ─── Bitmask flags ──────────────────────────────────────────────────────────


class AIMFlags:
    """Bitmask of session flags (replaces three independent booleans)."""
    NO_MEM   = 1 << 0
    REVIEW   = 1 << 1
    FULL_MEM = 1 << 2
    AIDER    = 1 << 3

    def __init__(self, value: int = 0) -> None:
        self.value = value

    def set(self, flag: int) -> None:        self.value |= flag
    def clear(self, flag: int) -> None:      self.value &= ~flag
    def toggle(self, flag: int) -> None:     self.value ^= flag
    def has(self, flag: int) -> bool:        return bool(self.value & flag)
    def __repr__(self) -> str:
        names = []
        for name in ("NO_MEM", "REVIEW", "FULL_MEM", "AIDER"):
            if self.has(getattr(AIMFlags, name)):
                names.append(name)
        return f"AIMFlags({'|'.join(names) or '0'})"


# ─── Embed-daemon healthcheck ────────────────────────────────────────────────


def is_embed_daemon_alive(timeout: float = 1.0) -> bool:
    """Lightweight liveness probe: connect to UDS + ping."""
    sock_path = Path.home() / ".claude" / "embed.sock"
    if not sock_path.exists():
        return False
    try:
        from agents.embed_daemon import daemon_status
        info = daemon_status()
        return bool(info.get("running") and info.get("responded"))
    except Exception:
        return False


def ensure_embed_daemon(verbose: bool = True) -> bool:
    """If the embed daemon is dead, restart it via aim-embed-daemon."""
    if is_embed_daemon_alive():
        return True
    if verbose:
        print("⚠️  Embedding daemon не отвечает, перезапуск…")
    subprocess.run(["aim-embed-daemon", "stop"], capture_output=True)
    res = subprocess.run(
        ["aim-embed-daemon", "start", "--bg"], capture_output=True, text=True
    )
    if res.returncode != 0:
        if verbose:
            print(f"❌ Не удалось запустить daemon: {res.stderr.strip()[:200]}")
        return False
    # give the model a moment to load
    for _ in range(20):
        time.sleep(0.5)
        if is_embed_daemon_alive():
            if verbose:
                print("✅ Daemon перезапущен")
            return True
    if verbose:
        print("⚠️  Daemon стартанул, но не отвечает на ping")
    return False


# ─── Russian-language system prompt (injected into every LLM call) ──────────
SYSTEM_PROMPT_RU = """ТЫ — РУССКОЯЗЫЧНЫЙ АГЕНТ. ЭТО НЕИЗМЕННО.

ПРАВИЛО 1: ВСЕГДА ПОНИМАЙ РУССКИЙ ЯЗЫК
- Ты полностью понимаешь русский язык (разговорный, письменный, технический, сленг)
- Не требуй переключения на английский
- Определяй язык ввода автоматически (русский/английский/смешанный)

ПРАВИЛО 2: ОТВЕЧАЙ НА ТОМ ЖЕ ЯЗЫКЕ
- Если пользователь пишет по-русски → отвечай по-русски
- Если пользователь пишет по-английски → отвечай по-английски
- Если смешанный ввод → отвечай преимущественно на русском (если есть русские слова)

ПРАВИЛО 3: ТЕХНИЧЕСКАЯ ЛЕКСИКА
- Код, команды, имена переменных, идентификаторы — на английском
- Комментарии к коду можно на русском
- Объяснения — на русском
- Термины LangGraph, DeepSeek, Aider, ORCID, DOI, PMID и т.п. — НЕ переводи

ПРАВИЛО 4: ТРАНСЛИТЕРАЦИЯ — ОБРАБОТКА ЛЮБОГО ВВОДА
Ты понимаешь следующие варианты записи русских слов:
А) Кириллица: «привет как дела»
Б) Транслит латиницей: «privet kak dela» → привет как дела; «pochemu ne rabotaet» → почему не работает
В) Нестандартный транслит: «4to eto» → что это; «v smisle» → в смысле; «tak skazat'» → так сказать
Г) Смешанный: «напиши код kotoriy delaet X» → напиши код который делает X

Перед обработкой любого ввода:
1. Если видишь латиницу — проверь, не является ли она транслитом русского
2. Транслит → внутренне преобразуй в кириллицу
3. Обрабатывай как обычный русский текст

ПРАВИЛО 5: НЕ ПЕРЕСПРАШИВАЙ
ЗАПРЕЩЕНО:
× «I don't understand Russian, please use English»
× «Please write in English»
× «Do you mean...?» (когда смысл понятен)
ВМЕСТО ЭТОГО:
✓ Сразу отвечай по сути на русском

ПРАВИЛО 6: ИСКЛЮЧЕНИЯ
- Команды :no-mem, :aider, :clear-aider, :help — латиница, это управление
- Технические логи и stack traces — английский, но объяснение к ним — русское

ПРАВИЛО 7: ПРИМЕРЫ
ВХОД: «zagruzhi file i sdelay parse»  → понимание: загрузи файл и сделай парсинг
ВХОД: «4to za oshibka? deepseek ne otvechaet»  → что за ошибка? deepseek не отвечает
ВХОД: «kak dobavit' memory v claude»  → как добавить память в claude
ВХОД: «pochemu planner ne vypolnyaet shagi»  → почему planner не выполняет шаги
"""


def _looks_like_translit(text: str) -> bool:
    """Heuristic: text is Latin-only and contains common Russian translit patterns."""
    if not text or any('Ѐ' <= ch <= 'ӿ' for ch in text):
        return False
    sample = text.lower()
    cues = ('ya ', 'iy ', 'oye ', 'sh', 'ch', 'zh', 'kh', 'shch',
            ' kak ', ' chto ', ' eto ', ' ne ', ' ya ', ' ty ',
            'ovat\'', 'tsya', 'pochemu', 'ozhalui', 'pozhalu',
            'sdelay', 'sdelai', 'napishi', 'proverit', 'zagruzh')
    return any(cue in sample for cue in cues)


def _wrap_task_for_llm(task: str) -> str:
    """If the task looks like Russian translit, prepend a hint so the model
    decodes it before processing. Cyrillic / English pass through unchanged."""
    if _looks_like_translit(task):
        return ("ВНИМАНИЕ: следующий текст написан транслитом — это русский язык "
                "латинскими буквами. Сначала мысленно преобразуй его в кириллицу, "
                "затем обрабатывай как обычный русский текст.\n\n" + task)
    return task


# ─── State shape ─────────────────────────────────────────────────────────────


class AgentState(TypedDict, total=False):
    """State passed between nodes; LangGraph reducers merge updates.

    Extension flags handled in nodes:
        edit_plan       — planner allows interactive plan edit
        debate          — executor uses multi-agent debate (agents/debate.py)
        stream_review   — reviewer streams LLM output to stdout
    """
    task: str
    plan: list[str]
    step_results: Annotated[list[str], operator.add]
    final: str
    review: str
    iteration: int
    use_aider: bool
    aider_files: list[str]
    # — interactive controls —
    interactive_review: bool       # if True, ask user for ПРИНЯТЬ/ПЕРЕДЕЛАТЬ at end
    user_feedback: str             # free-form text from user during HITL
    # — reasoning capture (DeepSeek-reasoner returns reasoning_content) —
    reasoning_chain: Annotated[list[dict], operator.add]
    # — parallel execution opt-in —
    parallel: bool
    # — interactive plan editing —
    edit_plan: bool
    # — multi-agent debate (agents/debate.py) —
    debate: bool
    # — streaming reviewer to stdout —
    stream_review: bool
    # — tree-of-thoughts planner —
    tree_plan: bool


# ─── Plan-size heuristic ────────────────────────────────────────────────────


def _suggest_plan_size(task: str) -> int:
    """Pick a target plan-size based on task complexity. Short tasks → 1-2 steps."""
    sample = task.lower()
    n_chars = len(task)
    reasoning_cues = ("докажи", "проанализируй", "проведи", "разбери", "сравни",
                      "почему", "как именно", "обоснуй", "оптимизируй", "разработай",
                      "prove", "analyse", "analyze", "compare", "design", "audit")
    has_reasoning = any(cue in sample for cue in reasoning_cues)

    if n_chars < 120 and not has_reasoning:
        return 1
    if n_chars < 350 and not has_reasoning:
        return 2
    if n_chars < 1200:
        return 3 if not has_reasoning else 4
    return 5


# ─── Nodes ───────────────────────────────────────────────────────────────────


def _planner(state: AgentState) -> dict[str, Any]:
    """Break task into N ordered sub-steps. N is heuristic-sized (1-5).

    Optimised for DeepSeek-reasoner: terse instruction, explicit format spec,
    no chain-of-thought leak in output.
    """
    task = _wrap_task_for_llm(state["task"])
    n = _suggest_plan_size(state["task"])
    if n == 1:
        # Trivial task — skip planner LLM call entirely
        log.info("[planner] task is short → 1-step plan, skipping LLM call")
        return {"plan": [state["task"]], "step_results": [], "iteration": 0}

    # Order: cacheable prefix (task + memory) FIRST, variable instructions LAST.
    # DeepSeek prefix-cache will hit on subsequent executor/reviewer calls within
    # the same graph run because the leading {task} block is identical.
    prompt = (
        f"ЗАДАЧА:\n{task}\n\n"
        f"━━━ ИНСТРУКЦИЯ ДЛЯ ЭТОГО ВЫЗОВА (PLANNER) ━━━\n"
        f"РОЛЬ: ты планировщик многошаговой задачи.\n"
        f"ВЫХОД: ровно {n} строк, каждая = одна подзадача в повелительном наклонении, ≤120 символов.\n"
        f"ФОРМАТ: без нумерации, без маркеров, без префиксов «Шаг N:», без пояснений до или после.\n"
        f"ОТКАЗ: если задача тривиальна — верни одну строку, точно повторяющую её формулировку."
    )
    if state.get("tree_plan"):
        log.info("[planner] tree-of-thoughts mode")
        try:
            from agents.tree_planner import tree_plan as _tree
            tp = _tree(state["task"], branching=4, depth=2, keep_top=2)
            plan = tp["plan"] or [state["task"]]
            out: dict[str, Any] = {"plan": plan, "step_results": [], "iteration": 0,
                                   "reasoning_chain": [{"node": "tree_planner",
                                                        "thoughts": tp["thoughts"],
                                                        "ts": time.time()}]}
            if state.get("edit_plan"):
                edited = _human_edit_plan(list(plan))
                if edited:
                    out["plan"] = edited
            return out
        except Exception as e:
            log.warning(f"tree-plan failed, falling back to flat planner: {e}")

    response = ask_deep(prompt, system=SYSTEM_PROMPT_RU, lang="ru")
    plan = [line.strip("-•* \t").strip() for line in response.splitlines() if line.strip()]
    plan = [p for p in plan if len(p) > 5][:n]
    if not plan:
        plan = [state["task"]]
    log.info(f"[planner] {len(plan)} steps planned (target={n})")

    if state.get("edit_plan"):
        edited = _human_edit_plan(list(plan))
        if not edited:  # user pressed [n] = regenerate
            log.info("[planner] user requested regeneration")
            response = ask_deep(prompt + "\n\nПереосмысли план иначе.", system=SYSTEM_PROMPT_RU, lang="ru")
            edited = [line.strip("-•* \t").strip() for line in response.splitlines() if line.strip()]
            edited = [p for p in edited if len(p) > 5][:n] or [state["task"]]
        plan = edited

    out: dict[str, Any] = {"plan": plan, "step_results": [], "iteration": 0}
    rc = get_last_reasoning()
    if rc:
        out["reasoning_chain"] = [{"node": "planner", "reasoning": rc, "ts": time.time()}]
    return out


def _can_parallelize(plan: list[str]) -> bool:
    """Steps are parallel-safe only if none reference earlier results."""
    if len(plan) < 2:
        return False
    cues = ("результат шага", "из шага", "step result", "previous step",
            "after step", "результат подзадачи")
    for s in plan:
        if any(cue in s.lower() for cue in cues):
            return False
    return True


def _executor(state: AgentState) -> dict[str, Any]:
    """Run all planned steps. Optionally parallelise independent steps."""
    plan = state.get("plan", [])
    single_step = len(plan) == 1
    task = _wrap_task_for_llm(state["task"])

    if state.get("debate") and not state.get("use_aider"):
        log.info("[executor] debate mode")
        try:
            from agents.debate import debate as _debate
            results: list[str] = []
            for i, step in enumerate(plan, 1):
                d = _debate(step, rounds=2, parallel=True)
                results.append(f"## Подзадача {i}: {step}\n\n{d['synthesis']}\n\n---\n_дебаты:_\n" +
                               "\n".join(f"- {n}: {t}" for n, t in d['opinions'].items()))
            return {"step_results": results}
        except Exception as e:
            log.warning(f"debate failed, falling back to sequential: {e}")

    parallel = bool(state.get("parallel")) and _can_parallelize(plan) and not state.get("use_aider")
    if parallel:
        log.info(f"[executor] parallel mode for {len(plan)} steps")
        return {"step_results": _executor_parallel(task, plan)}

    results = []
    for i, step in enumerate(plan, 1):
        if single_step:
            prompt = task   # for trivial tasks, ask the model directly
        else:
            context = "\n\n".join(state.get("step_results", []) + results)
            # Cacheable prefix (identical across executor steps + reviewer): {task}
            # Variable suffix: current sub-task + accumulated previous-step results
            prompt = (
                f"ЗАДАЧА:\n{task}\n\n"
                f"━━━ ИНСТРУКЦИЯ ДЛЯ ЭТОГО ВЫЗОВА (EXECUTOR step {i}/{len(plan)}) ━━━\n"
                f"ТЕКУЩАЯ ПОДЗАДАЧА: {step}\n"
                + (f"\nПРЕДЫДУЩИЕ РЕЗУЛЬТАТЫ:\n{context}\n" if context else "")
                + f"\nВыполни текущую подзадачу. Верни конкретный результат без преамбул, "
                f"без повторения формулировки задачи, без размышлений вслух."
            )
        result = ask(prompt, system=SYSTEM_PROMPT_RU, lang="ru")

        if state.get("use_aider") and state.get("aider_files"):
            result = _maybe_run_aider(step, state["aider_files"], result)

        if single_step:
            results.append(result)
        else:
            results.append(f"## Подзадача {i}: {step}\n\n{result}")
    return {"step_results": results}


def _executor_parallel(task: str, plan: list[str]) -> list[str]:
    """Run independent plan-steps in parallel via threads.
    Each step gets the original task as cacheable prefix."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _run_one(i: int, step: str) -> tuple[int, str]:
        prompt = (
            f"ЗАДАЧА:\n{task}\n\n"
            f"━━━ ИНСТРУКЦИЯ ДЛЯ ЭТОГО ВЫЗОВА (EXECUTOR step {i}/{len(plan)}, parallel) ━━━\n"
            f"ТЕКУЩАЯ ПОДЗАДАЧА: {step}\n\n"
            f"Выполни ТОЛЬКО эту подзадачу. Не используй результаты других шагов "
            f"(они выполняются параллельно). Верни конкретный результат без преамбул."
        )
        try:
            res = ask(prompt, system=SYSTEM_PROMPT_RU, lang="ru")
        except Exception as e:
            res = f"[parallel step {i} failed: {e}]"
        return i, res

    out: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(plan))) as pool:
        futures = [pool.submit(_run_one, i, step) for i, step in enumerate(plan, 1)]
        for fut in as_completed(futures):
            i, res = fut.result()
            out[i] = res
    return [f"## Подзадача {i}: {plan[i-1]}\n\n{out[i]}" for i in sorted(out)]


def _reviewer(state: AgentState) -> dict[str, Any]:
    """Check final assembled result. Two modes:

    interactive_review=False (default): LLM reviewer (DeepSeek-reasoner) returns
        ПРИНЯТЬ/ПЕРЕДЕЛАТЬ on first line.
    interactive_review=True: prints final result to stdout and asks user via input()
        to confirm. Falls back to LLM reviewer if stdin is not a TTY.
    """
    final = "\n\n".join(state.get("step_results", []))
    iteration = state.get("iteration", 0) + 1

    if state.get("interactive_review"):
        review = _human_in_the_loop_review(state["task"], final, iteration)
        return {"final": final, "review": review, "iteration": iteration}

    # Same caching strategy: task block first (matches planner/executor cache),
    # variable suffix (review instructions + solution) at the end.
    prompt = (
        f"ЗАДАЧА:\n{_wrap_task_for_llm(state['task'])}\n\n"
        f"━━━ ИНСТРУКЦИЯ ДЛЯ ЭТОГО ВЫЗОВА (REVIEWER) ━━━\n"
        f"РОЛЬ: внутренний рецензент.\n"
        f"ВЫХОД: первая строка = ровно одно слово ПРИНЯТЬ или ПЕРЕДЕЛАТЬ. "
        f"Вторая строка и далее — обоснование (≤3 предложений).\n"
        f"КРИТЕРИЙ: ПЕРЕДЕЛАТЬ только если решение фактически неверное, неполное "
        f"или противоречит задаче. ПРИНЯТЬ если задача решена адекватно, даже если "
        f"стиль не идеален.\n\n"
        f"РЕШЕНИЕ:\n{final}"
    )
    if state.get("stream_review"):
        import sys
        print("\n━━━ REVIEW (streaming) ━━━", file=sys.stderr, flush=True)
        chunks: list[str] = []
        try:
            for tok in stream_deepseek(prompt, system=SYSTEM_PROMPT_RU):
                chunks.append(tok)
                print(tok, end="", flush=True, file=sys.stderr)
        except Exception as e:
            log.warning(f"streaming reviewer failed, falling back: {e}")
            chunks = [ask_deep(prompt, system=SYSTEM_PROMPT_RU, lang="ru")]
        print(file=sys.stderr)
        review = "".join(chunks)
    else:
        review = ask_deep(prompt, system=SYSTEM_PROMPT_RU, lang="ru")
    out: dict[str, Any] = {"final": final, "review": review, "iteration": iteration}
    rc = get_last_reasoning()
    if rc:
        out["reasoning_chain"] = [{"node": "reviewer", "reasoning": rc, "ts": time.time()}]
    return out


def _human_edit_plan(plan: list[str]) -> list[str]:
    """Interactive plan editor: let user accept/regen/edit/add/delete steps."""
    import sys
    if not sys.stdin.isatty():
        return plan
    print("\n📋 PLAN:", file=sys.stderr)
    for i, s in enumerate(plan, 1):
        print(f"  {i}. {s}", file=sys.stderr)
    print("\n[Enter] accept · [n] regen · [N] edit step N · [a] add · [d N] delete N · [q] keep as-is",
          file=sys.stderr)
    while True:
        try:
            cmd = input("plan> ").strip()
        except (EOFError, KeyboardInterrupt):
            return plan
        if cmd in ("", "q"):
            return plan
        if cmd == "a":
            new = input("  new step: ").strip()
            if new:
                plan.append(new)
                print(f"  + step {len(plan)}: {new}", file=sys.stderr)
            continue
        if cmd.startswith("d "):
            try:
                idx = int(cmd[2:]) - 1
                if 0 <= idx < len(plan):
                    removed = plan.pop(idx)
                    print(f"  - removed: {removed}", file=sys.stderr)
            except ValueError:
                pass
            continue
        if cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(plan):
                new = input(f"  step {idx+1} (current: {plan[idx]}):\n  > ").strip()
                if new:
                    plan[idx] = new
            continue
        if cmd == "n":
            return []  # signal: regenerate
    return plan


def _human_in_the_loop_review(task: str, final: str, iteration: int) -> str:
    """Print result + ask user to confirm. Returns standard ПРИНЯТЬ/ПЕРЕДЕЛАТЬ format."""
    import sys
    if not sys.stdin.isatty():
        # Cannot prompt — fall back to LLM reviewer below
        log.warning("[reviewer/HITL] stdin is not a TTY, falling back to LLM reviewer")
        prompt = (
            f"РОЛЬ: внутренний рецензент.\nВЫХОД: первая строка = ПРИНЯТЬ или ПЕРЕДЕЛАТЬ.\n\n"
            f"ЗАДАЧА:\n{_wrap_task_for_llm(task)}\n\nРЕШЕНИЕ:\n{final}"
        )
        return ask_deep(prompt, system=SYSTEM_PROMPT_RU, lang="ru")

    print()
    print("━━━ HUMAN-IN-THE-LOOP REVIEW (итерация {}) ━━━".format(iteration), file=sys.stderr)
    # Final is already non-streaming (assembled from executor); just print.
    print(final, file=sys.stderr)
    print("━━━ конец решения ━━━", file=sys.stderr)
    print(file=sys.stderr)
    print("Подтверди решение:", file=sys.stderr)
    print("  [Enter] / 'y' / 'да'   → ПРИНЯТЬ (закончить)", file=sys.stderr)
    print("  'r' / 'нет' / комментарий → ПЕРЕДЕЛАТЬ (вернуться к planner)", file=sys.stderr)
    if iteration >= 2:
        print("  ⚠ это уже {}-я итерация; ПРИНЯТЬ закроет цикл".format(iteration), file=sys.stderr)
    print(file=sys.stderr)
    try:
        ans = input("review> ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = ""

    decision_lower = ans.lower()
    if decision_lower in ("", "y", "yes", "да", "ok", "ок", "+", "принять", "accept"):
        return "ПРИНЯТЬ\nОдобрено пользователем."
    if decision_lower in ("r", "n", "no", "нет", "redo", "переделать", "-"):
        return "ПЕРЕДЕЛАТЬ\nОтклонено пользователем без комментария."
    # any other text — treat as ПЕРЕДЕЛАТЬ with the user's feedback as guidance
    return f"ПЕРЕДЕЛАТЬ\nОбратная связь от пользователя: {ans}"


def _route_after_review(state: AgentState) -> str:
    """Decide whether to retry (planner again) or finish."""
    review_first_line = (state.get("review") or "").strip().splitlines()[:1]
    decision = (review_first_line[0] if review_first_line else "").upper()
    if "ПЕРЕДЕЛАТЬ" in decision and state.get("iteration", 0) < 2:
        log.info("[reviewer] requested retry")
        return "planner"
    return END


def _maybe_run_aider(step: str, files: list[str], current_result: str) -> str:
    """If a step requires file edits, dispatch to Aider as subprocess."""
    edit_keywords = ("исправ", "редакт", "правк", "измен", "edit", "modif", "rewrite")
    if not any(k in step.lower() for k in edit_keywords):
        return current_result

    try:
        cmd = [
            "/home/oem/.local/bin/aider",
            "--model", "deepseek/deepseek-chat",
            "--no-git", "--yes-always",
            "--message", step,
            *files,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return f"{current_result}\n\n[aider output]\n{proc.stdout[-2000:]}"
    except Exception as e:
        return f"{current_result}\n\n[aider failed: {e}]"


# ─── Graph compilation ───────────────────────────────────────────────────────


def _make_checkpointer():
    """SQLite-backed checkpointer at ~/.claude/aim_graph_state.db.

    Persists every node transition so HITL pauses survive process restart and
    new sessions can `resume` an in-flight task by thread_id.

    Falls back to MemorySaver if langgraph-checkpoint-sqlite is not installed.
    """
    db_path = Path.home() / ".claude" / "aim_graph_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        return SqliteSaver(conn)
    except Exception as e:
        log.info(f"[checkpointer] SqliteSaver unavailable ({e}); using in-memory MemorySaver")
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


def _compile_graph():
    builder = StateGraph(AgentState)
    builder.add_node("planner", _planner)
    builder.add_node("executor", _executor)
    builder.add_node("reviewer", _reviewer)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "executor")
    builder.add_edge("executor", "reviewer")
    builder.add_conditional_edges("reviewer", _route_after_review, {"planner": "planner", END: END})
    return builder.compile(checkpointer=_make_checkpointer())


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _compile_graph()
    return _GRAPH


# ─── Public entry point ──────────────────────────────────────────────────────


def _maybe_compress(blob: str, target_tokens: int = 2000) -> str:
    """Compress blob if it's huge; controlled by env AIM_COMPRESS_MEMORY=1."""
    import os as _os
    if not blob or _os.getenv("AIM_COMPRESS_MEMORY", "").lower() not in ("1", "true", "yes"):
        return blob
    if len(blob) < 8000:
        return blob
    try:
        from agents.context_compressor import compress, quick_dedup
        return compress(quick_dedup(blob), target_tokens=target_tokens)
    except Exception as e:
        log.info(f"compression unavailable ({e})")
        return blob


def _load_aim_memory(task: str | None = None, k: int = 12, use_graphrag: bool = False) -> str:
    """Load AIM's own memory (LanceDB + optional GraphRAG entity expansion).

    This REPLACES `_load_claude_memory()` (kept as alias below for backwards
    compatibility). All facts now live in AIM's LanceDB index — see
    `scripts/import_claude_memory.py` for one-time migration.

    Modes:
      1. task given, GraphRAG=True → entity-graph hop expansion + LanceDB
      2. task given, GraphRAG=False → flat semantic retrieval
      3. task is None → load all *.md from memory dir (legacy fallback)
    """
    if task is not None and use_graphrag:
        try:
            from agents.graphrag import query as graphrag_query
            hits = graphrag_query(task, k=k, hops=1)
            if hits:
                return _maybe_compress(_format_memory_hits(hits, label="GraphRAG (entity-graph)"))
        except Exception as e:
            log.info(f"graphrag unavailable ({e}); falling back to flat semantic")
    # ── Mode 1: semantic via embedding index, if available ──────────────────
    if task is not None:
        try:
            from agents.memory_index import retrieve as _semantic_retrieve  # local
            hits = _semantic_retrieve(task, k=k)
            if hits:
                base = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
                chunks: list[str] = []
                index = base / "MEMORY.md"
                if index.exists():
                    chunks.append(f"# MEMORY INDEX\n\n{index.read_text(encoding='utf-8')}")
                # group hits by file → emit each file once with a brief score note
                seen: dict[str, list[dict]] = {}
                for h in hits:
                    seen.setdefault(h["file"], []).append(h)
                for fname, hs in seen.items():
                    body = "\n\n…\n\n".join(h["text"] for h in hs)
                    best = min((h["_distance"] for h in hs), default=1.0)
                    chunks.append(f"# {Path(fname).stem}  [semantic distance={best:.3f}]\n\n{body}")
                log.info(f"[memory] semantic retrieval: {len(seen)} files / {len(hits)} chunks")
                return "\n\n---\n\n".join(chunks)
        except Exception as e:
            log.info(f"[memory] semantic retrieval unavailable ({e}); falling back to lexical")
            # fall through to lexical mode
    base = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
    if not base.exists():
        return ""

    files = [f for f in sorted(base.glob("*.md")) if f.name != "MEMORY.md"]

    if task is None:
        # Legacy: load everything
        chunks: list[str] = []
        index = base / "MEMORY.md"
        if index.exists():
            chunks.append(f"# MEMORY INDEX\n\n{index.read_text(encoding='utf-8')}")
        for f in files:
            try:
                chunks.append(f"# {f.stem}\n\n{f.read_text(encoding='utf-8')}")
            except Exception:
                continue
        return "\n\n---\n\n".join(chunks)

    # ── Relevance-ranked load ─────────────────────────────────────────────────
    import re as _re

    # Tokenise task into Cyrillic + Latin word stems (≥3 chars)
    raw_tokens = _re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", task.lower())
    stop = {"что", "как", "это", "для", "что-то", "etc", "the", "and", "for"}
    tokens = {t for t in raw_tokens if t not in stop}

    scored: list[tuple[float, Path, str]] = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        lc = content.lower()
        # 3× weight for filename matches, 2× for frontmatter description
        fname_score = sum(3 for t in tokens if t in f.stem.lower())
        # crude description region: between first '---' pair
        desc_match = _re.search(r"---(.*?)---", content, _re.DOTALL)
        desc = desc_match.group(1).lower() if desc_match else ""
        desc_score = sum(2 for t in tokens if t in desc)
        body_score = sum(1 for t in tokens if t in lc)
        score = fname_score + desc_score + body_score
        if score > 0:
            scored.append((score, f, content))

    scored.sort(key=lambda r: -r[0])
    selected = scored[:k]

    chunks: list[str] = []
    index = base / "MEMORY.md"
    if index.exists():
        # Always include the index — it's the table of contents
        chunks.append(f"# MEMORY INDEX\n\n{index.read_text(encoding='utf-8')}")
    for score, f, content in selected:
        chunks.append(f"# {f.stem}  [relevance={score}]\n\n{content}")

    log.info(
        f"[memory] semantic-lite load: {len(selected)}/{len(files)} files chosen "
        f"(top score {selected[0][0] if selected else 0})"
    )
    return _maybe_compress("\n\n---\n\n".join(chunks))


def _format_memory_hits(hits: list[dict], label: str = "semantic") -> str:
    """Render a list of {file, text, _distance} hits as a single context blob."""
    seen: dict[str, list[dict]] = {}
    for h in hits:
        seen.setdefault(h["file"], []).append(h)
    chunks = []
    for fname, hs in seen.items():
        body = "\n\n…\n\n".join(h["text"] for h in hs)
        best = min((h.get("_distance", 1.0) for h in hs), default=1.0)
        chunks.append(f"# {Path(fname).stem}  [{label}, distance={best:.3f}]\n\n{body}")
    return "\n\n---\n\n".join(chunks)


# Backwards-compatible alias — anything still calling _load_claude_memory()
# now transparently uses the AIM-native loader.
_load_claude_memory = _load_aim_memory


def run_agent(
    task: str,
    use_aider: bool = False,
    files: list[str] | None = None,
    use_memory: bool = False,
    full_memory: bool = False,
    interactive_review: bool = False,
    parallel: bool = False,
    edit_plan: bool = False,
    debate: bool = False,
    stream_review: bool = False,
    tree_plan: bool = False,
) -> dict[str, Any]:
    """Run the LangGraph agent on a task. Returns final state dict.

    Args:
        task: the user task in Russian / English / translit.
        use_aider: if True, executor steps containing edit-keywords spawn Aider.
        files: list of file paths to expose to Aider when use_aider=True.
        use_memory: if True, inject memory relevant to the task (top-k by lexical
                    score; ~30-60KB instead of full 250KB).
        full_memory: if True (and use_memory=True), inject ALL memory files
                     unfiltered — slower but covers edge cases.
        interactive_review: if True, the reviewer node prompts the user via
                            stdin to confirm the result.
    """
    full_task = task
    if use_memory:
        ensure_embed_daemon(verbose=False)
        memory_blob = _load_claude_memory(task=None if full_memory else task)
        if memory_blob:
            full_task = (
                f"━━━ ДОЛГОСРОЧНАЯ ПАМЯТЬ "
                f"({'полная' if full_memory else 'релевантные ' + 'файлы'}) ━━━\n\n"
                f"{memory_blob}\n\n"
                f"━━━ КОНЕЦ ПАМЯТИ ━━━\n\n"
                f"━━━ ТЕКУЩАЯ ЗАДАЧА ━━━\n\n{task}"
            )
            # Pre-warm DeepSeek prefix cache: planner+executor+reviewer all share
            # a long memory blob; the first real call would otherwise pay full price.
            if len(memory_blob) > 2000:
                warmup_deepseek_cache(f"ЗАДАЧА:\n{full_task}\n")
    # thread_id is required for the checkpointer — derive a stable hash from the
    # ORIGINAL task (not the memory-augmented version) so the same conceptual
    # task resumes the same checkpoint across sessions. Override via env if needed.
    import hashlib, os
    thread_id = os.environ.get("AIM_THREAD_ID") or hashlib.sha1(task.encode("utf-8")).hexdigest()[:16]
    config = {"configurable": {"thread_id": thread_id}}

    initial: AgentState = {
        "task": full_task,
        "interactive_review": interactive_review,
        "use_aider": use_aider,
        "aider_files": files or [],
        "parallel": parallel,
        "edit_plan": edit_plan,
        "debate": debate,
        "stream_review": stream_review,
        "tree_plan": tree_plan,
    }
    try:
        from agents.metrics import GRAPH_ITERATIONS, GRAPH_PLAN_SIZE
        result = get_graph().invoke(initial, config=config)
        GRAPH_ITERATIONS.observe(result.get("iteration", 0))
        GRAPH_PLAN_SIZE.observe(len(result.get("plan", [])))
        return result
    except ImportError:
        return get_graph().invoke(initial, config=config)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _main():
    import argparse
    p = argparse.ArgumentParser(description="AIM LangGraph multi-step agent (DeepSeek-driven)")
    p.add_argument("task", nargs="?", help="The task to solve. If omitted, reads from stdin.")
    p.add_argument("--aider", action="store_true", help="Allow Aider to make file edits during executor steps")
    p.add_argument("--file", action="append", default=[], help="File(s) to make available to Aider (-file repeatable)")
    p.add_argument("--memory", action="store_true", help="Inject AIM memory relevant to the task (semantic top-k or GraphRAG)")
    p.add_argument("--full-memory", action="store_true", help="Force full memory load (slow, ~250KB)")
    p.add_argument("--review", action="store_true", help="Human-in-the-loop reviewer: ask user to confirm result via stdin")
    p.add_argument("--parallel", action="store_true", help="Run independent plan steps in parallel (threads)")
    p.add_argument("--edit-plan", action="store_true", help="Interactive plan editor before execution")
    p.add_argument("--debate", action="store_true", help="Use multi-agent debate for the executor (slower, more rigorous)")
    p.add_argument("--stream-review", action="store_true", help="Stream the reviewer's tokens to stdout as they arrive")
    p.add_argument("--tree-plan", action="store_true", help="Use Tree-of-Thoughts planner (slower, higher quality on hard tasks)")
    p.add_argument("--metrics", action="store_true", help="Start Prometheus metrics + /healthz endpoint")
    args = p.parse_args()

    if args.metrics:
        try:
            from agents.metrics import start_metrics_server
            start_metrics_server()
        except ImportError:
            print("[!] prometheus-client not installed; --metrics ignored")

    import sys
    task = args.task or sys.stdin.read().strip()
    if not task:
        sys.exit("aim-graph: empty task")

    print(f"━━━ TASK ━━━\n{task}\n")
    if args.memory:
        print(f"[memory] loading AIM memory ({'full' if args.full_memory else 'task-relevant subset'})…")
    if args.review:
        print("[reviewer] human-in-the-loop mode — you will be asked to confirm")
    result = run_agent(
        task,
        use_aider=args.aider,
        files=args.file,
        use_memory=args.memory,
        full_memory=args.full_memory,
        interactive_review=args.review,
        parallel=args.parallel,
        edit_plan=args.edit_plan,
        debate=args.debate,
        stream_review=args.stream_review,
        tree_plan=args.tree_plan,
    )

    print("━━━ PLAN ━━━")
    for i, step in enumerate(result.get("plan", []), 1):
        print(f"  {i}. {step}")

    print("\n━━━ EXECUTION ━━━")
    for chunk in result.get("step_results", []):
        print(chunk)
        print()

    print("━━━ INTERNAL REVIEW ━━━")
    print(result.get("review", "(no review)"))
    print(f"\n[iterations: {result.get('iteration', 0)}]")


if __name__ == "__main__":
    _main()
