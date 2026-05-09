"""agents/notify.py — notification multiplexer (N1, 2026-05-03).

A single front door for every alert / brief / digest AIM wants to send.
Routes to channels in priority order, retries the next channel on
failure, and writes a unified JSONL audit so the user can replay what
was actually delivered.

Channels:
    telegram   — uses scripts.daily_brief.send_telegram (chunked, env-gated)
    email      — uses agents.email_agent (Gmail; gated by L_CONSENT)
    stdout     — fallback, always succeeds
    log        — log.info; never user-visible but always recorded

Pipeline:
    notify(message, *, channels=("telegram","email","stdout"),
           subject=None, level="info", source="generic",
           dedup_key=None) -> NotifyResult

Dedup:
    If `dedup_key` is given, we suppress repeat sends within
    `dedup_window_minutes` (default 60). Prevents the same alert flooding
    the user when escalation runs every hour.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.notify")


def audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "notify.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclasses.dataclass
class NotifyResult:
    delivered_via: Optional[str]   # winning channel, or None on full failure
    attempted: list[str]
    failures: dict[str, str]
    suppressed: bool = False       # True when dedup blocked the send
    dedup_key: Optional[str] = None


# ── channel implementations ──────────────────────────────────────


def _send_telegram(text: str, subject: Optional[str]) -> bool:
    body = f"{subject}\n\n{text}" if subject else text
    try:
        from agents.telegram_sender import send_telegram
    except Exception as e:
        log.debug("telegram channel unavailable: %s", e)
        return False
    try:
        return bool(send_telegram(body))
    except Exception as e:
        log.debug("telegram send failed: %s", e)
        return False


def _send_email(text: str, subject: Optional[str]) -> bool:
    """Send via the Gmail email_agent. Requires AIM_NOTIFY_EMAIL_TO set."""
    to_addr = os.environ.get("AIM_NOTIFY_EMAIL_TO")
    if not to_addr:
        return False
    try:
        from agents import email_agent as _em
    except Exception as e:
        log.debug("email_agent unavailable: %s", e)
        return False
    fn = getattr(_em, "send", None) or getattr(_em, "send_email", None)
    if fn is None:
        return False
    try:
        # Most send signatures: send(to, subject, body, user_confirmed=True)
        result = fn(
            to=to_addr,
            subject=subject or "AIM notification",
            body=text,
            user_confirmed=True,
        )
        return bool(result)
    except TypeError:
        try:
            return bool(fn(to_addr, subject or "AIM notification", text))
        except Exception as e:
            log.debug("email send failed: %s", e)
            return False
    except Exception as e:
        log.debug("email send failed: %s", e)
        return False


def _send_stdout(text: str, subject: Optional[str]) -> bool:
    if subject:
        print(f"=== {subject} ===")
    print(text)
    return True


def _send_log(text: str, subject: Optional[str]) -> bool:
    log.info("[%s] %s", subject or "notify", text[:1000])
    return True


# Indirection through globals() lets tests monkeypatch the inner senders
# (e.g. _send_telegram) without re-binding the dispatch table.
_CHANNEL_FN_NAMES = {
    "telegram": "_send_telegram",
    "email":    "_send_email",
    "stdout":   "_send_stdout",
    "log":      "_send_log",
}


def _channel_fn(name: str):
    fn_name = _CHANNEL_FN_NAMES.get(name)
    if fn_name is None:
        return None
    return globals().get(fn_name)


# ── dedup ────────────────────────────────────────────────────────


# ── N2 rate limiter (2026-05-03) ─────────────────────────────────


def _rate_limit_max() -> int:
    """How many notifications allowed per `_rate_window_minutes`. 0 = off."""
    try:
        return int(os.environ.get("AIM_NOTIFY_RATE_MAX", "20"))
    except ValueError:
        return 20


def _rate_window_minutes() -> float:
    try:
        return float(os.environ.get("AIM_NOTIFY_RATE_WINDOW_MIN", "60"))
    except ValueError:
        return 60.0


def _count_recent_deliveries(window_minutes: float) -> int:
    """Count recent notify entries with non-null delivered_via."""
    p = audit_path()
    if not p.exists():
        return 0
    cutoff = dt.datetime.now() - dt.timedelta(minutes=window_minutes)
    n = 0
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not row.get("delivered_via"):
                    continue
                ts_str = row.get("ts") or ""
                try:
                    ts = dt.datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts >= cutoff:
                    n += 1
    except OSError:
        return 0
    return n


def _was_recently_sent(key: str, window_minutes: float) -> bool:
    p = audit_path()
    if not p.exists():
        return False
    cutoff = dt.datetime.now() - dt.timedelta(minutes=window_minutes)
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("dedup_key") != key:
                    continue
                ts_str = row.get("ts") or ""
                try:
                    ts = dt.datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts >= cutoff and row.get("delivered_via"):
                    return True
    except OSError:
        return False
    return False


def _audit(payload: dict) -> None:
    payload = {**payload, "ts": dt.datetime.now().replace(microsecond=0).isoformat()}
    try:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("notify audit write failed: %s", e)


# ── public API ───────────────────────────────────────────────────


def notify(message: str, *,
           channels: Iterable[str] = ("telegram", "stdout"),
           subject: Optional[str] = None,
           level: str = "info",
           source: str = "generic",
           dedup_key: Optional[str] = None,
           dedup_window_minutes: float = 60.0) -> NotifyResult:
    """Route `message` through `channels` in order; first success wins.

    Channel order matters. Default: telegram first (user gets push
    instantly), stdout fallback (cron logs capture it). For digests use
    `("telegram", "email", "stdout")` so daily delivery survives an
    outage on either channel.
    """
    if dedup_key and _was_recently_sent(dedup_key, dedup_window_minutes):
        result = NotifyResult(delivered_via=None, attempted=[],
                              failures={}, suppressed=True,
                              dedup_key=dedup_key)
        _audit({"source": source, "level": level, "subject": subject,
                "dedup_key": dedup_key, "delivered_via": None,
                "suppressed": True})
        return result

    # N2 (2026-05-03): rate limit. High-priority levels bypass.
    rate_max = _rate_limit_max()
    if (rate_max > 0 and level not in ("high", "critical")
            and _count_recent_deliveries(_rate_window_minutes()) >= rate_max):
        result = NotifyResult(delivered_via=None, attempted=[],
                              failures={"rate_limit": "exceeded"},
                              suppressed=True, dedup_key=dedup_key)
        _audit({"source": source, "level": level, "subject": subject,
                "dedup_key": dedup_key, "delivered_via": None,
                "suppressed": True, "reason": "rate_limit"})
        return result

    attempted: list[str] = []
    failures: dict[str, str] = {}
    delivered_via: Optional[str] = None

    for ch in channels:
        attempted.append(ch)
        fn = _channel_fn(ch)
        if fn is None:
            failures[ch] = "unknown channel"
            continue
        try:
            ok = fn(message, subject)
        except Exception as e:  # noqa: BLE001
            failures[ch] = f"{type(e).__name__}: {e}"
            ok = False
        if ok:
            delivered_via = ch
            break
        else:
            failures.setdefault(ch, "send returned False")

    _audit({
        "source": source, "level": level, "subject": subject,
        "dedup_key": dedup_key, "channels": list(attempted),
        "failures": failures, "delivered_via": delivered_via,
    })
    return NotifyResult(delivered_via=delivered_via, attempted=attempted,
                        failures=failures, dedup_key=dedup_key)


def history(limit: int = 50, source: Optional[str] = None) -> list[dict]:
    p = audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if source and row.get("source") != source:
                continue
            out.append(row)
    return out[-limit:]
