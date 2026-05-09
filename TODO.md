# TODO.md — AIM v8.0

**Обновлено:** 2026-05-09
**После:** удаления AI-кода, создания реестра

---

## P0 — Сделать немедленно

- [x] CONCEPT.md v8.0 — переписан
- [x] registry.json — канонический реестр 15 проектов
- [x] MAP.md — карта зависимостей
- [x] README.md, CLAUDE.md, CHANGELOG.md, .gitignore — переписаны
- [x] AI-код v7.0 → `_archive/v7_ai_code/`
- [ ] **validate/counter_numbering.py** — проверка номеров счётчиков
- [ ] **validate/ze_vstar.py** — проверка v*
- [ ] **validate/concept_versions.py** — проверка версий CONCEPT.md
- [ ] **validate/references.py** — проверка PMID/DOI
- [ ] **dashboard/status.py** — генератор статус-дашборда
- [ ] **graph/ecosystem.dot** — DOT-граф
- [ ] **graph/ecosystem.mermaid** — Mermaid-граф
- [ ] **registry.toml** — человекочитаемая версия реестра

## P1 — Скоро

- [ ] READ CONCEPT.md из каждого подпроекта и обновить registry.json если параметры изменились
- [ ] Пройти по всем 15 проектам и сверить статусы с реальностью
- [ ] Создать Makefile: `make validate`, `make dashboard`, `make graph`

## P2 — Когда-нибудь

- [ ] Автоматический детектор дрифта (cron: раз в неделю проверять все CONCEPT.md на изменения)
- [ ] Веб-дашборд (простой HTML с JS, без сервера)
- [ ] Интеграция с GitHub: авто-валидация при push в любой подпроект
