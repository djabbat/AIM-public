# CLAUDE.md — AIM v7.0

---

## Startup Protocol

**Полные правила:** `~/Desktop/Claude/protocols/START.md`

---

## Архитектура

AIM v7.0 — гибридный LLM-роутер. Ядро:

| Файл | Роль |
|------|------|
| `medical_system.py` | Точка входа, agent loop |
| `llm.py` | Роутер: Groq → DeepSeek → KIMI → Qwen |
| `config.py` | Ключи, модели, пути, языки |
| `i18n.py` | 9 языков (ООН-6 + KA + KZ + DA) |
| `db.py` | SQLite: пациенты, сессии, кэш |

---

## Правило LLM

**Никогда не вызывать API напрямую.** Всегда через `llm.py`:

```python
from llm import ask, ask_deep, ask_long, ask_multilang, ask_fast
```

Роутер сам выберет модель.

---

## Правило языков

**9 языков везде.** Ни одна строка UI не пишется жёстко — только через `i18n.py`:

```python
from i18n import t
print(t("menu_title", lang))
```

---

## Пациенты (СТРОГО)

- `Patients/` — **НИКОГДА** не читать, не изменять, не коммитить без явной команды
- Новые файлы → `Patients/INBOX/`
- Формат папок: `SURNAME_NAME_YYYY_MM_DD/`

---

## Ключи

Только в `~/.aim_env`. Никогда в коде.

```
DEEPSEEK_API_KEY   KIMI_API_KEY   QWEN_API_KEY   GROQ_API_KEY
```

---

## Git push

Перед каждым push спрашивать: приватный (`djabbat/AIM`) или публичный (`djabbat/AIM-public`)?

Публичный **исключает**: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `Patients/`

---

## При добавлении пункта меню

Изменить **оба** файла: `medical_system.py` + `aim_gui.py` (когда будет создан).
Источник истины — ключи в `i18n.py`.
