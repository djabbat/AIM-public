# AIM v6.0 — TODO

Обновлено: 2026-03-28

---

## Фаза 1: Ядро системы (текущая)

- [x] CONCEPT.md v6.0 создан (peer-reviewed)
- [x] README.md
- [x] CLAUDE.md
- [x] TODO.md
- [x] PARAMETERS.md
- [x] MAP.md
- [x] MEMORY.md
- [x] LINKS.md
- [x] KNOWLEDGE.md
- [x] config.py
- [x] llm.py
- [x] db.py
- [x] i18n.py
- [x] medical_system.py (главный CLI)
- [x] requirements.txt
- [x] start.sh

## Фаза 2: RBAC и безопасность

- [ ] `core/rbac.py` — полная реализация из CONCEPT.md
- [ ] `core/tenant.py` — мульти-тенантность
- [ ] JWT-аутентификация
- [ ] Rate limiting middleware
- [ ] Audit log (каждое действие логируется)
- [ ] Шифрование чувствительных полей в БД (AES-256)

## Фаза 3: Медицинские модули

- [ ] `patient_intake.py` — полный pipeline OCR + PDF + AI
- [ ] `ocr_engine.py` — Tesseract + RapidOCR fallback
- [ ] `lab_parser.py` — парсинг лаб. значений из PDF/текста
- [ ] `lab_reference.py` — база референсных значений
- [ ] `diagnosis_engine.py` — байесовская дифференциальная диагностика
- [ ] `treatment_recommender.py` — доказательные протоколы
- [ ] `bayesian_medical.py` — байесовские сети на пациента
- [ ] `whatsapp_importer.py` — импорт WhatsApp экспортов

## Фаза 4: Ze-интеграция

- [ ] Модуль Ze-HRV (интеграция с ZeAnastasis/BioSense)
- [ ] Ze-теория в диагностическом движке
- [ ] EEG-данные из `~/Desktop/BioSense/`
- [ ] Связь с CDATA (клинические данные)

## Фаза 5: GUI и API

- [ ] `aim_gui.py` — GUI (паритет с medical_system.py)
- [ ] REST API (FastAPI)
- [ ] GraphQL endpoint
- [ ] WebSocket (real-time уведомления)
- [ ] Web Push / FCM уведомления

## Фаза 6: Мобильные приложения (Flutter)

- [ ] Patient App (offline mode, biometric auth)
- [ ] Doctor App (e-prescriptions, telemedicine)
- [ ] Institution Portal (admin, analytics, billing)
- [ ] Синхронизация офлайн-данных (SyncService)

## Фаза 7: Интеграции

- [ ] HL7/FHIR (лаборатории)
- [ ] E-prescriptions (аптеки)
- [ ] Страховые случаи
- [ ] Stripe биллинг
- [ ] Prometheus мониторинг
- [ ] Sentry error tracking

## Фаза 8: Деплой

- [ ] Docker Compose (PostgreSQL + Redis + API + Flutter Web)
- [ ] Nginx конфигурация
- [ ] SSL-сертификаты (drjaba.com + субдомены)
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Бэкап стратегия (ежедневный бэкап пациентских данных)

---

## Входящие из экосистемы

*(заполняется при сканировании TODO всех проектов)*

---

## Завершённые задачи

*(перемещать сюда при выполнении)*
