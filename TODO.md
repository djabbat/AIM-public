# AIM — TODO & Roadmap
_Последнее обновление: 2026-03-24_

---

## 🔴 Входящие из экосистемы (2026-03-24)

- [x] **[OJS] Заявка в Google Scholar подана 2026-03-24** ✅
  → Ждать 3–6 месяцев. Результат: 61+ статья в профиле → рост h-index
  → Следующая проверка Search Console: ~07.04.2026 (через 2 недели)

---

## 🌐 AIM — ЯДРО ЭКОСИСТЕМЫ ВСЕХ ПРОЕКТОВ

AIM — центральный хаб. Все проекты либо поставляют данные в AIM, либо получают из него.

```
Ze + HealthWearable  →  RR/HRV данные    →  ze_ecg.py        →  AIM пациент
dietebi              →  46 клин. случаев →  dietebi_import   →  AIM знания
CDATA                →  прогноз старения →  cdata_bridge     →  AIM диагноз
ClinicA              →  пациенты клиники →  patient_intake   →  AIM ведение
Regenesis            →  протокол лечения →  knowledge        →  AIM рекомендации
OJS (longevity.ge)   ←  AIM исследования                    →  публикации
DrJaba               ←  AIM диетология                       →  советы бота
```

**Статус интеграционных модулей:**
| Модуль | Источник | Статус |
|--------|----------|--------|
| `ze_ecg.py` | Ze + HealthWearable | ✅ Готов (2026-03-17) |
| `wearable_importer.py` | HealthWearable (BLE) | ✅ Готов (2026-03-17) |
| `cdata_bridge.py` | CDATA Rust симуляция | 🟡 Скелет готов |
| `dietebi_importer.py` | 9 статей .docx | ✅ Готов (2026-03-18) |
| `regenesis_protocol.py` | Regenesis протокол | ✅ Готов (2026-03-18) |

---

## ✅ Сделано (2026-03-17) — ze_ecg.py

- [x] **`ze_ecg.py`** — полный Ze-анализ RR-интервалов:
  - Ze-поток: RR↑=0 (T), RR↓=1 (S)
  - Ze-скорость v, Ze-τ, Z_Ze, χ_Ze
  - RMSSD, SDNN, pNN50, ЧСС
  - Классификация: healthy / stress / arrhythmia / bradyarrhythmia / tachyarrhythmia
  - Парсеры: CSV, wearable JSON, plain list
  - `save_to_patient()` → `ze_hrv.json` + `ze_hrv_report.txt` в папку пациента
  - CLI: `python3 ze_ecg.py data.csv`
  - Демо-тест: v=0.422, state=healthy ✅

---

## ✅ Сделано (сессия 2026-03-17 продолжение)

- [x] **INBOX watcher** — `inbox_watcher.py`: polling каждые 2 сек, при новых файлах → `patient_intake --all`
- [x] **Авто-старт watcher** в `aim_gui.py` при запуске — GUI уведомляет о новых файлах в статусбаре
- [x] **Локальный голос в GUI** — `voice_input.py`: микрофон → Whisper → текст в чат
- [x] **Кнопка 🎙 Голос** в чате GUI — push-to-talk, красная при записи, авто-отправка

---

## ✅ Сделано (сессия 2026-03-17)

- [x] DeepSeek API вместо Ollama (`llm.py` — единая точка LLM-вызовов)
- [x] Улучшен SYSTEM_PROMPT — SOAP-формат, 6 принципов
- [x] GUI починен — удалён мёртвый `script` с broken import
- [x] Диагностика: `run_diagnosis_ai()` — Байес + DeepSeek R1
- [x] Динамика лабораторий: `_lab_history.json` снапшоты
- [x] Telegram бот (`telegram_bot.py`) — aiogram 3.x
- [x] Голосовые сообщения в боте — Whisper + imageio-ffmpeg
- [x] Авто-запуск бота при старте `aim_gui.py`

### ✅ Критические баги исправлены (2026-03-17)
- [x] **Telegram auth** — `str(ALLOWED_ID).strip()` + guard для `from_user=None`
- [x] **`r.interpretation` AttributeError** — `getattr(r, "interpretation", r.status)`
- [x] **Singleton OpenAI client** — `_client` глобальный, создаётся один раз
- [x] **`_split_text` infinite loop** — hard split при `split_at <= 0`

---

## 🔴 CRITICAL — фиксить немедленно

- [x] **Race condition в knowledge base** — `medical_knowledge.json` без блокировок
  - `pip install filelock` → обернуть `MedicalKnowledge.save()` в `FileLock`
  - Файлы: `medical_system.py`, `patient_intake.py`

- [x] **Zip bomb в whatsapp_importer** — `zipfile.extractall()` без проверки
  - Добавить: проверка размера члена zip, максимальный суммарный размер
  - Файл: `whatsapp_importer.py`

- [x] **OCR ошибка возвращается как текст** — `ocr_engine.py` возвращает строку `"[OCR: не удалось...]"`
  - `lab_parser.py` пытается разобрать её как лабданные → мусорный диагноз
  - Fix: возвращать `None` или поднимать исключение; вызывающий код проверяет `if result is None`

- [x] **Temp файлы в /tmp без защиты** — медданные пациентов читаются всем
  - `telegram_bot.py`: добавить `os.chmod(tmp_path, 0o600)` сразу после создания

---

## 🟠 HIGH — в течение недели

- [x] **Sex/age в reference ranges** — сейчас всё считается для условного "*" пациента
  - Извлекать DOB из имени папки `SURNAME_NAME_YYYY_MM_DD`
  - Определять age_group: child (<18) / adult / senior (>65)
  - Передавать в `evaluate()` и `bayesian_differential()`
  - Файлы: `diagnosis_engine.py`, `lab_reference.py`, `patient_intake.py`

- [x] **DOB из текста — слишком жадный парсинг**
  - Сейчас берёт первую дату в тексте → дата анализа принимается за DOB
  - Fix: требовать ключевые слова перед датой: "р.", "дата рождения", "д/р", "born"
  - Файлы: `patient_intake.py`, `whatsapp_importer.py`

- [x] **OCR cache не thread-safe** — `@lru_cache` без блокировки
  - Telegram бот асинхронный → параллельные вызовы `ocr_image()` ломают кэш
  - Fix: `threading.Lock()` вокруг кэша или `cachetools.LRUCache` с lock

- [x] **DeepSeek R1 вызывается всегда** — дорогая модель даже при уверенности Байеса > 90%
  - Fix: `if max_posterior < 0.60 or confidence_gap < 0.15: ask_deep(...)`
  - Файл: `diagnosis_engine.py:run_diagnosis_ai()`

- [x] **Whisper модель грузится при каждом голосовом** — 140MB в RAM каждый раз
  - Fix: глобальная переменная `_whisper_model = None`, lazy init
  - Файл: `telegram_bot.py:handle_voice()`

- [x] **Rate limiting в боте** — один пользователь может исчерпать весь DeepSeek quota
  - Fix: `dict[user_id → last_request_time]`, throttle 1 req/10s per user

---

## 🟡 MEDIUM — следующий спринт

- [x] **lab_reference.py — дополнить базу** — 165 параметров (2026-03-17)
  - Витамины B1-B7/A/C/E/K, гормоны (SHBG, AMH, PTH, IGF1, ACTH, PRL, ALD, RENIN, GH)
  - Минералы (Zn, Cu, Se, Mn, P), метаболиты (HCY, лактат, пируват, NH3, СКФ)
  - Антитела (АТ-ТГ, ANA, ANCA, анти-дсДНК, RF, АСЛО, CCP), иммуноглобулины (IgA/G/M/E)
  - Онкомаркеры (PSA, CA125/199/153, AFP, CEA), кардиомаркеры (тропонин, BNP, NT-proBNP)
  - Гемостаз расшир. (антитромбин III, протеин C/S), апо-липопротеины, вч-СРБ, ИЛ-6

- [x] **Алиасы lab_reference.py — 291 алиас** (2026-03-17)
  - Народные (ГГЦ→GGT, Холес→CHOL, Сах→GLU), английские, грузинские

- [x] **Аудит-лог** — `logs/audit.jsonl` + `audit_log.py`, используется в telegram_bot.py
- [x] **Поиск пациентов по симптомам и диагнозу** — `search_patients_by_symptom()` + меню пункт 9
- [x] **Экспорт отчётов** — PDF пациента из GUI / бота
- [x] **Файловая блокировка для processed_files.json** — мигрировано в SQLite (db.py WAL)

---

## ✅ Сделано (2026-03-17) — db.py SQLite

- [x] **`db.py`** — полный слой SQLite для AIM:
  - Таблицы: `patients`, `lab_snapshots`, `diagnoses`, `ze_hrv`, `knowledge`, `processed_files`
  - FTS (Full Text Search) по диагнозам: `diagnoses_fts`
  - `upsert_patient()`, `save_labs()`, `save_diagnosis()`, `save_ze_hrv()`, `upsert_knowledge()`
  - `search_patients()`, `search_diagnoses()` (FTS), `get_lab_history()`, `get_ze_history()`
  - `is_processed()` / `mark_processed()` — замена `processed_files.json`
  - `migrate_from_json()` — миграция из старых JSON/файлов
  - CLI: `--migrate`, `--stats`, `--search`
- [x] **Миграция выполнена**: 5 пациентов, 5 диагнозов, 4 знания, 40 файлов → `aim.db`

---

## 🔴 СЛЕДУЮЩИЙ СПРИНТ — SQLite миграция (ПРИОРИТЕТ #1)

**Почему срочно:** при 100+ пациентах `Path.iterdir()` + JSON-парсинг тормозит.
Нет поиска по симптомам/диагнозу. Race conditions в knowledge base.

**Схема БД** (`~/AIM/aim.db`):
```sql
patients        (id, surname, name, dob, sex, folder_path, created_at)
lab_snapshots   (id, patient_id, taken_at, source_file, params_json)
diagnoses       (id, patient_id, created_at, bayesian_json, llm_text, confidence)
ze_hrv          (id, patient_id, recorded_at, ze_v, ze_state, rmssd, sdnn, mean_hr, raw_json)
knowledge       (id, condition, evidence_json, updated_at)
processed_files (id, path, hash_md5, processed_at, status)
```

**Задачи:**
- [x] Создать `db.py` — инициализация SQLite + CRUD функции
- [x] Мигрировать `medical_knowledge.json` → таблица `knowledge`
- [x] Мигрировать `processed_files.json` → таблица `processed_files`
- [x] Мигрировать папки пациентов → таблица `patients` + `diagnoses`
- [x] FTS (Full Text Search) по диагнозам — `diagnoses_fts`
- [x] **Подключить `patient_intake.py`** → пишет в БД:
  - `upsert_patient()` при обработке каждой папки
  - `save_diagnosis()` после LLM-анализа
  - `save_labs()` после парсинга лабораторий
  - `upsert_knowledge()` при самообучении
  - `is_processed()` / `mark_processed()` вместо JSON-кэша
- [x] **Подключить `ze_ecg.py`** → `save_ze_hrv()` при появлении RR-данных из HealthWearable
- [x] **Обновить `medical_system.py`** → интеграция с DB:
  - `list_patients()` читает из SQLite, fallback на filesystem
  - `search_patients_by_symptom(query)` — FTS поиск по всем диагнозам
  - `db_stats()` — статистика БД
  - Меню: пункт 9 (поиск 🔍), пункт 0 (статистика 📊)
  - Список пациентов показывает Ze-статус (💚🟡🔴)
- [x] **Обновить `config.py`** → добавить `DB_PATH`

---

## 🟢 LOW — перспектива (1-3 месяца)

- [ ] **Динамика лабораторий — графики**
  - `matplotlib` → PNG → отправлять в бот по `/trend Фамилия HGB`

- [ ] **Drug interaction checking**
  - Список текущих препаратов в профиле пациента
  - Cross-reference с `treatment_recommender.py`

- [ ] **Multi-user: логин и роли**
  - Врач / ассистент / только-чтение
  - JWT токены в GUI или Telegram whitelist по username

- [ ] **FHIR/HL7 экспорт** — для интеграции с внешними EHR

- [ ] **Offline режим** — кэшировать ответы LLM локально, работать без интернета

- [ ] **Голосовой анамнез** — пациент диктует жалобы → Whisper → структурированный intake

- [ ] **WhatsApp API (официальный)** — получать новые сообщения автоматически без экспорта

---

## Архитектурные решения (принятые)

| Решение | Почему |
|---------|--------|
| DeepSeek V3 (`deepseek-chat`) — основной | Дешёвый, быстрый, OpenAI-совместимый |
| DeepSeek R1 (`deepseek-reasoner`) — только для диагностики | Сильное рассуждение, но медленный и дорогой |
| Файловая система для пациентов | Простота, видимость, легко бэкапить |
| aiogram 3.x для Telegram | Async, активно поддерживается |
| Whisper `base` model | 140MB, хороший баланс скорость/качество для медтерминов |

---

## Известные ограничения (не баги, а дизайн)

- Система работает **только локально** на машине Dr. Jaba
- Нет шифрования данных пациентов (приемлемо для локального использования)
- WhatsApp импорт — только через ручной экспорт `.txt` файлов с iPhone
- DeepSeek API требует интернет-соединения

---

## Запуск

```bash
# GUI + авто-запуск Telegram бота
cd ~/AIM && source venv/bin/activate && python3 aim_gui.py

# Только Telegram бот
cd ~/AIM && source venv/bin/activate && python3 telegram_bot.py

# CLI обработка всех пациентов
cd ~/AIM && source venv/bin/activate && python3 patient_intake.py --all
```
