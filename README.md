# AIM — Assistant of Integrative Medicine

**Версия:** 2.0 | **Обновлено:** 2026-03-24 | **Автор:** Dr. Jaba Tkemaladze

> Локальный AI-ассистент интегративной медицины с управлением пациентами,
> анализом лабораторий, байесовской диагностикой и Telegram-ботом.
> Работает полностью локально — данные пациентов не покидают машину.

---

## Что такое AIM

**AIM (Assistant of Integrative Medicine)** — специализированная система искусственного интеллекта для практики интегративной медицины доктора Джабы Ткемаладзе. Система:

- 📋 **Ведёт карточки пациентов** — OCR анализов, PDF, WhatsApp-чаты, BLE-данные
- 🔬 **Анализирует лаборатории** — 165+ параметров, референсные диапазоны с учётом пола/возраста
- 🧠 **Байесовская диагностика** — дифференциальный диагноз с вероятностями
- 💊 **Рекомендации по лечению** — протоколы интегративной медицины
- 🥗 **Протокол питания** — система питания Dr. Ткемаладзе («Место Силы»), фильтр всех рекомендаций
- ❤️ **Ze ECG/HRV** — анализ RR-интервалов, Ze-поток, классификация состояния
- 📱 **Telegram-бот** — мультиязычный (RU/KA/EN), голос → Whisper → ответ
- 🖥 **GUI** — tkinter-интерфейс с вкладками: чат, пациенты, питание, система
- 🔗 **Интеграция** — CDATA, Ze HealthWearable, DrJaba бот, ClinicA

### Поддерживаемые языки

| Язык | GUI | Telegram | LLM |
|------|-----|----------|-----|
| Русский | ✅ | ✅ | ✅ |
| Грузинский | ✅ | ✅ | ✅ |
| Английский | ✅ | ✅ | ✅ |

---

## Архитектура

## Текущая статистика

| Показатель | Значение |
|------------|---------|
| Модулей Python | 34 |
| Параметров лабораторий | 165 |
| Запрещённых продуктов | 47 |
| Разрешённых продуктов | 69 |


```
aim_gui.py              ← Главная точка запуска (GUI + авто-старт бота)
  │
  ├── medical_system.py     ← Интерактивное CLI меню, SYSTEM_PROMPT
  ├── patient_intake.py     ← Pipeline: OCR → PDF → лабы → диагноз → DB
  │     ├── ocr_engine.py       tesseract / rapidocr
  │     ├── lab_parser.py       извлечение lab-значений из текста
  │     ├── lab_reference.py    165+ референсных диапазонов
  │     └── diagnosis_engine.py Байес + DeepSeek R1
  │
  ├── space_nutrition.py    ← Протокол питания (47 запрещённых, 69 разрешённых)
  ├── llm.py                ← Единая точка LLM-вызовов (DeepSeek API)
  ├── db.py                 ← SQLite слой (пациенты, лабы, диагнозы, Ze-HRV)
  ├── audit_log.py          ← Аудит-лог всех действий (logs/audit.jsonl)
  │
  ├── telegram_bot.py       ← aiogram 3.x бот "DrJaba"
  ├── inbox_watcher.py      ← Watcher для Patients/INBOX/
  ├── ze_ecg.py             ← RR → Ze-поток, HRV, классификация
  ├── wearable_importer.py  ← BLE Heart Rate Profile (UUID 0x180D)
  ├── numerology.py         ← Нумерологический профиль из DOB пациента
  ├── pdf_export.py         ← Экспорт PDF-отчёта пациента
  │
  ├── whatsapp_importer.py  ← Парсинг экспорта WhatsApp (TXT)
  ├── tg_desktop_importer.py← Парсинг экспорта Telegram Desktop (JSON)
  └── backup_github.py      ← Авто-бэкап на GitHub (3-е число каждого месяца)
```

### Хранилище данных

| Хранилище | Что хранится |
|-----------|-------------|
| `Patients/SURNAME_NAME_YYYY_MM_DD/` | Файлы пациента, OCR-тексты, PDF, анализы |
| `Patients/INBOX/` | Входящие файлы для авто-обработки |
| `aim.db` | SQLite: patients, lab_snapshots, diagnoses, ze_hrv, knowledge |
| `nutrition_rules.json` | Протокол питания (редактируется из GUI) |
| `logs/audit.jsonl` | Аудит-лог действий |

### LLM

| Модель | Когда |
|--------|-------|
| `deepseek-chat` (DeepSeek V3) | Все обычные запросы, чат, лабы |
| `deepseek-reasoner` (DeepSeek R1) | Диагностика (байес < 60% или разрыв < 15%) |

---

## Быстрый старт

### Требования

- Ubuntu 22.04+ / Debian 12+
- Python 3.11+
- Git
- Tesseract OCR
- DeepSeek API key (https://platform.deepseek.com)
- Telegram Bot Token (опционально)

### 1. Клонирование

```bash
git clone git@github.com:djabbat/AIM.git ~/AIM
cd ~/AIM
```

### 2. Установка зависимостей

```bash
# Системные
sudo apt-get update
sudo apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-kat tesseract-ocr-kaz \
    libportaudio2  # для голосового ввода

# Python venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Whisper (опционально, для голоса в боте)
pip install openai-whisper imageio-ffmpeg
```

### 3. Настройка ключей

Создать файл `~/.aim_env`:

```bash
cat > ~/.aim_env << 'EOF'
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_ALLOWED_ID=your-telegram-user-id
# Опционально: адрес BLE-браслета
# WEARABLE_ADDRESS=XX:XX:XX:XX:XX:XX
EOF
chmod 600 ~/.aim_env
```

**Получить ключи:**
- DeepSeek API: https://platform.deepseek.com/api_keys
- Telegram Bot: @BotFather → /newbot → имя "DrJaba"
- Telegram ID: написать @userinfobot

### 4. Инициализация БД

```bash
cd ~/AIM
source venv/bin/activate
python3 db.py --migrate   # если есть старые данные в JSON/папках
python3 db.py --stats     # проверить что всё OK
```

### 5. Запуск

```bash
# GUI + авто-старт Telegram бота (основной режим)
cd ~/AIM && source venv/bin/activate && python3 aim_gui.py

# Только бот (без GUI, для сервера)
cd ~/AIM && source venv/bin/activate && python3 telegram_bot.py

# CLI обработка всех пациентов
cd ~/AIM && source venv/bin/activate && python3 patient_intake.py --all
```

### Авто-старт при загрузке системы (systemd)

```bash
# Создать сервис
sudo tee /etc/systemd/system/aim-bot.service << 'EOF'
[Unit]
Description=AIM Telegram Bot
After=network.target

[Service]
User=oem
WorkingDirectory=/home/oem/AIM
ExecStart=/home/oem/AIM/venv/bin/python3 /home/oem/AIM/telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable aim-bot
sudo systemctl start aim-bot
```

---

## Работа с пациентами

### Добавить пациента вручную

```bash
mkdir ~/AIM/Patients/TKEMALADZE_JABA_1975_03_03
# Скопировать PDF/фото анализов в папку
python3 patient_intake.py --patient TKEMALADZE_JABA_1975_03_03
```

### Автоматический импорт

**WhatsApp:** экспортировать чат → `.txt` → положить в `Patients/INBOX/`

**Telegram Desktop:** File → Export Chat History → JSON → `tg_desktop_importer.py`:
```bash
python3 tg_desktop_importer.py --export ~/Downloads/TelegramExport/ --list
python3 tg_desktop_importer.py --export ~/Downloads/TelegramExport/
```

**BLE браслет:**
```bash
python3 wearable_importer.py --scan          # найти браслет
python3 wearable_importer.py --interactive   # записать HRV
```

### Маркировка пациентов в Telegram

Контакт должен называться: `ФАМИЛИЯ П ИМЯКИРИЛЛИЦА` (маркер П/п/პ)

Примеры: `Ткемаладзе П Джаба`, `Иванова П Мария`, `Beridze პ Giorgi`

---

## Протокол питания

Система питания Dr. Ткемаладзе встроена в ядро AIM как фильтр всех рекомендаций.

- **47 запрещённых продуктов** (11 категорий) с причинами и заменами
- **69 разрешённых продуктов** (12 категорий)

Редактируется из GUI → вкладка **🥗 Питание** → **💾 СОХРАНИТЬ В ЯДРО AIM**.

При любом вопросе о еде LLM автоматически получает полный протокол.

Источник: «Место Силы» + клинический протокол, версия 09.03.2026.

---

## Экосистема AIM

```
Ze + HealthWearable  →  RR/HRV данные     →  ze_ecg.py         →  AIM пациент
WhatsApp/Telegram    →  переписка          →  importers         →  AIM пациент
Анализы (PDF/фото)   →  OCR + парсинг     →  patient_intake    →  AIM диагноз
ClinicA              →  пациенты клиники   →  patient_intake    →  AIM ведение
CDATA                →  прогноз старения   →  cdata_bridge      →  AIM диагноз
Regenesis            →  протокол лечения   →  knowledge         →  AIM рекомендации
DrJaba (Telegram)   ←   AIM диетология                         →  советы
```

---

## Безопасность и конфиденциальность

- ✅ Данные пациентов хранятся **только локально** (`~/AIM/Patients/`, `aim.db`)
- ✅ `.gitignore` исключает все файлы с данными пациентов
- ✅ Временные файлы Telegram-бота создаются с правами `0o600`
- ✅ Аудит-лог всех обращений (`logs/audit.jsonl`)
- ✅ Telegram-бот фильтрует по `TELEGRAM_ALLOWED_ID`
- ⚠️ Нет шифрования данных на диске (приемлемо для локального использования)
- ⚠️ DeepSeek API требует интернет (данные анализов уходят к провайдеру)

---

## Восстановление из бэкапа

```bash
# 1. Клонировать репозиторий
git clone git@github.com:djabbat/AIM.git ~/AIM

# 2. Восстановить данные пациентов из отдельного бэкапа
# (Patients/ не хранятся в git — восстанавливать вручную или из зашифрованного архива)

# 3. Установить зависимости
cd ~/AIM
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4. Настроить ~/.aim_env (ключи API)

# 5. Инициализировать БД
python3 db.py

# 6. Запустить
python3 aim_gui.py
```

---

## Авто-бэкап на GitHub

Бэкап запускается **автоматически 3-го числа каждого месяца** (cron).

```bash
# Запустить вручную
python3 backup_github.py

# Статус cron
crontab -l | grep backup_github
```

Скрипт `backup_github.py`:
1. Обновляет `README.md` — дата, статистика (модули, параметры, протокол питания)
2. `git add` всех изменённых файлов (кроме `.gitignore`-исключений)
3. `git commit` с автоматическим сообщением
4. `git push origin main`

---

## Разработка

Требования к коду:
- Все LLM-вызовы через `llm.py` (`ask_llm()` / `ask_deep()`)
- Все DB-операции через `db.py`
- Все аудит-записи через `audit_log.py`
- Пациентские данные **никогда** не попадают в git
- Новые модули добавляются в `requirements.txt` и документируются в `TODO.md`

---

*AIM — Assistant of Integrative Medicine. Dr. Jaba Tkemaladze, Georgia.*
