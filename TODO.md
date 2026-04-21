# AIM v7.0 — TODO

Обновлено: 2026-04-21

---

## CONCEPT↔CODE MISMATCHES (2026-04-21 audit)

Полный лог: `CONCEPT_CODE_AUDIT_2026-04-21.md`.

FIX NOW уже применены в CLAUDE.md и CONCEPT.md. Оставшиеся пункты:

- [ ] **PARAMETERS.md / MAP.md / KNOWLEDGE.md / LINKS.md / MEMORY.md / UPGRADE.md** — по правилу `feedback_project_core` каждый проект должен иметь 10-файловое ядро. Текущее ядро AIM: CONCEPT/CLAUDE/README/TODO/UPGRADE (5/10). Создать недостающие 5 (генерировать из CONCEPT через DeepSeek).
- [ ] **Рассмотреть вынесение `_route()` в отдельный `router.py`** — CONCEPT §3 описывает Router как самостоятельный компонент, физически логика в `llm.py`. Вариант А: вынести в `router.py` (чище архитектурно). Вариант Б: закрепить текущее положение в CONCEPT (уже сделано в §5). Решить осознанно, а не случайно.
- [ ] **Цитирование `lab_reference.py`** — 59 аналитов без источников. Добавить для каждого референс (NCBI / WHO / UpToDate / локальные ГОСТ). Пока 0 цитат — потенциальная ответственность при клиническом использовании.
- [ ] **Fallback не учитывает Groq** — в `llm._fallback()` перебираются только DeepSeek/Qwen/KIMI, Groq не в цепочке. Добавить Groq в fallback-цепочку.
- [ ] **CONCEPT §6 Agent Loop** — описывает классификатор задач, которого нет как отдельного компонента. Либо реализовать task classifier, либо переписать §6 под текущую реальность (CLI → agent methods напрямую).
- [ ] **Удалить устаревший `DEEP_AUDIT_2026-04-21.md`** (ссылается на v6-модули: `bayesian_medical.py`, `diagnosis_engine.py`, `treatment_recommender.py`, `medical_knowledge.json`, `patient_analysis.py`, `lab_parser.py`, `ocr_engine.py`) — эти модули v7.0 НЕ имеет и иметь не планирует. Архивировать в `docs/` или удалить.
- [x] **CLAUDE.md на `~/CLAUDE.md` (global)** всё ещё ссылается на устаревшие модули v6 — ✅ ИСПРАВЛЕНО 2026-04-21. Global CLAUDE.md AIM section переписан в соответствии с v7.0.

---

## Drug Interactions — Full Integration (P1, not blocker)

Menu `m9` "Проверка лекарственных взаимодействий" добавлено 2026-04-21 в **manual-input mode** (CLI + GUI + i18n × 9 языков). Текущая версия принимает список препаратов через запятую, проверяет по static dictionary `agents/interactions.py` (35 curated pairs).

**Для полной clinical integration (P1, блокеры below):**

- [ ] **Migration SQLite:** `ALTER TABLE patients ADD COLUMN medications JSON DEFAULT '[]'` — хранить список препаратов пациента. Требует `db.py` migration helper + re-init script для existing DB.
- [ ] **UI для редактирования patient.medications** — либо новое подменю в `new_patient()`/`open_patient()`, либо отдельный menu item "редактировать препараты" (сейчас m8 занят Settings).
- [ ] **m9 dual-mode** — "9. Проверка взаимодействий → (а) для открытого пациента (auto-fetch меds), (б) вручную список". Сейчас доступен только (б).
- [ ] **Расширение static DB** — 35 pairs → 200+ pairs. Минимум для integrative medicine: senolytics × chemotherapy, senolytics × anticoagulants, all common supplements × warfarin, SSRI/MAOI × common OTC, immunosuppressants × grapefruit, full set. Source: DailyMed API + OpenFDA FAERS.
- [ ] **RxNorm integration** — per-drug `rxcui` lookup через NLM RxNorm API вместо simple name canonicalization. Решает class-to-instance expansion (e.g. "SSRI" → fluoxetine/sertraline/etc. без manual aliases).
- [ ] **Severity i18n** — сейчас severity labels ('major', 'moderate', ...) выводятся в английском. Локализовать в i18n.py для 9 языков.

**Status:** manual mode live and safe for integrative-practice use (35 verified pairs + disclaimer). Full auto-fetch workflow + RxNorm is a separate 2-3-day project.

---

---

## 🔴 СВЕРХСРОЧНО — P0

- [x] Добавить ключи в `~/.aim_env`: `KIMI_API_KEY`, `QWEN_API_KEY`, `GROQ_API_KEY`
- [x] GROQ ✅ работает
- [ ] **KIMI** ⚠️ ключ есть, нет баланса → пополнить счёт на moonshot.cn
- [ ] **Qwen** ⚠️ ключ есть (Alibaba Bailian WS), 403 AccessDenied.Unpurchased → активировать модели в Singapore-регионе Model Studio (принять ToS, подписаться на нужные модели)
  - Endpoint: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
  - Текущий ключ: `sk-fcd49c2ee5044c459dff68e58eaf73de`
  - После активации протестировать: `python3 -c "from llm import ask_multilang; print(ask_multilang('გამარჯობა', lang='ka'))"`
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
- [x] Лаб. нормы (`lab_reference.py`) ✅ 2026-04-16

---

## Фаза 4: Telegram-бот ✅ 2026-04-16

- [x] `telegram_bot.py` — диагностика, лечение, перевод, фото OCR, PDF intake
- [x] Мультиязычный (автодетект языка) + роутер LLM

---

## Фаза 5: GUI ✅ 2026-04-16

- [x] `aim_gui.py` — customtkinter, полный паритет с CLI (m1-m8)
- [x] Async LLM через threading (не замораживает UI)

---

## 🔴 ВХОДЯЩИЕ ИЗ ЭКОСИСТЕМЫ

### CDATA — Impetus Grant (P0)
- [ ] **ЗАВТРА 2026-04-17 в 20:00 Тбилиси** — Zoom с Aubrey de Grey (LEVF)
  - Link: https://us04web.zoom.us/j/79981692609 | Passcode: J7aeJ8
  - Цель: письмо поддержки для LOI Longevity Impetus Grants ($75K)
  - Шпаргалка: `CDATA/docs/SHPARGALKA_AUBREY_2026-04-17.docx`
- [ ] **Письмо от Aubrey нужно до 2026-04-21**
- [ ] **Дедлайн LOI: 2026-04-25** (LOI v22 готов: `CDATA/docs/LOI_Impetus_v22_2026-04-15.docx`)
- [ ] Геигер (Ulm) — подтвердить участие как Experimental Co-PI

### HAP — рукопись P0
- [ ] Написать полную рукопись → *Biological Reviews* (IF ~10)
- [ ] Расширить мета-анализ таксонов: 56 → 80+ (через DeepSeek)

### FCLC
- [ ] 2026-05-01: напомнить Кариму и Карлосу о встрече

## 2026-04-19 — Входящие из экосистемы

- **CDATA (P0):** Aubrey de Grey engaged scientifically, предлагает fibroblast polyGlu test; major refinement: P(n,t). Update CONCEPT + Dual-Counter paper. (CDATA/TODO.md + CDATA/UPGRADE.md)
- **PhD (P0):** Ждём ответ Лежава до 2026-05-03. Orchestrator peer reviews в фоне.
- **Microscope (P0):** Брат ищет на Taobao ToupCam E3CMOS05000KPA (USB 3.0 5MP) + T2→C-mount adapter. Bюджет ~782 GEL ($293). Jaba должен выбрать конкретный SKU.
- **Reference audit (ACTIVE):** 1017 potential PMID mismatches в core files — результаты в REFERENCE_AUDIT_*.md по каждому проекту. Остановить подготовку документов до audit complete.
