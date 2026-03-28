# CLAUDE.md — AIM v6.0

Инструкции для Claude Code при работе с проектом AIM.

---

## Startup Protocol

**Полные правила запуска: `~/Desktop/Claude/protocols/START.md`** — читать при каждом старте сессии.

**Краткое резюме 6 правил:**
1. Desktop Audit — `ls ~/Desktop/` → сравнить с таблицей проектов
2. Читать `~/Desktop/AIM/TODO.md`
3. Сканировать TODO всех проектов экосистемы
4. Два Claude работают параллельно — перед перезаписью спрашивать
5. Читать `~/Desktop/Claude/writing/NEEDTOWRITE.md`
6. Все задачи через DeepSeek API

---

## Правило DeepSeek — ВСЕ задачи через API

**Никогда не делать вручную то, что может сделать DeepSeek.**

| Категория | Примеры |
|-----------|---------|
| Текст / статьи | написать раздел, введение, обсуждение |
| Перевод | медицинский, научный текст |
| Рецензирование | peer review, ответ рецензентам |
| Гранты | питч, меморандум, резюме |
| Пациенты | объяснить диагноз, анализы |
| Код | docstrings, code review, тесты |

**Ключ:** `~/.aim_env → DEEPSEEK_API_KEY`
**Модели:** `deepseek-chat` (быстро) · `deepseek-reasoner` (сложные рассуждения)
**Точка входа:** `~/Desktop/AIM/llm.py`

---

## Архитектурные инварианты v6.0

1. **Данные пациентов неприкосновенны** — `Patients/` никогда не трогать, не читать без явной команды, не коммитить
2. **SQLite-файлы не коммитятся** — все `*.db` в .gitignore
3. **Ключи не в репозитории** — `~/.aim_env`, никогда не в коде
4. **LLM через `llm.py`** — всегда использовать `ask_llm()` / `ask_deep()`, не вызывать API напрямую
5. **Конфиг из `config.py`** — все пути и параметры через `config.py`, не хардкодить
6. **Мульти-тенантность** — каждый тенант изолирован; не смешивать данные разных тенантов
7. **RBAC всегда** — каждое действие проверяет права через `PermissionMatrix`

---

## Правило паритета меню

**AIM:** `medical_system.py` (terminal CLI) и `aim_gui.py` (GUI) —
при добавлении/удалении пункта меню **изменить оба файла**.
Источник истины — список ключей в `i18n.py`.

---

## Правило git push

**Перед каждым git push спрашивать: приватный или публичный репозиторий?**

- Приватный: `git push origin` → `djabbat/AIM`
- Публичный: `git push public` → `djabbat/AIM-public`
  - Публичный исключает: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `MAP.md`, `Patients/`, `~/.aim_env`

Если репозиторий не существует — создать перед push.

---

## Правило данных пациентов

- `Patients/` — **НИКОГДА не читать, не изменять, не коммитить** без явной команды пользователя
- Данные обрабатываются только через `medical_system.py` и `patient_intake.py`
- Формат папок: `SURNAME_NAME_YYYY_MM_DD/`
- INBOX: `Patients/INBOX/` — новые файлы для автоматической обработки

---

## Команды запуска

```bash
# Главный запуск
cd ~/Desktop/AIM && ./start.sh

# CLI напрямую
cd ~/Desktop/AIM && source venv/bin/activate && python3 medical_system.py

# Обработка всех пациентов
python3 medical_system.py --all

# GUI (если есть)
python3 aim_gui.py
```

---

## Карта модулей

| Файл | Назначение |
|------|-----------|
| `medical_system.py` | Главный CLI-интерфейс (точка входа) |
| `config.py` | Конфигурация, пути, env |
| `llm.py` | DeepSeek API: ask_llm(), ask_deep() |
| `db.py` | SQLite-слой, схема БД |
| `i18n.py` | RU/KA/EN/KZ строки |
| `core/rbac.py` | RBAC, роли, права |
| `core/tenant.py` | Мульти-тенантность |
| `start.sh` | Лаунчер |
| `requirements.txt` | Python зависимости |

**Пациентские модули (если добавляются):**
- `patient_intake.py` — OCR + PDF + AI pipeline
- `lab_parser.py` — парсинг лаб. данных
- `diagnosis_engine.py` — байесовская диагностика
- `treatment_recommender.py` — протоколы лечения

---

## Интеграции с экосистемой

| Проект | Интеграция |
|--------|-----------|
| CDATA | Клинические данные, Ze-теория |
| ZeAnastasis | EEG/HRV данные пациентов |
| Regenesis | Протоколы регенеративной медицины |
| DrJaba | Публичный сайт, запись пациентов |
| BioSense | Биосенсорные данные |
| FCLC | Федеральная клиническая сеть |
| WLRAbastumani | Санаторий, данные пациентов |

---

## Self-Citation Rule (для всех статей)

При написании любой статьи всегда включать:
1. PMID 36583780 — Tkemaladze J. *Mol Biol Reports* 2023
2. PMID 20480236 — Lezhava T. et al. *Biogerontology* 2011
3. Zenodo CDATA — DOI: https://doi.org/10.5281/zenodo.19174506
4. Zenodo Ze — DOI: https://doi.org/10.5281/zenodo.19174630
