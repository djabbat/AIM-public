# -*- coding: utf-8 -*-
"""
AIM v6.0 — config.py
Централизованная конфигурация. Единственный источник истины для всех путей и параметров.

Georgian (ქართული), Kazakh (Қазақша), Arabic (العربية) require UTF-8 throughout.
This module enforces UTF-8 for stdout/stderr and locale at import time.

Использование:
    from config import cfg
    print(cfg.DEEPSEEK_MODEL_FAST)
    print(cfg.DB_PATH)
"""

import io
import os
import sys
import locale
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# UTF-8 enforcement — must happen before any output
# Georgian (ქართული), Kazakh (Қазақша), Arabic (العربية) require UTF-8 throughout.
# ============================================================================

# Force UTF-8 on stdout/stderr (safe even if already UTF-8)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Set locale to UTF-8 (try common variants; silently skip if unavailable)
for _locale in ("C.UTF-8", "en_US.UTF-8", "ka_GE.UTF-8", "ru_RU.UTF-8", ""):
    try:
        locale.setlocale(locale.LC_ALL, _locale)
        break
    except locale.Error:
        continue

# ============================================================================
# Загрузка переменных окружения
# ============================================================================

_env_file = Path.home() / ".aim_env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Пробуем .env в корне проекта (для разработки)
    _local_env = Path(__file__).parent / ".env"
    if _local_env.exists():
        load_dotenv(_local_env)


# ============================================================================
# Конфигурационный класс
# ============================================================================

class AIMConfig:
    """Централизованная конфигурация AIM v6.0"""

    # ------------------------------------------------------------------
    # Версия
    # ------------------------------------------------------------------
    VERSION: str = "6.0"
    ENVIRONMENT: str = os.getenv("AIM_ENVIRONMENT", "development")

    # ------------------------------------------------------------------
    # Пути
    # ------------------------------------------------------------------
    ROOT_DIR: Path = Path(__file__).parent.resolve()
    PATIENTS_DIR: Path = ROOT_DIR / "Patients"
    PATIENTS_INBOX: Path = ROOT_DIR / "Patients" / "INBOX"
    LOGS_DIR: Path = ROOT_DIR / "logs"
    REPORTS_DIR: Path = ROOT_DIR / "reports"
    MEDIA_DIR: Path = ROOT_DIR / "media"

    # ------------------------------------------------------------------
    # База данных (SQLite для dev; PostgreSQL для production)
    # ------------------------------------------------------------------
    DB_TYPE: str = os.getenv("AIM_DB_TYPE", "sqlite")
    DB_PATH: Path = ROOT_DIR / "aim.db"
    DB_WAL_MODE: bool = True
    DB_TIMEOUT: int = 30
    DB_POOL_SIZE: int = 5

    # PostgreSQL (production)
    PG_HOST: str = os.getenv("AIM_DB_HOST", "localhost")
    PG_PORT: int = int(os.getenv("AIM_DB_PORT", "5432"))
    PG_NAME: str = os.getenv("AIM_DB_NAME", "aim_shared")
    PG_USER: str = os.getenv("AIM_DB_USER", "aim")
    PG_PASSWORD: str = os.getenv("AIM_DB_PASSWORD", "")

    # ------------------------------------------------------------------
    # LLM / DeepSeek
    # ------------------------------------------------------------------
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL_FAST: str = "deepseek-chat"
    DEEPSEEK_MODEL_REASON: str = "deepseek-reasoner"
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SEC: int = 60
    LLM_RETRY_ATTEMPTS: int = 3

    # Ollama fallback (если нет DeepSeek ключа)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    # ------------------------------------------------------------------
    # Язык по умолчанию
    # ------------------------------------------------------------------
    DEFAULT_LANG: str = os.getenv("AIM_LANG", "ru")
    SUPPORTED_LANGS: list = ["ru", "ka", "en", "kz"]

    # ------------------------------------------------------------------
    # API Gateway
    # ------------------------------------------------------------------
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "4"))

    RATE_LIMIT_DEFAULT: int = 60      # req/min
    RATE_LIMIT_AUTH: int = 300
    RATE_LIMIT_ADMIN: int = 1000

    CORS_ORIGINS: list = [
        "https://app.aim.local",
        "https://*.aim.local",
        "http://localhost:3000",
    ]

    # ------------------------------------------------------------------
    # JWT / Аутентификация
    # ------------------------------------------------------------------
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MIN: int = 60
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    SESSION_TTL_SEC: int = 86400 * 7  # 7 дней

    # ------------------------------------------------------------------
    # Мульти-тенантность
    # ------------------------------------------------------------------
    TENANT_MODE: str = "isolated"
    TENANT_DEFAULT_PLAN: str = "free"
    TENANT_MAX: int = 1000
    TENANT_DB_PREFIX: str = "aim_tenant_"

    # ------------------------------------------------------------------
    # Push-уведомления
    # ------------------------------------------------------------------
    FCM_CREDENTIALS_PATH: str = os.getenv(
        "FCM_CREDENTIALS_PATH", "/etc/aim/fcm-credentials.json"
    )
    APNS_KEY_ID: str = os.getenv("APNS_KEY_ID", "")
    APNS_TEAM_ID: str = os.getenv("APNS_TEAM_ID", "")
    APNS_BUNDLE_ID: str = "com.aim.patient"

    # ------------------------------------------------------------------
    # Хранилище медиа
    # ------------------------------------------------------------------
    STORAGE_PROVIDER: str = os.getenv("STORAGE_PROVIDER", "local")
    S3_BUCKET: str = os.getenv("AIM_S3_BUCKET", "aim-media")
    S3_REGION: str = os.getenv("AIM_S3_REGION", "eu-central-1")
    S3_KEY: str = os.getenv("AIM_S3_KEY", "")
    S3_SECRET: str = os.getenv("AIM_S3_SECRET", "")
    CDN_URL: str = os.getenv("CDN_URL", "")

    # ------------------------------------------------------------------
    # Биллинг (Stripe)
    # ------------------------------------------------------------------
    STRIPE_SECRET: str = os.getenv("STRIPE_SECRET", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # ------------------------------------------------------------------
    # Мониторинг
    # ------------------------------------------------------------------
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    PROMETHEUS_PORT: int = 9090
    HEALTH_CHECK_PATH: str = "/health"

    LOG_LEVEL: str = os.getenv("AIM_LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"
    LOG_RETENTION_DAYS: int = 30

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    OCR_ENGINE: str = "tesseract"
    OCR_FALLBACK: str = "rapidocr"
    OCR_LANGUAGES: str = "rus+kat+kaz+eng"
    OCR_DPI: int = 300

    # ------------------------------------------------------------------
    # Методы
    # ------------------------------------------------------------------

    def ensure_dirs(self):
        """Создать необходимые директории если не существуют"""
        for d in [self.LOGS_DIR, self.REPORTS_DIR, self.MEDIA_DIR, self.PATIENTS_INBOX]:
            d.mkdir(parents=True, exist_ok=True)

    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    def has_deepseek(self) -> bool:
        return bool(self.DEEPSEEK_API_KEY)

    def llm_model(self, deep: bool = False) -> str:
        """Выбрать модель LLM"""
        if not self.has_deepseek():
            return self.OLLAMA_MODEL
        return self.DEEPSEEK_MODEL_REASON if deep else self.DEEPSEEK_MODEL_FAST

    def validate(self):
        """Проверить критические параметры"""
        warnings = []
        if not self.DEEPSEEK_API_KEY:
            warnings.append("DEEPSEEK_API_KEY не задан — будет использован Ollama fallback")
        if self.JWT_SECRET == "change-me-in-production" and self.is_production():
            warnings.append("КРИТИЧНО: JWT_SECRET не изменён для production!")
        if not self.PATIENTS_DIR.exists():
            warnings.append(f"Папка Patients не найдена: {self.PATIENTS_DIR}")
        return warnings

    def __repr__(self):
        return (
            f"AIMConfig(v{self.VERSION}, env={self.ENVIRONMENT}, "
            f"lang={self.DEFAULT_LANG}, deepseek={self.has_deepseek()})"
        )


# ============================================================================
# Singleton
# ============================================================================

cfg = AIMConfig()

# Создать директории при импорте
try:
    cfg.ensure_dirs()
except Exception:
    pass  # Не критично при импорте


if __name__ == "__main__":
    print(f"AIM Config v{cfg.VERSION}")
    print(f"Environment: {cfg.ENVIRONMENT}")
    print(f"DB: {cfg.DB_TYPE} → {cfg.DB_PATH}")
    print(f"DeepSeek: {'да' if cfg.has_deepseek() else 'нет (Ollama fallback)'}")
    print(f"Язык по умолчанию: {cfg.DEFAULT_LANG}")

    warnings = cfg.validate()
    if warnings:
        print("\nПредупреждения:")
        for w in warnings:
            print(f"  ! {w}")
    else:
        print("\nКонфигурация ОК")
