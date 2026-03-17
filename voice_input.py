#!/usr/bin/env python3
"""
AIM — Local Voice Input
=======================
Запись с микрофона → Whisper → текст.
Используется из aim_gui.py (кнопка 🎙 в чате).

Зависимости:
  pip install sounddevice numpy openai-whisper
"""

import io
import os
import threading
import tempfile
from pathlib import Path

from config import get_logger

log = get_logger("voice_input")

# Параметры записи
SAMPLE_RATE = 16000   # Whisper ожидает 16kHz
CHANNELS    = 1
MAX_SECONDS = 30      # максимальная длина записи

# Singleton Whisper model
_model = None
_model_lock = threading.Lock()


def _get_model(model_name: str = "base"):
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import whisper
                log.info("Loading Whisper model '%s'...", model_name)
                _model = whisper.load_model(model_name)
                log.info("Whisper model loaded.")
    return _model


class VoiceRecorder:
    """
    Записывает аудио с микрофона пока удерживается кнопка (push-to-talk).
    Возвращает транскрибированный текст.
    """

    def __init__(self):
        self._frames = []
        self._recording = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Начать запись (вызывать при нажатии кнопки)."""
        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError("sounddevice не установлен: pip install sounddevice")

        self._frames = []
        self._recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        log.debug("Recording started")

    def stop_and_transcribe(self, model_name: str = "base") -> str:
        """
        Остановить запись и вернуть транскрибированный текст.
        Блокирует до завершения транскрипции.
        """
        self._recording = False
        if hasattr(self, "_stream"):
            self._stream.stop()
            self._stream.close()

        if not self._frames:
            return ""

        import numpy as np
        audio = np.concatenate(self._frames, axis=0).flatten()

        if len(audio) < SAMPLE_RATE * 0.3:  # < 0.3 сек — слишком короткий
            return ""

        # Записать в temp wav
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()
        os.chmod(tmp_path, 0o600)

        try:
            import soundfile as sf
            sf.write(tmp_path, audio, SAMPLE_RATE)
        except ImportError:
            # Fallback: scipy
            try:
                from scipy.io import wavfile
                import numpy as np
                audio_int = (audio * 32767).astype(np.int16)
                wavfile.write(tmp_path, SAMPLE_RATE, audio_int)
            except ImportError:
                _write_wav_raw(tmp_path, audio, SAMPLE_RATE)

        try:
            model = _get_model(model_name)
            result = model.transcribe(tmp_path, language=None, fp16=False)
            text = result.get("text", "").strip()
            log.debug("Transcribed: %s", text[:100])
            return text
        except Exception as e:
            log.error("Transcription error: %s", e)
            return f"[Ошибка транскрипции: {e}]"
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            import numpy as np
            self._frames.append(indata.copy())


def _write_wav_raw(path: str, audio, sample_rate: int):
    """Minimal WAV writer без scipy/soundfile."""
    import struct
    import numpy as np
    audio_int = (audio * 32767).astype(np.int16)
    data = audio_int.tobytes()
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                            sample_rate * 2, 2, 16))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)
