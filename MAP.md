# AIM v6.0 — MAP (Карта компонентов)

---

## Верхнеуровневая архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        AIM v6.0                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  ТОЧКИ ВХОДА                             │   │
│  │  start.sh → aim_gui.py (GUI) | medical_system.py (CLI)  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  ЯДРО СИСТЕМЫ                            │   │
│  │  config.py ── llm.py ── db.py ── i18n.py                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              МЕДИЦИНСКИЕ МОДУЛИ                          │   │
│  │  patient_intake.py → ocr_engine.py + lab_parser.py       │   │
│  │  diagnosis_engine.py → treatment_recommender.py          │   │
│  │  bayesian_medical.py                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              БЕЗОПАСНОСТЬ                                │   │
│  │  core/rbac.py ── core/tenant.py ── JWT ── Rate Limiting  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  ДАННЫЕ                                  │   │
│  │  aim.db (SQLite) │ Patients/ │ medical_knowledge.json    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              ВНЕШНИЕ СЕРВИСЫ                             │   │
│  │  DeepSeek API │ FCM/APNs │ Stripe │ S3 │ Sentry          │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Потоки данных

### 1. Обработка нового пациента (intake pipeline)

```
Patients/INBOX/ (новый файл)
    ↓
patient_intake.py
    ├── WhatsApp → whatsapp_importer.py → текст
    ├── Изображение → ocr_engine.py (tesseract/rapidocr) → текст
    └── PDF → pdfplumber → текст
         ↓
    lab_parser.py → лаб. значения + оценка vs reference
         ↓
    llm.py → ask_llm() → AI-анализ (DeepSeek)
         ↓
    diagnosis_engine.py → байесовская диагностика
         ↓
    treatment_recommender.py → протоколы лечения
         ↓
    _ai_analysis.txt (в папке пациента)
```

### 2. CLI-сессия врача

```
medical_system.py (запуск)
    ↓
i18n.py (выбор языка: RU/KA/EN/KZ)
    ↓
Главное меню (пункты m1..mw)
    ├── Просмотр пациента → db.py → данные
    ├── AI-консультация → llm.py → DeepSeek
    ├── Анализ EEG/HRV → интеграция ZeAnastasis/BioSense
    └── Отчёт → reports/
```

### 3. LLM-вызов

```
ask_llm(prompt, lang="ru")         # быстро, deepseek-chat
    ↓
config.py → DEEPSEEK_API_KEY
    ↓
DeepSeek API (api.deepseek.com)
    ↓
ответ → caller

ask_deep(prompt)                   # глубокое рассуждение, deepseek-reasoner
    ↓
DeepSeek API (reasoning mode)
    ↓
ответ → caller
```

### 4. Мульти-тенантная изоляция

```
HTTP запрос + X-Tenant-ID header
    ↓
core/tenant.py → get_tenant(tenant_id)
    ↓
TenantLimits.check()  → ошибка если лимит превышен
    ↓
db.py → использует схему aim_tenant_{id}
    ↓
core/rbac.py → AccessContext(tenant_id=...)
    ↓
бизнес-логика с изолированными данными
```

---

## Файловая структура

```
~/Desktop/AIM/
├── CONCEPT.md              ← Источник истины v6.0
├── CLAUDE.md               ← Инструкции для Claude
├── README.md               ← Публичное описание
├── TODO.md                 ← Задачи
├── PARAMETERS.md           ← Все параметры конфигурации
├── MAP.md                  ← Этот файл
├── MEMORY.md               ← Решения и история
├── LINKS.md                ← Ссылки на экосистему
├── KNOWLEDGE.md            ← Медицинская база знаний
│
├── config.py               ← Централизованная конфигурация
├── llm.py                  ← DeepSeek API wrapper
├── db.py                   ← SQLite слой
├── i18n.py                 ← RU/KA/EN/KZ строки
├── medical_system.py       ← Главный CLI
├── requirements.txt
├── start.sh
│
├── core/
│   ├── rbac.py             ← RBAC (из CONCEPT.md)
│   └── tenant.py           ← Мульти-тенантность
│
├── Patients/               ← НИКОГДА НЕ КОММИТИТЬ
│   ├── INBOX/              ← Входящие файлы
│   └── SURNAME_NAME_YYYY_MM_DD/
│       ├── *.jpg / *.pdf
│       └── _ai_analysis.txt
│
├── .gitignore
├── venv/                   ← Python venv (не коммитить)
└── .git/
```

---

## Схема БД (SQLite → PostgreSQL в Production)

### Основные таблицы

| Таблица | Назначение |
|---------|-----------|
| `tenants` | Клиники/организации |
| `users` | Все пользователи (врачи, пациенты, персонал) |
| `patients` | Профили пациентов |
| `analyses` | Анализы и лаб. данные |
| `prescriptions` | Рецепты и назначения |
| `appointments` | Записи на приём |
| `messages` | Чат врач-пациент |
| `push_tokens` | FCM/APNs токены |
| `audit_log` | Аудит всех действий |
| `billing` | Оплаты и подписки |

### Связи

```
tenants ──< users ──< patients
                  ──< analyses
                  ──< prescriptions
                  ──< appointments
                  ──< messages
                  ──< push_tokens
users ──< audit_log
tenants ──< billing
```

---

## Петли обратной связи

### Самообучение

```
Пациент обработан
    ↓
diagnosis_engine.py → паттерн диагноза
    ↓
MedicalKnowledge.update(pattern)
    ↓
medical_knowledge.json (накопление)
    ↓
Следующий пациент — более точный диагноз
```

### Ze-HRV обратная связь

```
BioSense EEG/HRV данные
    ↓
ZeAnastasis анализ → Ze-статус пациента
    ↓
AIM diagnosis_engine.py → учитывает Ze-статус
    ↓
treatment_recommender.py → Ze-скорректированный протокол
    ↓
Мониторинг ответа на лечение
    ↓
CDATA обновление клинических данных
```

---

## Экосистемные связи (детали в LINKS.md)

```
AIM
 ├── → CDATA (клинические данные, Ze-теория)
 ├── → ZeAnastasis (Ze-терапия, EEG/HRV)
 ├── → Regenesis (протоколы)
 ├── → DrJaba (публичный сайт)
 ├── → BioSense (биосенсоры)
 ├── → FCLC (федеральная клиника)
 └── → WLRAbastumani (санаторий)
```
