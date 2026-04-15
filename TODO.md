# AIM v7.0 — TODO

Обновлено: 2026-04-15

---

## 🔴 СВЕРХСРОЧНО — P0

- [ ] Добавить ключи в `~/.aim_env`: `KIMI_API_KEY`, `QWEN_API_KEY`, `GROQ_API_KEY`
- [ ] Протестировать роутер: `python3 -c "from llm import providers_status; print(providers_status())"`

---

## Фаза 1: Ядро (текущая) ✅

- [x] CONCEPT.md v7.0
- [x] config.py — 4 провайдера, 9 языков
- [x] llm.py — гибридный роутер
- [x] i18n.py — 9 языков
- [x] db.py — SQLite (пациенты, сессии, кэш)
- [x] medical_system.py — agent loop, CLI
- [x] requirements.txt
- [x] start.sh
- [x] README.md

---

## Фаза 2: Агенты ✅ 2026-04-16

- [x] `agents/doctor.py` — диагностика, лечение, интерпретация анализов, чат
- [x] `agents/intake.py` — OCR (tesseract+rapidocr), PDF (pymupdf+pdfplumber), INBOX, WhatsApp
- [x] `agents/lang.py` — перевод 4 типов, detect, explain_term, simplify

---

## Фаза 3: Пациентский pipeline ✅ 2026-04-16

- [x] OCR (tesseract / rapidocr)
- [x] PDF-парсер (pymupdf + pdfplumber)
- [x] Автоматический intake из `Patients/INBOX/`
- [ ] Лаб. нормы (`lab_reference.py`) — следующий шаг

---

## Фаза 4: Telegram-бот ✅ 2026-04-16

- [x] `telegram_bot.py` — диагностика, лечение, перевод, фото OCR, PDF intake
- [x] Мультиязычный (автодетект языка) + роутер LLM

---

## Фаза 5: GUI ✅ 2026-04-16

- [x] `aim_gui.py` — customtkinter, полный паритет с CLI (m1-m8)
- [x] Async LLM через threading (не замораживает UI)
