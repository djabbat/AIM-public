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

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Google AI Studio — free tier 50 req/day on gemini-2.5-pro, 1M context.
# Get key at https://aistudio.google.com/apikey (no credit card).
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")

# ── Модели ────────────────────────────────────────────────────────────────────

class Models:
    # DeepSeek (V4 series, released 2026-04; old IDs deepseek-chat/deepseek-reasoner
    # remain valid as aliases per https://api-docs.deepseek.com/quick_start/pricing).
    # Capabilities: 1M-token context, 384K max output, JSON/tool/FIM support.
    # v4-pro on 75% promo discount until 2026-05-31.
    DS_CHAT     = os.getenv("AIM_DS_CHAT_MODEL",     "deepseek-v4-flash")
    DS_REASONER = os.getenv("AIM_DS_REASONER_MODEL", "deepseek-v4-pro")
    # Legacy IDs kept available for log/test pinning if needed
    DS_CHAT_LEGACY     = "deepseek-chat"
    DS_REASONER_LEGACY = "deepseek-reasoner"

    # Groq (ultra-fast inference)
    GROQ_LLAMA  = "llama-3.3-70b-versatile"
    GROQ_LLAMA_FAST = "llama-3.1-8b-instant"
    GROQ_MIXTRAL = "mixtral-8x7b-32768"

    # Ollama (local — runs on the user's own machine via http://127.0.0.1:11434)
    # Each AIM node ships these by default. Override per-user via env.
    OLLAMA_CHAT     = os.getenv("AIM_OLLAMA_CHAT_MODEL",     "qwen2.5:7b-instruct")
    OLLAMA_FAST     = os.getenv("AIM_OLLAMA_FAST_MODEL",     "qwen2.5:3b-instruct")
    OLLAMA_REASONER = os.getenv("AIM_OLLAMA_REASONER_MODEL", "deepseek-r1:7b")

    # Anthropic Claude — premium tier for critical reasoning + native vision.
    # Used by ask_critical() and ensemble adjudication.
    CLAUDE_OPUS    = os.getenv("AIM_CLAUDE_OPUS_MODEL",    "claude-opus-4-7")
    CLAUDE_SONNET  = os.getenv("AIM_CLAUDE_SONNET_MODEL",  "claude-sonnet-4-6")
    CLAUDE_HAIKU   = os.getenv("AIM_CLAUDE_HAIKU_MODEL",   "claude-haiku-4-5-20251001")

    # Google Gemini — free tier as of mid-2026:
    #   gemini-2.5-pro       → paid only / invite-only on free keys (limit:0)
    #   gemini-2.5-flash     → 503 high-demand on free keys
    #   gemini-2.5-flash-lite → ✅ actually free, 1500 req/day
    # We try pro→flash-lite at runtime; lite is the realistic free-tier model.
    GEMINI_PRO       = os.getenv("AIM_GEMINI_PRO_MODEL",       "gemini-2.5-pro")
    GEMINI_FLASH     = os.getenv("AIM_GEMINI_FLASH_MODEL",     "gemini-2.5-flash")
    GEMINI_FLASH_LITE = os.getenv("AIM_GEMINI_FLASH_LITE_MODEL", "gemini-2.5-flash-lite")

# ── Endpoints ─────────────────────────────────────────────────────────────────

class Endpoints:
    DEEPSEEK  = "https://api.deepseek.com/v1"
    GROQ      = "https://api.groq.com/openai/v1"
    # Ollama exposes an OpenAI-compatible /v1 surface since 0.1.27 — same client.
    OLLAMA    = os.getenv("AIM_OLLAMA_URL", "http://127.0.0.1:11434/v1")
    # Anthropic uses native messages API (not OpenAI-compatible).
    ANTHROPIC = "https://api.anthropic.com/v1"
    # Google Gemini exposes an OpenAI-compatible /v1beta/openai surface.
    GEMINI    = "https://generativelanguage.googleapis.com/v1beta/openai"

# ── Языки ─────────────────────────────────────────────────────────────────────

SUPPORTED_LANGS = ["ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da"]

DEFAULT_LANG = "ru"

# ── Роутер: пороги ────────────────────────────────────────────────────────────

REASONING_KEYWORDS = [
    "диагноз", "diagnosis", "дифференциальный", "differential",
    "анализ", "analysis", "причина", "cause", "почему", "why",
    "объясни механизм", "explain mechanism", "патогенез", "pathogenesis",
]

# ── Параметры LLM ─────────────────────────────────────────────────────────────

LLM_TEMPERATURE = 0.3
# DeepSeek V4 caps: input ≤ 1M tokens, output ≤ 384K. Default raised 4096 → 16384
# to match v4 capabilities; per-call override via max_tokens kwarg or AIM_LLM_MAX_TOKENS env.
# For long-form generation (full-document audits, book-chunk synthesis) use ask_long
# which raises the cap to LLM_MAX_TOKENS_LONG.
LLM_MAX_TOKENS      = int(os.getenv("AIM_LLM_MAX_TOKENS",      "16384"))
LLM_MAX_TOKENS_LONG = int(os.getenv("AIM_LLM_MAX_TOKENS_LONG", "131072"))
LLM_TIMEOUT         = float(os.getenv("AIM_LLM_TIMEOUT",         "180"))  # raised для long-context
LLM_CONNECT_TIMEOUT = float(os.getenv("AIM_LLM_CONNECT_TIMEOUT", "10"))

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
