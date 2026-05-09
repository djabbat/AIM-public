"""agents/user_keys.py — Per-user LLM provider keys.

Architecture rule (per project memory `feedback_per_user_deepseek_key`):
each AIM user holds their own DeepSeek / Groq / Anthropic / Gemini API key.
Billing goes to that user's provider account, never to a shared pool.

Two layers of key resolution, in priority order:

  1. **Thread-local override** (set via `with user_context(uid)`)
     — used by the Telegram bot and the multi-tenant web API to scope a
     single request to a single user's keys.

  2. **Process env** (`DEEPSEEK_API_KEY` from `~/.aim_env`)
     — the default for the local CLI, where the OS user == the AIM user.

Storage of per-user keys (when not coming from `~/.aim_env`):
  ``~/.cache/aim/user_keys.json`` — owner-only chmod 0600. Keys are stored
  plaintext on disk just like ``~/.aim_env`` is — same trust boundary
  (the local user's account). Rotate by calling :func:`set_keys` again or
  :func:`clear_keys`.

The Hub MUST NEVER store these keys. The hub only knows users + tokens +
audit; LLM credentials never cross the network.

Public API:
  - ``get_key(provider)`` — current effective key for the active context
  - ``set_keys(uid, **keys)`` — persist keys for a user-id (Telegram id, hub
    user-id, or the literal ``"local"`` for the CLI default)
  - ``clear_keys(uid, *providers)`` — delete some/all keys
  - ``which_provider_keys(uid)`` — list of providers with a stored key
  - ``user_context(uid)`` — context-manager that scopes :func:`get_key`
    lookups to ``uid``'s stored keys for the duration of the with-block

Provider names: ``"deepseek"``, ``"groq"``, ``"anthropic"``, ``"gemini"``.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

PROVIDERS = ("deepseek", "groq", "anthropic", "gemini")
ENV_VARS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# On-disk store: per-user keys for non-CLI tenants (Telegram, web).
_STORE_PATH = Path(os.getenv("AIM_USER_KEYS_FILE",
                             str(Path.home() / ".cache" / "aim" / "user_keys.json")))
_STORE_LOCK = threading.Lock()

# Active per-thread tenant. None → fall through to env (single-user default).
_LOCAL = threading.local()


# ── On-disk store ──────────────────────────────────────────────────────────


def _load_store() -> dict[str, dict[str, str]]:
    if not _STORE_PATH.exists():
        return {}
    try:
        with _STORE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(data: dict[str, dict[str, str]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(_STORE_PATH)
    try:
        os.chmod(_STORE_PATH, 0o600)
    except OSError:
        pass


# ── Mutators (call from CLI / Telegram /setkey / web admin) ─────────────────


def set_keys(uid: str, **keys: str) -> None:
    """Persist one or more provider keys for ``uid``.

    >>> set_keys("tg:12345", deepseek="sk-...", groq="gsk-...")

    Empty values are silently ignored (use :func:`clear_keys` to remove).
    Unknown providers raise :class:`ValueError`.
    """
    uid = str(uid)
    bad = [p for p in keys if p not in PROVIDERS]
    if bad:
        raise ValueError(f"unknown provider(s): {bad}; allowed = {PROVIDERS}")
    with _STORE_LOCK:
        data = _load_store()
        record = data.get(uid, {})
        for prov, key in keys.items():
            if key:
                record[prov] = key
        if record:
            data[uid] = record
        _save_store(data)


def clear_keys(uid: str, *providers: str) -> None:
    """Delete stored keys. With no providers — delete all keys for ``uid``."""
    uid = str(uid)
    with _STORE_LOCK:
        data = _load_store()
        if uid not in data:
            return
        if not providers:
            data.pop(uid, None)
        else:
            for p in providers:
                data[uid].pop(p, None)
            if not data[uid]:
                data.pop(uid, None)
        _save_store(data)


def which_provider_keys(uid: str) -> list[str]:
    """Return the list of providers with a stored key for ``uid``."""
    uid = str(uid)
    with _STORE_LOCK:
        return sorted(_load_store().get(uid, {}).keys())


def get_user_keys(uid: str) -> dict[str, str]:
    """Return all stored keys for ``uid`` (do NOT log this!)."""
    uid = str(uid)
    with _STORE_LOCK:
        return dict(_load_store().get(uid, {}))


# ── Resolver (called from llm.py) ───────────────────────────────────────────


def get_key(provider: str) -> str:
    """Return the effective key for ``provider`` for the active context.

    Priority:
      1. Thread-local override (set via :func:`user_context`)
      2. ``$DEEPSEEK_API_KEY`` etc. from process env

    Empty string when nothing is configured. Callers should treat empty as
    "provider unavailable, try the next tier".
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}; allowed = {PROVIDERS}")
    override = getattr(_LOCAL, "keys", None)
    if override and override.get(provider):
        return override[provider]
    return os.getenv(ENV_VARS[provider], "")


@contextmanager
def user_context(uid: Optional[str]) -> Iterator[None]:
    """Scope :func:`get_key` lookups to ``uid``'s stored keys.

    >>> with user_context("tg:12345"):
    ...     reply = ask("hello")  # uses tg:12345's DeepSeek key

    ``uid=None`` is a no-op (env-only resolution), used when the bot has no
    record of the Telegram user yet — the ask will fall through to the env
    and may return an "no key" error to the user, prompting them to /setkey.
    """
    if uid is None:
        yield
        return
    uid = str(uid)
    keys = get_user_keys(uid)
    prev = getattr(_LOCAL, "keys", None)
    _LOCAL.keys = keys
    try:
        yield
    finally:
        if prev is None:
            try:
                del _LOCAL.keys
            except AttributeError:
                pass
        else:
            _LOCAL.keys = prev


# ── Diagnostics ─────────────────────────────────────────────────────────────


def store_path() -> Path:
    """Where the on-disk store lives."""
    return _STORE_PATH


def all_user_ids() -> list[str]:
    """List of uids with at least one stored key."""
    with _STORE_LOCK:
        return sorted(_load_store().keys())
