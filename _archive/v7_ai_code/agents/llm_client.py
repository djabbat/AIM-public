"""agents/llm_client.py — opt-in HTTP client to the `aim-llm` Rust
service (Phase 5b, 2026-05-07).

When `AIM_LLM_HTTP_URL=http://127.0.0.1:8770` is set, this module
becomes a drop-in replacement for the deterministic core of `llm.py`
(ask / ask_fast / ask_deep / ask_long / ask_critical). All
provider-specific HTTP, retry, rate-limit, and circuit-breaker logic
runs in Rust now.

The Python `llm.py` keeps its 1017 LoC of legacy Python implementation
as a fallback path — when `AIM_LLM_HTTP_URL` is unset OR the service
is unreachable, callers fall back to the original code.

Public API (matches `llm.py`):
    ask(prompt: str, *, system: str = "") -> str
    ask_fast(prompt, *, system="") -> str
    ask_deep(prompt, *, system="") -> str
    ask_long(prompt, *, system="") -> str
    ask_critical(prompt, *, system="") -> str
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error

log = logging.getLogger("aim.llm_client")


def _base_url() -> str:
    """Read at call time so tests can `monkeypatch.setenv(...)`."""
    return os.environ.get("AIM_LLM_HTTP_URL", "").rstrip("/")


def _timeout() -> float:
    return float(os.environ.get("AIM_LLM_HTTP_TIMEOUT", "60"))


def is_enabled() -> bool:
    """True iff the HTTP shim should be used in front of llm.py."""
    return bool(_base_url())


def _post_chat(prompt: str, *, system: str = "", tier: str = "default") -> str:
    """Send a /v1/chat request to aim-llm and return reply text.

    Raises on transport / 5xx errors so the caller can fall back to
    legacy Python implementation.
    """
    base = _base_url()
    if not base:
        raise RuntimeError("AIM_LLM_HTTP_URL not set")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"messages": messages, "tier": tier}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/v1/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Surface body so the caller can decide on fallback.
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        raise RuntimeError(f"aim-llm HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"aim-llm unreachable: {e.reason}") from e
    return str(payload.get("reply", ""))


def ask(prompt: str, *, system: str = "") -> str:
    return _post_chat(prompt, system=system, tier="default")


def ask_fast(prompt: str, *, system: str = "") -> str:
    return _post_chat(prompt, system=system, tier="fast")


def ask_deep(prompt: str, *, system: str = "") -> str:
    return _post_chat(prompt, system=system, tier="deep")


def ask_long(prompt: str, *, system: str = "") -> str:
    return _post_chat(prompt, system=system, tier="long")


def ask_critical(prompt: str, *, system: str = "") -> str:
    return _post_chat(prompt, system=system, tier="critical")


def health() -> dict:
    """Probe the service. Returns parsed JSON or raises."""
    base = _base_url()
    if not base:
        raise RuntimeError("AIM_LLM_HTTP_URL not set")
    req = urllib.request.Request(f"{base}/health")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def providers() -> list[dict]:
    """List provider readiness from the service."""
    base = _base_url()
    if not base:
        raise RuntimeError("AIM_LLM_HTTP_URL not set")
    req = urllib.request.Request(f"{base}/v1/providers")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))
