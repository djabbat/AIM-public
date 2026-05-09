"""agents/speculative.py — speculative decoding (draft + target).

Uses Groq (fast) as the draft model to produce a quick response, then
DeepSeek-reasoner (target) to verify/refine. Falls back to a plain
DeepSeek call if Groq is unavailable.

Trade-off: 1.5–2× speedup on long answers when Groq agrees with DeepSeek's
direction; otherwise overhead. Use only when latency matters more than
nuance (e.g. interactive UIs).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

# Routing rule (MEMORY.md #1, REMINDER.md #6): all LLM calls go through
# `llm.py`. ask_fast() = Groq tier (with DS-chat fallback if Groq down).
from llm import ask, ask_deep, ask_fast
from config import GROQ_API_KEY, DEEPSEEK_API_KEY, Models

log = logging.getLogger("aim.speculative")


def speculative_generate(
    prompt: str,
    system: str = "",
    draft_model: str = Models.GROQ_LLAMA_FAST,
    draft_tokens: int = 200,
    target_max_tokens: int = 4096,
) -> str:
    """Generate via draft → target verification.

    Strategy:
      1. Draft a candidate answer with Groq (fast, ~1s) — via `ask_fast()`.
      2. Ask DeepSeek-reasoner to validate/refine, with the draft in-prompt.
         The reasoner can accept (cheap, only reads), or rewrite.

    Returns the target's verdict (always DeepSeek-quality).

    Note (2026-05-07): `draft_model` and `draft_tokens` parameters are
    kept for backward-compat but ignored — `ask_fast()` selects the model
    + caps tokens internally per `llm.py` policy. To override, set the
    relevant env vars (`AIM_GROQ_FAST_MODEL`, `AIM_FAST_MAX_TOKENS`).
    """
    if not GROQ_API_KEY or not DEEPSEEK_API_KEY:
        # Single-model fallback
        return ask_deep(prompt, system=system) if DEEPSEEK_API_KEY else ask(prompt, system=system)

    t0 = time.time()
    try:
        # Draft via the centralised router. `ask_fast` already wires
        # Groq → DS-chat → Ollama 3b fallback chain (see llm.py).
        draft = ask_fast(prompt if not system else f"{system}\n\n{prompt}").strip()
        log.info(f"draft generated in {time.time()-t0:.1f}s ({len(draft)} chars)")
    except Exception as e:
        log.warning(f"draft failed ({e}); fallback to direct DeepSeek")
        return ask_deep(prompt, system=system)

    verify_prompt = (
        f"ЗАДАЧА:\n{prompt}\n\n"
        f"━━━ DRAFT (от быстрой модели; может быть неточным) ━━━\n{draft}\n\n"
        f"━━━ ИНСТРУКЦИЯ ━━━\n"
        f"Если draft точен и полон — повтори его без изменений.\n"
        f"Если есть мелкие неточности — исправь, сохранив структуру.\n"
        f"Если draft принципиально неверный — напиши с нуля.\n"
        f"Верни ТОЛЬКО окончательный ответ, без мета-комментариев."
    )
    final = ask_deep(verify_prompt, system=system)
    log.info(f"speculative total: {time.time()-t0:.1f}s")
    return final
