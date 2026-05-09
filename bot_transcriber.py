#!/usr/bin/env python3
"""
Telegram-бот транскрибации голосовых сообщений.
Любое голосовое сообщение → Whisper → текст → файл пациента.

Возможности:
  • Автоопределение языка (ru/ka/en/auto)
  • Сохранение транскриптов в patient_intake/transcripts/
  • Медицинский словарь для грузинского
  • DeepSeek пост-обработка (--fix)
  • Voice chat в группах (через pytgcalls, --vc)

Запуск:
  python bot_transcriber.py                          # базовый
  python bot_transcriber.py --fix                    # + DeepSeek
  python bot_transcriber.py --lang ka                # грузинский по умолчанию
  python bot_transcriber.py --vc                     # + voice chat (экспериментально)
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import whisper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot_transcriber")

# ─── конфиг ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "turbo"
SAMPLE_RATE = 16000
OUTPUT_DIR = Path("patient_intake/transcripts")
DICT_PATH = Path("ka_medical_dict.json")

# Читаем токен
TOKEN = ""
env_path = Path.home() / ".aim_env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip()
                break

model = None
ka_dict = {}
args = None
user_patient_map = {}  # user_id -> patient_name

# ─── микрофон ────────────────────────────────────────────────────────────
mic_active = False
mic_thread = None
current_output_path = None  # текущий файл для записи (устанавливается при голосовом)


def load_ka_dict():
    """Загрузить грузинский медицинский словарь."""
    global ka_dict
    try:
        if DICT_PATH.exists():
            with open(DICT_PATH, "r", encoding="utf-8") as f:
                ka_dict = json.load(f)
            prompt_parts = []
            if "whisper_prompt" in ka_dict:
                prompt_parts.append(ka_dict["whisper_prompt"])
            if "common_phrases" in ka_dict:
                prompt_parts.append(". ".join(ka_dict["common_phrases"][:5]))
            terms = []
            for cat in ka_dict.get("medical_terms", {}).values():
                terms.extend(cat[:10])
            if terms:
                prompt_parts.append(". ".join(terms))
            ka_dict["_whisper_prompt"] = ". ".join(prompt_parts)
            log.info(f"Словарь загружен: {sum(len(v) if isinstance(v, list) else 0 for v in ka_dict.values())} записей")
            return True
    except Exception as e:
        log.warning(f"Не удалось загрузить словарь: {e}")
    ka_dict = {}
    return False


def get_transcript_path(user_id: int, chat_id: int) -> Path:
    """Получить путь к файлу транскрипта для пациента/пользователя."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Если пользователь задал имя пациента — используем его
    patient_name = user_patient_map.get(user_id, f"tg_{user_id}")
    safe_name = patient_name.replace(" ", "_").lower()

    return OUTPUT_DIR / f"{safe_name}_{datetime.now().strftime('%Y%m%d')}.md"


def append_to_transcript(file_path: Path, text: str, timestamp: str, lang: str, speaker: str = "unknown"):
    """Дописать строку в конец файла транскрипта."""
    is_new = not file_path.exists()
    with open(file_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# Транскрипт — {file_path.stem}\n")
            f.write(f"Создан: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"{'='*60}\n\n")
        f.write(f"**[{timestamp}]** *({speaker}, {lang})*\n")
        f.write(f"{text}\n\n")


def transcribe_audio(audio_path: str, lang: str = "auto", fix: bool = False) -> tuple[str, str]:
    """Транскрибация аудиофайла через Whisper."""
    global model

    if model is None:
        model_name = args.model if args else DEFAULT_MODEL
        log.info(f"Загрузка модели whisper-{model_name}...")
        model = whisper.load_model(model_name)
        log.info("Модель загружена")

    opts = {"fp16": False}
    if lang != "auto":
        opts["language"] = lang
    else:
        opts["language"] = None

    # Промпт из словаря для грузинского
    if lang == "ka" and ka_dict and ka_dict.get("_whisper_prompt"):
        opts["initial_prompt"] = ka_dict["_whisper_prompt"]

    result = model.transcribe(audio_path, **opts)
    text = result.get("text", "").strip()
    detected = result.get("language", lang)

    # DeepSeek пост-обработка
    if fix and text and detected == "ka":
        log.info("DeepSeek коррекция...")
        text = _fix_with_deepseek(text, "грузинском")

    return text, detected


def _fix_with_deepseek(text: str, lang_name: str) -> str:
    """Пост-обработка через DeepSeek."""
    if not text or len(text) < 3:
        return text

    prompt = (
        f"Ты — корректор медицинской транскрибации. "
        f"Исправь ошибки в распознанном тексте на {lang_name} языке. "
        f"Сохрани смысл, исправь опечатки. Верни только исправленный текст.\n\n"
        f"Текст: {text}"
    )

    try:
        result = subprocess.run(
            [
                sys.executable, "-c", f"""
import os, json, urllib.request
key = os.environ.get('DEEPSEEK_API_KEY', '')
if not key:
    try:
        with open(os.path.expanduser('~/.aim_env')) as f:
            for line in f:
                if 'DEEPSEEK_API_KEY' in line:
                    key = line.split('=')[1].strip().split()[0]
                    break
    except: pass
data = json.dumps({{
    "model": "deepseek-chat",
    "messages": [{{"role": "user", "content": {json.dumps(prompt)}}}],
    "temperature": 0.05,
    "max_tokens": 500
}}).encode()
req = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=data,
    headers={{"Content-Type": "application/json", "Authorization": f"Bearer {{key}}"}}
)
resp = json.loads(urllib.request.urlopen(req).read())
print(resp["choices"][0]["message"]["content"].strip())
"""
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        fixed = result.stdout.strip()
        if fixed and len(fixed) > 2:
            return fixed
    except Exception as e:
        log.warning(f"DeepSeek: {e}")

    return text


async def handle_voice_message(update, context):
    """Обработка голосового сообщения."""
    global current_output_path, mic_active
    user = update.effective_user
    chat = update.effective_chat

    log.info(f"Голосовое от {user.id} ({user.first_name}) в чате {chat.id}")

    msg = await update.message.reply_text("🎤 Распознаю речь...")

    # Скачиваем
    voice = update.message.voice
    file = await voice.get_file()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        audio_path = tmp.name

    try:
        lang = args.lang if args else "auto"
        text, detected = transcribe_audio(audio_path, lang=lang, fix=args.fix if args else False)

        ts = datetime.now().strftime("%H:%M:%S")
        output_path = get_transcript_path(user.id, chat.id)

        # Устанавливаем как текущий файл для микрофона
        current_output_path = output_path

        speaker = user.first_name or f"Пациент(tg)"
        append_to_transcript(output_path, text, ts, detected, speaker)

        reply = f"📝 *{speaker}* [{ts}]\n\n{text}"

        if mic_active:
            reply += f"\n\n_🎙 Микрофон активен — говорите ответ_"

        if detected != lang and lang == "auto":
            detected_name = {"ru": "русский", "ka": "ქართული", "en": "english"}.get(detected, detected)
            reply += f"\n\n_🌐 Язык: {detected_name}_"

        await msg.edit_text(reply, parse_mode="Markdown")

    except Exception as e:
        log.exception("Ошибка транскрибации")
        await msg.edit_text(f"❌ Ошибка: {e}")
    finally:
        os.unlink(audio_path)


async def handle_audio_message(update, context):
    """Обработка аудиосообщения (не голосовое, а файл .ogg/.mp3)."""
    user = update.effective_user
    chat = update.effective_chat

    log.info(f"Аудиофайл от {user.id}")

    msg = await update.message.reply_text("🎤 Распознаю аудиофайл...")

    audio = update.message.audio or update.message.document
    file = await audio.get_file()

    # Определяем расширение
    name = audio.file_name or "audio"
    suffix = Path(name).suffix or ".ogg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        audio_path = tmp.name

    try:
        lang = args.lang if args else "auto"
        text, detected = transcribe_audio(audio_path, lang=lang, fix=args.fix if args else False)

        ts = datetime.now().strftime("%H:%M:%S")
        output_path = get_transcript_path(user.id, chat.id)
        speaker = user.first_name or f"tg_{user.id}"
        append_to_transcript(output_path, text, ts, detected, speaker)

        reply = f"📝 *{speaker}* [{ts}]\n\n{text}"
        await msg.edit_text(reply, parse_mode="Markdown")

    except Exception as e:
        log.exception("Ошибка транскрибации")
        await msg.edit_text(f"❌ Ошибка: {e}")
    finally:
        os.unlink(audio_path)


async def handle_text(update, context):
    """Обработка текстовых команд."""
    user = update.effective_user
    text = update.message.text.strip()

    # /start
    if text == "/start":
        await update.message.reply_text(
            f"🩺 *AIM Transcriber*\n\n"
            f"Пришли голосовое сообщение — я распознаю речь и сохраню в файл пациента.\n\n"
            f"Команды:\n"
            f"`/patient Имя` — задать имя пациента\n"
            f"`/lang ru|ka|en|auto` — язык\n"
            f"`/file` — получить сегодняшний транскрипт\n"
            f"`/help` — помощь\n\n"
            f"Голосовые сообщения обрабатываются автоматически.",
            parse_mode="Markdown"
        )
        return

    # /patient
    if text.startswith("/patient"):
        name = text[len("/patient"):].strip()
        if name:
            user_patient_map[user.id] = name
            await update.message.reply_text(f"✅ Пациент: *{name}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("ℹ️ Укажи имя: `/patient Иван Петров`", parse_mode="Markdown")
        return

    # /lang
    if text.startswith("/lang"):
        lang = text[len("/lang"):].strip()
        if lang in ("ru", "ka", "en", "auto"):
            global args
            if args is None:
                args = argparse.Namespace(lang=lang, fix=False, model=DEFAULT_MODEL)
            else:
                args.lang = lang
            await update.message.reply_text(f"🌐 Язык: *{lang}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("Доступно: ru, ka, en, auto")
        return

    # /file
    if text == "/file":
        output_path = get_transcript_path(user.id, update.effective_chat.id)
        if output_path.exists():
            with open(output_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Telegram лимит 4096 символов
            if len(content) > 4000:
                content = content[-4000:]
            await update.message.reply_text(f"📄 *Транскрипт:*\n\n{content}", parse_mode="Markdown")
        else:
            await update.message.reply_text("ℹ️ Сегодня ещё не было транскрипций.")
        return

    # /mic
    if text == "/mic":
        global mic_active, mic_thread, current_output_path
        mic_active = not mic_active

        if mic_active:
            # Если есть активный пациент — используем его файл
            if user.id in user_patient_map:
                current_output_path = get_transcript_path(user.id, chat.id)
            else:
                current_output_path = get_transcript_path(user.id, chat.id)

            from threading import Thread
            mic_thread = Thread(target=_mic_listener, args=(user.id, chat.id), daemon=True)
            mic_thread.start()
            await update.message.reply_text(
                "🎙 *Микрофон ВКЛЮЧЁН*\n\n"
                "Говорите — ваш голос будет транскрибироваться "
                "в тот же файл, что и голосовые пациента.\n"
                "`/mic` — выключить",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🎙 *Микрофон выключен*", parse_mode="Markdown")
        return

    # /help
    if text == "/help":
        await update.message.reply_text(
            "📖 *Помощь*\n\n"
            "• Пришли голосовое — я расшифрую и сохраню\n"
            "• `/patient Имя` — задать имя текущего пациента\n"
            "• `/lang ka` — переключить язык на грузинский\n"
            "• `/mic` — включить/выключить микрофон врача\n"
            "• `/file` — показать сегодняшний транскрипт\n"
            "• `/help` — эта справка\n\n"
            "Транскрипты сохраняются в `patient_intake/transcripts/`",
            parse_mode="Markdown"
        )
        return

    # Всё остальное игнорируем (это не голосовое)
    await update.message.reply_text("ℹ️ Пришли *голосовое сообщение* для распознавания.", parse_mode="Markdown")


async def error_handler(update, context):
    """Обработка ошибок."""
    log.error(f"Update {update} вызвал ошибку {context.error}")


async def voice_chat_mode():
    """
    Voice Chat режим: использует pytgcalls для записи голосовых чатов.
    Требует отдельный Telegram аккаунт (не бот, а user account).
    """
    log.info("Voice Chat режим активирован (pytgcalls)")

    try:
        from pyrogram import Client as PyroClient
        from pytgcalls import PyTgCalls
        from pytgcalls.types import Update
        import pytgcalls

        # Загрузка credentials для user account
        api_id = os.getenv("TG_API_ID", "")
        api_hash = os.getenv("TG_API_HASH", "")
        session_str = os.getenv("TG_SESSION", "")

        if not all([api_id, api_hash]):
            log.error("❌ Для voice chat нужны TG_API_ID и TG_API_HASH в ~/.aim_env")
            log.error("   Получи их на https://my.telegram.org/apps")
            return

        # Асинхронная функция обработки
        from pyrogram import filters as pyro_filters

        app = PyroClient(
            "aim_voice_chat",
            api_id=int(api_id),
            api_hash=api_hash,
            session_string=session_str or None,
        )

        call_handler = PyTgCalls(app)

        @call_handler.on_stream_end()
        async def on_stream_end(client, update: Update):
            log.info(f"Поток завершён: {update}")

        @call_handler.on_kicked()
        async def on_kicked(client, update: Update):
            log.info(f"Выгнан из голосового чата")

        await app.start()
        await call_handler.start()

        log.info("✅ Voice Chat слушатель запущен")
        log.info("   Добавьте аккаунт в групповой голосовой чат для записи")

        # Бесконечное ожидание
        while True:
            await asyncio.sleep(10)

    except ImportError:
        log.error("❌ voice chat требует: pip install pyrogram pytgcalls")
        log.error("   pip install pyrogram pytgcalls tgcrypto")
    except Exception as e:
        log.exception(f"Voice Chat ошибка: {e}")


async def main_async():
    """Главная асинхронная функция."""
    global args

    parser = argparse.ArgumentParser(description="Telegram бот транскрибации")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        choices=["tiny", "base", "small", "medium", "large", "turbo",
                                 "large-v3", "large-v3-turbo"],
                        help="Модель Whisper")
    parser.add_argument("--lang", "-l", default="auto",
                        choices=["ru", "ka", "en", "auto"],
                        help="Язык по умолчанию")
    parser.add_argument("--fix", action="store_true",
                        help="Пост-обработка DeepSeek")
    parser.add_argument("--vc", action="store_true",
                        help="Voice chat режим (экспериментально)")
    parser.add_argument("--no-bot", action="store_true",
                        help="Только voice chat, без Telegram бота")
    parser.add_argument("--mic", action="store_true",
                        help="Автовключение микрофона врача при старте")
    parser.add_argument("--no-voice", action="store_true",
                        help="Не обрабатывать входящие голосовые")
    args = parser.parse_args()
    globals()["args"] = args

    print(f"\n{'='*60}")
    print(f"📱 AIM Telegram Transcriber")
    print(f"{'='*60}")
    print(f"   Модель: whisper-{args.model}")
    print(f"   Язык:   {args.lang}")

    if args.fix:
        print(f"   DeepSeek: ✅ коррекция")
    if args.mic:
        print(f"   Микрофон: ✅ режим врача")

    # Словарь
    if load_ka_dict():
        print(f"   Словарь: ✅ грузинский")

    # Voice chat режим
    if args.vc:
        asyncio.create_task(voice_chat_mode())

    if args.no_bot:
        print(f"\n✅ Voice Chat режим (бота нет)")
        while True:
            await asyncio.sleep(10)
        return

    # Загружаем модель сразу (первый голосовой запрос)
    print(f"\n🔄 Предзагрузка whisper-{args.model}...")
    global model
    model = whisper.load_model(args.model)
    print(f"✅ Модель готова")

    # Запуск Telegram бота
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не найден в ~/.aim_env")
        sys.exit(1)

    from telegram.ext import ApplicationBuilder

    app = ApplicationBuilder().token(TOKEN).build()

    # Обработчики
    if not args.no_voice:
        app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        app.add_handler(MessageHandler(filters.AUDIO | filters.Document.AUDIO, handle_audio_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CommandHandler("start", handle_text))
    app.add_handler(CommandHandler("help", handle_text))
    app.add_handler(CommandHandler("patient", handle_text))
    app.add_handler(CommandHandler("lang", handle_text))
    app.add_handler(CommandHandler("mic", handle_text))
    app.add_handler(CommandHandler("file", handle_text))
    app.add_error_handler(error_handler)

    # Автовключение микрофона
    if args.mic:
        log.info("Автозапуск микрофона...")
        from threading import Thread
        global mic_active, mic_thread, current_output_path
        mic_active = True
        current_output_path = OUTPUT_DIR / f"doctor_{datetime.now().strftime('%Y%m%d')}.md"
        mic_thread = Thread(target=_mic_listener, args=(0, 0), daemon=True)
        mic_thread.start()

    print(f"\n🤖 Бот запущен. Ожидаю голосовые сообщения...")
    print(f"   Команды: /start, /patient, /lang, /mic, /file, /help")
    print(f"   Транскрипты: {OUTPUT_DIR.resolve()}")
    print(f"{'='*60}")

    # Graceful shutdown
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: stop_event.set()
            )
        except NotImplementedError:
            pass  # Windows

    await app.run_polling(stop_signals=None)
    log.info("Бот остановлен")


def _mic_listener(user_id: int, chat_id: int):
    """Фоновый поток: слушает микрофон и транскрибирует в файл."""
    global mic_active, current_output_path

    import sounddevice as sd
    import numpy as np

    log.info("🎙 Микрофон запущен")

    CHUNK = 10  # секунд на чанк
    SAMPLE_RATE = 16000

    while mic_active:
        try:
            # Запись с микрофона
            audio = sd.rec(
                int(CHUNK * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()

            audio = audio.flatten()
            rms = np.sqrt(np.mean(audio ** 2))
            if rms < 0.015:
                continue  # тишина

            # Нормализация
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val

            # Транскрибация
            lang = args.lang if args else "auto"
            opts = {"fp16": False}
            if lang != "auto":
                opts["language"] = lang
            else:
                opts["language"] = None

            if lang == "ka" and ka_dict and ka_dict.get("_whisper_prompt"):
                opts["initial_prompt"] = ka_dict["_whisper_prompt"]

            result = model.transcribe(audio, **opts)
            text = result.get("text", "").strip()
            detected = result.get("language", lang)

            if text:
                ts = datetime.now().strftime("%H:%M:%S")

                # Используем текущий файл пациента или создаём новый
                path = current_output_path
                if path is None:
                    path = get_transcript_path(user_id, chat_id)
                    current_output_path = path

                append_to_transcript(path, text, ts, detected, "Врач")
                log.info(f"🎙 [Врач] {text[:80]}...")

        except Exception as e:
            log.warning(f"Микрофон: {e}")
            if not mic_active:
                break
            import time
            time.sleep(1)

    log.info("🎙 Микрофон остановлен")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
