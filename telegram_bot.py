"""
AIM v7.0 — Telegram Bot
Мультиязычный бот с роутером LLM. Только для авторизованных пользователей.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / ".aim_env")

TELEGRAM_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_ID = int(os.getenv("TELEGRAM_ALLOWED_ID", "0"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в ~/.aim_env")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler,
)

from agents import DoctorAgent, IntakeAgent, LangAgent
from db import upsert_patient, new_session, save_message, get_history
from i18n import t
from config import SUPPORTED_LANGS, DEFAULT_LANG
from llm import _detect_lang

log = logging.getLogger("aim.telegram")

# ── Состояния диалога ─────────────────────────────────────────────────────────

IDLE, AWAITING_SYMPTOMS, AWAITING_DIAGNOSIS, AWAITING_TRANSLATE_TARGET, AWAITING_TRANSLATE_TEXT = range(5)

# ── Экземпляры агентов ────────────────────────────────────────────────────────

doctor = DoctorAgent()
intake = IntakeAgent()
lang_agent = LangAgent()

# ── Состояние пользователей (в памяти; для production — Redis/БД) ─────────────

user_state: dict[int, dict] = {}


def _state(uid: int) -> dict:
    if uid not in user_state:
        user_state[uid] = {"lang": DEFAULT_LANG, "session_id": None, "patient": None}
    return user_state[uid]


def _check_auth(update: Update) -> bool:
    uid = update.effective_user.id
    if TELEGRAM_ALLOWED_ID and uid != TELEGRAM_ALLOWED_ID:
        return False
    return True


def _main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(t("m4", lang)), KeyboardButton(t("m5", lang))],
        [KeyboardButton(t("m3", lang)), KeyboardButton(t("m6", lang))],
        [KeyboardButton(t("m7", lang)), KeyboardButton("⚙️")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# ── Хендлеры ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return IDLE

    uid = update.effective_user.id
    st = _state(uid)
    # Определяем язык по языку Telegram-клиента
    tg_lang = update.effective_user.language_code or "ru"
    if tg_lang[:2] in SUPPORTED_LANGS:
        st["lang"] = tg_lang[:2]
    # Создаём анонимную сессию
    st["session_id"] = new_session(None, st["lang"])

    await update.message.reply_text(
        f"👋 {t('menu_title', st['lang'])}\nv7.0",
        reply_markup=_main_keyboard(st["lang"]),
    )
    return IDLE


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    langs_text = "\n".join(f"/lang_{c} — {n}"
                           for c, n in lang_agent.available_langs())
    await update.message.reply_text(f"Выберите язык:\n{langs_text}")
    return IDLE


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE

    uid = update.effective_user.id
    st = _state(uid)
    text = update.message.text or ""
    lang = st["lang"]

    # Автодетект языка сообщения
    detected = _detect_lang(text)
    if detected in SUPPORTED_LANGS and detected != lang:
        st["lang"] = detected
        lang = detected

    # Роутинг по кнопкам меню
    m4 = t("m4", lang)  # Диагностика
    m5 = t("m5", lang)  # Лечение
    m6 = t("m6", lang)  # Перевод
    m7 = t("m7", lang)  # Консультация

    if text == m4 or text.lower() in ("диагностика", "diagnosis", "diagnose"):
        await update.message.reply_text(t("ask_symptoms", lang) if "ask_symptoms" in _all_keys() else
                                        "Опишите жалобы и симптомы:")
        return AWAITING_SYMPTOMS

    if text == m5 or text.lower() in ("лечение", "treatment", "протокол"):
        await update.message.reply_text("Введите диагноз:")
        return AWAITING_DIAGNOSIS

    if text == m6 or text.lower() in ("перевод", "translate", "translation"):
        langs_str = " | ".join(SUPPORTED_LANGS)
        await update.message.reply_text(f"Целевой язык ({langs_str}):")
        return AWAITING_TRANSLATE_TARGET

    # Свободный диалог
    await update.message.reply_text(t("thinking", lang))
    sid = st["session_id"]
    if not sid:
        sid = new_session(None, lang)
        st["session_id"] = sid
    history = get_history(sid, limit=6)
    result = doctor.chat(text, history=history, lang=lang, session_id=sid)
    await update.message.reply_text(result)
    return IDLE


async def receive_symptoms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    lang = st["lang"]
    symptoms = update.message.text or ""

    await update.message.reply_text(t("thinking", lang))
    result = doctor.diagnose(symptoms, lang=lang, session_id=st["session_id"])
    await update.message.reply_text(result, reply_markup=_main_keyboard(lang))
    return IDLE


async def receive_diagnosis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    lang = st["lang"]
    diagnosis = update.message.text or ""

    await update.message.reply_text(t("thinking", lang))
    result = doctor.treatment_plan(diagnosis, lang=lang, session_id=st["session_id"])
    await update.message.reply_text(result, reply_markup=_main_keyboard(lang))
    return IDLE


async def receive_translate_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    target = (update.message.text or "").strip().lower()

    if target not in SUPPORTED_LANGS:
        await update.message.reply_text(f"Неизвестный язык: {target}. Попробуйте ещё.")
        return AWAITING_TRANSLATE_TARGET

    context.user_data["translate_target"] = target
    await update.message.reply_text("Введите текст для перевода:")
    return AWAITING_TRANSLATE_TEXT


async def receive_translate_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    lang = st["lang"]
    target = context.user_data.get("translate_target", "en")
    text = update.message.text or ""

    await update.message.reply_text(t("thinking", lang))
    result = lang_agent.translate(text, target_lang=target, translation_type="medical",
                                  session_id=st["session_id"])
    await update.message.reply_text(result, reply_markup=_main_keyboard(lang))
    return IDLE


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """OCR фото анализов."""
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    lang = st["lang"]

    await update.message.reply_text(t("thinking", lang))
    photo = update.message.photo[-1]  # наибольшее разрешение
    file = await context.bot.get_file(photo.file_id)

    # Скачиваем во временный файл
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    await file.download_to_drive(str(tmp_path))

    result = intake.process_file(tmp_path, lang=lang, session_id=st["session_id"])
    tmp_path.unlink(missing_ok=True)
    await update.message.reply_text(result, reply_markup=_main_keyboard(lang))
    return IDLE


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приём PDF документов."""
    if not _check_auth(update):
        return IDLE
    uid = update.effective_user.id
    st = _state(uid)
    lang = st["lang"]

    doc = update.message.document
    if not doc.file_name.lower().endswith((".pdf", ".txt")):
        await update.message.reply_text("Поддерживаются PDF и TXT.")
        return IDLE

    await update.message.reply_text(t("thinking", lang))
    file = await context.bot.get_file(doc.file_id)

    import tempfile
    suffix = Path(doc.file_name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    await file.download_to_drive(str(tmp_path))

    result = intake.process_file(tmp_path, lang=lang, session_id=st["session_id"])
    tmp_path.unlink(missing_ok=True)
    await update.message.reply_text(result, reply_markup=_main_keyboard(lang))
    return IDLE


def _all_keys():
    """Вспомогательная — список всех ключей i18n."""
    from i18n import STRINGS
    return STRINGS.keys()


# ── Запуск ────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        ],
        states={
            IDLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.Document.ALL, handle_document),
            ],
            AWAITING_SYMPTOMS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_symptoms),
            ],
            AWAITING_DIAGNOSIS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_diagnosis),
            ],
            AWAITING_TRANSLATE_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_translate_target),
            ],
            AWAITING_TRANSLATE_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_translate_text),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    log.info("AIM Telegram Bot запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
