"""agents/ensemble.py — multi-model ensemble with adjudication.

For high-stakes decisions ask N models in parallel; if they agree, return
the consensus; if they disagree, route the divergence to the highest-tier
adjudicator (Claude Opus 4.7 if available, else DeepSeek-V4-pro).

This is the single best mechanism we have to *exceed* the quality of any
one provider's reasoning: cross-checking forces models to agree on the
same answer or be surfaced for human review.

Public API:
    ensemble_ask(prompt, *, system="", tiers=None, n=3) → dict
        returns {
            "consensus":   bool,
            "answer":      str,         # final answer (consensus or adjudicated)
            "individual":  [(model, answer), ...],
            "adjudicator": str | None,  # name of the tie-breaker if used
            "agreement":   float,       # 0..1 pairwise similarity
        }

    is_critical(prompt) → bool      # heuristic trigger
"""
from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from llm import (
    ask, ask_deep, ask_critical,
    _claude_chat, _gemini_chat, _deepseek, _ollama,
    anthropic_available, gemini_available, ollama_available,
    DEEPSEEK_API_KEY, GROQ_API_KEY,
)
from config import Models

log = logging.getLogger("aim.ensemble")


# ── Critical-decision heuristic ────────────────────────────────────────────


_CRITICAL_PATTERNS = (
    r"\bgrant\b", r"\bsubmission\b", r"\bdiagnos[ie]s\b", r"\btreatment\b",
    r"\bpatient\b", r"\bclinical\b", r"\bsurger", r"\bdose", r"\bcontraindicat",
    r"\bpublish\b", r"\baccept\b.*reject", r"\baudit\b",
    r"\bbillion\b|\bmillion\b", r"\bsign\b.*contract", r"\bdeadline\b.*today",
    r"\bdiagn",                                                  # RU
    r"\bлеч[еи]", r"\bпациент", r"\bоперац", r"\bдоз[ау]",
    r"\bконтракт", r"\bподпис", r"\bдедлайн",
)
_CRITICAL_RE = re.compile("|".join(_CRITICAL_PATTERNS), re.IGNORECASE)


def is_critical(prompt: str) -> bool:
    """Heuristic: is this prompt likely a high-stakes decision?"""
    return bool(_CRITICAL_RE.search(prompt))


# ── Per-tier callers ───────────────────────────────────────────────────────


def _call_claude(prompt: str, system: str) -> str:
    if not anthropic_available():
        return ""
    return _claude_chat(prompt, system=system, model=Models.CLAUDE_OPUS,
                        temperature=0)


def _call_gemini(prompt: str, system: str) -> str:
    if not gemini_available():
        return ""
    return _gemini_chat(prompt, system=system, model=Models.GEMINI_PRO,
                        temperature=0)


def _call_ds_pro(prompt: str, system: str) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    try:
        client = _deepseek()
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=Models.DS_REASONER, messages=msgs,
            temperature=0, max_tokens=4096)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"DS-pro call failed: {e}")
        return ""


def _call_ds_flash(prompt: str, system: str) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    try:
        client = _deepseek()
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=Models.DS_CHAT, messages=msgs,
            temperature=0, max_tokens=4096)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"DS-flash call failed: {e}")
        return ""


def _call_ollama(prompt: str, system: str) -> str:
    if not ollama_available():
        return ""
    try:
        client = _ollama()
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=Models.OLLAMA_CHAT, messages=msgs,
            temperature=0, max_tokens=4096)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"Ollama call failed: {e}")
        return ""


_TIER_CALLERS: dict[str, Callable[[str, str], str]] = {
    "claude":   _call_claude,
    "gemini":   _call_gemini,
    "ds-pro":   _call_ds_pro,
    "ds-flash": _call_ds_flash,
    "ollama":   _call_ollama,
}


def _default_tiers() -> list[str]:
    """Pick up to 3 distinct providers in priority order, prioritising
    cross-vendor diversity (Anthropic + Google + DeepSeek if available)."""
    out = []
    if anthropic_available(): out.append("claude")
    if gemini_available():    out.append("gemini")
    if DEEPSEEK_API_KEY:
        out.append("ds-pro")
        if len(out) < 2:
            out.append("ds-flash")
    if ollama_available() and len(out) < 3:
        out.append("ollama")
    return out[:3]


# ── Agreement scoring ──────────────────────────────────────────────────────


def _normalize(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower())
    s = re.sub(r"[^\w\s]", "", s)
    return s


def _shingle_set(s: str, k: int = 5) -> set[str]:
    toks = _normalize(s).split()
    if len(toks) < k:
        return {" ".join(toks)}
    return {" ".join(toks[i:i+k]) for i in range(len(toks) - k + 1)}


def _jaccard(a: str, b: str) -> float:
    sa, sb = _shingle_set(a), _shingle_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _agreement_score(answers: list[str]) -> float:
    """Average pairwise Jaccard over k-shingles. 1.0 = identical, 0 = unrelated."""
    answers = [a for a in answers if a.strip()]
    if len(answers) < 2:
        return 1.0 if answers else 0.0
    n = len(answers)
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += _jaccard(answers[i], answers[j])
            pairs += 1
    return total / max(pairs, 1)


# ── Main ────────────────────────────────────────────────────────────────────


_AGREEMENT_THRESHOLD = float(os.getenv("AIM_ENSEMBLE_AGREE", "0.35"))


def ensemble_ask(prompt: str, *, system: str = "",
                 tiers: Optional[list[str]] = None,
                 force_adjudicator: bool = False,
                 timeout: float = 120.0) -> dict:
    """Run prompt across N tiers in parallel; adjudicate on disagreement.

    Returns a dict with `answer`, `consensus`, `individual`, `adjudicator`,
    `agreement`. Caller can inspect which model agreed or how much they
    diverged.
    """
    tiers = tiers or _default_tiers()
    if not tiers:
        out = ask(prompt, system=system)
        return {"answer": out, "consensus": True, "individual": [("ask", out)],
                "adjudicator": None, "agreement": 1.0}

    individual: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(tiers)) as pool:
        futs = {pool.submit(_TIER_CALLERS[t], prompt, system): t for t in tiers}
        for fut in as_completed(futs, timeout=timeout):
            t = futs[fut]
            try:
                ans = fut.result()
            except Exception as e:
                log.warning(f"tier {t} raised: {e}")
                ans = ""
            individual.append((t, ans))

    answers = [a for _, a in individual if a.strip()]
    score = _agreement_score(answers)
    consensus = score >= _AGREEMENT_THRESHOLD and not force_adjudicator

    if consensus and answers:
        return {
            "answer": max(answers, key=len),
            "consensus": True,
            "individual": individual,
            "adjudicator": None,
            "agreement": round(score, 3),
        }

    # Disagreement (or forced) → route to adjudicator (highest-tier available)
    blocks = []
    for tier, ans in individual:
        if ans.strip():
            blocks.append(f"=== {tier} answer ===\n{ans}\n")
    adj_prompt = (
        "Multiple models answered the same question with conflicting outputs. "
        "Read all answers, identify points of agreement and divergence, then "
        "produce the best consolidated answer that resolves the disagreement. "
        "Be explicit about which claims you accept, reject, or refine.\n\n"
        f"=== ORIGINAL QUESTION ===\n{prompt}\n\n"
        + "\n".join(blocks)
    )
    adjudicator = "claude" if anthropic_available() else \
                  "gemini" if gemini_available() else \
                  "ds-pro" if DEEPSEEK_API_KEY else \
                  "ollama"
    final = ask_critical(adj_prompt, system=system) or _TIER_CALLERS[adjudicator](adj_prompt, system)
    return {
        "answer": final or (answers[0] if answers else "[ensemble: no model returned an answer]"),
        "consensus": False,
        "individual": individual,
        "adjudicator": adjudicator,
        "agreement": round(score, 3),
    }
