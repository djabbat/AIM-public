#!/usr/bin/env python3
"""
AIM — LLM client.
Single point for all AI calls. Uses DeepSeek API (OpenAI-compatible).
Set DEEPSEEK_API_KEY in environment or ~/.aim_env
"""

import os
from config import get_logger

log = get_logger("llm")

# ── Models ────────────────────────────────────────────────────
MODEL_FAST   = "deepseek-chat"       # DeepSeek V3 — fast, cheap
MODEL_DEEP   = "deepseek-reasoner"   # DeepSeek R1 — slow, strong reasoning

# ── API key ───────────────────────────────────────────────────
def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        env_file = os.path.expanduser("~/.aim_env")
        if os.path.exists(env_file):
            for line in open(env_file):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key


# ── Singleton client ──────────────────────────────────────────
_client = None

def _get_client():
    global _client
    api_key = _get_api_key()
    if not api_key:
        return None, "[AIM: DEEPSEEK_API_KEY не задан. Добавьте в ~/.aim_env]"
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client, None


def ask_llm(prompt: str,
            system: str = "",
            max_tokens: int = 2048,
            temperature: float = 0.3,
            model: str = MODEL_FAST) -> str:
    """
    Call DeepSeek API. Returns the response text.
    Falls back to a clear error message if API key is missing or call fails.
    Automatically injects nutrition rules if prompt contains food queries.
    """
    client, err = _get_client()
    if err:
        return err

    # ── Nutrition filter: inject rules if food-related query ──
    try:
        from space_nutrition import get_nutrition_context
        nutrition_ctx = get_nutrition_context(prompt)
        if nutrition_ctx and nutrition_ctx not in (system or ""):
            system = (system or "") + nutrition_ctx
    except Exception:
        pass

    try:

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(  # type: ignore[union-attr]
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result = resp.choices[0].message.content.strip()
        log.debug("LLM OK: %d chars, model=%s", len(result), model)
        return result

    except Exception as e:
        log.error("LLM error: %s", e)
        return f"[LLM error: {e}]"


def ask_deep(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """Use DeepSeek-R1 for complex reasoning (diagnosis, treatment plans)."""
    return ask_llm(prompt, system=system, max_tokens=max_tokens,
                   temperature=0.1, model=MODEL_DEEP)
