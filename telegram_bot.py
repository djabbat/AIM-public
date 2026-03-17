#!/usr/bin/env python3
"""
AIM Telegram Bot — Dr. Jaba Tkemaladze
=======================================
Позволяет работать с AIM прямо из Telegram:
  • Фото анализов → OCR → диагноз
  • Текст → AI-чат (DeepSeek)
  • /patients — список пациентов
  • /analyze Фамилия — полный анализ пациента
  • /labs Фамилия — только лабораторный анализ

Запуск:
  cd ~/AIM && source venv/bin/activate && python3 telegram_bot.py

Токен: добавить в ~/.aim_env:
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_ALLOWED_ID=...  (ваш Telegram user_id, опционально)
"""

import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict

# ── Path setup ────────────────────────────────────────────────
AIM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AIM_DIR)

from config import PATIENTS_DIR, INBOX_DIR, get_logger
from llm import ask_llm, ask_deep
from audit_log import audit

log = get_logger("telegram_bot")


# ── Language detection ────────────────────────────────────────

def detect_lang(text: str) -> str:
    """Detect language: 'ka' (Georgian), 'ru' (Russian), 'en' (English/default)."""
    if not text:
        return "en"
    geo = len(re.findall(r'[\u10D0-\u10FF\u10A0-\u10CF]', text))
    rus = len(re.findall(r'[\u0400-\u04FF]', text))
    if geo > rus and geo > 2:
        return "ka"
    if rus > geo and rus > 2:
        return "ru"
    return "en"


# ── Multilingual messages ─────────────────────────────────────

MSG = {
    "start": {
        "ka": (
            "🤖 *მე ვარ ბოტი* — ხელოვნური ინტელექტის ასისტენტი.\n"
            "მე ვარ პროგრამა, არა ექიმი. თქვენი შეტყობინებებს გადავცემ "
            "ინტეგრაციული მედიცინის ექიმ ჯაბა თქემალაძეს.\n\n"
            "📋 შეგიძლიათ:\n"
            "• გამომიგზავნეთ ანალიზების ფოტო ან PDF\n"
            "• დაწერეთ თქვენი ჩივილები\n"
            "• გამომიგზავნეთ ხმოვანი შეტყობინება\n\n"
            "⚠️ ეს არ არის სასწრაფო სამედიცინო დახმარება."
        ),
        "ru": (
            "🤖 *Я — бот*, программа искусственного интеллекта.\n"
            "Я не врач. Ваши сообщения передаются врачу интегративной медицины "
            "Джабе Ткемаладзе для анализа.\n\n"
            "📋 Вы можете:\n"
            "• Отправить фото или PDF анализов\n"
            "• Описать ваши жалобы текстом\n"
            "• Отправить голосовое сообщение\n\n"
            "⚠️ Это не служба скорой помощи."
        ),
        "en": (
            "🤖 *I am a bot* — an artificial intelligence assistant.\n"
            "I am not a doctor. Your messages are forwarded to integrative medicine "
            "physician Dr. Jaba Tkemaladze for analysis.\n\n"
            "📋 You can:\n"
            "• Send photos or PDFs of your lab results\n"
            "• Describe your symptoms in text\n"
            "• Send a voice message\n\n"
            "⚠️ This is not an emergency medical service."
        ),
    },
    "thinking": {"ka": "🤔 ვფიქრობ...", "ru": "🤔 Думаю...", "en": "🤔 Thinking..."},
    "ocr_start": {"ka": "🔍 ვამუშავებ სურათს...", "ru": "🔍 OCR обработка...", "en": "🔍 Processing image..."},
    "ocr_fail": {
        "ka": "ვერ ამოვიკითხე ტექსტი. სცადეთ უფრო მკაფიო ფოტო.",
        "ru": "Не удалось распознать текст. Попробуйте более чёткое фото.",
        "en": "Could not read the text. Please try a clearer photo.",
    },
    "analyzing": {"ka": "🧠 ვაანალიზებ...", "ru": "🧠 Анализирую...", "en": "🧠 Analysing..."},
    "voice_start": {"ka": "🎙 ვამუშავებ ხმოვანს...", "ru": "🎙 Распознаю голос...", "en": "🎙 Transcribing voice..."},
    "voice_fail": {
        "ka": "ვერ ამოვიცანი მეტყველება.",
        "ru": "Не удалось распознать речь.",
        "en": "Could not transcribe speech.",
    },
    "you_said": {"ka": "🗣 *თქვენ თქვით:*\n", "ru": "🗣 *Вы сказали:*\n", "en": "🗣 *You said:*\n"},
    "pdf_start": {"ka": "📄 ვამუშავებ PDF-ს...", "ru": "📄 Извлекаю текст из PDF...", "en": "📄 Extracting PDF text..."},
    "pdf_empty": {
        "ka": "PDF ცარიელია ან ტექსტი არ შეიცავს.",
        "ru": "PDF пустой или не содержит текста.",
        "en": "PDF is empty or contains no text.",
    },
    "pdf_extracted": {
        "ka": lambda n: f"📝 *{n} სიმბოლო ამოღებულია.* ვაანალიზებ...",
        "ru": lambda n: f"📝 *Извлечено {n} символов.* Анализирую...",
        "en": lambda n: f"📝 *Extracted {n} characters.* Analysing...",
    },
    "rate_limit": {
        "ka": "⏳ ცოტა მოიცადეთ შემდეგ მოთხოვნამდე.",
        "ru": "⏳ Подождите немного перед следующим запросом.",
        "en": "⏳ Please wait a moment before the next request.",
    },
    "unsupported_file": {
        "ka": "მხარდაჭერილია PDF და ფოტო.",
        "ru": "Поддерживаются PDF и фото.",
        "en": "Supported formats: PDF and photos.",
    },
    "error": {"ka": "❌ შეცდომა: ", "ru": "❌ Ошибка: ", "en": "❌ Error: "},
    "ocr_text_header": {
        "ka": "📝 *ამოღებული ტექსტი:*\n```\n",
        "ru": "📝 *Распознанный текст:*\n```\n",
        "en": "📝 *Recognised text:*\n```\n",
    },
}


def t(key: str, lang: str, *args) -> str:
    """Translate message key to lang."""
    v = MSG.get(key, {}).get(lang) or MSG.get(key, {}).get("en", key)
    if callable(v):
        return v(*args)
    return v


def lang_instruction(lang: str) -> str:
    """System prompt addition to force response language."""
    return {
        "ka": "პასუხი გასცი მხოლოდ ქართულად.",
        "ru": "Отвечай только на русском языке.",
        "en": "Respond only in English.",
    }.get(lang, "")


# ── Config ────────────────────────────────────────────────────

def _load_env():
    env = {}
    env_file = os.path.expanduser("~/.aim_env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_env = _load_env()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _env.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_ID = os.environ.get("TELEGRAM_ALLOWED_ID") or _env.get("TELEGRAM_ALLOWED_ID", "")

# ── Rate limiting ──────────────────────────────────────────────
_RATE_LIMIT_SEC = 10        # min seconds between requests per user
_rate_last: Dict[int, float] = {}

def _check_rate(user_id: int) -> bool:
    """Returns True if request is allowed, False if throttled."""
    now = time.monotonic()
    last = _rate_last.get(user_id, 0.0)
    if now - last < _RATE_LIMIT_SEC:
        return False
    _rate_last[user_id] = now
    return True

# ── Whisper singleton ──────────────────────────────────────────
_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper as _whisper
        _whisper_model = _whisper.load_model("base")
    return _whisper_model


# ── Helpers ───────────────────────────────────────────────────

def list_patients():
    docs = Path(PATIENTS_DIR)
    result = []
    if not docs.exists():
        return result
    for d in sorted(docs.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name != "INBOX":
            parts = d.name.split("_")
            if len(parts) >= 2:
                result.append({
                    "folder": str(d),
                    "name": f"{parts[0]} {parts[1]}",
                    "folder_name": d.name,
                    "has_analysis": (d / "_ai_analysis.txt").exists(),
                })
    return result


def read_analysis(folder_path: str) -> str:
    f = Path(folder_path) / "_ai_analysis.txt"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    return "Анализ не найден. Нужно обработать пациента."


def run_labs(folder_path: str) -> str:
    """Quick lab analysis — Bayesian + R1."""
    from pathlib import Path
    folder = Path(folder_path)
    all_text = ""
    for f in list(folder.glob("*_text.txt")) + list(folder.glob("*_ocr.txt")):
        all_text += f.read_text(encoding="utf-8", errors="replace") + "\n"
    if not all_text.strip():
        return "Нет обработанных данных. Сначала загрузите файлы пациента."
    try:
        from lab_parser import extract_from_text
        from diagnosis_engine import run_diagnosis_ai
        results = extract_from_text(all_text)
        if not results:
            return "Лабораторные показатели не найдены."
        lines = ["📊 *ЛАБОРАТОРНЫЕ ПОКАЗАТЕЛИ*\n"]
        for r in results:
            icon = {"normal": "✓", "low": "↓", "high": "↑",
                    "critical_low": "⚠↓", "critical_high": "⚠↑"}.get(r.status, "?")
            interp = getattr(r, "interpretation", None) or r.status
            lines.append(f"`{icon} {r.param_id}: {r.value} {r.unit}` — {interp}")
        patient_name = " ".join(folder.name.split("_")[:2])
        dx = run_diagnosis_ai(results, patient_name=patient_name)
        lines.append("\n" + dx)
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка: {e}"


def ocr_image(image_path: str) -> str:
    try:
        from ocr_engine import ocr_image as _ocr
        return _ocr(image_path)
    except Exception as e:
        return f"[OCR error: {e}]"


def analyze_ocr_text(text: str, lang: str = "ru") -> str:
    """Send OCR'd text to AI for medical analysis."""
    from medical_system import SYSTEM_PROMPT
    prompt = f"""Medical document received. OCR text:

{text[:3000]}

Extract lab values, flag abnormal results, give a brief clinical summary."""
    system = SYSTEM_PROMPT + "\n\n" + lang_instruction(lang)
    return ask_llm(prompt, system=system, max_tokens=1500)


# ── Bot ───────────────────────────────────────────────────────

async def main():
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не задан в ~/.aim_env")
        print("   Получить токен: @BotFather в Telegram → /newbot")
        return

    from aiogram import Bot, Dispatcher, F
    from aiogram.types import Message
    from aiogram.filters import Command
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()

    # ── Auth middleware ────────────────────────────────────────
    async def is_allowed(message: Message) -> bool:
        # If ALLOWED_ID not set — allow everyone (log a warning once)
        if not ALLOWED_ID:
            return True
        uid = str(message.from_user.id) if message.from_user else ""
        return uid == str(ALLOWED_ID).strip()

    # ── /start ────────────────────────────────────────────────
    def _uid(message: Message) -> str:
        return str(message.from_user.id) if message.from_user else "unknown"

    def _uname(message: Message) -> str:
        u = message.from_user
        if not u:
            return "unknown"
        return u.username or f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id)

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        audit("start", user_id=_uid(message), details=_uname(message))
        lang = detect_lang(message.text or "")
        # Always show all 3 languages so any patient understands
        await message.answer(
            "🏥 *DrJaba — Integrative Medicine*\n\n"
            + MSG["start"]["ka"] + "\n\n―――――――――――――――\n\n"
            + MSG["start"]["ru"] + "\n\n―――――――――――――――\n\n"
            + MSG["start"]["en"]
        )
        # If Dr. Jaba — show admin hint
        uid = str(message.from_user.id) if message.from_user else ""
        if ALLOWED_ID and uid == str(ALLOWED_ID).strip():
            await message.answer(
                "👨‍⚕️ *Режим врача:*\n"
                "/patients — список пациентов\n"
                "/analyze Фамилия — полный анализ\n"
                "/labs Фамилия — лабораторный анализ\n"
                "/pdf Фамилия — скачать PDF отчёт"
            )

    # ── /patients ─────────────────────────────────────────────
    @dp.message(Command("patients"))
    async def cmd_patients(message: Message):
        if not await is_allowed(message):
            await message.answer("⛔")
            return
        audit("view_patients", user_id=_uid(message), details=_uname(message))
        patients = list_patients()
        if not patients:
            await message.answer("Пациентов не найдено.")
            return
        lines = ["👥 *Пациенты:*\n"]
        for p in patients:
            icon = "✅" if p["has_analysis"] else "⏳"
            lines.append(f"{icon} {p['name']} — `{p['folder_name']}`")
        await message.answer("\n".join(lines))

    # ── /pdf ──────────────────────────────────────────────────
    @dp.message(Command("pdf"))
    async def cmd_pdf(message: Message):
        if not await is_allowed(message):
            await message.answer("⛔")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: `/pdf Фамилия`")
            return
        query = args[1].strip().lower()
        patients = list_patients()
        matches = [p for p in patients if query in p["name"].lower() or query in p["folder_name"].lower()]
        if not matches:
            await message.answer(f"Пациент '{args[1]}' не найден.")
            return
        p = matches[0]
        audit("download_pdf", user_id=_uid(message), patient=p["folder_name"], details=_uname(message))
        await message.answer(f"📄 Генерирую PDF для {p['name']}...")
        try:
            from pdf_export import export_patient
            pdf_path = export_patient(p["folder"])
            await bot.send_document(
                message.chat.id,
                document=open(str(pdf_path), "rb"),
                filename=f"{p['folder_name']}_report.pdf",
                caption=f"📋 {p['name']}"
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # ── /analyze ─────────────────────────────────────────────
    @dp.message(Command("analyze"))
    async def cmd_analyze(message: Message):
        if not await is_allowed(message):
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: `/analyze Фамилия`")
            return
        query = args[1].strip().lower()
        patients = list_patients()
        matches = [p for p in patients if query in p["name"].lower() or query in p["folder_name"].lower()]
        if not matches:
            await message.answer(f"Пациент '{args[1]}' не найден.")
            return
        p = matches[0]
        audit("analyze_patient", user_id=_uid(message), patient=p["folder_name"], details=_uname(message))
        await message.answer(f"⏳ Обрабатываю {p['name']}...")
        try:
            from patient_intake import process_patient_folder
            result = process_patient_folder(p["folder"])
            analysis = read_analysis(p["folder"])
            # Telegram limit: 4096 chars — split if needed
            text = f"✅ *{p['name']}*\n\n{analysis}"
            for chunk in _split_text(text, 4000):
                await message.answer(chunk)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # ── /labs ─────────────────────────────────────────────────
    @dp.message(Command("labs"))
    async def cmd_labs(message: Message):
        if not await is_allowed(message):
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: `/labs Фамилия`")
            return
        query = args[1].strip().lower()
        patients = list_patients()
        matches = [p for p in patients if query in p["name"].lower() or query in p["folder_name"].lower()]
        if not matches:
            await message.answer(f"Пациент '{args[1]}' не найден.")
            return
        p = matches[0]
        audit("view_labs", user_id=_uid(message), patient=p["folder_name"], details=_uname(message))
        await message.answer(f"🔬 Анализирую лаборатории {p['name']}...")
        result = run_labs(p["folder"])
        for chunk in _split_text(result, 4000):
            await message.answer(chunk)

    # ── Photo → OCR → Analysis ────────────────────────────────
    @dp.message(F.photo)
    async def handle_photo(message: Message):
        lang = detect_lang(message.caption or "")
        uid = message.from_user.id if message.from_user else 0
        audit("send_photo", user_id=str(uid), details=_uname(message))
        if not _check_rate(uid):
            await message.answer(t("rate_limit", lang))
            return
        await message.answer(t("ocr_start", lang))
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            os.chmod(tmp_path, 0o600)
            await bot.download_file(file.file_path, destination=tmp_path)

            ocr_text = ocr_image(tmp_path)
            os.unlink(tmp_path)

            if not ocr_text or len(ocr_text) < 20:
                await message.answer(t("ocr_fail", lang))
                return

            await message.answer(t("ocr_text_header", lang) + ocr_text[:800] + "\n```")
            await message.answer(t("analyzing", lang))

            analysis = analyze_ocr_text(ocr_text, lang)
            for chunk in _split_text(analysis, 4000):
                await message.answer(chunk)

        except Exception as e:
            await message.answer(t("error", lang) + str(e))

    # ── Voice → Whisper → AI ──────────────────────────────────
    @dp.message(F.voice)
    async def handle_voice(message: Message):
        uid = message.from_user.id if message.from_user else 0
        audit("send_voice", user_id=str(uid), details=_uname(message))
        if not _check_rate(uid):
            await message.answer(t("rate_limit", "ru"))
            return
        await message.answer(t("voice_start", "ru"))
        try:
            _get_whisper()
        except ImportError:
            await message.answer("❌ Whisper не установлен: pip install openai-whisper")
            return
        try:
            file = await bot.get_file(message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_ogg:
                ogg_path = tmp_ogg.name
            os.chmod(ogg_path, 0o600)
            await bot.download_file(file.file_path, destination=ogg_path)

            wav_path = ogg_path.replace(".ogg", ".wav")
            try:
                import imageio_ffmpeg
                _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                _ffmpeg = "ffmpeg"
            ret = os.system(f'"{_ffmpeg}" -y -i "{ogg_path}" "{wav_path}" -loglevel quiet 2>/dev/null')
            audio_path = wav_path if ret == 0 and os.path.exists(wav_path) else ogg_path

            model_w = _get_whisper()
            result = model_w.transcribe(audio_path, language=None)
            text = result.get("text", "").strip()

            for p in [ogg_path, wav_path]:
                try:
                    os.unlink(p)
                except Exception:
                    pass

            if not text:
                await message.answer(t("voice_fail", "ru"))
                return

            # Detect language from transcribed text
            lang = detect_lang(text)
            await message.answer(t("you_said", lang) + text)
            await message.answer(t("thinking", lang))
            from medical_system import SYSTEM_PROMPT
            system = SYSTEM_PROMPT + "\n\n" + lang_instruction(lang)
            reply = ask_llm(text, system=system, max_tokens=1500)
            for chunk in _split_text(reply, 4000):
                await message.answer(chunk)

        except Exception as e:
            await message.answer(t("error", "ru") + str(e))

    # ── Document (PDF) ────────────────────────────────────────
    @dp.message(F.document)
    async def handle_document(message: Message):
        lang = detect_lang(message.caption or "")
        uid = message.from_user.id if message.from_user else 0
        audit("send_document", user_id=str(uid), details=f"{_uname(message)} — {message.document.file_name if message.document else ''}")
        if not _check_rate(uid):
            await message.answer(t("rate_limit", lang))
            return
        doc = message.document
        if not doc.file_name.lower().endswith(".pdf"):
            await message.answer(t("unsupported_file", lang))
            return
        await message.answer(t("pdf_start", lang))
        try:
            file = await bot.get_file(doc.file_id)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            os.chmod(tmp_path, 0o600)
            await bot.download_file(file.file_path, destination=tmp_path)

            import pdfplumber
            texts = []
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    pg = page.extract_text()
                    if pg:
                        texts.append(pg)
            os.unlink(tmp_path)
            text = "\n".join(texts)

            if not text.strip():
                await message.answer(t("pdf_empty", lang))
                return

            # Refine lang from actual document content
            lang = detect_lang(text[:500]) or lang
            await message.answer(t("pdf_extracted", lang, len(text)))
            analysis = analyze_ocr_text(text, lang)
            for chunk in _split_text(analysis, 4000):
                await message.answer(chunk)

        except Exception as e:
            await message.answer(t("error", lang) + str(e))

    # ── Text → AI chat ────────────────────────────────────────
    @dp.message(F.text)
    async def handle_text(message: Message):
        if message.text.startswith("/"):
            return
        lang = detect_lang(message.text)
        uid = message.from_user.id if message.from_user else 0
        audit("send_text", user_id=str(uid), details=f"{_uname(message)}: {message.text[:80]}")
        if not _check_rate(uid):
            await message.answer(t("rate_limit", lang))
            return
        await message.answer(t("thinking", lang))
        try:
            from medical_system import SYSTEM_PROMPT
            system = SYSTEM_PROMPT + "\n\n" + lang_instruction(lang)
            reply = ask_llm(message.text, system=system, max_tokens=1500)
            for chunk in _split_text(reply, 4000):
                await message.answer(chunk)
        except Exception as e:
            await message.answer(t("error", lang) + str(e))

    # ── Start polling ─────────────────────────────────────────
    print("🤖 AIM Telegram Bot запущен. Ctrl+C для остановки.")
    await dp.start_polling(bot)


def _split_text(text: str, max_len: int) -> list:
    """Split long text into chunks for Telegram."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:          # no newline found — hard split to avoid infinite loop
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


if __name__ == "__main__":
    asyncio.run(main())
