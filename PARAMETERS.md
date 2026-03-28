# AIM v6.0 — PARAMETERS

Все конфигурационные параметры системы.

---

## Версия

| Параметр | Значение |
|----------|---------|
| `AIM_VERSION` | `6.0` |
| `AIM_ENVIRONMENT` | `development` / `staging` / `production` |
| `AIM_LOCALE` | `ru` / `ka` / `en` / `kz` |

---

## Пути (по умолчанию)

| Параметр | Путь |
|----------|------|
| `AIM_ROOT` | `~/Desktop/AIM/` |
| `PATIENTS_DIR` | `~/Desktop/AIM/Patients/` |
| `PATIENTS_INBOX` | `~/Desktop/AIM/Patients/INBOX/` |
| `LOGS_DIR` | `~/Desktop/AIM/logs/` |
| `REPORTS_DIR` | `~/Desktop/AIM/reports/` |
| `DB_PATH` | `~/Desktop/AIM/aim.db` |
| `KNOWLEDGE_FILE` | `~/Desktop/AIM/medical_knowledge.json` |
| `ENV_FILE` | `~/.aim_env` |

---

## LLM / DeepSeek

| Параметр | Значение |
|----------|---------|
| `DEEPSEEK_API_KEY` | из `~/.aim_env` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL_FAST` | `deepseek-chat` |
| `DEEPSEEK_MODEL_REASON` | `deepseek-reasoner` |
| `LLM_TEMPERATURE` | `0.3` |
| `LLM_MAX_TOKENS` | `4096` |
| `LLM_TIMEOUT_SEC` | `60` |
| `LLM_RETRY_ATTEMPTS` | `3` |

---

## База данных (SQLite — локально)

| Параметр | Значение |
|----------|---------|
| `DB_TYPE` | `sqlite` |
| `DB_PATH` | `aim.db` |
| `DB_WAL_MODE` | `true` |
| `DB_TIMEOUT` | `30` |
| `DB_POOL_SIZE` | `5` |

*(Production: PostgreSQL — параметры в config.yaml)*

---

## API Gateway

| Параметр | Значение |
|----------|---------|
| `API_HOST` | `0.0.0.0` |
| `API_PORT` | `8000` |
| `API_WORKERS` | `4` |
| `API_RATE_LIMIT_DEFAULT` | `60 req/min` |
| `API_RATE_LIMIT_AUTH` | `300 req/min` |
| `API_RATE_LIMIT_ADMIN` | `1000 req/min` |
| `CORS_ORIGINS` | `https://app.aim.local, https://*.aim.local` |

---

## JWT / Аутентификация

| Параметр | Значение |
|----------|---------|
| `JWT_SECRET` | из `~/.aim_env` |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_ACCESS_EXPIRE_MIN` | `60` |
| `JWT_REFRESH_EXPIRE_DAYS` | `7` |
| `SESSION_TTL_SEC` | `604800` (7 дней) |

---

## Мульти-тенантность

| Параметр | Значение |
|----------|---------|
| `TENANT_MODE` | `isolated` |
| `TENANT_DEFAULT_PLAN` | `free` |
| `TENANT_MAX` | `1000` |
| `TENANT_DB_PREFIX` | `aim_tenant_` |

### Лимиты по планам

| План | Пациентов | Врачей | Хранилище | API calls/min |
|------|-----------|--------|-----------|---------------|
| FREE | 50 | 2 | 1 GB | 30 |
| BASIC | 500 | 10 | 10 GB | 100 |
| PRO | 5000 | 50 | 100 GB | 300 |
| ENTERPRISE | без лимита | без лимита | без лимита | 1000 |

---

## Push-уведомления

| Параметр | Значение |
|----------|---------|
| `FCM_CREDENTIALS_PATH` | `/etc/aim/fcm-credentials.json` |
| `APNS_KEY_ID` | из `~/.aim_env` |
| `APNS_TEAM_ID` | из `~/.aim_env` |
| `APNS_BUNDLE_ID` | `com.aim.patient` |

---

## Хранилище медиа

| Параметр | Значение |
|----------|---------|
| `STORAGE_PROVIDER` | `s3` / `local` / `gcs` |
| `S3_BUCKET` | `aim-media` |
| `S3_REGION` | `eu-central-1` |
| `CDN_URL` | `https://cdn.aim.local` |
| `LOCAL_MEDIA_PATH` | `~/Desktop/AIM/media/` |

---

## Биллинг (Stripe)

| Параметр | Значение |
|----------|---------|
| `STRIPE_SECRET_KEY` | из `~/.aim_env` |
| `STRIPE_WEBHOOK_SECRET` | из `~/.aim_env` |
| `PRICE_FREE` | `price_free` |
| `PRICE_BASIC` | `price_basic_monthly` |
| `PRICE_PRO` | `price_pro_monthly` |
| `PRICE_ENTERPRISE` | `price_enterprise` |

---

## Мониторинг

| Параметр | Значение |
|----------|---------|
| `SENTRY_DSN` | из `~/.aim_env` |
| `PROMETHEUS_PORT` | `9090` |
| `HEALTH_CHECK_PATH` | `/health` |
| `LOG_LEVEL` | `INFO` |
| `LOG_FORMAT` | `json` |
| `LOG_RETENTION_DAYS` | `30` |

---

## OCR (для patient_intake)

| Параметр | Значение |
|----------|---------|
| `OCR_ENGINE` | `tesseract` |
| `OCR_FALLBACK` | `rapidocr` |
| `OCR_LANGUAGES` | `rus+kat+kaz+eng` |
| `OCR_DPI` | `300` |

---

## Файл `~/.aim_env` (шаблон)

```bash
# AIM Environment — НЕ КОММИТИТЬ
DEEPSEEK_API_KEY=sk-...
JWT_SECRET=...
AIM_DB_PASSWORD=...
AIM_REDIS_PASSWORD=...
AIM_S3_KEY=...
AIM_S3_SECRET=...
STRIPE_SECRET=...
STRIPE_WEBHOOK_SECRET=...
SENTRY_DSN=...
APNS_KEY_ID=...
APNS_TEAM_ID=...
```
