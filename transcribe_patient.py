#!/usr/bin/env python3
"""
Транскрибация диалога с пациентом в текстовый файл.
Поддерживает русский, грузинский (ka), английский и другие языки Whisper.

Использование:
  python transcribe_patient.py                                    # русский, turbo
  python transcribe_patient.py --lang ka                          # грузинский
  python transcribe_patient.py --lang ka --fix                    # + пост-обработка DeepSeek
  python transcribe_patient.py --patient "გიორგი" --lang ka       # пациент გიორგი
  python transcribe_patient.py --lang auto                        # автоопределение языка
  python transcribe_patient.py --list-devices                     # список микрофонов

Горячие клавиши:
  Enter — начать/остановить запись
  Ctrl+C — завершить и сохранить
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import whisper

# ─── конфиг ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "turbo"           # turbo — оптимально по скорости/качеству
SAMPLE_RATE = 16000               # Hz (Whisper)
CHUNK_SECONDS = 20                # длительность чанка для транскрибации
SILENCE_THRESHOLD = 0.01          # порог тишины (RMS)
OUTPUT_DIR = Path("patient_intake/transcripts")

# Языки Whisper: код → название
WHISPER_LANGS = {
    "ru": "russian", "ka": "georgian", "en": "english",
    "de": "german", "fr": "french", "es": "spanish",
    "it": "italian", "tr": "turkish", "auto": "auto",
}

recording = False
stop_program = False
audio_buffer = []
transcript_lines = []
current_patient = "patient"
output_file = None
model = None
args = None


def list_microphones():
    """Показать доступные микрофоны."""
    devices = sd.query_devices()
    print("\n🎤 Доступные микрофоны:")
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            print(f"  [{i}] {dev['name']}")
            print(f"      каналов: {dev['max_input_channels']}, "
                  f"частота: {int(dev['default_samplerate'])} Hz")
    print()


def audio_callback(indata, frames, time_info, status):
    """Колбэк: собираем аудио в буфер."""
    global recording, audio_buffer
    if recording:
        audio_buffer.append(indata.copy())


def _fix_text_with_deepseek(text, lang_code, lang_name):
    """Пост-обработка: DeepSeek исправляет ошибки распознавания."""
    if not text or len(text) < 3:
        return text

    prompt = (
        f"Ты — корректор автоматического распознавания речи. "
        f"Исправь ошибки в следующем тексте на {lang_name} языке. "
        f"Сохрани смысл, исправь только явные опечатки/транскрипционные ошибки. "
        f"Не добавляй лишнего. Верни только исправленный текст.\n\n"
        f"Текст: {text}"
    )

    try:
        result = subprocess.run(
            [
                sys.executable, "-c", f"""
import os, json, urllib.request
key = os.environ.get('DEEPSEEK_API_KEY', '')
if not key:
    key = open(os.path.expanduser('~/.aim_env')).read().strip().split('=')[1].split()[0]
data = json.dumps({{
    "model": "deepseek-chat",
    "messages": [{{"role": "user", "content": {json.dumps(prompt)}}}],
    "temperature": 0.1,
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
            env={**os.environ, "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", "")},
        )
        fixed = result.stdout.strip()
        if fixed and len(fixed) > 2:
            return fixed
    except Exception as e:
        print(f"  ⚠ DeepSeek: {e}")

    return text


def transcribe_chunk(audio_data, model, lang="ru", fix=False):
    """Транскрибация одного аудио-чанка."""
    if len(audio_data) == 0:
        return ""

    audio_float = np.concatenate(audio_data, axis=0).flatten()

    # Нормализация
    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val

    # Проверка на тишину
    rms = np.sqrt(np.mean(audio_float ** 2))
    if rms < SILENCE_THRESHOLD:
        return ""

    # Опции транскрибации
    opts = {"fp16": False}
    if lang != "auto":
        opts["language"] = lang
    else:
        opts["language"] = None  # автоопределение

    result = model.transcribe(audio_float, **opts)
    text = result.get("text", "").strip()
    detected = result.get("language", lang)

    # Пост-обработка DeepSeek для грузинского
    if fix and text and lang == "ka":
        lang_name = WHISPER_LANGS.get(lang, lang)
        print(f"  🔧 DeepSeek исправляет...", end=" ", flush=True)
        text = _fix_text_with_deepseek(text, lang, lang_name)
        print(f"✓")

    return text, detected if lang == "auto" else lang


def save_transcript():
    """Сохранить транскрипт в файл."""
    global output_file, transcript_lines

    if not transcript_lines:
        print("  (пусто)")
        return None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = current_patient.replace(" ", "_").lower()
    output_file = output_dir / f"{safe_name}_{timestamp}.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Пациент: {current_patient}\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Язык: {WHISPER_LANGS.get(args.lang, args.lang)}\n")
        f.write(f"Модель: whisper-{args.model}\n")
        if args.fix:
            f.write("Пост-обработка: DeepSeek\n")
        f.write(f"{'='*60}\n\n")
        for line in transcript_lines:
            f.write(line + "\n")

    return output_file


def record_and_transcribe_loop(model):
    """Главный цикл: запись → транскрибация порциями."""
    global recording, audio_buffer, transcript_lines, stop_program, args

    lang = args.lang
    fix = args.fix
    lang_name = WHISPER_LANGS.get(lang, lang)

    print(f"\n🎤 Режим: {'Enter — старт/стоп' if not args.continuous else 'непрерывная запись'}")
    print(f"   Модель: whisper-{args.model}  |  Язык: {lang_name}")
    if fix:
        print(f"   Пост-обработка: DeepSeek (коррекция распознавания)")
    print(f"   Выход: Ctrl+C\n")

    last_transcript_time = time.time()

    while not stop_program:
        if recording:
            elapsed = time.time() - last_transcript_time
            if elapsed >= CHUNK_SECONDS:
                if audio_buffer:
                    print("  🧠 Распознаю...", end=" ", flush=True)
                    text, detected = transcribe_chunk(audio_buffer, model, lang, fix)
                    audio_buffer = []

                    if text:
                        ts = datetime.now().strftime("%H:%M:%S")
                        detected_str = f" [{detected}]" if lang == "auto" else ""
                        line = f"[{ts}]{detected_str} {text}"
                        transcript_lines.append(line)
                        print(f"✓\n  {text}")
                    else:
                        print("—")

                last_transcript_time = time.time()

        time.sleep(0.1)


def toggle_recording():
    """Переключить запись."""
    global recording, audio_buffer, args
    recording = not recording
    audio_buffer = []
    if recording:
        print("\n🔴 Запись НАЧАТА (говорите)")
    else:
        print("\n⏸️  Запись ПРИОСТАНОВЛЕНА")
        if audio_buffer:
            print("  🧠 Распознаю остаток...", end=" ", flush=True)
            text, detected = transcribe_chunk(audio_buffer, model, args.lang, args.fix)
            audio_buffer = []
            if text:
                ts = datetime.now().strftime("%H:%M:%S")
                line = f"[{ts}] {text}"
                transcript_lines.append(line)
                print(f"✓\n  {text}")
            else:
                print("—")


def main():
    global args, current_patient, model, stop_program

    parser = argparse.ArgumentParser(
        description="Транскрибация диалога с пациентом. Поддерживает русский, грузинский (ka) и другие языки."
    )
    parser.add_argument("--patient", "-p", default="patient", help="Имя пациента")
    parser.add_argument("--lang", "-l", default="ru",
                        choices=list(WHISPER_LANGS.keys()),
                        help="Язык: ru (русский), ka (грузинский), en, auto")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        choices=["tiny", "base", "small", "medium", "large", "turbo",
                                 "large-v3", "large-v3-turbo"],
                        help="Модель Whisper (turbo/large-v3-turbo — лучше для ka)")
    parser.add_argument("--fix", action="store_true",
                        help="Пост-обработка через DeepSeek (исправление грузинского)")
    parser.add_argument("--continuous", "-c", action="store_true",
                        help="Непрерывная запись")
    parser.add_argument("--list-devices", action="store_true",
                        help="Список микрофонов")
    parser.add_argument("--device", "-d", type=int, default=None,
                        help="ID микрофона")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Папка для транскриптов")
    parser.add_argument("--chunk", type=int, default=CHUNK_SECONDS,
                        help=f"Секунд на чанк (умолч. {CHUNK_SECONDS})")
    args = parser.parse_args()
    current_patient = args.patient

    output_dir = Path(args.output_dir)

    if args.list_devices:
        list_microphones()
        return

    # Загрузка модели
    model_name = args.model
    print(f"\n{'='*60}")
    print(f"🩺 Транскрибатор диалога с пациентом")
    print(f"{'='*60}")
    print(f"   Пациент: {current_patient}")
    print(f"   Модель:  whisper-{model_name}")
    print(f"   Язык:    {WHISPER_LANGS.get(args.lang, args.lang)}")
    if args.fix:
        print(f"   Коррекция: DeepSeek")

    print(f"\n🔄 Загрузка модели whisper-{model_name} (первый раз ~минута)...")
    model = whisper.load_model(model_name)
    print(f"✅ Модель загружена")

    # Микрофон
    device = args.device
    if device is None:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                device = i
                break
    if device is None:
        print("❌ Микрофон не найден!")
        sys.exit(1)

    device_info = sd.query_devices(device)
    print(f"🎤 Микрофон: {device_info['name']} (id={device})")

    stream = sd.InputStream(
        device=device,
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    )
    stream.start()

    # Ctrl+C
    def signal_handler(sig, frame):
        global stop_program, recording
        stop_program = True
        recording = False
        print("\n\n⏹  Завершение...")
    signal.signal(signal.SIGINT, signal_handler)

    # Поток транскрибации
    transcriber = threading.Thread(target=record_and_transcribe_loop, args=(model,), daemon=True)
    transcriber.start()

    # Управление
    try:
        if not args.continuous:
            print("\n⌨️  Enter — старт/стоп записи, Ctrl+C — сохранить и выйти\n")
            while not stop_program:
                input()
                if not stop_program:
                    toggle_recording()
        else:
            print("\n🔴 Непрерывная запись (Enter — разделитель, Ctrl+C — выход)\n")
            while not stop_program:
                try:
                    input()
                    if not stop_program:
                        ts = datetime.now().strftime("%H:%M:%S")
                        transcript_lines.append(f"\n--- 📍 {ts} ---")
                        print(f"  Разделитель {ts}")
                except EOFError:
                    pass
    except (KeyboardInterrupt, SystemExit):
        pass

    # Очистка
    stream.stop()
    stream.close()

    # Сохраняем
    result = save_transcript()
    if result:
        print(f"\n📄 Файл: {result}")
        print(f"📝 Строк: {len(transcript_lines)}")

    # Показываем последние строки
    if transcript_lines:
        print(f"\n{'='*60}")
        print(f"📋 Последние строки диалога:")
        print(f"{'='*60}")
        for line in transcript_lines[-10:]:
            print(f"  {line}")

    print(f"\n✅ Готово!")


if __name__ == "__main__":
    main()
