"""
AIM v7.1 — Hook system
=======================

Lightweight event registry, вдохновлённый Personal AI Infrastructure (Miessler).
Позволяет подписываться на ключевые события AIM без модификации основного кода.

События:
    on_lab_critical     — Lab interpretation выявил critical value (e.g. K+ > 6.5)
    on_kernel_decision  — kernel.decide() завершил scoring + выбрал alternative
    on_session_end      — сессия закрыта (для миграции hot→warm memory)
    on_intake_pdf       — новый файл попал в Patients/INBOX/
    on_pre_commit       — git pre-commit (kernel.py sync, AI_LOG.md flush)

Использование:
    from agents.hooks import register, fire, HOOK_LAB_CRITICAL

    @register(HOOK_LAB_CRITICAL)
    def alert_telegram(payload):
        # payload = {"patient_id", "analyte", "value", "threshold", "lang"}
        send_telegram_alert(payload)

    # внутри labs.py:
    fire(HOOK_LAB_CRITICAL, {"patient_id": pid, "analyte": "K+", ...})

Принципы:
    - Hook handlers выполняются sync, в порядке регистрации
    - Exception в handler логируется, но не прерывает цепочку
    - fire() возвращает list результатов (None если handler ничего не вернул)
    - Регистрация идемпотентна (та же функция не дублируется)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger("aim.hooks")

# ── Имена событий (константы для type-safety) ─────────────────────────────────

HOOK_LAB_CRITICAL    = "on_lab_critical"
HOOK_KERNEL_DECISION = "on_kernel_decision"
HOOK_SESSION_END     = "on_session_end"
HOOK_INTAKE_PDF      = "on_intake_pdf"
HOOK_PRE_COMMIT      = "on_pre_commit"

KNOWN_HOOKS = {
    HOOK_LAB_CRITICAL,
    HOOK_KERNEL_DECISION,
    HOOK_SESSION_END,
    HOOK_INTAKE_PDF,
    HOOK_PRE_COMMIT,
}

# ── Реестр ─────────────────────────────────────────────────────────────────────

_handlers: dict[str, list[Callable[[dict], Any]]] = defaultdict(list)


def register(event: str) -> Callable[[Callable], Callable]:
    """Декоратор регистрации handler-а на событие.

    >>> @register(HOOK_LAB_CRITICAL)
    ... def my_handler(payload): ...
    """
    if event not in KNOWN_HOOKS:
        raise ValueError(f"Unknown hook: {event}. Known: {sorted(KNOWN_HOOKS)}")

    def decorator(fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
        if fn not in _handlers[event]:
            _handlers[event].append(fn)
            log.debug("registered %s for %s", fn.__name__, event)
        return fn
    return decorator


def unregister(event: str, fn: Callable) -> bool:
    """Снять handler. Возвращает True если был зарегистрирован."""
    if fn in _handlers[event]:
        _handlers[event].remove(fn)
        return True
    return False


def fire(event: str, payload: dict | None = None) -> list[Any]:
    """Запустить всех handler-ов события. Не падает на исключениях handler-а."""
    if event not in KNOWN_HOOKS:
        log.warning("fire() called with unknown event: %s", event)
        return []
    payload = payload or {}
    results: list[Any] = []
    for fn in _handlers[event]:
        try:
            results.append(fn(payload))
        except Exception as e:
            log.exception("hook handler %s failed for %s: %s", fn.__name__, event, e)
            results.append(None)
    return results


def list_handlers(event: str | None = None) -> dict[str, list[str]]:
    """Diagnostic: какие handler-ы зарегистрированы. Для отладки."""
    if event:
        return {event: [fn.__name__ for fn in _handlers[event]]}
    return {ev: [fn.__name__ for fn in _handlers[ev]] for ev in KNOWN_HOOKS}


def clear(event: str | None = None) -> None:
    """Очистить handler-ы (главным образом для тестов)."""
    if event:
        _handlers[event].clear()
    else:
        _handlers.clear()
