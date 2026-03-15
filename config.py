#!/usr/bin/env python3
"""
AIM — Central configuration.
All other modules import constants from here.
"""

import os
import logging
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────
AIM_DIR      = os.path.dirname(os.path.abspath(__file__))
PATIENTS_DIR = os.path.expanduser("~/AIM/Patients")
INBOX_DIR    = os.path.join(PATIENTS_DIR, "INBOX")
LOGS_DIR     = os.path.join(AIM_DIR, "logs")
KNOWLEDGE_FILE = os.path.join(AIM_DIR, "medical_knowledge.json")
PROCESSED_LOG  = os.path.join(AIM_DIR, "processed_files.json")

# ── LLM ───────────────────────────────────────────────────────
MODEL         = "llama3.2"          # change here → applies everywhere
MODEL_FAST    = "llama3.2"          # lightweight tasks
MODEL_DEEP    = "deepseek-r1:7b"    # deep analysis (slower)

# ── OCR ───────────────────────────────────────────────────────
OCR_LANGS     = "rus+kat+eng"       # tesseract language string
OCR_MIN_DPI   = 300                 # upscale images below this

# ── WhatsApp CDP ──────────────────────────────────────────────
CDP_PORT      = 9222
CDP_HOST      = f"http://localhost:{CDP_PORT}"
WA_BINARY     = "/home/oem/whatsapp-desktop-linux/build/linux-unpacked/whatsapp-desktop-linux"

# ── Logging ───────────────────────────────────────────────────
os.makedirs(LOGS_DIR, exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    """Return a configured logger that writes to both console and file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")

    # File handler
    fh = logging.FileHandler(os.path.join(LOGS_DIR, "aim.log"),
                              encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler (INFO and above)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
