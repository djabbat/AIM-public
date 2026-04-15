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

## Фаза 2: Агенты

- [ ] `agents/doctor.py` — диагностика + рекомендации
- [ ] `agents/intake.py` — OCR + PDF + анализы
- [ ] `agents/lang.py` — языковой агент + автодетект

---

## Фаза 3: Пациентский pipeline

- [ ] OCR (tesseract / rapidocr)
- [ ] PDF-парсер (pymupdf или pdfplumber)
- [ ] Автоматический intake из `Patients/INBOX/`
- [ ] Лаб. нормы (`lab_reference.py`)

---

## Фаза 4: Telegram-бот

- [ ] `telegram_bot.py` — Telegram-интерфейс (уже есть TOKEN)
- [ ] Мультиязычный + роутер

---

## Фаза 5: GUI

- [ ] `aim_gui.py` — графический интерфейс (паритет с CLI)
