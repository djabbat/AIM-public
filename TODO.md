# AIM — TODO & Roadmap

## 📌 Правило: язык программирования по умолчанию

**Если нет явного указания на конкретный язык — писать код на Rust.**
Если другой язык объективно лучше для задачи — сначала предложить и обосновать, и только после подтверждения писать код.

---

## 📌 Правило: DeepSeek для текстовых задач

**Если задача подходит DeepSeek — использовать DeepSeek API, не делать вручную.**

| Категория | Примеры |
|-----------|---------|
| **Текст / статьи** | написать статью, раздел, введение, обсуждение |
| **Перевод** | научный, медицинский, художественный текст |
| **Рецензирование** | peer review, ответ рецензентам, cover letter |
| **Гранты / документы** | грант, питч, меморандум, резюме, абстракт |
| **Редактура** | полировка текста, стиль, академический английский |
| **Пациенты (AIM)** | объяснить диагноз, назначение, анализы — понятным языком |
| **Код** | объяснить код, docstrings, code review, тесты, SQL |
| **kSystem** | статьи лексикона на 8 языках |
| **Kartvely** | главы книги, анализ исторических источников |
| **Space** | описания упражнений на 4 языках |
| **Regenesis** | протоколы, клинические обоснования |
| **ŠamnuAzuzi** | либретто на др. языках, программные заметки |
| **Переписка** | письма инвесторам, деловые email, ответы на замечания EIC |

**Ключ:** `~/.aim_env → DEEPSEEK_API_KEY` · **Вход:** `~/Desktop/AIM/llm.py` · **Модели:** `deepseek-chat` (быстро) · `deepseek-reasoner` (сложно)

---

_Последнее обновление: 2026-03-25_

---

## 🟢 Завершено 2026-03-25 — Опера ŠamnuAzuzi v4

- [x] **[ŠamnuAzuzi] Полная партитура оперы написана** ✅ 2026-03-25
  - Файл: `~/Desktop/ŠamnuAzuzi/Score/SAMNU_AZUZI_v4.musicxml` (34.2 MB)
  - **1800 тактов** точно: Увертюра=180 + Акт I=450 + Акт II=270 + Акт III=360 + Акт IV=540
  - Все 12 аутентичных грузинских песен интегрированы:
    Цинцкаро, Бери-Берикоба, Мравалжамиер, Хасанбегура, Нана, Самкурао,
    Одоия, Лиле, Мтиулури, Виришхау, Рехвиаши, Чакруло
  - Динамика: pp → fff во всех секциях
  - Грузинские инструменты (Ламури, Чунири, Пандури) — мелодические партии
  - Трио (Мкримани/Мтавари/Бани) — во всех актах включая Увертюру
  - Асимметричные такты: 5/8 (Бери-Берикоба, Мтиулури) и 7/8 (Чакруло, Хумбаба)
  - Генератор: `~/Desktop/ŠamnuAzuzi/Score/generate_score_v4.py`

## 🟢 Завершено 2026-03-25 — Kartvely финальная версия

- [x] **[Kartvely] Финальная версия книги + переводы** ✅ 2026-03-25
  - Peer review Claude: `~/Desktop/Kartvely/PEER_REVIEW_CLAUDE.md`
  - Все 51 остаток «ТХТ» → «ГХТ» заменены
  - Добавлено Приложение Д: Таблица фактов и гипотез (15/15/3)
  - Добавлено Приложение Е: Список литературы
  - Исправлено KTT → KHT в Глоссарии
  - Усилено предупреждение к Директиве 1948
  - Добавлена критика Рубио 1999 в лингвистическую главу
  - Уточнены даты Вектора I
  - .docx (RU): `~/Desktop/Kartvely/Kartvely_RU_final.docx`
  - .docx (EN): в процессе — фоновый агент
  - .docx (KA): в процессе — фоновый агент

---

## 🔴 Входящие из экосистемы (2026-03-25) — книга Diets

- [x] **[Diets] Дописать книгу + quality check** ✅ 2026-03-25
  Главы 12 (меню), 13 (кулинарный практикум), 14 + Заключение написаны через DeepSeek.
  Quality review сохранён: `~/Desktop/Diets/QUALITY_REVIEW.md`.
  Книга: `Diets_v1.md` (1524 стр.). Следующий шаг: peer review (см. `Diets/TODO.md`).

---

## 🔴 Входящие из экосистемы (2026-03-25) — обновлено

- [x] **[AIMIntegration / CDATA] Полная цепочка AIM→CDATA завершена** ✅ 2026-03-25
  - Бинарник `cdata_patient_sim` скомпилирован (release)
  - `DamageParams::scaled(factor)` + `set_damage_rates()` в Rust
  - `cdata_bridge.py`: исправлен путь, добавлен `damage_scale_from_ze(ze_v, ze_state)`
  - `medical_system.py`: Ze-HRV из SQLite → blend 40%/60% clinical/Ze → симуляция
  - Тест: damage_scale 0.6→99.9y, 1.0→75.4y, 5.0→18.9y ✅

## 🔴 Входящие из экосистемы (2026-03-25)

- [x] **[CDATA / Ze] Препринты опубликованы на Zenodo** ✅ 2026-03-25
  - Tkemaladze J. *The Centriolar Damage Accumulation Theory of Aging (CDATA)* → https://doi.org/10.5281/zenodo.19174506
  - Tkemaladze J. *Ze System as Observer* → https://doi.org/10.5281/zenodo.19174630
  - ~~bioRxiv preprint~~ задача закрыта — опубликовано на Zenodo вместо bioRxiv

---

## 🔴 Входящие из экосистемы (2026-03-24)

- [x] **[CDATA / GUI-CRIT-1] GUI не выводит реальные числа симуляции** ✅ ИСПРАВЛЕНО 2026-03-24
  `SimulationManager` запускается в фоновом потоке, `mpsc`-канал передаёт `SimSnapshot` в GUI.
  Графики строятся по реальным ECS-данным (frailty, pool, ROS, myeloid, telomere, epigenetic).
  Детали: `/home/oem/Desktop/CDATA/TODO.md` → [GUI-CRIT-1]

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

**Схема БД** (`~/Desktop/AIM/aim.db`):
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

## 🟡 Space — Нумерологический помощник (web + mobile)

> **Источник 1:** «Место Силы» → Приложение 1 Нумерологическая система (v6.docx)
> **Источник 2:** Александров, книги в `~/Desktop/Space/Materials/numerologia/Alexandrov_Numerologia/`
> **Алгоритм изучен** ✅ 2026-03-26 (см. ниже)

- [ ] **[Space] Web + Mobile: помощник изменения нумерологической матрицы**

  **Ключевая идея:** матрицы (личная + матрица дня) меняются — и в этом весь смысл.
  Помощник не просто показывает матрицу, а **ведёт пользователя через её изменение**.

  ### Алгоритм (Александров) — ИЗУЧЕН ✅

  **Личная матрица (психоматрица Пифагора) из даты рождения:**
  1. Число 1 = сумма всех цифр даты (ДД+ММ+ГГГГ)
  2. Число 2 = сумма цифр числа 1
  3. Число 3 = число 1 − (2 × первая цифра даты)
  4. Число 4 = сумма цифр числа 3
  - Все цифры даты + 4 числа → расставляются в сетку 3×3 по значению (1→[1,1], 9→[9] и т.д.)

  **Матрица дня (по Александрову) — уточнённый алгоритм** ✅ 2026-03-26

  > Александров не строит «матрицу дня» как сетку 3×3.
  > Он рассчитывает **дополнительные цифры из даты события/дня**
  > и ищет **совпадения и позиционные переходы** с числами рождения человека.

  **Алгоритм работы с датой дня:**
  1. Взять сегодняшнюю дату → рассчитать 4 дополнительных числа (тот же алгоритм, что для личной матрицы):
     - Число A = сумма всех цифр даты
     - Число B = сумма цифр A
     - Число C = A − (2 × первая цифра даты)
     - Число D = сумма цифр C
  2. Взять 4 дополнительных числа из даты **рождения** пользователя (его A, B, C, D)
  3. Найти **совпадения** между числами дня и числами рождения:
     - Полное совпадение набора → «сегодня ты действуешь в своей силе» (как Жуков под Сталинградом)
     - Частичное совпадение → какие именно твои качества активированы сегодня
  4. Найти **позиционные переходы** — число из позиции «основа» рождения переходит в позицию «цель» дня (или наоборот) → указывает направление усилий
  5. Сформулировать рекомендацию: какое личное качество (из матрицы рождения) сегодняшняя дата **активирует, усиливает или блокирует** — и что с этим делать

  **Пример логики (Сталинград 19.11.1942):**
  - Доп. числа дня: `28 10 26 8` — полное совпадение с числами рождения Жукова
  - Вывод: день «работает» через качества Жукова
  - `26 8` переходит из «цели» даты Барбароссы → в «основу» дня → в «итог» смерти Гитлера
  - Так Александров читает причинно-следственную цепь через числа

  **Функции помощника:**
  - Расчёт личной матрицы (дата рождения)
  - Расчёт матрицы дня (автоматически: сегодня)
  - **Ежедневные рекомендации**: как использовать энергию дня для изменения своей матрицы
  - **Рекомендации по изменению личной матрицы**: что наработать, через что, что это изменит в человеке
  - Отслеживание динамики (дневник изменений)

  **Стек:** рассмотреть Phoenix LiveView (уже в DrJaba) + React Native / Flutter для mobile

---

## 🟢 LOW — перспектива (1-3 месяца)

- [x] **Динамика лабораторий — графики** ✅
  - `trend_chart.py` → PNG с нормой → Telegram `/trend Фамилия HGB`

- [x] **Drug interaction checking** ✅
  - `drug_interaction_checker.py` — локальная БД 40+ пар, синонимы, CYP
  - Telegram `/meds Фамилия interactions` + `check_patient_medications()`

- [x] **Multi-user: логин и роли** ✅
  - `auth.py` — роли admin/doctor/readonly, PBKDF2, сессии 30 дней
  - `require_auth()` интегрирован в `medical_system.py`

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
