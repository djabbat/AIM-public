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

    # Qwen (Alibaba DashScope International)
    QWEN_TURBO  = "qwen3.6-plus"           # основной (multimodal, 1M ctx)
    QWEN_PLUS   = "qwen3.6-plus"           # то же
    QWEN_MAX    = "qwen3.6-plus"           # то же
    QWEN_MT     = "qwen-mt-plus"           # специализированный перевод
    QWEN_VL_OCR = "qwen-vl-ocr-2025-11-20" # OCR

    # Groq (ultra-fast inference)
    GROQ_LLAMA  = "llama-3.3-70b-versatile"
    GROQ_LLAMA_FAST = "llama-3.1-8b-instant"
    GROQ_MIXTRAL = "mixtral-8x7b-32768"

# ── Endpoints ─────────────────────────────────────────────────────────────────

class Endpoints:
    DEEPSEEK = "https://api.deepseek.com/v1"
    KIMI     = "https://api.moonshot.cn/v1"
    QWEN     = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
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

# ── Decision kernel (Asimov Three Laws + Ze Theory consciousness) ──────────────

class KernelWeights:
    """Utility weights: U(D) = ALPHA·𝒞 + BETA·Φ_Ze + GAMMA·Ethics.

    Ethics сам составной: 0.4·Ze_learning_cheating + 4×0.15·bioethics_principle.

    Config via ~/.aim_env:
      AIM_KERNEL_ALPHA=0.2  (instant consciousness 𝒞 = −d𝓘/dt)
      AIM_KERNEL_BETA=0.4   (integrated Φ_Ze = ∫𝓘 dt)
      AIM_KERNEL_GAMMA=0.4  (Ethics)
    """
    ALPHA = float(os.getenv("AIM_KERNEL_ALPHA", "0.2"))   # instant 𝒞
    BETA  = float(os.getenv("AIM_KERNEL_BETA",  "0.4"))   # integrated Φ_Ze
    GAMMA = float(os.getenv("AIM_KERNEL_GAMMA", "0.4"))   # Ethics

    # Ethics sub-weights (sum to 1 inside Ethics score)
    ETHICS_ZE       = 0.40   # Ze learning/cheating ratio
    ETHICS_AUTO     = 0.15   # Autonomy
    ETHICS_BENEF    = 0.15   # Beneficence
    ETHICS_NONMAL   = 0.15   # Non-maleficence
    ETHICS_JUSTICE  = 0.15   # Justice

    # Clarifying-question threshold: если 𝓘 > этого порога, агент сперва спрашивает
    CLARIFY_IMPEDANCE_THRESHOLD = 0.7

    # Presets (for quick switching)
    PRESETS = {
        "conservative": (0.1, 0.3, 0.6),   # ethics-heavy
        "balanced":     (0.2, 0.4, 0.4),   # default per Q4
        "aggressive":   (0.3, 0.6, 0.1),   # Phi-heavy, ethics minimal (не рекомендуется)
    }

# ── Версия ────────────────────────────────────────────────────────────────────

VERSION = "7.0.0"
APP_NAME = "AIM — Assistant of Integrative Medicine"
