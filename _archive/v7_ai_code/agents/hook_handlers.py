"""agents/hook_handlers.py — registration glue для hooks (HW1, 2026-05-06).

Регистрирует handlers для HOOK_* событий из `agents/hooks.py` при импорте
модуля. Каждый handler — короткий glue, который вызывает existing Python
модули (`agents/notify.py`, `agents/escalation_engine.py`, `db.py`).

Принципы:
    1. Никакой новой бизнес-логики — только маршрутизация.
    2. Идемпотентная регистрация (один и тот же handler не дублируется).
    3. Auto-register на import; для тестов / специальных запусков —
       env `AIM_NO_AUTO_HOOKS=1` блокирует регистрацию.

Зарегистрированные handlers (см. AUDIT_PROJECT_MANAGER_2026-05-06.md §3.3):
    HOOK_LAB_CRITICAL  → alert_lab_critical    (Telegram+log, 4h dedup)
    HOOK_SESSION_END   → archive_on_session_end (db.archive_old_events)

Намеренно НЕ зарегистрированы (точки расширения, fire() есть, handler нет):
    HOOK_KERNEL_DECISION  — ждёт AI subproject pattern miner / calibration
    HOOK_INTAKE_PDF       — ждёт Phase D patient_comms / dashboard
    HOOK_PRE_COMMIT       — ждёт интеграции с git pre-commit hook
"""
from __future__ import annotations

import hashlib
import logging
import os

from agents.hooks import (
    HOOK_LAB_CRITICAL,
    HOOK_SESSION_END,
    register,
)

log = logging.getLogger("aim.hook_handlers")


# ── HOOK_LAB_CRITICAL — Telegram + log alert with 4h dedup ──────────


def alert_lab_critical(payload: dict) -> None:
    """Telegram + log alert при detection critical lab values.

    payload schema (Q4.B):
        {patient_id: str, red_flags: list[str], lang: str}

    Dedup (Q5.B): 4h fingerprint = sha1(patient_id + sorted(red_flags))[:12].
    Проверяется через `escalation_engine._was_recently_dispatched`,
    audit через `escalation_engine._audit` (объединяет lab_critical с
    project escalations в одном `~/.cache/aim/escalation.jsonl`).
    """
    patient_id = str(payload.get("patient_id") or "?")
    red_flags = list(payload.get("red_flags") or [])
    if not red_flags:
        return

    fp = hashlib.sha1(
        (patient_id + "|" + "|".join(sorted(red_flags))).encode("utf-8")
    ).hexdigest()[:12]

    try:
        from agents.escalation_engine import (
            Alert,
            _audit as _esc_audit,
            _was_recently_dispatched,
        )
    except Exception as e:
        log.warning("escalation_engine import failed: %s", e)
        return

    if _was_recently_dispatched(fp, cooldown_hours=4.0):
        log.debug("HOOK_LAB_CRITICAL %s suppressed (4h cooldown)", fp)
        return

    subject = f"⚠️ LAB CRITICAL — {patient_id}"
    detail = "\n".join(f"• {f}" for f in red_flags)

    try:
        from agents.notify import notify as _notify
        _notify(
            detail,
            subject=subject,
            channels=("telegram", "log"),
            level="critical",
            source="hook_lab_critical",
            dedup_key=f"lab_critical:{fp}",
        )
    except Exception as e:
        log.warning("notify failed for HOOK_LAB_CRITICAL: %s", e)

    alert = Alert(
        project=patient_id,
        rule="lab_critical",
        action="telegram_alert",
        subject=subject,
        detail=detail,
        fingerprint=fp,
    )
    try:
        _esc_audit(alert)
    except Exception as e:
        log.warning("escalation audit failed: %s", e)


# ── HOOK_SESSION_END — auto-archive WARM→COLD events ────────────────


def archive_on_session_end(payload: dict) -> None:
    """Запускает `db.archive_old_events()` при закрытии session.

    `archive_old_events()` идемпотентен (проверяет `original_id + ts`
    в `ai_events_archive` перед INSERT). Каждое закрытие сессии — шанс
    подвинуть WARM (>7d) → COLD archive без отдельного cron.
    """
    try:
        from db import archive_old_events
        n = archive_old_events()
        if n:
            log.debug("archive_on_session_end moved %d events", n)
    except Exception as e:
        log.warning("archive_old_events failed: %s", e)


# ── Bootstrap ───────────────────────────────────────────────────────


_REGISTERED = False


def register_all() -> None:
    """Идемпотентная регистрация handlers.

    Вызывается из `agents/__init__.py` при импорте, если не задано
    `AIM_NO_AUTO_HOOKS=1`. Безопасно вызывать многократно.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    register(HOOK_LAB_CRITICAL)(alert_lab_critical)
    register(HOOK_SESSION_END)(archive_on_session_end)
    _REGISTERED = True
    log.debug("hook_handlers registered")


def reset_for_tests() -> None:
    """Сброс флага регистрации — для unit-тестов (после `hooks.clear()`).

    Не вызывает `hooks.clear()` сам — оставляет это на совести fixture'ы.
    """
    global _REGISTERED
    _REGISTERED = False


if not os.environ.get("AIM_NO_AUTO_HOOKS"):
    register_all()
