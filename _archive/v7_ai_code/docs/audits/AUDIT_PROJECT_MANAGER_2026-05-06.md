# AUDIT: AIM как менеджер долгоживущих проектов

**Дата:** 2026-05-06
**Скоуп:** AIM v7.0 (Python `agents/`, Rust `rust-core/crates/`, Phoenix `phoenix-umbrella/`, AI subproject `AI/ai/`).
**Метод:** read-only аудит ключевых модулей + cross-reference с PHASES_1-5_DONE_2026-05-03.md, AUDIT_AIM_vs_ClaudeCode_2026-05-02.md, AUDIT_2026-05-02.md, ROADMAP_SURPASS_ClaudeCode_2026-05-02.md, и DeepSeek-reasoner adversarial review (2026-05-06).
**Цель:** превратить AIM из reactive medical assistant + grant tracker в **proactive owner** долгоживущих entity-проектов трёх классов: пациенты, исследования (papers/grants — уже есть), роботизированные эксперименты.

---

## 0. Резюме одной строкой

AIM v7.0 имеет **70 % готовых строительных блоков** для project-manager роли (kernel, escalation_engine, stakeholder_tracker, project_state_machine, kpi_tracker, hooks framework, hive_queen каркас, AI self-improvement loop), но три **архитектурных пробела** не дают им сложиться в целое: (1) **patient-проекты живут в параллельной несовместимой схеме** относительно `project_owner.yaml`; (2) **нет long-running owner actor** — единственный proactive trigger это cron 09:00; (3) **нет hardware-bridge** для роботизированных экспериментов (AutomatedMicroscopy и PhD/E0 используют **Claude Code**, не AIM, см. `AutomatedMicroscopy/CONCEPT.md:23`).

Ниже — детализация и прогрессивный план в 4 фазы (~10–14 недель). План не требует переписывать ядро — только склеить уже работающие куски.

---

## 1. Текущая модель проекта в AIM — что есть

### 1.1 Schema "грантовый/научный проект" (зрелая, единственный pilot)

`agents/project_owner.py:115` `ProjectState{name, canonical, phase, goals, milestones, stakeholders, daily_checks}`
`USER/projects/FCLC.yaml` (единственный YAML на момент 2026-05-06, line-count 88)

Покрывает:

| Поле | Тип | Где обрабатывается |
|---|---|---|
| `phase` | enum DRAFT/REVIEW/SUBMITTED/ACCEPTED/PUBLISHED/REJECTED/ARCHIVED | `project_state_machine.py:46`, JSONL audit `~/.cache/aim/phase_history.jsonl` |
| `milestones[]` | id+deadline+criticality+blockers | `project_owner.py:96` `Milestone.is_hot` (≤7d или high≤14d) |
| `stakeholders[]` | name+role+last_contact+awaiting_reply+expected_response_by | `project_owner.py:75` + cross-table `agents/stakeholder_tracker.py:101` (SQLite contacts) |
| `escalation_rules[]` | tiny DSL: `deadline_within_days <= 7 and milestone.criticality == 'high'` | `agents/escalation_engine.py:80` deterministic recursive-descent parser, fingerprint dedup 24h |
| `kpis[]` | id+target+target_kind(floor/ceiling)+history | `agents/kpi_tracker.py:56`; auto-bound sources `agents/kpi_auto_updater.py:100` (`cost.weekly`, `stakeholders.total`, `eval.latest`, `literature.own_count`) |
| `daily_checks[]` | свободные строки | вставляются в `morning_brief` |

Артефакт: `morning_brief(FCLC)` рендерит ≤30-строчный Telegram-ready текст (`project_owner.py:234`); cron ежедневно 09:00 через `scripts/daily_brief.py` + systemd timer (`deploy/systemd/aim-daily-brief.timer`); escalation_engine evaluate_all прогон по всем YAML с cooldown.

**Rust mirror:** `rust-core/crates/aim-project-owner/src/lib.rs:1` (824 LoC, точный port) + `aim-project-state-machine/src/lib.rs:1` (524 LoC, тесты на phase machine 12 штук). Логика идентична Python — это часть rolling-port в Rust+Phoenix.

### 1.2 Schema "пациент" (зрелая, отдельная)

`agents/patient_memory.py:35` `PatientMemory{id, demographics, allergies, medications, conditions, history, known_unknowns, red_flags, missing_labs_count,..}`
`Patients/<Surname_Name_YYYY_MM_DD>/MEMORY.md` (markdown canonical, regex-парсер `read_memory`) + `aim.db.patient_index` SQLite индекс.

Покрывает:

- **Клиническое состояние:** demographics, allergies, medications (`name·dose·freq`), conditions (`dx·since·notes`), history (reverse-chron).
- **Kernel scoring inputs:** `red_flags`, `missing_labs_count`, `history_contradictions`, `unexplained_symptoms_count`, `last_visit_years_ago`, `dx_without_evidence`, `primary_complaint_undiagnosed`, `has_confirmed_dx` — феды для `agents/kernel.py:104` (Asimov + Ze utility scorer).
- **Intake auto-routing:** `agents/patient_inbox_watcher.py:202` — OCR → name+DOB extraction → move file `Patients/INBOX/*.pdf` → `Patients/<Surname>_<Name>_<DOB>/` + `AI_LOG.md` line.

**Rust mirror:** `rust-core/crates/aim-patient-memory/src/lib.rs:1` (markdown roundtrip + index trait) + `aim-patient-inbox-watcher/src/lib.rs:1` (OCR engine trait + classification, pure functions).

### 1.3 AI subproject (closed-loop self-improvement, **inward-facing**)

`AI/ai/` (33 модуля по `wc -l`, 6 840 LoC) — мониторит САМО качество AIM:

- **SD1 → DG1 → RD1 → S13 → S14 → FE1 → S1** pipeline:
 build self-diagnostic prompt → run via DS-V4-pro → ledger record → regression detect → stable_run consolidator → fix_planner → emit YAML eval cases → harness gate
- **Hive (HV2/HV3):** `hive_queen.py:80` — workers POST anonymized signals → queen `distill_candidates` → publish updates to feed; пока **2 типа candidate**: prompt_patch (compliance drift), skill (theme convergence)
- **S6 self-modify** (`self_modify.py:62` `_MIN_BASELINE_RUNS=28`, `_MIN_BASELINE_AGE_DAYS=28`) — gate ЗАКРЫТ до 4 недель ledger; framework есть.

### 1.4 Operational layer (зрелые primitives)

| Primitive | Файл | Что готово |
|---|---|---|
| Asimov decision kernel | `agents/kernel.py:104` (914 LoC) | L0-L3 + L_PRIVACY + L_CONSENT + L_VERIFIABILITY hard gates |
| Orchestrator pipeline | `agents/orchestrator.py:324` | PRE-laws → service_fn → POST L_VERIFIABILITY → Ze-verify (file:line refs мех. checked) → AST-verify (symbol-at-line + negative-call) |
| Permission broker | `agents/permission.py:1` | TUI / Telegram, audit, TTL cache, opt-in `AIM_INTERACTIVE_CONSENT=1` |
| Notify multiplexer | `agents/notify.py:1` | telegram + email + stdout + log + dedup window + rate-limit |
| Routines bundles | `agents/routines.py:1` + `USER/preferences/routines.yaml` | YAML-defined bundles `morning`, `pre-grant-submit`, `weekly-review` |
| Hooks framework | `agents/hooks.py:1` | 5 событий (LAB_CRITICAL, KERNEL_DECISION, SESSION_END, INTAKE_PDF, PRE_COMMIT) — **обработчики НЕ подключены к продьюсерам** (см. `TODO.md:96`) |
| serve_daemon | `agents/serve_daemon.py:1` | tick scheduler (daily/weekly/every) + Unix socket — каркас, НЕ запущен как owner-loop |

---

## 2. Архитектурные пробелы

### 2.1 GAP-1 (CRIT) — Patient ≠ Project, два несовместимых мира

**Симптом:**

| Аспект | project_owner | patient_memory |
|---|---|---|
| Storage | YAML, single file per project | Markdown в папке + SQLite index |
| Phase machine | DRAFT→..→ARCHIVED | **отсутствует** |
| Milestones / deadlines | да | **нет** (есть только `last_visit_years_ago`) |
| Stakeholders | да + SQLite contacts table | **нет** (пациент сам по себе single entity) |
| Escalation rules | DSL evaluator, Telegram dispatch | **нет** |
| Cross-project graph | `agents/project_graph.py:81` обнаружение depends_on / blocker refs | **нет** |
| Cron daily_brief | отображает все YAML | **пациенты вне scope** (`scripts/daily_brief.py`) |
| KPI tracking | да | **нет** (есть `agents/own_pubs_tracker` для своих публикаций, но не для пациентских KPI типа HbA1c, BP) |
| Phase advisory next_actions | per-phase | **нет** |

**DeepSeek контр-аргумент:** "разделение intentional из-за HIPAA/GDPR; patient — EHR fragment, project — grant lifecycle; объединение нарушит separation of concerns".

**Ответ:** контр-аргумент сильный для **прямого слияния таблиц**. Но не блокирует **общий supertype** + per-domain phase machines:

- HIPAA не запрещает single dispatcher-уровень. AIM kernel уже трактует пациентские данные через L_PRIVACY (`agents/orchestrator.py:73` `_PRIVACY_ACTIONS`); никакой утечки project↔patient не возникает.
- "Patient as project" — это про **operational lifecycle**, не данные. Пациентский лайфцикл реален: INTAKE → DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT → MONITORING → STABLE → CLOSED. Без него пациент — мёртвый файл, до которого никто не дотягивается до следующего визита.
- Real-world пример: `Robakidze_Nino_2026_03_14/` (см. `TODO.md:60`) — placeholder DOB, реальная DOB неизвестна, требует follow-up. Сейчас этот follow-up **никуда не записан**. Если бы пациент имел `awaiting_reply` + `expected_response_by`, он попал бы в morning_brief как overdue.

**Рекомендация:** trait-подобный `Lifecycle` interface, по которому работают `project_owner`, `patient_owner`, `experiment_owner` независимо. Шаги ниже в §3.1.

### 2.2 GAP-2 (CRIT) — Robotics gap: AIM не управляет hardware-on-loop экспериментами

**Симптом:**

- `~/Desktop/LongevityCommon/AutomatedMicroscopy/CONCEPT.md:23` — "Claude Code agent operating в `/overnight` mode serves as AI night-shift technician". **AIM не упомянут**.
- `~/Desktop/PhD/E0/CONCEPT.md` (line 1-15) — "Claude Code /overnight agent управление прецизионным инвертированным микроскопом". Опять Claude Code.
- В AIM нет ни одного крейта/модуля под hardware-control: grep `move_stage|fire_laser|capture_image|opentron|opcua|labautomation` по `~/Desktop/LongevityCommon/AIM/` находит 0 совпадений (только упоминание "Liquid handling robot" в `AutomatedMicroscopy/docs/`, которое внешнее).

**DeepSeek контр-аргумент:** "медицинские роботы требуют IEC 62304; встраивать `fire_laser` в AI-runtime — путь к катастрофе; Claude Code как изолированный оркестратор — правильный паттерн".

**Ответ:** различение между **agent layer** и **driver layer** — корректное, но ничего не говорит про то, кто **должен быть mission-control** для эксперимента. AIM хорошо подходит для роли менеджера, который:

- держит `experiment_owner.yaml` (analog `project_owner.yaml`) с phases COMMISSIONING → CALIBRATING → RUNNING → ANALYSIS → REPORT
- читает journals (NDJSON, который сейчас пишет AutomatedMicroscopy в `~/.cache/aim/microscopy/sessions/*.ndjson` — не существует, но spec в `AutomatedMicroscopy/CONCEPT.md`)
- escalation_rules: `failure_rate_per_hour > 5` → telegram_alert; `imaging_uptime < 0.95` → email_dr_jaba
- НЕ дёргает hardware напрямую — посылает task в Claude-Code-runner или внешнего worker через MCP server (G4 уже в AIM, `agents/mcp_loader.py:1`)

Sertification IEC 62304 относится к firmware, не к "runtime, который читает logs и пушит phase transitions". AIM как проектный наблюдатель + retry-coordinator = legal grey: те же права, что у lab tech читающего notebook.

**Рекомендация:** §3.2 — крейт `aim-experiment` + MCP server `~/.aim/mcp/lab-runner.toml`, разъединение agent↔driver.

### 2.3 GAP-3 (HIGH) — Нет long-running owner actor

**Симптом:**

- `agents/serve_daemon.py:1` (321 LoC, G10) описывает tick scheduler, но НЕ запущен в продакшне как ownership loop.
- В Phoenix umbrella (4 apps) ровно **один** GenServer: `apps/aim_orchestrator/lib/aim_orchestrator/hub_client.ex:18` — heartbeat node→hub каждые N секунд (auth, не project ownership).
- Единственный proactive trigger в системе = systemd timer `aim-daily-brief.timer` 09:00 → `morning_brief` рендер → Telegram chunked send.
- `morning_brief` — **pure render function**. Между двумя её вызовами (24h gap) AIM не делает ничего автономного для проекта. Если пациент пропустил визит — узнаем через 24 часа в лучшем случае.

**DeepSeek контр-аргумент:** "event-driven > polling; long-running actor для 10K пациентов = CPU без пользы; это feature для v8".

**Ответ:** контр-аргумент частично прав. Pulling всех 10K пациентов каждую минуту — глупо. Но:

- Большинство triggers **должны** быть event-driven (новый файл в `Patients/INBOX/`, новый email в Gmail, новый журнал в `microscopy/sessions/`). Эти hooks **уже определены в `agents/hooks.py`**, но **не подключены** к продьюсерам — это GAP-4.
- Polling нужен **только** для time-based триггеров: deadline countdown, awaiting_reply timeout, KPI auto-update sync. Это ~4 проверки в час на entity, не каждую минуту.
- Один long-running serve_daemon на 200 entity = ~13 проверок в секунду, вообще не нагрузка.

**Рекомендация:** §3.3 — поднять serve_daemon как systemd unit, подписать на hooks, реализовать tick для deadline-class triggers.

### 2.4 GAP-4 (HIGH) — Hooks framework определён, но не подключён к продьюсерам

**Симптом:** `TODO.md:96-104` зафиксировал по состоянию 2026-04-26:

> - [ ] Подключить `fire(HOOK_LAB_CRITICAL,..)` в `agents/labs.py` при detection critical values (K+>6.5, glucose>20,..)
> - [ ] Подключить `fire(HOOK_KERNEL_DECISION,..)` в `agents/kernel.py:log_decision` после INSERT в ai_events
> - [ ] Подключить `fire(HOOK_SESSION_END,..)` в `db.close_session`
> - [ ] Подключить `fire(HOOK_INTAKE_PDF,..)` в `agents/intake.py`

**На 2026-05-06 ни один hook не подключён.** Это значит:

- Lab K+>6.5 — обнаружится визуально врачом, но AIM **не уведомит**.
- Каждое kernel decision не логируется в hook-bus, только в DB.
- Session end не triggers cleanup или archive.
- Patient intake PDF не запускает downstream pipeline (например, auto re-scan допустимости лекарств).

**Это не "архитектурный долг", это "забыли подключить кабель"** — 5 минут работы на каждый hook (одна строчка `from agents.hooks import fire; fire(HOOK_LAB_CRITICAL,..)` после нужного места).

**Рекомендация:** §3.3 фаза 0 — wire up за один день.

### 2.5 GAP-5 (MED) — Stakeholder tracker и patient — разные таблицы, но коммуникации одинаковые

**Симптом:**

- `agents/stakeholder_tracker.py:101` — SQLite `contacts(name, email, role, project, last_contact_at, awaiting_reply, expected_response_by,..)`. Подходит для Geiger / Miguel / Janke.
- Пациентские коммуникации — нигде. Если Maia Feradze (`Patients/Feradze_Maia_1981_12_20/`) пишет в WhatsApp "повторный анализ когда?" — нет места записать `last_message_at`, `awaiting_doctor_reply`, `expected_response_by`.
- `patient_inbox_watcher.py:232` пишет `AI_LOG.md` для intake, но это per-folder лог, не cross-patient communications layer.

**DeepSeek контр-аргумент:** "GDPR/HIPAA: контакты Co-PI и пациента нельзя в одной таблице — разные политики обработки".

**Ответ:** правильно, **физически** должны быть разные tables (или хотя бы row-level scoped). Но **API + brief** одинаковые: "кто ждёт ответа", "сколько дней молчания", "expected_response_by". Достаточно создать `agents/patient_communications.py` (parallel `stakeholder_tracker.py`) + общий `Communications` interface для morning_brief.

**Рекомендация:** §3.4 — `patient_comms.py` SQLite table, тот же hook lifecycle, общий dispatch на morning_brief.

### 2.6 GAP-6 (MED) — daily_brief не покрывает пациентов

**Симптом:** `scripts/daily_brief.py` (читал indirect через `routines.py:107`) пробегает только `project_owner.list_projects` (YAML files в `USER/projects/`). Пациенты не дёргаются. `morning_brief("FCLC")` ≠ `morning_brief_patient("Feradze_Maia_1981_12_20")`.

**Рекомендация:** §3.4 — добавить функцию `patient_owner.morning_brief(patient_id)` + расширить `daily_brief.py` чтобы шёл по обоим путям.

### 2.7 GAP-7 (MED) — Project graph только soft-refs по тексту

**Симптом:** `agents/project_graph.py:67` использует regex `\b([A-Z][A-Za-z0-9_-]{1,30})\b` для поиска cross-references в blockers/goals/notes. Это даст ложные срабатывания (например, "EIC" как название → совпадёт с любым проектом начинающимся на E).

**Замечание:** в текущем виде граф работает только для grant projects. Для пациентов — нет смысла (пациенты не "зависят" друг от друга в обычной практике, кроме family contacts). Для experiments — реальный смысл (Experiment 0 → CDATA Phase A → MCOA validation).

**Рекомендация:** оставить как есть для grant projects; для experiments расширить через `depends_on: [..]` явный список (уже поддержан `_yaml_raw` reading).

### 2.8 GAP-8 (LOW) — AI subproject inward-facing, не помогает project ownership

**Симптом:** все `AI/ai/*` миннеры (`gap_detector`, `reflexion_cluster`, `pattern_miner`, `regression_detector`, `meta_evaluator`) измеряют качество AIM-self, не качество ведения проектов.

- `gap_detector.py:148` ищет AIM-surrender patterns ("I cannot help") в session JSONL — для self-improvement.
- `hive_queen.py:169` `distill_candidates` ищет cross-worker compliance drift — для prompt patches.

Что упускается: те же миннеры могли бы прогоняться по **project signals** — "ledger Geiger replied late на 7d" → tag stakeholder для re-engagement; "patient X пропустил 2 follow-up за 6 weeks" → flag для kernel.

**DeepSeek контр-аргумент:** "интровертность AI-слоя — нормальный паттерн для meta-уровня; gap_detector можно переиспользовать без переписывания".

**Ответ:** согласен. Это не CRIT, а добавочное использование уже работающих модулей. §3.5 — переиспользовать `pattern_miner` для project-level events.

### 2.9 GAP-9 (LOW) — Identity / authz между типами пользователей не определены

**Указано DeepSeek в "что упустил":** пациент, врач, Co-PI, admin — у всех разные права на чтение/запись.

**Текущее состояние:** `agents/auth.py` (хаб-сторона, JWT/opaque tokens, audit log). Различение **per-instance** (один пользователь = один node), не **per-role**.

**Рекомендация:** при unification по `Lifecycle` (§3.1) добавить `entity.allowed_actors[]` — список ролей которым позволено читать/писать/transition. Проверка в `orchestrator.py` через L_CONSENT extension.

---

## 3. План — 4 фазы

Принципы: **никакой rewrite ядра**, только склейка существующих модулей + 4–6 новых лёгких primitives. Каждая фаза проходит eval gate (S1) и не блокирует следующую.

### 3.1 Фаза A — Lifecycle abstraction (1 неделя, 200–300 LoC)

**Цель:** общий interface поверх `project_owner`, `patient_memory`, и нового `experiment_owner`. НЕ объединять storage — только API.

**Шаги:**

1. **Define `agents/lifecycle.py`** — Protocol class:
 ```python
 class Lifecycle(Protocol):
 def list_entities(self) -> list[str]:..
 def load_entity(self, id: str) -> Any:..
 def current_phase(self, id: str) -> str:..
 def legal_phases(self, src: str) -> list[str]:..
 def hot_items(self, id: str, today: date) -> list[HotItem]:..
 def overdue_items(self, id: str, today: date) -> list[HotItem]:..
 def morning_brief(self, id: str, today: date) -> str:..
 ```
2. **Wrap `project_owner` в `GrantLifecycle`** — без изменений в самом модуле, добавить адаптер.
3. **Создать `PatientLifecycle`** — реализация на patient_memory + новые поля (см. ниже).
4. **Создать `ExperimentLifecycle`** — реализация на новом `experiment_owner.yaml` (see §3.2).
5. **Расширить patient_memory** новыми опциональными секциями MEMORY.md:
 - `## Phase` (one of: INTAKE / DIAGNOSTIC_WORKUP / ACTIVE_TREATMENT / MONITORING / STABLE / CLOSED)
 - `## Milestones (medical)` — формат `{id, deadline, blockers, criticality}`, например `{id: "thyroid-recheck", deadline: 2026-08-15, criticality: medium}`
 - `## Awaiting` — list of follow-ups с `{topic, since, expected_by}`
6. **Phase machine for patients** — новый файл `agents/patient_state_machine.py` (мини-копия `project_state_machine.py:46` с другими enum):
 ```
 INTAKE → DIAGNOSTIC_WORKUP, CLOSED
 DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT, MONITORING, CLOSED
 ACTIVE_TREATMENT → MONITORING, CLOSED
 MONITORING → ACTIVE_TREATMENT, STABLE, CLOSED
 STABLE → MONITORING (relapse), CLOSED
 ```
7. **`unified_brief`** в `agents/brief_preamble.py` — итерирует все три Lifecycle.

**Тесты:** parametrized по lifecycle (~30 тестов).
**Acceptance gate:** существующий `morning_brief("FCLC")` рендерится pixel-identical (regression test); новый `morning_brief_patient("Feradze_Maia_1981_12_20")` показывает phase + hot milestones + overdue follow-ups.

### 3.2 Фаза B — Experiment owner + hardware bridge (2 недели, 600–800 LoC)

**Цель:** AIM начинает быть mission-control для AutomatedMicroscopy и PhD/E0 через MCP — без прямого hardware control.

**Шаги:**

1. **`USER/projects/E0.yaml`** + **`USER/projects/AutomatedMicroscopy.yaml`** — pilot файлы по схеме `project_owner.yaml`, но с `kind: experiment` в шапке.
2. **Расширить `project_state_machine`:** добавить experiment phases (`COMMISSIONING / CALIBRATING / RUNNING / DATA_PROCESSING / REPORTED / ARCHIVED`). Граф:
 ```
 COMMISSIONING → CALIBRATING, ARCHIVED
 CALIBRATING → COMMISSIONING (regression), RUNNING, ARCHIVED
 RUNNING → DATA_PROCESSING, CALIBRATING (recalibrate), ARCHIVED
 DATA_PROCESSING → REPORTED, RUNNING (more data), ARCHIVED
 ```
3. **`agents/journal_watcher.py`** (новый, ~150 LoC):
 - watches `~/.cache/aim/microscopy/sessions/*.ndjson` (or env-configurable path)
 - parses NDJSON entries `{ts, decision, observation, outcome}`
 - emits `fire(HOOK_EXPERIMENT_EVENT,..)`
 - rolls KPI updates: `experiment.uptime`, `experiment.decisions_per_hour`, `experiment.contamination_events`
4. **MCP server `~/.aim/mcp/lab-runner.toml`** — AIM не дёргает hardware, а отправляет structured task другому процессу:
 ```toml
 [server]
 command = "claude"
 args = ["--mcp-mode", "--project", "/home/oem/Desktop/LongevityCommon/AutomatedMicroscopy"]

 [tools]
 queue_imaging_run = "Schedule a imaging run with given ROI / channel / interval"
 request_calibration = "Mark experiment for next-window calibration"
 ```
5. **Escalation rules для experiments** в YAML:
 ```yaml
 escalation_rules:
 - when: "milestone.id == 'e0-platform-uptime' and kpi.uptime_pct < 95"
 action: telegram_alert
 - when: "milestone.id == 'contamination' and kpi.events_per_run > 0"
 action: email_dr_jaba
 ```
6. **`agents/experiment_owner.py`** — обёртка над `project_owner` с experiment-specific KPI sources:
 - `experiment.uptime` (from journal NDJSON)
 - `experiment.decisions_human_concordance` (from blind-review log, fed by post-hoc)
 - `experiment.contamination_rate`

**Тесты:** mock NDJSON file; trigger journal_watcher → verify KPI updated, hook fired.
**Acceptance gate:** `morning_brief("E0")` показывает реальный uptime % + hot milestones + любые overdue calibrations.

### 3.3 Фаза C — Long-running owner actor + hooks wiring (1 неделя, 100–150 LoC)

**Цель:** убрать единственный proactive trigger (cron 09:00) → 24/7 reactive owner.

**Шаги:**

1. **Wire up все 4 dangling hooks** (1 час работы на всё):
 - `agents/labs.py` → `fire(HOOK_LAB_CRITICAL,..)` после critical detection
 - `agents/kernel.py:log_decision` → `fire(HOOK_KERNEL_DECISION,..)`
 - `db.close_session` → `fire(HOOK_SESSION_END,..)`
 - `agents/intake.py` → `fire(HOOK_INTAKE_PDF,..)`
2. **Поднять serve_daemon** как systemd unit `deploy/systemd/aim-serve-daemon.service`:
 ```
 [Service]
 ExecStart=/home/oem/Desktop/LongevityCommon/AIM/venv/bin/python -m agents.serve_daemon --tick=60 --hook-mode
 ```
3. **Tick handlers в `serve_daemon`:**
 - каждую минуту: `escalation_engine.evaluate_all` (cooldown 24h уже есть, дешёво)
 - каждые 15 минут: `deadline_scanner.scan_all` + check для today=in7d items
 - каждый час: `kpi_auto_updater.sync` (idempotent)
 - каждый час: `journal_watcher.poll` (Фаза B integration)
4. **HOOK_LAB_CRITICAL → escalation_engine.dispatch_immediate(..)** напрямую через `notify.py` мультиплексор. NO 24-hour delay.
5. **Add `agents/lifecycle_dispatcher.py`** — на каждый tick прогоняет все Lifecycle через `hot_items` + `overdue_items`, скармливает escalation_engine.

**Тесты:** mock systemd timer, verify tick fires; HOOK_LAB_CRITICAL → telegram dispatched in <5s.
**Acceptance gate:** lab K+=6.8 detected → Telegram in <30s. EIC deadline -7d → Telegram in <1 min.

### 3.4 Фаза D — Patient communications + unified daily_brief (1 неделя, ~200 LoC)

**Цель:** patient follow-ups видны в daily_brief наравне с FCLC/E0.

**Шаги:**

1. **`agents/patient_comms.py`** — параллель `stakeholder_tracker.py`, отдельный SQLite файл `~/.cache/aim/patient_comms.db`:
 ```sql
 CREATE TABLE patient_messages(
 id INTEGER PRIMARY KEY,
 patient_id TEXT, -- folder name
 channel TEXT, -- whatsapp / sms / email / clinic
 direction TEXT, -- in / out
 body TEXT,
 ts TEXT
 )
 CREATE TABLE patient_followups(
 patient_id TEXT,
 topic TEXT,
 awaiting_reply INTEGER,
 expected_response_by TEXT,
 last_contact_at TEXT,
 PRIMARY KEY(patient_id, topic)
 )
 ```
2. **Hooks для intake:** `HOOK_INTAKE_PDF` + новый `HOOK_PATIENT_MESSAGE` обновляют `patient_followups.last_contact_at`.
3. **CLI commands:**
 - `aim patient followup add <patient_id> <topic> --due 2026-06-01`
 - `aim patient followup list --overdue`
4. **Расширить `daily_brief.py`** — после `all_briefs` пройти все patient folder + добавить `🏥 patients` секцию: overdue follow-ups + upcoming scheduled visits + patients without contact > 6 mo.
5. **Privacy enforcement:** L_PRIVACY уже работает на egress; добавить redaction patient_id в Telegram (показать только `Surname_F.` initials), full data — только в TUI.

**Тесты:** добавить и mark overdue follow-up, verify shown in daily_brief.
**Acceptance gate:** для каждого пациента из `Patients/` (6 штук в pilot) — рендер строки "last contact / overdue / next visit due".

### 3.5 Фаза E — AI-subproject reuse for project signals (1 неделя, ~150 LoC)

**Цель:** репозиционировать `pattern_miner` / `gap_detector` на project events, не только AIM-self.

**Шаги:**

1. **Расширить `pattern_miner.py`:** добавить миннер `stakeholder_silence_pattern` — анализирует contacts.last_contact_at + ledger; если N stakeholders молчат >14d при awaiting_reply=1, вызывает `notify` ("3 awaiting Co-PI replies overdue").
2. **Расширить `gap_detector.py`:** второй mode `project_gaps` — пациенты без visits >6 mo, milestones blocked >30d, KPI velocity = 0 за 4 weeks → cluster + suggestion.
3. **Hive queen distill:** добавить `patient_followup_drift` candidate kind — если N workers (multi-clinic deployment) показывают drift в follow-up rate → emit prompt patch / process improvement.
4. **Weekly project digest** (новый `scripts/weekly_project_digest.py`) — параллель `weekly_digest.py` (который про AIM self): Telegram message каждое воскресенье с per-project velocity + per-patient follow-up status + experiment uptime trend.

**Acceptance gate:** через 2 недели после deploy — first weekly digest содержит реальные insights (не "0 changes").

### 3.6 Фаза F (опциональная) — Identity / authz (2 недели)

**Цель:** разные роли видят разное.

**Шаги:**

1. `entity.allowed_actors[]` поле в YAML/MD, со списком роли (admin / doctor / coPI / patient_self / observer)
2. Расширить `kernel.evaluate_l_consent` чтобы блокировать transition если actor не в `allowed_actors`
3. Per-role brief в `morning_brief` — фильтрует hot/overdue по правам видимости
4. Phoenix LiveView `aim_web` — добавить per-user dashboards с фильтрацией

**Когда:** только когда появится 2-й пользователь (сейчас single-user). Откладываем.

---

## 4. Anti-recommendations — что НЕ делать

DeepSeek в своей критике справедливо указал на over-engineering tendencies. Эти соблазны я отвергаю:

### 4.1 ❌ НЕ объединять `ProjectState` и `PatientMemory` в одну таблицу

Storage остаётся раздельным. Только API через `Lifecycle` interface.
Реальная причина: HIPAA compliance + audit trail должны быть разными.

### 4.2 ❌ НЕ создавать `ParameterizedStateMachine` с if/else по типу

Три отдельных state machine файла (`project_state_machine.py`, `patient_state_machine.py`, `experiment_state_machine.py`) понятнее, чем `Universal.transition(kind, src, dst)`.

### 4.3 ❌ НЕ интегрировать hardware drivers напрямую в AIM

Никаких `move_stage` / `fire_laser` в Rust crate AIM. AIM посылает структурированные tasks **через MCP** Claude Code (или другому worker). Hardware control остаётся в **отдельном process** с right sandbox/cert.

### 4.4 ❌ НЕ пушить S6 (code self-modify) до накопления 28 ledger runs

`AI/ai/self_modify.py:62` уже имеет правильный gate. Не открывать раньше: иначе AIM "улучшит" себя в худшую сторону без baseline для регрессии.

### 4.5 ❌ НЕ строить hive queen → workers update distribution до 2-х реальных workers

`HIVE_ARCHITECTURE.md:131` Phase 1+2 готовы (worker telemetry + queen aggregator). Phase 3 (distribution) откладывается до 2-х physical nodes.

---

## 5. Список конкретных файлов / строк к правке

### 5.1 Wire up dangling hooks (Фаза C, день 1)

| Файл:строка | Изменение |
|---|---|
| `agents/labs.py` (после detection) | `from agents.hooks import fire, HOOK_LAB_CRITICAL; fire(HOOK_LAB_CRITICAL, patient=p, lab=k, value=v)` |
| `agents/kernel.py` (after `_log_event`) | `fire(HOOK_KERNEL_DECISION, decision=d, scoring=s)` |
| `db.py:close_session` | `fire(HOOK_SESSION_END, sid=sid)` |
| `agents/intake.py` (after PDF processed) | `fire(HOOK_INTAKE_PDF, patient_dir=pd, file=f)` |
| `agents/patient_inbox_watcher.py:227` (после shutil.move) | `fire(HOOK_PATIENT_FILE_MOVED, patient_dir=target_folder)` |

### 5.2 Дефекты из ROADMAP/AUDIT, всё ещё не закрытые

| ID | Файл | Что | Severity |
|---|---|---|---|
| A1 (Rust) | `rust-core/crates/aim-generalist/src/tools/bash_tool.rs` | bash sandbox: убрать `python -c`, `find -delete`, `cargo run` из whitelist | 🔴 CRIT (blocks prod) |
| A2 (Rust) | `rust-core/crates/aim-generalist/src/tools/fs_tools.rs` | path sandbox: AIM_GENERALIST_ROOT prefix-check + extension whitelist | 🔴 CRIT |
| B1 | `rust-core/crates/aim-llm/src/router.rs` | model_hint → правильный provider routing (сейчас first-ready) | 🟡 |
| C2 | `deploy/systemd/*.service` | systemd units для всех Rust binaries (`aim-llm`, `aim-rag`, `aim-medkb`, `aim-doctor`, `aim-generalist`) | 🟡 |
| C4 | `rust-core/../tests/` | 0 unit tests в Rust crates (Python tests есть) | 🟡 |
| Patient parser fragility | `patient_memory.py:206-296` | regex-парсер `read_memory` ломается на любой нестандартной структуре MD (e.g. дополнительные subsections); пора заменить на `markdown-it` AST или явный YAML front-matter | 🟡 |
| Stakeholder/YAML sync | `stakeholder_tracker.py:295` `sync_from_yaml` | не делает обратный sync (DB → YAML) — данные из email_agent на_email_received не отражаются в YAML notes | 🟡 |
| daily_brief patient blind | `scripts/daily_brief.py` | не пробегает `Patients/` (Фаза D) | 🟡 |
| escalation_engine action types | `escalation_engine.py:407` | реализован только `telegram_dispatch`; нужен `email_dispatch`, `calendar_event_create`, `task_create` | 🟡 |
| project_owner.morning_brief patient mention | `project_owner.py:241` | hardcoded "📌 {state.name}" — для пациента нужно "🏥.."; нужна type-aware рендер | 🟡 |

### 5.3 Сильные стороны, которые надо сохранить

| Где | Что | Не трогать |
|---|---|---|
| `agents/orchestrator.py:225` | Ze-verify file:line refs auto-check | работает; покрывает hallucinated paths |
| `agents/orchestrator.py:445` | AST-verify для symbol-at-line | ловит то, что regex не ловит |
| `agents/permission.py` | TUI/Telegram broker с TTL cache | production-quality |
| `agents/escalation_engine.py:80` | tiny DSL `_eval_rpn` без `eval` | safe from injection |
| `agents/citation_guard.py` | PMID/DOI verify через PubMed/Crossref | реально предотвращает фабрикованные citations |
| `agents/regimen_validator.py` | hard refusal на contraindicated/major pairs | clinical safety |
| `AI/ai/self_modify.py:62` | gate закрыт до 28 runs | НЕ открывать раньше |
| `agents/kernel.py:104` | Asimov L0-L3 + L_PRIVACY/CONSENT/VERIFIABILITY | foundation |

---

## 6. Приоритетный порядок работ

```
Неделя 1: Фаза C (hooks wiring + serve_daemon как systemd) — quick win
Неделя 1-2: Фаза A (Lifecycle abstraction + patient state machine)
Неделя 3-4: Фаза B (experiment_owner + journal_watcher + MCP lab-runner)
Неделя 5: Фаза D (patient_comms + unified daily_brief)
Неделя 6: Фаза E (pattern_miner reuse for project signals)
Параллельно: закрыть Rust A1+A2+B1+C2 (security + supervision)
Откладываем: Фаза F (identity/authz) — до 2-го пользователя
 S6 self-modify — до 28+ ledger runs
 Hive distribution — до 2-х physical workers
```

Total effort: **~8 недель** для одного разработчика. Меньше если фазы B/D/E идут в параллель.

---

## 7. Метрики успеха

После всех фаз AIM должен:

1. **Patient as project visible:** для каждого из 6 пациентов в `Patients/` daily_brief показывает phase + hot milestones + last contact + overdue follow-ups. (Сейчас: 0 пациентов в brief.)
2. **Real-time lab escalation:** lab K+>6.5 → Telegram alert <30s. (Сейчас: до 24h delay if seen at all.)
3. **Experiment owner active:** `morning_brief("E0")` показывает реальный uptime % из journal NDJSON, hot milestones, calibration overdue. (Сейчас: experiment живёт в Claude Code, AIM не знает о нём.)
4. **5+ projects tracked:** FCLC, E0, AutomatedMicroscopy, plus ≥2 patients with non-trivial phase transitions logged in `~/.cache/aim/phase_history.jsonl`. (Сейчас: только FCLC.)
5. **No regression in security:** Rust A1+A2 закрыты (production-deployable), Python тесты остаются 553+ passing.
6. **Self-improvement metrics OK:** `AI/ai/dashboard.py` health_score ≥80, gap_detector cluster count <5, hive_queen contributions accumulating.

---

## 8. Что было реальным открытием в аудите

- **PHASES_1-5_DONE** показывает что AIM уже сделал **57 новых модулей** между 2026-05-02 и 2026-05-03 за overnight session — это очень мощная итеративная working capacity. Большая часть нужного для project ownership уже **существует** как primitive, нужно только склеить.
- **Hive queen + worker telemetry** (`HIVE_ARCHITECTURE.md`) — это правильный путь к multi-clinic deployment, но Phase 3 (distribution) откладывается до 2 реальных workers — мудрое решение.
- **Rust port — не альтернатива Python, а параллельный mirror.** В Python 30K LoC, в Rust ~200 крейтов. Logic identical. Это плюс (testability + future migration), но текущий **operational stack** = Python. AI subproject — Python only. Никакой prod-нагрузки в Rust пока нет (smoke-test-only per AUDIT_2026-05-02).
- **Asimov kernel + Ze-verify + AST-verify в orchestrator** — это **уникальное** safety property AIM, которого нет ни у Claude Code, ни у других agent runtime. Gold standard для медицинского применения. Не трогать.
- **DeepSeek контр-аргументы** показали, что соблазн "all-in-one ManagedEntity" — over-engineering. Правильный путь: **interface-level unification, storage-level separation.** Этого подхода придерживается план выше.

---

## 9. Открытые вопросы для пользователя (требуют решения)

1. **Patient phase machine vocabulary:** предложен INTAKE → DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT → MONITORING → STABLE → CLOSED. Согласен с этими названиями или нужны другие? (Например, в integrative medicine может быть `LIFESTYLE_INTERVENTION` фаза до `ACTIVE_TREATMENT`.)
2. **Experiment phase machine:** предложен COMMISSIONING → CALIBRATING → RUNNING → DATA_PROCESSING → REPORTED. Подходит ли для AutomatedMicroscopy / E0?
3. **Кто должен быть owner процесса (Фаза C systemd unit):** сам пользователь как root, или dedicated `aim` system user? Влияет на путь к `~/.aim_env` / `Patients/`.
4. **MCP server для lab-runner (Фаза B):** какой именно external runner — Claude Code в headless mode, отдельный Rust binary, или Python script? Сейчас AutomatedMicroscopy использует Claude Code — продолжить или мигрировать?
5. **Hive queen — single instance:** есть ли смысл поднимать queen на server (longevity.ge) или достаточно local development setup?

---

**Конец отчёта.** Готов к обсуждению / правкам / запуску любой из фаз.
