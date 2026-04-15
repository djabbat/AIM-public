"""
AIM v7.0 — Гибридный LLM-роутер
Выбирает модель по типу задачи: KIMI · Qwen · DeepSeek
"""

import re
import time
import logging
from typing import Optional
from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY, KIMI_API_KEY, QWEN_API_KEY, GROQ_API_KEY,
    Models, Endpoints,
    QWEN_LANGS, DS_LANGS,
    LONG_CONTEXT_THRESHOLD, REASONING_KEYWORDS,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT,
    SUPPORTED_LANGS,
)

log = logging.getLogger("aim.llm")

# ── Клиенты (OpenAI-совместимый интерфейс у всех трёх) ───────────────────────

def _client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key, timeout=LLM_TIMEOUT)

def _deepseek() -> OpenAI:
    return _client(Endpoints.DEEPSEEK, DEEPSEEK_API_KEY)

def _kimi() -> OpenAI:
    return _client(Endpoints.KIMI, KIMI_API_KEY)

def _qwen() -> OpenAI:
    return _client(Endpoints.QWEN, QWEN_API_KEY)

def _groq() -> OpenAI:
    return _client(Endpoints.GROQ, GROQ_API_KEY)

# ── Утилиты ───────────────────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    """Грубая оценка токенов: ~4 символа = 1 токен."""
    return len(text) // 4

def _is_reasoning_task(prompt: str) -> bool:
    prompt_lower = prompt.lower()
    return any(kw in prompt_lower for kw in REASONING_KEYWORDS)

def _detect_lang(text: str) -> str:
    """Простой детектор языка по Unicode-блокам."""
    if re.search(r'[\u0600-\u06FF]', text):   return "ar"
    if re.search(r'[\u4E00-\u9FFF]', text):   return "zh"
    if re.search(r'[\u10D0-\u10FF]', text):   return "ka"
    if re.search(r'[\u0400-\u04FF]', text):
        # Русский vs Казахский — по характерным буквам
        if re.search(r'[әіңғүұқөһ]', text, re.IGNORECASE): return "kz"
        return "ru"
    if re.search(r'[æøåÆØÅ]', text):          return "da"
    return "en"

# ── Роутер ────────────────────────────────────────────────────────────────────

def _route(prompt: str, lang: Optional[str], system: str) -> tuple[str, str, OpenAI]:
    """
    Возвращает (model_name, provider_name, client).
    Логика:
    1. Длинный контекст → KIMI
    2. Qwen-языки (AR/ZH/KA/KZ/DA) → Qwen
    3. Рассуждение / диагностика → DeepSeek-reasoner
    4. Быстрый простой ответ → Groq (если ключ есть)
    5. Всё остальное → DeepSeek-chat
    """
    detected = lang or _detect_lang(prompt + " " + system)

    total_tokens = _count_tokens(prompt + system)
    if total_tokens > LONG_CONTEXT_THRESHOLD and KIMI_API_KEY:
        model = Models.KIMI_128K if total_tokens > 30_000 else Models.KIMI_32K
        log.info(f"Router → KIMI ({model}), ~{total_tokens} tokens")
        return model, "kimi", _kimi()

    if detected in QWEN_LANGS and QWEN_API_KEY:
        model = Models.QWEN_TURBO
        log.info(f"Router → Qwen ({model}), lang={detected}")
        return model, "qwen", _qwen()

    if _is_reasoning_task(prompt) and DEEPSEEK_API_KEY:
        log.info("Router → DeepSeek-reasoner")
        return Models.DS_REASONER, "deepseek", _deepseek()

    # Groq — если задача простая и ключ есть (самый быстрый)
    if GROQ_API_KEY and total_tokens < 3_000:
        log.info("Router → Groq (fast)")
        return Models.GROQ_LLAMA, "groq", _groq()

    log.info("Router → DeepSeek-chat")
    return Models.DS_CHAT, "deepseek", _deepseek()

# ── Основной вызов ────────────────────────────────────────────────────────────

def ask(
    prompt: str,
    system: str = "You are a helpful medical assistant.",
    lang: Optional[str] = None,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS,
    retries: int = 2,
) -> str:
    """
    Универсальная точка входа. Роутер выбирает модель автоматически.

    Args:
        prompt:      Пользовательский запрос
        system:      Системный промпт
        lang:        Явное указание языка (код из SUPPORTED_LANGS)
        temperature: Температура (default 0.3)
        max_tokens:  Макс. токенов в ответе
        retries:     Попыток при ошибке

    Returns:
        Строка ответа от LLM
    """
    model, provider, client = _route(prompt, lang, system)

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]

    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            log.warning(f"[{provider}/{model}] attempt {attempt+1} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                return _fallback(prompt, system, provider, e)

    return "[AIM: LLM error]"


def _fallback(prompt: str, system: str, failed_provider: str, err: Exception) -> str:
    """Fallback: если основной провайдер упал — пробуем следующий."""
    log.warning(f"Fallback triggered, {failed_provider} failed: {err}")

    # Порядок fallback
    chain = []
    if failed_provider != "deepseek" and DEEPSEEK_API_KEY:
        chain.append((Models.DS_CHAT, _deepseek()))
    if failed_provider != "qwen" and QWEN_API_KEY:
        chain.append((Models.QWEN_TURBO, _qwen()))
    if failed_provider != "kimi" and KIMI_API_KEY:
        chain.append((Models.KIMI_8K, _kimi()))

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]

    for model, client in chain:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )
            log.info(f"Fallback succeeded with {model}")
            return resp.choices[0].message.content.strip()
        except Exception as e2:
            log.warning(f"Fallback {model} also failed: {e2}")

    return f"[AIM: все LLM-провайдеры недоступны. Ошибка: {err}]"


# ── Удобные алиасы ────────────────────────────────────────────────────────────

def ask_fast(prompt: str, lang: str = None) -> str:
    """Быстрый ответ — DeepSeek-chat напрямую."""
    return ask(prompt, lang=lang, temperature=0.2)

def ask_deep(prompt: str, system: str = "", lang: str = None) -> str:
    """Глубокий анализ — DeepSeek-reasoner напрямую."""
    if not DEEPSEEK_API_KEY:
        return ask(prompt, system=system, lang=lang)
    client = _deepseek()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = client.chat.completions.create(
            model=Models.DS_REASONER,
            messages=messages,
            temperature=0,
            max_tokens=LLM_MAX_TOKENS,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"ask_deep failed: {e}")
        return ask(prompt, system=system, lang=lang)

def ask_long(prompt: str, system: str = "", lang: str = None) -> str:
    """Длинный контекст — KIMI напрямую."""
    if not KIMI_API_KEY:
        log.warning("KIMI_API_KEY не задан, fallback на DeepSeek")
        return ask(prompt, system=system, lang=lang)
    client = _kimi()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = client.chat.completions.create(
            model=Models.KIMI_128K,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"ask_long (KIMI) failed: {e}")
        return ask(prompt, system=system, lang=lang)

def ask_multilang(prompt: str, lang: str) -> str:
    """Многоязычный ответ — Qwen напрямую."""
    if not QWEN_API_KEY:
        log.warning("QWEN_API_KEY не задан, fallback на DeepSeek")
        return ask(prompt, lang=lang)
    client = _qwen()
    try:
        resp = client.chat.completions.create(
            model=Models.QWEN_TURBO,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"ask_multilang (Qwen) failed: {e}")
        return ask(prompt, lang=lang)


# ── Статус провайдеров ────────────────────────────────────────────────────────

def providers_status() -> dict:
    """Проверяет какие ключи заданы."""
    return {
        "deepseek": bool(DEEPSEEK_API_KEY),
        "kimi":     bool(KIMI_API_KEY),
        "qwen":     bool(QWEN_API_KEY),
        "groq":     bool(GROQ_API_KEY),
    }
