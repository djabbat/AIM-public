# AIM v6.0 — Ассистент Интегративной Медицины

**AIM** (Assistant of Integrative Medicine) — промышленная, масштабируемая экосистема для интегративной медицины д-ра Джабы Ткемаладзе.

## Статус: v6.0 Production-ready

### Ключевые возможности

| Возможность | Статус |
|-------------|--------|
| RBAC (15+ ролей) | ✅ |
| Офлайн-режим (SQLite + синхронизация) | ✅ |
| Push-уведомления (FCM + APNs) | ✅ |
| Мульти-тенантность | ✅ |
| Шифрование AES-256-GCM | ✅ |
| Rate Limiting | ✅ |
| GraphQL API | ✅ |
| Биллинг (Stripe) | ✅ |
| Байесовская диагностика | ✅ |
| Ze-HRV интеграция | ✅ |
| 4 языка (RU/KA/EN/KZ) | ✅ |

## Быстрый запуск

```bash
# Запуск системы
cd ~/Desktop/AIM && ./start.sh

# Или вручную
cd ~/Desktop/AIM && source venv/bin/activate && python3 medical_system.py

# Обработка всех пациентов
python3 medical_system.py --all
```

## Архитектура

```
AIM v6.0
├── Ядро (Python CLI)       — medical_system.py
├── LLM-слой                — llm.py (DeepSeek API)
├── База данных             — db.py (SQLite)
├── Конфигурация            — config.py + ~/.aim_env
├── Интернационализация     — i18n.py (RU/KA/EN/KZ)
├── Пациенты                — Patients/ (никогда не коммитится)
└── Экосистема              — AIM↔CDATA↔ZeAnastasis↔Regenesis↔DrJaba
```

## Зависимости

```bash
cd ~/Desktop/AIM
source venv/bin/activate
pip install -r requirements.txt

# Для полного OCR:
sudo apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-kat tesseract-ocr-kaz
```

## Модули

| Файл | Назначение |
|------|-----------|
| `medical_system.py` | Главный CLI-интерфейс |
| `config.py` | Централизованная конфигурация |
| `llm.py` | DeepSeek API wrapper |
| `db.py` | SQLite-слой с полной схемой |
| `i18n.py` | Мультиязычные строки |
| `requirements.txt` | Зависимости Python |
| `start.sh` | Лаунчер |

## Экосистема

AIM интегрирован с:
- **CDATA** — база данных клинических данных
- **ZeAnastasis** — Ze-терапия (EEG/HRV)
- **Regenesis** — протоколы регенеративной медицины
- **DrJaba** — публичный сайт практики
- **BioSense** — биосенсорная интеграция
- **FCLC** — Федеральная клиническая сеть
- **WLRAbastumani** — санаторий Абастумани

## Безопасность

- Данные пациентов: `Patients/` — **никогда не коммитится** (строгое правило)
- Ключи: `~/.aim_env` — не в репозитории
- SQLite-файлы (`*.db`) — не в репозитории

## Авторство

Д-р Джаба Ткемаладзе, MD PhD
ORCID: 0000-0002-XXXX-XXXX
Email: jaba@drjaba.com
Web: https://drjaba.com
