# AIM v8.0 — Architecture Integration Matrix

**Сердце экосистемы LongevityCommon.** Не AI. Не медицина. Интеграционный хаб.

## Что это

Центральный реестр, граф зависимостей и кросс-проектная валидация для 15 проектов LongevityCommon.

## Запуск

```bash
# Показать статус всех проектов
python3 dashboard/status.py

# Сгенерировать граф экосистемы
dot graph/ecosystem.dot -Tpng -o graph/ecosystem.png

# Проверить согласованность
python3 validate/counter_numbering.py
python3 validate/ze_vstar.py
python3 validate/concept_versions.py
```

## Структура

- `registry.json` — машиночитаемый реестр (канон)
- `validate/` — скрипты кросс-проектной валидации
- `dashboard/` — статус-дашборд
- `graph/` — граф в DOT/Mermaid
- `MAP.md` — карта зависимостей (человекочитаемая)

## Архив

`_archive/v7_ai_code/` — полный код AIM v7.0 (AI-медицинская система). Удалён из концепции 2026-05-09.
