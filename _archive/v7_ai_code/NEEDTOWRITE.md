# NEEDTOWRITE.md — AIM

Список документации / статей / постов, которые нужно написать. Не
трекер задач (это `UPGRADE.md` / `TODO.md`), а очередь written content.

**Convention:**
- 🔥 = high-priority (нужно для гранта / pilot enrolment / publication deadline)
- ⏳ = на потом (когда руки дойдут)
- ✅ = написано, источник в `docs/manuscripts/` или published

---

## Внутренние technical docs

- ✅ `docs/operational/DEPLOY_RUNBOOK.md` — production deploy step-by-step
 для `aim-llm`, `aim-ai-*` binaries, Phoenix release. Создано 2026-05-07
 (308 LoC, 8 секций + production-readiness checklist).

- ✅ `docs/operational/PILOT_PROTOCOL.md` — клинический протокол enrolment
 для STRATEGY.md P1-3 pilot. **DRAFT — требует MD review**, помечены
 `[CLIN-FILL]` placeholders. 13 секций + open questions для Dr. Jaba.
 Создан 2026-05-07 (226 LoC).

- ⏳ `docs/api/RUST_CRATES_REFERENCE.md` — публичный API всех 192 Rust
 crates (можно автогенерить через `cargo doc` + post-process).

- ⏳ `docs/api/PHOENIX_ROUTES_REFERENCE.md` — список 21 route + что
 принимают / возвращают / какие assigns используют.

- ⏳ `docs/architecture/MULTI_USER_AUTH_FLOW.md` — node→hub validate-token
 flow + offline grace + Telegram /link codes (упомянуто в CLAUDE.md, нет
 отдельного документа).

## Научные публикации

- 🔥 RCT-результаты pilot когорты (после STRATEGY P1-3 закрыт): целевой
 журнал = *npj Digital Medicine* или *Lancet Digital Health*; вспом.
 публикация в *Longevity Horizon*.

- ⏳ Описание `aim-disagreement` Blumenthal-Lee implementation как
 technical note. *JAMIA Open* — open access.

- ✅ `docs/manuscripts/MANUSCRIPT_PATIENT_AS_PROJECT_2026-05-07.md` —
 cornerstone paper, опубликован в *Longevity Horizon* 2(4)
 .

- ✅ Technical note: *Architecture and Design of a Prototype Multi-Modal
 Clinical Decision Support System for Integrative Medicine*. *Longevity
 Horizon* 2(4).

## Outreach / blog / video

- ⏳ `JabaEkimi` YouTube эпизод про L_AGENCY и почему AI должен спрашивать
 пациента, а не за него решать.

- ⏳ Twitter/X thread про PAM-13 как primary outcome — почему это сильнее
 чем "physician satisfaction" метрика.

- ⏳ Пост на longevity.ge: "Что такое L3 — пациент как проект разработки,
 а не объект диагностики?"

## Internal training

- ⏳ Onboarding doc для новых разработчиков (читать в порядке): `README` →
 `THEORY.md` → `STRATEGY.md` → `CLAUDE.md` → `STACK.md` → `MAP.md`.

- ⏳ Onboarding для врачей (Dr. Jaba's clinic team): что такое PAM-13,
 как заполнять, как читать coach prompts.

---

**Триггеры пополнения:**
- При закрытии `STRATEGY.md` P1-3 (pilot) → автоматически активируется
 publication writing (RCT paper).
- При обнаружении third-party хочет deploy AIM → активируется
 `DEPLOY_RUNBOOK.md` writing.
- При появлении CDS-error под законом → `KERNEL_VIOLATIONS_LOG.md` (не
 существует, нужно создать когда появится первое нарушение).
