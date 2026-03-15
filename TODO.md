# AIM — Assistant of Integrative Medicine
# TODO / ПЛАН РАЗВИТИЯ

Последнее обновление: 2026-03-14

---

## ✅ ЗАВЕРШЕНО

### Архитектура
- [x] Переименование AI → AIM, перенос ~/Documents/patients → ~/AIM/Patients/
- [x] config.py — централизованные константы (MODEL, PATIENTS_DIR, INBOX_DIR, CDP_PORT, OCR_LANGS, get_logger)
- [x] Логирование в файл ~/AIM/logs/aim.log через get_logger()

### Обработка пациентов (patient_intake.py)
- [x] OCR скринов (tesseract + RapidOCR fallback)
- [x] Предобработка изображений: grayscale → upscale → deskew → contrast → binarize
- [x] Извлечение текста из PDF (pdfplumber)
- [x] AI анализ (llama3.2 через ollama) → _ai_analysis.txt
- [x] processed_files.json — кэш загружается один раз (_processed_cache)
- [x] Исправлен конфликт имён: локальный список log → steps
- [x] _try_fix_folder_dob — возвращает новый Path после переименования
- [x] process_patient_folder — обновляет folder после переименования
- [x] _find_existing_folder — защита от отсутствующего documents_dir

### Самообучение
- [x] MedicalKnowledge.record_patient_analysis() — накопление диагнозов/назначений
- [x] _record_to_knowledge() — вызывается после AI анализа
- [x] knowledge base → medical_knowledge.json

### Диагностика (diagnosis_engine.py)
- [x] Байесовский движок дифференциальной диагностики
- [x] DISEASE_KB расширена (13 нозологий):
  - Железодефицитная анемия (D50)
  - Гипотиреоз / Хашимото (E03, E06.3)
  - Дефицит витамина D (E55)
  - Дефицит B12/фолатов (D51/D52)
  - Преддиабет (R73)
  - Инсулинорезистентность (E11.9) ← новое
  - Дислипидемия (E78)
  - Надпочечниковая дисфункция / HPA-ось (E27.4) ← новое
  - Синдром хронической усталости (G93.3) ← новое
  - Дисфункция кишечника / СИБР (K63)
  - Хроническое воспаление (R50)
  - Паразитарная инвазия (B82)
  - Нарушение гормонального фона — женский цикл (N91/N94)

### WhatsApp импорт
- [x] whatsapp_importer.py — парсинг .txt и .zip экспортов
- [x] Разделитель P/П/პ между фамилией и именем
- [x] Имена папок сохраняют оригинальный скрипт (без .capitalize())
- [x] wa_extractor.py — CDP автоматическое извлечение из WhatsApp Desktop
- [x] patch_wa_launcher() — добавляет --remote-debugging-port=9222 в .desktop

### GUI и UX
- [x] aim_gui.py — tkinter GUI (5 вкладок: Пациент, AI Анализ, Лаборатория, AI Чат, Система)
- [x] LLM в фоновом потоке (не блокирует UI)
- [x] Сохранение/загрузка истории чата → chat_history.json
- [x] Кнопка "Sync WhatsApp" (вызывает wa_extractor)
- [x] Иконка AIM (кадуцей с 2 змеями) → aim_icon.png
- [x] Ярлык на рабочем столе → ~/Desktop/AIM.desktop

### Документация
- [x] ИНСТРУКЦИЯ.md — полное руководство пользователя
- [x] lab_parser.py — исправлен баг с regex (UNIT_INNER)

---

## 🔲 СЛЕДУЮЩИЕ ЗАДАЧИ

### Высокий приоритет
- [ ] Протестировать CDP подключение к WhatsApp Desktop (запустить wa_extractor.py --list-only)
- [ ] Проверить полный pipeline на реальном пациенте (--folder)
- [ ] Убедиться что tesseract-ocr-kat установлен: `tesseract --list-langs | grep kat`

### Лабораторные анализы
- [ ] lab_reference.py — расширить референсные диапазоны (добавить DHEA, CORT, HOMA, половые гормоны)
- [ ] lab_parser.py — поддержка грузинских лаб-бланков (колонки на грузинском)
- [ ] Визуализация трендов лаб показателей по времени (несколько анализов одного пациента)

### Обработка данных
- [ ] Поддержка DOCX файлов (python-docx) в patient_intake.py
- [ ] Дедупликация анализов: не перезаписывать _ai_analysis.txt если данные не изменились
- [ ] Автоматическое определение языка пациента → выбор языка ответа в AI анализе

### GUI
- [ ] Вкладка "Динамика" — графики лаб показателей в разрезе времени (matplotlib)
- [ ] Поиск по всем пациентам (полнотекстовый)
- [ ] Печать/экспорт анализа в PDF

### Интеграция
- [ ] Telegram бот для Dr. Jaba (уведомления о новых пациентах/анализах)
- [ ] Автозапуск wa_extractor по расписанию (cron/systemd)

---

## ЗАПУСК

```bash
cd ~/AIM && source venv/bin/activate

# GUI
python3 aim_gui.py

# Обработка одного пациента
python3 patient_intake.py --folder ~/AIM/Patients/ФАМИЛИЯ_ИМЯ_ГГГГ_ММ_ДД

# Обработка всех пациентов
python3 patient_intake.py --all

# WhatsApp синхронизация
python3 wa_extractor.py
python3 wa_extractor.py --list-only   # только список пациентов
python3 wa_extractor.py --patch-launcher  # один раз для настройки
```

## ЗАВИСИМОСТИ

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-kat
pip install pdfplumber pytesseract rapidocr-onnxruntime pillow numpy ollama websocket-client requests
ollama pull llama3.2
```
