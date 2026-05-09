"""agents/telegram_sender.py — standalone Telegram sender (HW1, 2026-05-06).

Extracted from `scripts/daily_brief.py` so that:
  * `agents/notify.py` (telegram channel) doesn't import from `scripts/`,
  * Future `scripts/daily_brief.py` removal doesn't cascade-break notify,
  * `scripts/weekly_digest.py` and other senders use one canonical impl.

Pure utility — chunked POST to Telegram Bot API. Reads
`TELEGRAM_BOT_TOKEN` (or `AIM_TG_BOT_TOKEN`) and `AIM_TELEGRAM_CHAT_ID`
from env. Returns False on missing config / network failure.

Telegram limit is 4096 chars; we chunk at 3800 to leave headroom.

Public API:
    send_telegram(text) -> bool
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("aim.telegram_sender")

LIMIT = 3800


def send_telegram(text: str) -> bool:
    """POST text to Telegram. Returns True on 200, False on failure / missing config.

    Chunks text into 3800-char windows (Telegram API limit is 4096).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("AIM_TG_BOT_TOKEN")
    chat = os.environ.get("AIM_TELEGRAM_CHAT_ID")
    if not token or not chat:
        log.warning("Telegram not configured "
                    "(need TELEGRAM_BOT_TOKEN + AIM_TELEGRAM_CHAT_ID)")
        return False
    try:
        import httpx
    except ImportError:
        log.error("httpx not installed; cannot send to Telegram")
        return False
    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [text]
    ok = True
    with httpx.Client(timeout=10) as cl:
        for body in chunks:
            r = cl.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat, "text": body,
                              "disable_web_page_preview": True})
            if r.status_code != 200:
                log.error("Telegram %d: %s", r.status_code, r.text[:200])
                ok = False
                break
    return ok
