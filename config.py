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
PATIENTS_DIR = os.path.expanduser("~/Desktop/AIM/Patients")
INBOX_DIR    = os.path.join(PATIENTS_DIR, "INBOX")
LOGS_DIR     = os.path.join(AIM_DIR, "logs")
KNOWLEDGE_FILE = os.path.join(AIM_DIR, "medical_knowledge.json")
PROCESSED_LOG  = os.path.join(AIM_DIR, "processed_files.json")
DB_PATH        = os.path.join(AIM_DIR, "aim.db")

# ── LLM ───────────────────────────────────────────────────────
# DeepSeek API — set key in ~/.aim_env:  DEEPSEEK_API_KEY=sk-...
MODEL         = "deepseek-chat"     # DeepSeek V3 (fast, cheap)
MODEL_FAST    = "deepseek-chat"     # lightweight tasks
MODEL_DEEP    = "deepseek-reasoner" # DeepSeek R1 (deep reasoning)

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
