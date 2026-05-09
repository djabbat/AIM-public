"""agents/voice.py — local voice in/out for AIM.

ASR (speech-to-text):
    • faster-whisper if installed (default model: base; AIM_WHISPER_MODEL)
    • OpenAI Whisper API if `OPENAI_API_KEY` is set (fallback)

TTS (text-to-speech):
    • pyttsx3 (offline, native voices)
    • espeak-ng via subprocess (last-resort fallback)

Optional deps:
    pip install faster-whisper sounddevice numpy
    pip install pyttsx3
    sudo apt install espeak-ng              # fallback TTS

CLI:
    aim-voice listen --duration 6     # capture 6s, transcribe, print text
    aim-voice say "привет"            # speak text
    aim-voice run                     # listen → ask aim-graph → speak the result
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.voice")

WHISPER_MODEL  = os.getenv("AIM_WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("AIM_WHISPER_DEVICE", "cpu")
SAMPLE_RATE    = int(os.getenv("AIM_VOICE_SR", "16000"))


# ── ASR ────────────────────────────────────────────────────────────────────


def record(duration: float = 5.0, sample_rate: int = SAMPLE_RATE) -> Path:
    """Record from default mic into a temp WAV; return its path."""
    try:
        import sounddevice as sd
        import numpy as np
        import wave
    except ImportError as e:
        raise RuntimeError("pip install sounddevice numpy") from e

    print(f"🎤 recording {duration:.1f}s…", file=sys.stderr)
    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                   channels=1, dtype="int16")
    sd.wait()
    out = Path(tempfile.gettempdir()) / f"aim_rec_{os.getpid()}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio.tobytes())
    return out


def transcribe(audio_path: Path, language: Optional[str] = None) -> str:
    """Try faster-whisper local first, then OpenAI API."""
    # Local
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8")
        segments, _ = m.transcribe(str(audio_path), language=language, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    except ImportError:
        log.info("faster-whisper not installed, trying OpenAI Whisper API")
    except Exception as e:
        log.warning(f"local ASR failed: {e}")

    # API fallback
    try:
        from openai import OpenAI
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("set OPENAI_API_KEY for ASR fallback")
        cl = OpenAI(api_key=key)
        with open(audio_path, "rb") as fh:
            resp = cl.audio.transcriptions.create(model="whisper-1", file=fh)
        return resp.text.strip()
    except Exception as e:
        log.error(f"ASR failed: {e}")
        return ""


# ── TTS ────────────────────────────────────────────────────────────────────


def speak(text: str, lang: str = "ru") -> None:
    if not text:
        return
    # 1. pyttsx3
    try:
        import pyttsx3
        engine = pyttsx3.init()
        # Try to pick a voice that matches lang
        for v in engine.getProperty("voices"):
            if lang in (v.languages[0].decode() if v.languages else ""):
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
        return
    except Exception as e:
        log.info(f"pyttsx3 unavailable: {e}; trying espeak-ng")

    # 2. espeak-ng
    if subprocess.run(["which", "espeak-ng"], capture_output=True).returncode == 0:
        subprocess.run(["espeak-ng", "-v", lang, text[:5000]],
                       capture_output=True)
        return

    log.warning("no TTS engine available; install pyttsx3 or espeak-ng")


# ── End-to-end run ─────────────────────────────────────────────────────────


def voice_round_trip(duration: float = 5.0) -> str:
    """Record → transcribe → run aim-graph → speak result. Returns the text result."""
    audio = record(duration=duration)
    text = transcribe(audio)
    audio.unlink(missing_ok=True)
    if not text:
        speak("Не распознал, повтори.")
        return ""
    print(f"🎤 → {text}")
    try:
        from agents.graph import run_agent
        result = run_agent(text, use_memory=True)
        review = result.get("review", "") or "\n\n".join(result.get("step_results", []))
        speak(review[:600])
        return review
    except Exception as e:
        log.error(f"agent failed: {e}")
        speak(f"Ошибка: {e}")
        return ""


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-voice")
    sub = p.add_subparsers(dest="cmd", required=True)
    L = sub.add_parser("listen")
    L.add_argument("--duration", type=float, default=5.0)
    L.add_argument("--lang", default=None)
    S = sub.add_parser("say")
    S.add_argument("text")
    S.add_argument("--lang", default="ru")
    R = sub.add_parser("run")
    R.add_argument("--duration", type=float, default=5.0)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "listen":
        audio = record(duration=args.duration)
        text = transcribe(audio, language=args.lang)
        audio.unlink(missing_ok=True)
        print(text)
    elif args.cmd == "say":
        speak(args.text, lang=args.lang)
    elif args.cmd == "run":
        voice_round_trip(duration=args.duration)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
