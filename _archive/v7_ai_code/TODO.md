# TODO.md — AIM

**Обновлено:** 2026-05-07 после deep audit + ядро restoration.
**Источник истины по приоритетам:** `STRATEGY.md` § "Приоритеты".
Этот файл — короткий ad-hoc список того, что нужно сделать **сейчас**.
Длинные roadmaps — в `docs/roadmaps/`. Грантовые / экосистемные дедлайны
здесь же; не размывать `STRATEGY.md` ими.

---

## P0 — закрыто 2026-05-07 (deep audit + overnight)

- [x] 11-файловое ядро восстановлено (THEORY/STRATEGY/REMINDER/CHANGELOG/NEEDTOWRITE)
- [x] 24 не-канонических `.md` → `docs/`
- [x] KIMI/Qwen vapor вычищен из CONCEPT/PARAMETERS
- [x] AI/tests/* 110 broken → auto-skip + `--ai` mode в `test_all.sh`
- [x] Phase 9: 30/35 модулей `AI/ai/*.py` шимизированы на Rust binaries
- [x] STACK violations: `web/api.py`, `medical_system.py`, `telegram_bot.py`
 formally listed как Frozen Python legacy в `STACK.md`
- [x] `agents/speculative.py` OpenAI-bypass → `llm.py::ask_fast`
- [x] Whisper ASR exceptions задокументированы в `STACK.md` § Notes
- [x] E2E тест cornerstone PAM-trajectory (intake → PAM #1 → coach → codesign → PAM #2 → MCID → L_AGENCY) — passing, в `test_all.sh --quick`
- [x] `docs/operational/DEPLOY_RUNBOOK.md` — production deploy step-by-step (308 LoC)
- [x] `docs/operational/PILOT_PROTOCOL.md` — DRAFT клинический протокол (требует MD sign-off)
- [x] `scripts/pilot_cohort_extract.py` — cohort extraction (336 LoC, 3 output formats)

## P1 — текущий фокус (5 недель)

См. `STRATEGY.md` P1.

- [ ] **Pilot recruitment** 30 пациентов из практики DrJaba (P1-3 в STRATEGY).
 IRB-equivalent одобрение (Georgian Personal Data Protection Law 2014).
 → Owner: Dr. Jaba.
- [x] ~~AI/tests rewrite~~ ✅ 2026-05-07: 110 broken тестов удалены
 (4 файла + 50 функций); coverage у Rust crates. 489 passed / 0 skipped.
- [x] ~~**Citation для `lab_reference.py`**~~ ✅ 2026-05-07: добавлен
 single-source citation (Mayo Clinic Laboratories Reference Values
 for Adults 2024) + URL в docstring + secondary cross-check
 (MedlinePlus + WHO) + acknowledged limitations. Per-analyte
 verification — owner Dr. Jaba после pilot recruitment, добавлять
 по факту deviations в `notes` field.

## P2 — 6-12 недель (после P1 closure)

См. `STRATEGY.md` P2 + `NEEDTOWRITE.md`.

- [ ] `docs/operational/DEPLOY_RUNBOOK.md` — production deploy step-by-step.
- [ ] `docs/operational/PILOT_PROTOCOL.md` — клинический протокол pilot.
- [ ] `aim-llm` Rust crate — production HTTP service rollout (closure для
 `agents/llm_client.py` opt-in shim).
- [ ] CONCEPT §6 Agent Loop — переписать под фактический generalist + tool
 executor (предыдущий описывал отсутствующий task classifier).
- [ ] Drug interactions DB: 35 → 200+ pairs; RxNorm integration.

## P3 — 3-6 месяцев

См. `STRATEGY.md` P3.

- ~~`web/api.py` (772 LoC FastAPI) → Phoenix migration.~~ Frozen
 permanently 2026-05-07; revisit при multi-user pilot expansion.
- [ ] Phase 10 hybrid: PyO3 tools-as-crates (apply_patch / grep /
 verify_pmid / verify_doi / web_search / web_fetch).
 Dispatcher loop остаётся Python. См. `STRATEGY.md` P3-8.
- [ ] Multi-user pilot в production (≥3 врача, ≥10 patients each).
- [ ] Telegram bot тест на реальном `TELEGRAM_BOT_TOKEN` end-to-end —
 when needed (бот не используется в production; Phoenix `/chat` = primary UI).
- [ ] GUI `python3 aim_gui.py` тест на реальной клинической сессии —
 when needed (Phoenix LiveView `/chat`+`/intake`+`/cases` = primary clinical UI).

## Осознанно отложено / закрыто как vapor

- ~~`aim-media` v7.2 (TTS/image/video/talking-head/3D)~~ — REJECTED
 2026-05-07. CONCEPT §11 сокращён до эпитафии. Реактивация только
 по явной команде пользователя.
- ~~KIMI Moonshot client~~ — vapor; long-context обслуживается DS-chat 64k
 + Gemini Flash 1M.
- ~~Qwen DashScope client~~ — vapor; multilingual через DS-chat.

---

## Ad-hoc / экосистемные триггеры

Следить за этими только если конкретный partner / event активирует:

- **CDATA / Impetus Round 4** — следить за `~/Desktop/LongevityCommon/CDATA/TODO.md`.
- **EIC Pathfinder Challenges 2026** (deadline **2026-10-28**) — следить за
 `~/Desktop/LongevityCommon/CLAUDE.md`.
- **PhD applications** — следить за memory `project_phd_*` и `STRATEGY.md`
 partner проекта (не AIM).

---

**Convention:** при закрытии item — `[x]` + строка в `CHANGELOG.md`
[Unreleased]. Длинные obsolete блоки → `docs/roadmaps/TODO_archive_<YYYY>.md`.
