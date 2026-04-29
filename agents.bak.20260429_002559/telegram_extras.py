"""agents/telegram_extras.py — drop-in helpers for telegram_bot.py.

Adds:
    • inline-keyboard HITL handler (Accept / Reject / Comment)
    • voice → text via Whisper (DeepSeek doesn't expose ASR; use OpenAI / faster-whisper)
    • throttling per chat_id

Wire-in (one-liner in telegram_bot.py):

    from agents.telegram_extras import register_extras
    register_extras(application)
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.telegram_extras")


# ── Throttle ───────────────────────────────────────────────────────────────


_last_call: dict[int, float] = defaultdict(float)
_MIN_GAP_S = float(os.getenv("AIM_TG_MIN_GAP_S", "1.5"))


def throttled(chat_id: int) -> bool:
    """True if this chat_id is calling too fast — caller should drop the request."""
    now = time.time()
    if now - _last_call[chat_id] < _MIN_GAP_S:
        return True
    _last_call[chat_id] = now
    return False


# ── HITL inline keyboard ────────────────────────────────────────────────────


def make_review_keyboard():
    """Return InlineKeyboardMarkup for HITL review buttons.
    Importable lazily so module loads without telegram lib."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принять", callback_data="aim:accept")],
        [InlineKeyboardButton("❌ Отклонить", callback_data="aim:reject")],
        [InlineKeyboardButton("✏️ Комментарий", callback_data="aim:comment")],
    ])


async def review_callback(update, context):
    """Handle :accept/:reject/:comment buttons. Stores decision in user_data."""
    query = update.callback_query
    await query.answer()
    decision = query.data.split(":", 1)[1]
    if decision == "accept":
        context.user_data["review_decision"] = "ACCEPTED"
        await query.edit_message_text("✅ Принято.")
    elif decision == "reject":
        context.user_data["review_decision"] = "REJECTED"
        await query.edit_message_text("❌ Отклонено. Перегенерирую…")
    elif decision == "comment":
        context.user_data["review_decision"] = "COMMENT"
        context.user_data["awaiting_comment"] = True
        await query.edit_message_text("✏️ Пришли комментарий следующим сообщением.")


# ── Voice → text ────────────────────────────────────────────────────────────


async def transcribe_voice(file_path: str) -> Optional[str]:
    """Transcribe ogg/wav. Tries faster-whisper first (local), then OpenAI ASR."""
    # Local first
    try:
        from faster_whisper import WhisperModel
        size = os.getenv("AIM_WHISPER_MODEL", "base")
        model = WhisperModel(size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(file_path, language=None, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    except ImportError:
        log.info("faster-whisper not installed, trying OpenAI Whisper API")
    except Exception as e:
        log.warning(f"faster-whisper failed: {e}")

    # OpenAI Whisper API fallback
    try:
        from openai import OpenAI
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            log.info("no OPENAI_API_KEY for Whisper fallback")
            return None
        client = OpenAI(api_key=key)
        with open(file_path, "rb") as fh:
            resp = client.audio.transcriptions.create(model="whisper-1", file=fh)
        return resp.text.strip()
    except Exception as e:
        log.warning(f"OpenAI ASR failed: {e}")
        return None


async def handle_voice(update, context):
    """python-telegram-bot voice handler."""
    chat_id = update.message.chat_id
    if throttled(chat_id):
        await update.message.reply_text("⏳ слишком быстро, подожди секунду")
        return
    voice = update.message.voice or update.message.audio
    if voice is None:
        return
    await update.message.reply_text("🎤 распознаю…")
    f = await voice.get_file()
    out = Path("/tmp") / f"aim_voice_{chat_id}_{int(time.time())}.ogg"
    await f.download_to_drive(str(out))
    text = await transcribe_voice(str(out))
    try:
        out.unlink()
    except Exception:
        pass
    if not text:
        await update.message.reply_text("⚠️ не смог распознать — попробуй текстом")
        return
    await update.message.reply_text(f"📝 {text}\n\n⏳ обрабатываю…")
    # Run agent in a thread (run_agent is sync)
    from agents.graph import run_agent
    try:
        result = run_agent(text, use_memory=True)
        await update.message.reply_text(
            "\n\n".join(result.get("step_results", []))[:4000]
            or "(пустой результат)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


# ── Wire-in ────────────────────────────────────────────────────────────────


def register_extras(application) -> None:
    """Attach inline-keyboard handler + voice handler + throttle filter to a
    python-telegram-bot Application."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    application.add_handler(CallbackQueryHandler(review_callback, pattern=r"^aim:"))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    log.info("telegram_extras: HITL + voice handlers registered")
