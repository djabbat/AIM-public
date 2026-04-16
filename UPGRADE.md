# UPGRADE.md — AIM

## v7.1 (следующая)

- [ ] **KIMI**: пополнить баланс на moonshot.cn → протестировать длинные контексты (>12k токенов)
- [ ] **Qwen**: активировать модели в Singapore-регионе Alibaba Model Studio → принять ToS → протестировать AR/ZH/KA/KZ/DA языки
- [x] `lab_reference.py` — база лабораторных норм ✅ 2026-04-16
- [ ] Протестировать Telegram-бот (TELEGRAM_BOT_TOKEN уже в ~/.aim_env)
- [ ] Протестировать GUI: `python3 aim_gui.py`

## v7.0 (текущая) ✅ 2026-04-16

### Фаза 1: Ядро ✅
- [x] `config.py` — 4 провайдера, 9 языков
- [x] `llm.py` — гибридный роутер (Groq → DeepSeek → KIMI → Qwen → DeepSeek-chat)
- [x] `i18n.py` — 9 языков (ООН-6 + KA + KZ + DA)
- [x] `db.py` — SQLite (пациенты, сессии, кэш)
- [x] `medical_system.py` — agent loop, CLI (m1–m8)
- [x] `requirements.txt`, `start.sh`, `README.md`

### Фаза 2: Агенты ✅
- [x] `agents/doctor.py` — диагностика, лечение, лаб. интерпретация, чат
- [x] `agents/intake.py` — OCR (tesseract+rapidocr), PDF (pymupdf+pdfplumber), INBOX, WhatsApp
- [x] `agents/lang.py` — перевод 4 типов, detect, explain_term, simplify

### Фаза 3: Пациентский pipeline ✅
- [x] OCR (tesseract / rapidocr)
- [x] PDF-парсер (pymupdf + pdfplumber)
- [x] Автоматический intake из `Patients/INBOX/`
- [x] `lab_reference.py` — база норм ✅ 2026-04-16

### Фаза 4: Telegram-бот ✅
- [x] `telegram_bot.py` — диагностика, лечение, перевод, фото OCR, PDF intake
- [x] Мультиязычный (автодетект) + роутер LLM

### Фаза 5: GUI ✅
- [x] `aim_gui.py` — customtkinter, полный паритет с CLI (m1–m8)
- [x] Async LLM через threading

## Известные проблемы

| Провайдер | Статус | Решение |
|-----------|--------|---------|
| DeepSeek | ✅ работает | — |
| Groq | ✅ работает | — |
| KIMI | ⚠️ нет баланса | пополнить moonshot.cn |
| Qwen | ⚠️ 403 AccessDenied.Unpurchased | активировать модели в Singapore Model Studio |
