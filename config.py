"""
AIM v7.0 — Configuration
Все пути, модели, языки — отсюда.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Пути ──────────────────────────────────────────────────────────────────────

ROOT_DIR    = Path(__file__).parent
PATIENTS_DIR = ROOT_DIR / "Patients"
INBOX_DIR   = PATIENTS_DIR / "INBOX"
LOGS_DIR    = ROOT_DIR / "logs"
DB_PATH     = ROOT_DIR / "aim.db"
ENV_FILE    = Path.home() / ".aim_env"

# ── Ключи ─────────────────────────────────────────────────────────────────────

load_dotenv(ENV_FILE)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
KIMI_API_KEY     = os.getenv("KIMI_API_KEY", "")
QWEN_API_KEY     = os.getenv("QWEN_API_KEY", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")

# ── Модели ────────────────────────────────────────────────────────────────────

class Models:
    # DeepSeek
    DS_CHAT     = "deepseek-chat"
    DS_REASONER = "deepseek-reasoner"

    # KIMI (Moonshot)
    KIMI_128K   = "moonshot-v1-128k"
    KIMI_32K    = "moonshot-v1-32k"
    KIMI_8K     = "moonshot-v1-8k"

    # Qwen (Alibaba DashScope)
    QWEN_TURBO  = "qwen-turbo"
    QWEN_MAX    = "qwen-max"
    QWEN_PLUS   = "qwen-plus"

    # Groq (ultra-fast inference)
    GROQ_LLAMA  = "llama-3.3-70b-versatile"
    GROQ_LLAMA_FAST = "llama-3.1-8b-instant"
    GROQ_MIXTRAL = "mixtral-8x7b-32768"

# ── Endpoints ─────────────────────────────────────────────────────────────────

class Endpoints:
    DEEPSEEK = "https://api.deepseek.com/v1"
    KIMI     = "https://api.moonshot.cn/v1"
    QWEN     = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    GROQ     = "https://api.groq.com/openai/v1"

# ── Языки ─────────────────────────────────────────────────────────────────────

SUPPORTED_LANGS = ["ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da"]

# Языки, которые идут через Qwen
QWEN_LANGS = {"ar", "zh", "ka", "kz", "da"}

# Языки, которые идут через DeepSeek по умолчанию
DS_LANGS = {"ru", "en", "fr", "es"}

DEFAULT_LANG = "ru"

# ── Роутер: пороги ────────────────────────────────────────────────────────────

LONG_CONTEXT_THRESHOLD = 12_000   # токенов — отправить в KIMI
REASONING_KEYWORDS = [
    "диагноз", "diagnosis", "дифференциальный", "differential",
    "анализ", "analysis", "причина", "cause", "почему", "why",
    "объясни механизм", "explain mechanism", "патогенез", "pathogenesis",
]

# ── Параметры LLM ─────────────────────────────────────────────────────────────

LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS  = 4096
LLM_TIMEOUT     = 60   # секунд

# ── Версия ────────────────────────────────────────────────────────────────────

VERSION = "7.0.0"
APP_NAME = "AIM — Assistant of Integrative Medicine"
