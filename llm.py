"""
AIM v7.0 — LLM-роутер
DeepSeek (chat / reasoner) + Groq (быстрые короткие запросы).
"""

import os
import re
import time
import logging
import threading
import httpx
from typing import Optional
from openai import OpenAI, APITimeoutError

from config import (
    DEEPSEEK_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
    Models, Endpoints,
    REASONING_KEYWORDS,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_TOKENS_LONG, LLM_TIMEOUT, LLM_CONNECT_TIMEOUT,
    SUPPORTED_LANGS,
)

log = logging.getLogger("aim.llm")


# ── Rate limiter (token bucket) ────────────────────────────────────────────


class TokenBucket:
    """Thread-safe token bucket. `rate` = tokens/sec; `capacity` = max burst."""

    def __init__(self, rate_per_minute: float, capacity: int):
        self.rate = max(rate_per_minute, 1) / 60.0
        self.capacity = max(capacity, 1)
        self.tokens = float(self.capacity)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, n: int = 1, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                now = time.time()
                elapsed = now - self.last_refill
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.last_refill = now
                if self.tokens >= n:
                    self.tokens -= n
                    return True
                wait = (n - self.tokens) / self.rate
            if time.time() + wait > deadline:
                raise TimeoutError(
                    f"rate-limit wait {wait:.1f}s exceeds timeout {timeout:.1f}s"
                )
            time.sleep(min(wait, 1.0))


if os.getenv("AIM_RATE_ADAPTIVE", "").lower() in ("1", "true", "yes"):
    from agents.adaptive_limiter import AdaptiveRateLimiter
    _DS_LIMITER = AdaptiveRateLimiter(
        target_rpm=int(os.getenv("AIM_RATE_LIMIT_RPM", "50")),
        min_rpm=int(os.getenv("AIM_RATE_MIN_RPM", "5")),
        error_threshold=int(os.getenv("AIM_RATE_ERR_THRESHOLD", "3")),
    )
    _GROQ_LIMITER = AdaptiveRateLimiter(
        target_rpm=int(os.getenv("AIM_GROQ_RATE_RPM", "30")),
        min_rpm=int(os.getenv("AIM_RATE_MIN_RPM", "3")),
    )
else:
    _DS_LIMITER = TokenBucket(
        rate_per_minute=int(os.getenv("AIM_RATE_LIMIT_RPM", "50")),
        capacity=int(os.getenv("AIM_RATE_BURST", "100")),
    )
    _GROQ_LIMITER = TokenBucket(
        rate_per_minute=int(os.getenv("AIM_GROQ_RATE_RPM", "30")),
        capacity=int(os.getenv("AIM_GROQ_RATE_BURST", "60")),
    )

# Ollama is local — no remote rate limit. Use a generous bucket so it never blocks.
_OLLAMA_LIMITER = TokenBucket(rate_per_minute=10000, capacity=1000)
# Anthropic — conservative; tier 1 is 50 RPM. Adaptive via env.
_ANTHROPIC_LIMITER = TokenBucket(
    rate_per_minute=int(os.getenv("AIM_ANTHROPIC_RATE_RPM", "50")),
    capacity=int(os.getenv("AIM_ANTHROPIC_RATE_BURST", "20")),
)
# Gemini free tier — 50 RPD on gemini-2.5-pro. Conservative RPM.
_GEMINI_LIMITER = TokenBucket(
    rate_per_minute=int(os.getenv("AIM_GEMINI_RATE_RPM", "10")),
    capacity=int(os.getenv("AIM_GEMINI_RATE_BURST", "5")),
)


def _limiter_for(provider: str) -> TokenBucket:
    if provider == "deepseek":
        return _DS_LIMITER
    if provider == "ollama":
        return _OLLAMA_LIMITER
    if provider == "anthropic":
        return _ANTHROPIC_LIMITER
    if provider == "gemini":
        return _GEMINI_LIMITER
    return _GROQ_LIMITER


# ── Circuit breaker ─────────────────────────────────────────────────────────


class CircuitBreaker:
    """3-state breaker: CLOSED → OPEN (after N failures) → HALF_OPEN (after recovery)."""

    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half-open"

    def __init__(self, threshold: int = 3, recovery: float = 60.0):
        self.threshold = threshold
        self.recovery = recovery
        self.failures = 0
        self.opened_at = 0.0
        self.state = self.CLOSED
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self.state == self.OPEN:
                if time.time() - self.opened_at >= self.recovery:
                    self.state = self.HALF_OPEN
                    log.info(f"circuit half-open (testing recovery)")
                else:
                    raise CircuitBreakerError(
                        f"circuit open; retry in {self.recovery - (time.time() - self.opened_at):.0f}s"
                    )

    def on_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.state = self.CLOSED

    def on_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.state = self.OPEN
                self.opened_at = time.time()
                log.warning(f"circuit OPEN after {self.failures} failures (cooldown {self.recovery}s)")


class CircuitBreakerError(RuntimeError):
    pass


_DS_BREAKER = CircuitBreaker(
    threshold=int(os.getenv("AIM_CIRCUIT_THRESHOLD", "3")),
    recovery=float(os.getenv("AIM_CIRCUIT_RECOVERY", "60")),
)
_GROQ_BREAKER = CircuitBreaker(
    threshold=int(os.getenv("AIM_GROQ_CIRCUIT_THRESHOLD", "5")),
    recovery=float(os.getenv("AIM_GROQ_CIRCUIT_RECOVERY", "30")),
)
# Ollama is local; once it's up it rarely fails — small breaker.
_OLLAMA_BREAKER = CircuitBreaker(threshold=2, recovery=15.0)
_ANTHROPIC_BREAKER = CircuitBreaker(threshold=3, recovery=60.0)
_GEMINI_BREAKER = CircuitBreaker(threshold=3, recovery=120.0)


def _breaker_for(provider: str) -> CircuitBreaker:
    if provider == "deepseek":
        return _DS_BREAKER
    if provider == "ollama":
        return _OLLAMA_BREAKER
    if provider == "anthropic":
        return _ANTHROPIC_BREAKER
    if provider == "gemini":
        return _GEMINI_BREAKER
    return _GROQ_BREAKER

# ── Клиенты (OpenAI-совместимый интерфейс) ───────────────────────────────────

def _client(base_url: str, api_key: str) -> OpenAI:
    timeout = httpx.Timeout(LLM_TIMEOUT, connect=LLM_CONNECT_TIMEOUT)
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

def _deepseek() -> OpenAI:
    return _client(Endpoints.DEEPSEEK, DEEPSEEK_API_KEY)

def _groq() -> OpenAI:
    return _client(Endpoints.GROQ, GROQ_API_KEY)


# ── Ollama (local LLM via OpenAI-compat /v1) ────────────────────────────────

_OLLAMA_PROBE_AT: float = 0.0
_OLLAMA_UP: bool = False
_OLLAMA_PROBE_TTL = 30.0  # seconds; re-probe at most every 30s


def _ollama() -> OpenAI:
    # Ollama doesn't require an API key but the openai client insists on one.
    return _client(Endpoints.OLLAMA, "ollama-local")


def ollama_available() -> bool:
    """Quick TCP probe with TTL cache. Avoids hammering localhost."""
    global _OLLAMA_PROBE_AT, _OLLAMA_UP
    now = time.time()
    if now - _OLLAMA_PROBE_AT < _OLLAMA_PROBE_TTL:
        return _OLLAMA_UP
    _OLLAMA_PROBE_AT = now
    try:
        # /api/tags is the cheapest endpoint (lists local models)
        url = Endpoints.OLLAMA.rsplit("/v1", 1)[0] + "/api/tags"
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0)) as c:
            r = c.get(url)
        _OLLAMA_UP = r.status_code == 200
    except Exception:
        _OLLAMA_UP = False
    return _OLLAMA_UP


def ollama_force_reprobe() -> bool:
    global _OLLAMA_PROBE_AT
    _OLLAMA_PROBE_AT = 0.0
    return ollama_available()


# ── Gemini (Google AI Studio) — free tier 50 req/day on 2.5-pro ────────────


def gemini_available() -> bool:
    return bool(GEMINI_API_KEY)


def _gemini() -> OpenAI:
    """Gemini exposes an OpenAI-compatible /v1beta/openai surface — same client."""
    return _client(Endpoints.GEMINI, GEMINI_API_KEY)


def _gemini_chat(prompt: str, *, system: str = "", model: Optional[str] = None,
                 temperature: float = LLM_TEMPERATURE,
                 max_tokens: int = LLM_MAX_TOKENS) -> str:
    """Minimal Gemini wrapper. Returns "" on failure (caller falls through)."""
    if not gemini_available():
        return ""
    _breaker_for("gemini").before_call()
    _limiter_for("gemini").acquire()
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    try:
        resp = _gemini().chat.completions.create(
            model=model or Models.GEMINI_PRO,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _breaker_for("gemini").on_success()
        return resp.choices[0].message.content.strip()
    except Exception as e:
        _breaker_for("gemini").on_failure()
        _record_llm_error("gemini", e)
        log.warning(f"Gemini call failed: {e}")
        return ""


# ── Anthropic (Claude) — premium tier for critical reasoning + native vision ──
#
# Used by ask_critical(), ensemble adjudication, and tools/vision.see().
# Native messages API (not OpenAI-compatible). Falls through to ds-v4-pro
# when ANTHROPIC_API_KEY is missing.

_ANTHROPIC_CLIENT = None


def anthropic_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _anthropic():
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is not None:
        return _ANTHROPIC_CLIENT
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; pip install anthropic")
        return None
    _ANTHROPIC_CLIENT = Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=httpx.Timeout(LLM_TIMEOUT, connect=LLM_CONNECT_TIMEOUT),
    )
    return _ANTHROPIC_CLIENT


def _claude_chat(prompt: str, *, system: str = "", model: Optional[str] = None,
                 temperature: float = LLM_TEMPERATURE,
                 max_tokens: int = LLM_MAX_TOKENS,
                 images: Optional[list[dict]] = None,
                 cache_system: bool = True) -> str:
    """Minimal Claude wrapper. `images` = list of {'type','source':{'data':b64,'media_type':...}}.

    If `cache_system=True` and the system prompt is long (>1024 tokens),
    the LAST chunk of the system block is marked with `cache_control: ephemeral`
    so subsequent calls within 5 minutes hit the prompt cache (~10× cheaper input).
    """
    client = _anthropic()
    if client is None:
        return ""
    _breaker_for("anthropic").before_call()
    _limiter_for("anthropic").acquire()
    try:
        # Build content blocks (text + optional images)
        content: list[dict] = []
        if images:
            content.extend(images)
        content.append({"type": "text", "text": prompt})
        kwargs = {
            "model": model or Models.CLAUDE_OPUS,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            # When caching, system MUST be a list of content blocks. We mark
            # the last block with cache_control to enable prefix-cache.
            if cache_system and len(system) > 4000:   # ~1000 tokens minimum
                kwargs["system"] = [{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        _breaker_for("anthropic").on_success()
        # Log cache stats if returned
        try:
            usage = resp.usage
            cr = getattr(usage, "cache_read_input_tokens", None)
            cw = getattr(usage, "cache_creation_input_tokens", None)
            if cr or cw:
                log.info(f"[anthropic] cache: read={cr or 0}  write={cw or 0}")
        except Exception:
            pass
        out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return out.strip()
    except Exception as e:
        _breaker_for("anthropic").on_failure()
        _record_llm_error("anthropic", e)
        log.warning(f"Claude call failed: {e}")
        return ""

# ── Утилиты ───────────────────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    """Грубая оценка токенов: ~4 символа = 1 токен."""
    return len(text) // 4

def _is_reasoning_task(prompt: str) -> bool:
    prompt_lower = prompt.lower()
    return any(kw in prompt_lower for kw in REASONING_KEYWORDS)

def _detect_lang(text: str) -> str:
    """Простой детектор языка по Unicode-блокам."""
    if re.search(r'[؀-ۿ]', text):   return "ar"
    if re.search(r'[一-鿿]', text):   return "zh"
    if re.search(r'[ა-ჿ]', text):   return "ka"
    if re.search(r'[Ѐ-ӿ]', text):
        if re.search(r'[әіңғүұқөһ]', text, re.IGNORECASE): return "kz"
        return "ru"
    if re.search(r'[æøåÆØÅ]', text):          return "da"
    return "en"

# ── Роутер ────────────────────────────────────────────────────────────────────

def _route(prompt: str, lang: Optional[str], system: str) -> tuple[str, str, OpenAI]:
    """
    Возвращает (model_name, provider_name, client).

    Routing policy (cloud-first, per user 2026-04-30):
      1. Reasoning task   → DeepSeek-V4-pro (cloud)
      2. Long-context     → DeepSeek-V4-flash (1M ctx)
      3. Default chat     → DeepSeek-V4-flash (cloud)
      4. Fallback when DeepSeek unreachable / key missing:
         a. Groq (if key + short prompt)
         b. Ollama qwen2.5:7b (if running locally)
      5. Smart routing override (AIM_SMART_ROUTING=1) takes precedence.
    """
    # Smart routing override (opt-in)
    if os.getenv("AIM_SMART_ROUTING", "").lower() in ("1", "true", "yes"):
        try:
            from agents.smart_routing import route as _sr_route
            r = _sr_route(prompt + "\n" + (system or ""))
            model = r["model"]
            if model.startswith("deepseek-") and DEEPSEEK_API_KEY:
                log.info(f"SmartRouter → {model} (tier={r['tier']})")
                return model, "deepseek", _deepseek()
            if model.startswith("llama-") and GROQ_API_KEY:
                log.info(f"SmartRouter → {model} (tier={r['tier']})")
                return model, "groq", _groq()
            if (model.startswith("qwen") or model.startswith("llama3")) and ollama_available():
                log.info(f"SmartRouter → ollama:{model}")
                return model, "ollama", _ollama()
        except Exception as e:
            log.debug(f"smart_routing fallback: {e}")

    total_tokens = _count_tokens(prompt + system)
    is_reasoning = _is_reasoning_task(prompt)
    is_long = total_tokens > 30_000

    # PRIMARY PATH — DeepSeek-V4 cloud (chosen as default 2026-04-30).
    if DEEPSEEK_API_KEY:
        if is_reasoning:
            log.info("Router → DeepSeek-V4-pro (reasoner)")
            return Models.DS_REASONER, "deepseek", _deepseek()
        if is_long:
            log.info("Router → DeepSeek-V4-flash (long-ctx 1M)")
            return Models.DS_CHAT, "deepseek", _deepseek()
        log.info("Router → DeepSeek-V4-flash (default)")
        return Models.DS_CHAT, "deepseek", _deepseek()

    # FALLBACKS — only when DeepSeek key is missing or breaker is open.
    if GROQ_API_KEY and total_tokens < 3_000 and not is_reasoning:
        log.info("Router → Groq (no DS key — cloud fallback)")
        return Models.GROQ_LLAMA, "groq", _groq()

    if ollama_available():
        if is_reasoning:
            log.info("Router → Ollama deepseek-r1 (offline reasoner)")
            return Models.OLLAMA_REASONER, "ollama", _ollama()
        log.info("Router → Ollama qwen2.5:7b (offline fallback)")
        return Models.OLLAMA_CHAT, "ollama", _ollama()

    raise RuntimeError(
        "No LLM provider available. Set DEEPSEEK_API_KEY in ~/.aim_env "
        "(primary) or run Ollama locally as offline fallback."
    )

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
    """
    model, provider, client = _route(prompt, lang, system)

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]

    # Semantic LLM cache (opt-in via AIM_LLM_CACHE=1)
    try:
        from agents.llm_cache import maybe_cached, store as _cache_store
        cached = maybe_cached(prompt, system)
        if cached is not None:
            log.info(f"llm cache HIT (provider={provider}, model={model})")
            return cached
    except Exception:
        _cache_store = None  # type: ignore[assignment]

    for attempt in range(retries + 1):
        try:
            _breaker_for(provider).before_call()
            _limiter_for(provider).acquire()
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _breaker_for(provider).on_success()
            # feed adaptive limiter
            limiter = _limiter_for(provider)
            if hasattr(limiter, "record_success"):
                limiter.record_success()
            _log_cache_metrics(resp, provider, model)
            _record_token_usage(resp, provider, model)
            content = resp.choices[0].message.content.strip()
            if _cache_store:
                try:
                    _cache_store(prompt, system, content, model=model, provider=provider)
                except Exception:
                    pass
            return content

        except CircuitBreakerError as e:
            log.warning(f"[{provider}/{model}] circuit open, fallback: {e}")
            return _fallback(prompt, system, provider, e)

        except Exception as e:
            _breaker_for(provider).on_failure()
            limiter = _limiter_for(provider)
            if hasattr(limiter, "record_error"):
                limiter.record_error()
            _record_llm_error(provider, e)
            log.warning(f"[{provider}/{model}] attempt {attempt+1} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                return _fallback(prompt, system, provider, e)

    return "[AIM: LLM error]"


def _log_cache_metrics(resp, provider: str, model: str) -> None:
    """Surface DeepSeek prompt-cache stats from the response.

    DeepSeek auto-caches the prefix of every request that exceeds 64 tokens.
    Hits cost ~10% of regular input tokens. The hit count is reported in
    `usage.prompt_cache_hit_tokens` (cached) and `prompt_cache_miss_tokens`
    (not cached) when calling api.deepseek.com /chat/completions.

    Other providers don't expose this; they get a no-op log line.
    """
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        usage_dict = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage.__dict__)
        hit = usage_dict.get("prompt_cache_hit_tokens")
        miss = usage_dict.get("prompt_cache_miss_tokens")
        if hit is None and miss is None:
            return
        total = (hit or 0) + (miss or 0)
        ratio = (hit or 0) / total * 100 if total else 0
        log.info(
            f"[{provider}/{model}] cache: hit={hit or 0:,}  miss={miss or 0:,}  "
            f"ratio={ratio:.0f}%  (10% billed on hits)"
        )
    except Exception as e:
        log.debug(f"cache metrics extraction failed: {e}")


def _record_token_usage(resp, provider: str, model: str) -> None:
    """Push usage to Prometheus + cost_monitor if available."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    d = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage.__dict__)
    in_tok  = d.get("prompt_tokens", 0) or 0
    out_tok = d.get("completion_tokens", 0) or 0
    try:
        from agents.metrics import LLM_TOKENS_IN, LLM_TOKENS_OUT
        if in_tok:  LLM_TOKENS_IN.labels(provider=provider, model=model).inc(in_tok)
        if out_tok: LLM_TOKENS_OUT.labels(provider=provider, model=model).inc(out_tok)
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"prometheus push failed: {e}")
    try:
        from agents.cost_monitor import record as _cost_record
        _cost_record(model, in_tok, out_tok, provider=provider)
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"cost_monitor record failed: {e}")


def _record_llm_error(provider: str, err: Exception) -> None:
    try:
        from agents.metrics import LLM_ERRORS
        cause = type(err).__name__
        LLM_ERRORS.labels(provider=provider, cause=cause).inc()
    except ImportError:
        pass
    except Exception:
        pass


def _fallback(prompt: str, system: str, failed_provider: str, err: Exception) -> str:
    """Fallback: если основной провайдер упал — пробуем следующий."""
    log.warning(f"Fallback triggered, {failed_provider} failed: {err}")
    # Try smart fallback chain first (#62) — walks all configured tiers.
    try:
        from agents.smart_fallback import call_with_fallback
        return call_with_fallback(prompt, system=system,
                                  temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS)
    except Exception as sf_err:
        log.warning(f"smart_fallback exhausted: {sf_err}; falling back to legacy chain")

    chain = []
    # Cloud-first per user 2026-04-30: DeepSeek primary, Groq next, Ollama last.
    if failed_provider != "deepseek" and DEEPSEEK_API_KEY:
        chain.append((Models.DS_CHAT, _deepseek()))
    if failed_provider != "groq" and GROQ_API_KEY:
        chain.append((Models.GROQ_LLAMA, _groq()))
    if failed_provider != "ollama" and ollama_available():
        chain.append((Models.OLLAMA_CHAT, _ollama()))

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

def ask_critical(prompt: str, system: str = "", lang: str = None,
                 max_tokens: int = LLM_MAX_TOKENS) -> str:
    """Critical-tier reasoning. Priority chain (per user 2026-04-30):
        Claude Opus 4.7 → Gemini 2.5 Pro (free) → DeepSeek-V4-pro → Ollama r1.

    Use for: high-stakes decisions, ensemble adjudication, peer-review
    synthesis, manuscript critique, grant strategy. Highest quality, lowest
    hallucination rate available given configured keys.
    """
    if anthropic_available():
        out = _claude_chat(prompt, system=system, model=Models.CLAUDE_OPUS,
                           max_tokens=max_tokens, temperature=0)
        if out:
            return out
        log.warning("ask_critical: Claude unavailable, trying Gemini 2.5 Pro")
    if gemini_available():
        out = _gemini_chat(prompt, system=system, model=Models.GEMINI_PRO,
                           max_tokens=max_tokens, temperature=0)
        if out:
            return out
        log.warning("ask_critical: Gemini unavailable, falling back to DS-V4-pro")
    if DEEPSEEK_API_KEY:
        return ask_deep(prompt, system=system, lang=lang)
    return ask(prompt, system=system, lang=lang, max_tokens=max_tokens)


def ask_fast(prompt: str, lang: str = None) -> str:
    """Быстрый ответ. Приоритет (cloud-first per user 2026-04-30):
       Groq → DeepSeek-V4-flash → Ollama qwen2.5:3b (offline)."""
    # Groq is fastest for short prompts on cloud
    if GROQ_API_KEY and _count_tokens(prompt) < 3_000:
        try:
            _breaker_for("groq").before_call()
            _limiter_for("groq").acquire()
            resp = _groq().chat.completions.create(
                model=Models.GROQ_LLAMA_FAST,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=LLM_MAX_TOKENS,
            )
            _breaker_for("groq").on_success()
            return resp.choices[0].message.content.strip()
        except Exception as e:
            _breaker_for("groq").on_failure()
            log.warning(f"ask_fast: groq failed: {e}; trying DeepSeek")

    if DEEPSEEK_API_KEY:
        return ask(prompt, lang=lang, temperature=0.2)

    # Offline fallback
    if ollama_available():
        try:
            _breaker_for("ollama").before_call()
            _limiter_for("ollama").acquire()
            resp = _ollama().chat.completions.create(
                model=Models.OLLAMA_FAST,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=LLM_MAX_TOKENS,
            )
            _breaker_for("ollama").on_success()
            return resp.choices[0].message.content.strip()
        except Exception as e:
            _breaker_for("ollama").on_failure()
            log.warning(f"ask_fast: ollama also failed: {e}")
    return ask(prompt, lang=lang, temperature=0.2)

_LAST_REASONING: Optional[str] = None


def get_last_reasoning() -> Optional[str]:
    """Return DeepSeek-reasoner's hidden reasoning_content from the most recent
    ask_deep() call, or None if the previous call was not a reasoner call.

    DeepSeek R1 returns the chain-of-thought in `message.reasoning_content`.
    Other providers don't expose it; this function returns None for them.
    """
    return _LAST_REASONING


def ask_deep(prompt: str, system: str = "", lang: str = None) -> str:
    """Глубокий анализ — DeepSeek-V4-pro (cloud) → Ollama deepseek-r1 (local fallback).

    DeepSeek-V4-pro качественнее distilled deepseek-r1:7b, поэтому это первый
    выбор когда есть API-ключ. При отсутствии ключа — локальный reasoner.
    """
    global _LAST_REASONING
    _LAST_REASONING = None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Primary: cloud reasoner
    if DEEPSEEK_API_KEY:
        try:
            resp = _deepseek().chat.completions.create(
                model=Models.DS_REASONER,
                messages=messages,
                temperature=0,
                max_tokens=LLM_MAX_TOKENS,
            )
            _log_cache_metrics(resp, "deepseek", Models.DS_REASONER)
            msg = resp.choices[0].message
            rc = getattr(msg, "reasoning_content", None)
            if rc:
                _LAST_REASONING = rc
            return msg.content.strip()
        except Exception as e:
            log.warning(f"ask_deep DeepSeek failed: {e}; trying local reasoner")

    # Fallback: local distilled reasoner
    if ollama_available():
        try:
            resp = _ollama().chat.completions.create(
                model=Models.OLLAMA_REASONER,
                messages=messages,
                temperature=0,
                max_tokens=LLM_MAX_TOKENS,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning(f"ask_deep Ollama reasoner failed: {e}")

    return ask(prompt, system=system, lang=lang)


def ask_long(prompt: str, system: str = "", lang: str = None,
             max_tokens: int = None) -> str:
    """Длинный контекст / длинный output — DeepSeek V4 (1M context, 384K output).

    Use this when the prompt is large (e.g. full document audit) OR when the
    expected output is long (book-chunk synthesis). Default raises max_tokens
    to LLM_MAX_TOKENS_LONG. Cloud-first because Ollama context windows
    (typically 32K-128K) cannot fit truly long inputs.

    Falls back to ask() (which prefers Ollama) if DeepSeek key missing.
    """
    if DEEPSEEK_API_KEY:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = _deepseek().chat.completions.create(
                model=Models.DS_CHAT,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=max_tokens or LLM_MAX_TOKENS_LONG,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning(f"ask_long DeepSeek failed: {e}; falling back to router")
    return ask(prompt, system=system, lang=lang,
               max_tokens=max_tokens or LLM_MAX_TOKENS_LONG)


def ask_multilang(prompt: str, lang: str) -> str:
    """Многоязычный ответ — DeepSeek (Qwen убран). DeepSeek хорошо работает с RU/EN/FR/ES/KA/AR/ZH."""
    return ask(prompt, lang=lang)


def stream_deepseek(prompt: str, system: str = "", model: Optional[str] = None,
                    temperature: float = LLM_TEMPERATURE, max_tokens: int = LLM_MAX_TOKENS):
    """Yield tokens from DeepSeek as they arrive (streaming).

    Usage:
        for chunk in stream_deepseek(prompt, system=SYSTEM_PROMPT_RU):
            print(chunk, end="", flush=True)
    """
    if not DEEPSEEK_API_KEY:
        yield ask(prompt, system=system)
        return

    _breaker_for("deepseek").before_call()
    _limiter_for("deepseek").acquire()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        stream = _deepseek().chat.completions.create(
            model=model or Models.DS_CHAT,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for event in stream:
            try:
                delta = event.choices[0].delta
                token = getattr(delta, "content", None)
                if token:
                    yield token
            except (IndexError, AttributeError):
                continue
        _breaker_for("deepseek").on_success()
    except Exception as e:
        _breaker_for("deepseek").on_failure()
        _record_llm_error("deepseek", e)
        log.warning(f"stream failed, falling back to non-stream: {e}")
        yield ask(prompt, system=system, temperature=temperature, max_tokens=max_tokens)


def warmup_deepseek_cache(prefix: str, max_tokens: int = 4) -> bool:
    """Send a tiny request whose prompt prefix matches what subsequent calls
    will reuse; DeepSeek's prefix cache will then serve the shared prefix at
    ~10% billing on the next real call.

    Returns True if the warmup call succeeded.
    """
    if not DEEPSEEK_API_KEY:
        return False
    if len(prefix) < 200:
        return False  # cache only kicks in past 64 tokens; 200 chars is the floor
    try:
        resp = _deepseek().chat.completions.create(
            model=Models.DS_CHAT,
            messages=[
                {"role": "system", "content": "Ты агент AIM. Отвечай одним словом."},
                {"role": "user",   "content": prefix + "\n\nИГНОРИРУЙ. ОТВЕТЬ: OK"},
            ],
            temperature=0,
            max_tokens=max_tokens,
        )
        _log_cache_metrics(resp, "deepseek", Models.DS_CHAT)
        log.info("DeepSeek prefix cache warmup OK")
        return True
    except Exception as e:
        log.warning(f"warmup failed: {e}")
        return False


# ── Статус провайдеров ────────────────────────────────────────────────────────

def providers_status() -> dict:
    """Какие LLM-провайдеры доступны."""
    has_claude  = anthropic_available()
    has_gemini  = gemini_available()
    has_ds      = bool(DEEPSEEK_API_KEY)
    has_ollama  = ollama_available()
    has_groq    = bool(GROQ_API_KEY)
    return {
        "anthropic": has_claude,
        "gemini":    has_gemini,
        "deepseek":  has_ds,
        "groq":      has_groq,
        "ollama":    has_ollama,
        "ollama_url": Endpoints.OLLAMA,
        "tier_chain": {
            "critical":   ("claude-opus-4-7"     if has_claude
                           else Models.GEMINI_PRO if has_gemini
                           else Models.DS_REASONER if has_ds
                           else Models.OLLAMA_REASONER),
            "reasoning":  (Models.DS_REASONER    if has_ds
                           else "claude-opus-4-7" if has_claude
                           else Models.GEMINI_PRO if has_gemini
                           else Models.OLLAMA_REASONER),
            "default":    (Models.DS_CHAT        if has_ds
                           else Models.GEMINI_FLASH if has_gemini
                           else Models.OLLAMA_CHAT if has_ollama
                           else Models.GROQ_LLAMA),
            "fast":       (Models.GROQ_LLAMA_FAST if has_groq
                           else Models.OLLAMA_FAST if has_ollama
                           else Models.DS_CHAT),
        },
    }
