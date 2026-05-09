#!/usr/bin/env python3
"""
Транскрибация диалога с пациентом в текстовый файл.
Поддерживает русский, грузинский (ka), английский.

Возможности:
  • VAD (Silero) — отсев тишины и шума перед распознаванием
  • Грузинский медицинский словарь — промпт для точности терминов
  • DeepSeek пост-обработка — исправление ошибок распознавания
  • Непрерывный или интерактивный режим

Использование:
  python transcribe_patient.py --lang ka                          # грузинский
  python transcribe_patient.py --lang ka --fix --model large-v3-turbo  # + DeepSeek
  python transcribe_patient.py --lang ru                          # русский
  python transcribe_patient.py --lang auto                        # авто
  python transcribe_patient.py --list-devices                     # микрофоны
"""

import argparse
import json
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
import torch
import whisper

# ─── конфиг ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "turbo"
SAMPLE_RATE = 16000
CHUNK_SECONDS = 20
SILENCE_THRESHOLD = 0.015
VAD_THRESHOLD = 0.5             # Silero VAD: порог уверенности (0-1)
OUTPUT_DIR = Path("patient_intake/transcripts")
DICT_PATH = Path("ka_medical_dict.json")

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
vad_model = None
ka_dict = {}
args = None


def load_ka_dict():
    """Загрузить грузинский медицинский словарь."""
    global ka_dict
    try:
        if DICT_PATH.exists():
            with open(DICT_PATH, "r", encoding="utf-8") as f:
                ka_dict = json.load(f)
            print(f"   Словарь: загружен ({len(ka_dict)} разделов)")
            # Собираем промпт для Whisper из словаря
            prompt_parts = []
            if "whisper_prompt" in ka_dict:
                prompt_parts.append(ka_dict["whisper_prompt"])
            if "common_phrases" in ka_dict:
                prompt_parts.append(". ".join(ka_dict["common_phrases"][:5]))
            # Все термины компактно
            terms = []
            for cat in ka_dict.get("medical_terms", {}).values():
                terms.extend(cat[:10])
            if terms:
                prompt_parts.append(". ".join(terms))
            # Имена (первые 20)
            names = []
            for g in ka_dict.get("common_names", {}).values():
                names.extend(g[:10])
            if names:
                prompt_parts.append(". ".join(names))

            ka_dict["_whisper_prompt"] = ". ".join(prompt_parts)
            return True
    except Exception as e:
        print(f"   ⚠ Словарь: ошибка загрузки — {e}")
    ka_dict = {}
    return False


def list_microphones():
    devices = sd.query_devices()
    print("\n🎤 Доступные микрофоны:")
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            print(f"  [{i}] {dev['name']}")
            print(f"      каналов: {dev['max_input_channels']}, "
                  f"частота: {int(dev['default_samplerate'])} Hz")
    print()


def audio_callback(indata, frames, time_info, status):
    global recording, audio_buffer
    if recording:
        audio_buffer.append(indata.copy())


def init_vad():
    """Инициализировать Silero VAD."""
    global vad_model
    try:
        vad_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        print(f"   VAD: Silero (подавление шума/тишины)")
        return True
    except Exception as e:
        print(f"   VAD: не загружен — {e}")
        return False


def apply_vad(audio_float):
    """Применить VAD: вернуть только речевые сегменты."""
    global vad_model
    if vad_model is None:
        return audio_float

    try:
        # Конвертируем в тензор
        audio_tensor = torch.from_numpy(audio_float).float()

        # Silero VAD ожидает батчи по ~512 сэмплов
        speech_frames = []
        window_size = 512  # 32ms at 16kHz
        step = 256  # 50% overlap

        for i in range(0, len(audio_tensor) - window_size, step):
            chunk = audio_tensor[i:i + window_size]
            if len(chunk) < window_size:
                break
            prob = vad_model(chunk, SAMPLE_RATE).item()
            if prob >= VAD_THRESHOLD:
                speech_frames.append(chunk)

        if not speech_frames:
            return np.array([], dtype=np.float32)

        return np.concatenate(speech_frames)
    except Exception as e:
        return audio_float  # fallback


def _fix_text_with_deepseek(text, lang_code, lang_name):
    """Пост-обработка DeepSeek: исправление ошибок распознавания."""
    if not text or len(text) < 3:
        return text

    system_prompt = (
        f"Ты — корректор медицинской транскрибации. "
        f"Исправь ошибки в распознанном тексте на {lang_name} языке. "
        f"Сохрани смысл, исправь опечатки, транскрипционные ошибки. "
        f"Не добавляй лишнего. Верни только исправленный текст."
    )

    # Добавляем контекст из словаря для грузинского
    dict_context = ""
    if lang_code == "ka" and ka_dict:
        terms = []
        for cat in ka_dict.get("medical_terms", {}).values():
            terms.extend(cat[:10])
        names = []
        for g in ka_dict.get("common_names", {}).values():
            names.extend(g[:10])
        dict_context = f"\nСловарь терминов: {', '.join(terms[:20])}\nСловарь имён: {', '.join(names[:20])}"

    prompt = system_prompt + dict_context + f"\n\nТекст: {text}"

    try:
        result = subprocess.run(
            [
                sys.executable, "-c", f"""
import os, json, urllib.request
key = os.environ.get('DEEPSEEK_API_KEY', os.popen('bash -c "source ~/.aim_env 2>/dev/null && echo $DEEPSEEK_API_KEY"').read().strip())
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
        print(f"  ⚠ DeepSeek: {e}")

    return text


def transcribe_chunk(audio_data, model, lang="ru", fix=False, use_vad=True):
    """Транскрибация аудио-чанка с VAD и словарём."""
    if len(audio_data) == 0:
        return "", lang

    audio_float = np.concatenate(audio_data, axis=0).flatten()

    # VAD: отсекаем тишину/шум
    if use_vad:
        audio_float = apply_vad(audio_float)

    if len(audio_float) < SAMPLE_RATE * 0.3:  # меньше 0.3 сек
        return "", lang

    # Нормализация
    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val

    # Проверка RMS
    rms = np.sqrt(np.mean(audio_float ** 2))
    if rms < SILENCE_THRESHOLD:
        return "", lang

    # Опции транскрибации
    opts = {"fp16": False}
    if lang != "auto":
        opts["language"] = lang
    else:
        opts["language"] = None

    # Промпт из словаря (для грузинского)
    if lang == "ka" and ka_dict and ka_dict.get("_whisper_prompt"):
        opts["initial_prompt"] = ka_dict["_whisper_prompt"]

    result = model.transcribe(audio_float, **opts)
    text = result.get("text", "").strip()
    detected = result.get("language", lang)

    # Пост-обработка DeepSeek
    if fix and text and lang == "ka":
        print(f"  🔧 DeepSeek...", end=" ", flush=True)
        text = _fix_text_with_deepseek(text, lang, "грузинском")
        print(f"✓", end="", flush=True)

    return text, detected if lang == "auto" else lang


def save_transcript():
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
        if args.vad:
            f.write("VAD: Silero (подавление шума)\n")
        if args.fix:
            f.write("Пост-обработка: DeepSeek\n")
        if args.lang == "ka" and ka_dict:
            f.write("Словарь: грузинский медицинский\n")
        f.write(f"{'='*60}\n\n")
        for line in transcript_lines:
            f.write(line + "\n")

    return output_file


def record_loop(model):
    """Фоновый поток: запись + транскрибация."""
    global recording, audio_buffer, transcript_lines, stop_program, args

    lang = args.lang
    fix = args.fix
    use_vad = args.vad
    lang_name = WHISPER_LANGS.get(lang, lang)

    print(f"\n🎤 Режим: {'Enter — старт/стоп' if not args.continuous else 'непрерывная запись'}")
    print(f"   Модель: whisper-{args.model}  |  Язык: {lang_name}")
    if use_vad:
        print(f"   VAD: активен (шумоподавление)")
    if fix:
        print(f"   DeepSeek: коррекция распознавания")
    print(f"   Выход: Ctrl+C\n")

    last_transcript_time = time.time()

    while not stop_program:
        if recording:
            elapsed = time.time() - last_transcript_time
            if elapsed >= args.chunk:
                if audio_buffer:
                    print("  🧠 Распознаю...", end=" ", flush=True)
                    text, detected = transcribe_chunk(
                        audio_buffer, model, lang, fix, use_vad
                    )
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
    global recording, audio_buffer, args
    recording = not recording
    audio_buffer = []
    if recording:
        print("\n🔴 Запись НАЧАТА")
    else:
        print("\n⏸️  Пауза")
        if audio_buffer:
            print("  🧠 Распознаю остаток...", end=" ", flush=True)
            text, detected = transcribe_chunk(
                audio_buffer, model, args.lang, args.fix, args.vad
            )
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
        description="Транскрибация диалога с пациентом. "
                    "VAD, словарь, DeepSeek для грузинского."
    )
    parser.add_argument("--patient", "-p", default="patient", help="Имя пациента")
    parser.add_argument("--lang", "-l", default="ru",
                        choices=list(WHISPER_LANGS.keys()),
                        help="Язык: ru (русский), ka (грузинский), en, auto")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        choices=["tiny", "base", "small", "medium",
                                 "large", "large-v3", "large-v3-turbo", "turbo"],
                        help="Модель Whisper")
    parser.add_argument("--fix", action="store_true",
                        help="Пост-обработка DeepSeek (рекомендуется для ka)")
    parser.add_argument("--vad", action="store_true", default=True,
                        help="VAD шумоподавление (вкл по умолчанию)")
    parser.add_argument("--no-vad", action="store_false", dest="vad",
                        help="Отключить VAD")
    parser.add_argument("--dict", action="store_true", default=True,
                        help="Грузинский медицинский словарь (вкл по умолчанию)")
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

    if args.list_devices:
        list_microphones()
        return

    # Загрузка словаря
    dict_loaded = False
    if args.lang == "ka" and args.dict:
        dict_loaded = load_ka_dict()

    # VAD
    vad_loaded = False
    if args.vad:
        vad_loaded = init_vad()

    model_name = args.model
    print(f"\n{'='*60}")
    print(f"🩺 Транскрибатор диалога с пациентом")
    print(f"{'='*60}")
    print(f"   Пациент: {current_patient}")
    print(f"   Модель:  whisper-{model_name}")
    print(f"   Язык:    {WHISPER_LANGS.get(args.lang, args.lang)}")
    if args.vad and vad_loaded:
        print(f"   VAD:     ✅ шумоподавление")
    if args.fix:
        print(f"   DeepSeek: ✅ коррекция распознавания")
    if dict_loaded:
        print(f"   Словарь:  ✅ грузинский медицинский")

    print(f"\n🔄 Загрузка whisper-{model_name} (первый раз ~минута)...")
    model = whisper.load_model(model_name)
    print(f"✅ Модель готова")

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
    transcriber = threading.Thread(target=record_loop, args=(model,), daemon=True)
    transcriber.start()

    # Управление
    try:
        if not args.continuous:
            print("\n⌨️  Enter — старт/стоп, Ctrl+C — сохранить и выйти\n")
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

    stream.stop()
    stream.close()

    result = save_transcript()
    if result:
        print(f"\n📄 Файл: {result}")
        print(f"📝 Строк: {len(transcript_lines)}")

    if transcript_lines:
        print(f"\n{'='*60}")
        print(f"📋 Последние строки:")
        print(f"{'='*60}")
        for line in transcript_lines[-10:]:
            print(f"  {line}")

    print(f"\n✅ Готово!")


if __name__ == "__main__":
    main()
