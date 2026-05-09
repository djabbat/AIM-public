"""agents/permission.py — interactive permission broker (G3, 2026-05-02).

The kernel's L_CONSENT is a hard binary: action allowed only when
context["user_confirmed"] is True. That makes it impossible for AIM to
ASK the user at the moment of side-effect — it just refuses. This module
adds an opt-in interactive layer:

    from agents.permission import request as request_permission
    granted = request_permission(
        action_type="email_send",
        scope="djabbat@gmail.com → tinatin@example.com",
        preview="Subject: Reminder\\n\\nDear Tinatin, ...",
        blast_radius="external — visible to third party",
    )

Behaviour:
    * Returns True/False.
    * Caches `(action_type, scope) → (decision, expires_at)` for `ttl_minutes`
      so repeated similar actions in one session don't spam the user.
    * Persistence: per-process dict + JSONL audit log
      (`~/.cache/aim/permission_log.jsonl`) for retrospective review.
    * Channel resolution: TUI (stdin) by default. Set `AIM_PERMISSION_CHANNEL=tg`
      to route through a TelegramConfirmationBroker (separate module, not
      shipped here — has to share the bot's event loop).
    * Override flags (in priority order):
        - `AIM_AUTO_CONSENT=1`            → grant everything (CI/cron).
        - `AIM_NONINTERACTIVE=1`          → never prompt, deny by default.
        - explicit `user_confirmed=True`  → granted (skip prompt).

The kernel.evaluate_l_consent integration is opt-in: set
`AIM_INTERACTIVE_CONSENT=1`. Without that, behaviour is unchanged
(callers must pass user_confirmed=True or the call is refused).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.permission")

# Default cache TTL for granted decisions. Denials are NOT cached — we
# re-prompt on next call so a user mistake can be corrected.
_DEFAULT_TTL_S = 15 * 60

# Stdin prompt timeout. After this we treat silence as deny.
_PROMPT_TIMEOUT_S = 60.0

_CACHE: dict[tuple[str, str], tuple[bool, float]] = {}
_CACHE_LOCK = threading.RLock()

_AUDIT_PATH = Path.home() / ".cache" / "aim" / "permission_log.jsonl"


@dataclasses.dataclass(frozen=True)
class Decision:
    granted: bool
    reason: str
    cached: bool
    via: str   # "auto_consent", "noninteractive_deny", "tui", "tg", "cache",
               # "user_confirmed_flag", "timeout_deny", "fallback_block"


def _audit(action_type: str, scope: str, decision: Decision) -> None:
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "action_type": action_type,
                "scope": scope,
                "granted": decision.granted,
                "via": decision.via,
                "reason": decision.reason,
            }) + "\n")
    except OSError as e:
        log.warning("permission audit log write failed: %s", e)


def _cache_get(action_type: str, scope: str) -> Optional[bool]:
    with _CACHE_LOCK:
        v = _CACHE.get((action_type, scope))
        if v is None:
            return None
        granted, expires = v
        if time.time() >= expires:
            _CACHE.pop((action_type, scope), None)
            return None
        return granted


def _cache_put(action_type: str, scope: str, granted: bool, ttl_s: float) -> None:
    with _CACHE_LOCK:
        _CACHE[(action_type, scope)] = (granted, time.time() + ttl_s)


def _read_stdin_with_timeout(prompt: str, timeout_s: float) -> Optional[str]:
    """Read one line from stdin with a timeout. Returns None on timeout
    or when stdin is not a TTY."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    print(prompt, end="", flush=True)
    import selectors
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin, selectors.EVENT_READ)
    events = sel.select(timeout_s)
    sel.close()
    if not events:
        print()  # newline so subsequent output lands on a fresh line
        return None
    return sys.stdin.readline().rstrip("\n")


def _prompt_tui(action_type: str, scope: str, preview: str,
                blast_radius: str) -> tuple[bool, str]:
    banner = (
        "\n┌─ AIM permission request ─────────────────────────────────────\n"
        f"│ action:  {action_type}\n"
        f"│ scope:   {scope}\n"
        f"│ blast:   {blast_radius}\n"
        "│ preview:\n"
    )
    for line in (preview or "(no preview)").splitlines()[:8]:
        banner += f"│   {line[:200]}\n"
    banner += "└──────────────────────────────────────────────────────────────\n"
    print(banner, file=sys.stderr)
    answer = _read_stdin_with_timeout(
        f"Allow [a] / Deny [d] / Always-allow this kind for 15m [A]"
        f" / Always-deny [D] (timeout {int(_PROMPT_TIMEOUT_S)}s, default deny): ",
        _PROMPT_TIMEOUT_S,
    )
    if answer is None:
        return False, "tui timeout / non-tty"
    a = answer.strip()
    if a == "a":
        return True, "tui allow"
    if a == "A":
        return True, "tui always-allow (15m)"
    if a == "d":
        return False, "tui deny"
    if a == "D":
        return False, "tui always-deny (15m)"
    return False, f"tui invalid input {answer!r} → deny"


def request(action_type: str, scope: str, preview: str = "",
            blast_radius: str = "external",
            ttl_minutes: int = 15) -> Decision:
    """Resolve a permission request through cache → env overrides → channel.

    Returns a Decision (boolean is on .granted)."""
    ttl_s = max(1, int(ttl_minutes)) * 60.0

    # 1. Hard overrides via env.
    if os.environ.get("AIM_AUTO_CONSENT") == "1":
        d = Decision(True, "AIM_AUTO_CONSENT=1", False, "auto_consent")
        _audit(action_type, scope, d)
        return d
    if os.environ.get("AIM_NONINTERACTIVE") == "1":
        d = Decision(False, "AIM_NONINTERACTIVE=1 → deny", False,
                     "noninteractive_deny")
        _audit(action_type, scope, d)
        return d

    # 2. Cache.
    cached = _cache_get(action_type, scope)
    if cached is not None:
        d = Decision(cached, "cached", True, "cache")
        _audit(action_type, scope, d)
        return d

    # 3. Channel.
    channel = os.environ.get("AIM_PERMISSION_CHANNEL", "tui").lower()
    if channel == "tui":
        granted, reason = _prompt_tui(action_type, scope, preview, blast_radius)
        via = "tui"
    elif channel == "tg":
        # Telegram broker is wired up out-of-band; we attempt to import a
        # broker the bot has registered. If it isn't loaded, fall back to
        # deny (visible failure beats silent grant).
        try:
            from agents.telegram_extras import permission_broker  # type: ignore
            granted, reason = permission_broker.ask(
                action_type, scope, preview, blast_radius,
                timeout_s=_PROMPT_TIMEOUT_S,
            )
            via = "tg"
        except Exception as e:
            granted, reason = False, f"tg channel unavailable: {e}"
            via = "fallback_block"
    else:
        granted, reason = False, f"unknown channel {channel!r}"
        via = "fallback_block"

    # Cache only positive grants & "always-X" decisions for the TTL.
    if granted or "always" in reason:
        _cache_put(action_type, scope, granted, ttl_s)

    d = Decision(granted, reason, False, via)
    _audit(action_type, scope, d)
    return d


def clear_cache() -> None:
    """Drop all cached decisions. Useful for tests and `/permissions reset`."""
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["request", "clear_cache", "Decision"]
