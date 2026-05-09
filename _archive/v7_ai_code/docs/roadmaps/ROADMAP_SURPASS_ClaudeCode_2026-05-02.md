# Roadmap: AIM > Claude Code + project-driving + self-improving

**Дата:** 2026-05-02
**Цель:** AIM должен (1) превзойти Claude Code по возможностям, (2) уметь **вести проекты** долгосрочно как owner, (3) **саморазвиваться** — улучшать свой код, prompt'ы, инструменты на основе опыта.

---

## Текущее состояние — что уже есть в AIM

После сканирования `~/Desktop/LongevityCommon/AIM/agents/` (66 файлов, 17.6K LoC) AIM уже имеет почти все building blocks:

### Self-improvement primitives (уже готово ✅)

| Компонент | Файл | Что делает |
|---|---|---|
| **Reflexion** | `agents/reflexion.py` | Verbal reflection после фейла → injection в next-run hint. Shinn et al. 2023, +10-15% на ReAct. |
| **Tree-of-Thoughts** | `agents/tree_planner.py` | branching candidate approaches → DS-reasoner judge → top-2 expansion |
| **Evolutionary prompt optimizer** | `agents/prompt_optimizer.py` | LLM-mediated mutation, K candidates × N generations |
| **Self-health diagnostic** | `agents/self_health.py` | Probes every runtime component → /healthz/full |
| **PI agent** | `agents/pi_agent.py` | Learns frequency/time patterns, proactive suggestions, auto-mode nightly memory reorg |
| **Complexity classifier** | `agents/complexity_classifier.py` | Routes simple/complex tasks differently |
| **Smart routing/fallback/context** | `agents/smart_*.py` | Adaptive model selection |
| **Cost monitor** | `agents/cost_monitor.py` | Tracks spend per provider |
| **AB router** | `agents/router_ab_test.py` | A/B testing routing decisions |

### Project-driving primitives (уже готово ✅)

| Компонент | Файл | Что делает |
|---|---|---|
| **Orchestrator** | `agents/orchestrator.py` | L0→L3 + L_PRIVACY + L_CONSENT + L_VERIFIABILITY + Ze-verify post-check |
| **Session manager** | `agents/session_manager.py` | resume + auto-update STATE.md если summary упоминает проект |
| **Cross-project memory** | `agents/memory_index.py` | DESKTOP_PROJECT_GLOB → индексирует CONCEPT/STATE/THEORY всех проектов |
| **Patient memory** | `agents/patient_memory.py` | canonical state per-patient |
| **Job queue** | `agents/job_queue.py` | background tasks |
| **Hooks** | `agents/hooks.py` | event-driven actions |

### Capabilities превосходящие Claude Code (уже сейчас ✅)

1. ✅ Multi-model ensemble (3-model + adjudicator) — у CC нет
2. ✅ Tier-chain с fallback (5 tiers) — у CC одна модель
3. ✅ Semantic vector memory (LanceDB) — у CC только grep markdown
4. ✅ Reflexion + ToT + prompt evo — у CC нет
5. ✅ OCR + Vision pipeline — у CC только через MCP
6. ✅ PubMed/Crossref verification — у CC нет
7. ✅ Multi-user hub/node — у CC single-user
8. ✅ 9 языков с domain-specific переводом (medical/scientific/patient/general) — у CC нет

**Вывод: AIM уже имеет фундамент. Не хватает не модулей, а интеграции и closed-loop саморазвития.**

---

## Чего не хватает чтобы превзойти Claude Code (must-fix gaps)

### G1. ✅ ЗАКРЫТО 2026-05-02 — Bash sandbox

**Что сделано:**
- `_validate_bash` хелпер в `agents/generalist.py` (общий gate для sync+async).
- Per-command `_BASH_FORBIDDEN_FLAGS` policy: `python -c/-m/-i`, `find -delete/-exec*/-fprint*/-ok*`, `git config/remote/clone/fetch/pull/push`, `pip install/uninstall/wheel/download`, `pytest -p`, `npm/yarn/cargo/go/mvn/gradle install|publish|run`.
- `_BASH_DANGEROUS_TOKENS` расширен: shells (bash/sh/zsh/fish/ksh/csh/tcsh/dash), eval/exec/source, xargs/tee/truncate/shred, ex/vim/nvim/emacs.
- `_t_bash_async` теперь использует тот же `_validate_bash`, не имеет `shell=True`, и валидирует cwd.
- `_maybe_sandbox` возвращает прямой argv (не `/bin/sh -c`) — Popen запускает бинарь без shell parsing.
- Rust `crates/aim-generalist/src/tools/bash_tool.rs`: `BLOCKED_FLAG_PREFIXES` теперь prefix-match (`--exec-path=`, `--config-env=`), `git remote` убран из allow-list.
- Тесты: `tests/test_bash_sandbox.py` (51), `rust-core/.../tests/bash_tool_tests.rs` (11), регрессия `test_law_gates` обновлена.

### G2. ✅ ЗАКРЫТО 2026-05-02 — Path sandbox

**Что сделано (Python):**
- `_gate_path(path, *, write)` в `agents/generalist.py`.
- Secret-path deny-list: `~/.ssh/`, `~/.aim_env`, `~/.aws/`, `~/.kube/`, `~/.gnupg/`, `~/.netrc`, `~/.config/sops/`, `/etc/shadow`, `/etc/sudoers*`, `/etc/gshadow`, `~/.bash_history`, `~/.zsh_history`, `~/.npmrc`, `~/.pypirc`, `~/.docker/config.json` — блок и на read, и на write.
- Write-side: `AIM_GENERALIST_ROOT` env (default `~/Desktop`), canonicalize + prefix-check.
- Wired in: `read_file`, `view_file`, `write_file`, `edit_file`, `apply_patch` (последний парсит `+++ b/<path>` и валидирует каждый target).
- Override: `AIM_NO_PATH_SANDBOX=1`.
- `tests/conftest.py` расширен: `_allow_tmp_writes_for_tests` autouse session fixture, чтобы pytest tmp_path в /tmp работал.
- Тесты: `tests/test_path_sandbox.py` (31).

**Что сделано (Rust):** `crates/aim-generalist/src/tools/sandbox.rs::validate` уже был — root canonicalize, traversal block, symlink escape via partial-canonicalize, extension whitelist (md/txt/json/csv/yml/yaml/py/rs/ex/exs/heex/toml/html/log). Используется в `fs_tools.rs` ReadFile/WriteFile. Тесты `sandbox_tests.rs` (4) + `tool_logic_tests.rs` (5) — все зелёные.

### G3. ✅ ЗАКРЫТО 2026-05-02 — Interactive permission broker

**Что сделано:**
- `agents/permission.py` — broker с `request(action_type, scope, preview, blast_radius, ttl_minutes=15)`.
- Channels: TUI (stdin с timeout 60s), Telegram (`AIM_PERMISSION_CHANNEL=tg` через `agents.telegram_extras.permission_broker`).
- Cache: dict с TTL, gdrant и always-deny кешируются, обычные deny — нет (re-prompt чтобы исправить ошибку).
- Audit log: `~/.cache/aim/permission_log.jsonl` — каждый decision записан с action_type/scope/via/reason/granted/timestamp.
- Env overrides: `AIM_AUTO_CONSENT=1` (CI/cron), `AIM_NONINTERACTIVE=1` (deny-all).
- Kernel integration: `evaluate_l_consent` теперь при `AIM_INTERACTIVE_CONSENT=1` и отсутствии `user_confirmed` запрашивает broker, иначе сохраняет старое поведение (block).
- TUI prompt parsing: a (allow once), A (always-allow 15m), d (deny once), D (always-deny 15m), invalid → deny.
- Тесты: `tests/test_permission_broker.py` (20).

### G4. 🟡 MCP-style extensibility

**Проблема:** все 33 tool'а hard-coded в `generalist.py`. Добавление нового tool'а = code change.
**CC лучше:** MCP servers подключаются через config; user добавляет новый tool без правки harness.
**Fix:** `~/.aim/mcp/*.toml` — runtime tool registry; load JSON-schema, spawn subprocess for each MCP server, tunnel calls.
**Effort:** 1-2 дня.

### G5. 🟡 Native streaming в Rust-стэке

**Проблема:** Python streaming работает; новый Rust `aim-generalist` SSE не имеет.
**Fix:** `axum::response::sse::Sse` + tokio channels.
**Effort:** 1 день.

---

## Чего не хватает для project-driving (превзойти CC)

CC реактивен (отвечает на запрос). AIM должен **владеть** проектом неделями.

### P1. 🆕 Project Owner Agent

**Что:** долгоживущий agent на проект. Знает goals/milestones/deadlines, мониторит state, сам инициирует actions.

**Что должен уметь:**
- Читать `~/Desktop/<project>/CONCEPT.md + STATE.md + TODO.md + NEEDTOWRITE.md` → строить Internal Model.
- Каждое утро: "что висит, что блокирует, что критично сегодня?"
- Каждый вечер: "что сделано, обновить STATE.md, добавить в NEEDTOWRITE если что-то всплыло".
- При обнаружении nearing deadline (FCLC peer review, EIC submission) → escalate.
- Знает stakeholders (FCLC: Geiger/Janke/Miguel/Tsomaia) и tracks их статус.

**Реализация:**
```
~/Desktop/LongevityCommon/AIM/agents/project_owner.py
~/Desktop/LongevityCommon/AIM/USER/projects/<project_name>.yaml
 goals: [...]
 milestones: [{id, deadline, status, blockers}]
 stakeholders: [{name, role, last_contact, awaiting}]
 daily_checks: [...]
 escalation_rules: [...]
```

**Triggers:** cron каждое утро 9:00 → `project_owner.morning_brief` → Telegram message.
**Effort:** 3-5 дней (полная реализация).

### P2. 🆕 Calendar-aware planner

**Что:** AIM знает текущую дату (today=2026-05-02), читает Gmail/Calendar, видит deadlines в memory (FCLC peer review, EIC Oct 28).

**Реализация:**
- Hook на `mcp__claude_ai_Google_Calendar__list_events` — pull events на горизонт 30 дней.
- Project memory `project_*.md` с строками типа `**Deadline:** 2026-10-28 17:00 CET` → парсить.
- Каждое утро: "deadlines in 7 days: ...".
- При создании task без deadline — спросить.

**Effort:** 2-3 дня.

### P3. 🆕 Stakeholder tracker

**Что:** для каждого внешнего человека — last_contact, awaiting_reply_since, follow_up_after_days.

**Реализация:**
- DB table `contacts(name, email, role, last_contact_at, awaiting_reply, expected_response_date)`.
- Hook на `email_agent.send` → update last_contact_at.
- Hook на `email_agent.check_inbox` → mark awaiting_reply=False if reply detected.
- Cron: "Janke не ответил за 5 дней — напомнить?"

**Effort:** 2 дня.

### P4. 🆕 Daily stand-up & weekly review

**Что:** автоматический Telegram message каждое утро с топ-5 приоритетов на день, каждое воскресенье — weekly review.

**Memory `feedback_daily_strategic_check.md` уже это требует**, но не имплементировано.

**Effort:** 1 день.

### P5. 🆕 Project state machine

**Что:** проекты имеют формальные phases (DRAFT → REVIEW → SUBMITTED → ACCEPTED → PUBLISHED). AIM знает где сейчас и какие actions нужны для transition.

**Effort:** 2 дня.

---

## Чего не хватает для самообучения (closed-loop)

### S1. 🆕 Eval harness — измеряем улучшается ли AIM

**Проблема:** Reflexion/prompt-evo есть, но нет benchmark чтобы измерить эффект.

**Что нужно:**
- `tests/evals/` — 50-100 typical AIM tasks (медицинская диагностика, написание грантов, перевод, peer review).
- Каждую неделю: запустить evals, сохранить score → SQLite `eval_runs(date, version, task_id, score, latency_ms, cost_usd)`.
- Регрессия detected → blocker для self-modification commit.

**Effort:** 1 неделя для базового набора.

### S2. 🆕 Tool synthesis — AIM создаёт новые tools

**Проблема:** все tools hard-coded.

**Что нужно:**
- При повторяющемся pattern (n повторов одной последовательности bash + parse) → AIM генерирует `tool_<name>.py`, тестирует на 5 случаях, регистрирует в registry.
- Пример: "I keep doing `find ~/Desktop/<project> -name '*.md' | xargs grep PMID | sort | uniq`" → synthesise `count_pmids_in_project(project)` tool.

**Реализация:**
- `agents/tool_synthesis.py` — LLM generates Python function, runs against fixture, validates, adds to `~/.aim/tools/synthesised/*.py`, hot-reload registry.
- Gate через L_VERIFIABILITY (test must pass).

**Effort:** 1-2 недели.

### S3. 🆕 Self-modification of prompts (closed loop)

**Проблема:** prompt_optimizer.py есть, но требует ручного запуска и evaluator.

**Что нужно:**
- После each session: `reflexion.on_failure` already saves verbal reflection.
- Каждые 100 sessions: aggregate reflections → identify recurring failure patterns → generate prompt patch via prompt_optimizer.
- Run patch через eval harness (S1) → if Δscore > 0 with p<0.05, commit prompt change to `~/.aim/prompts/v<n>.md`.
- Versioned, rollback-able.

**Effort:** 1 неделя (зависит от S1 + reflexion).

### S4. 🆕 Pattern mining из session logs

**Проблема:** JSONL логи (`~/.cache/aim/sessions/*.jsonl`) хранятся, но не анализируются.

**Что нужно:**
- `agents/pattern_miner.py` — еженедельно сканирует logs.
- Detects: "tool X fails 30% of time when called after tool Y" → suggest fix.
- Detects: "user repeatedly asks for same info from memory" → cache it.
- Detects: "model A is 3× slower for task class B than model C" → update routing.

**Effort:** 1 неделя.

### S5. 🆕 A/B routing с persisted decisions

**Что есть:** `router_ab_test.py` (A/B framework).
**Чего не хватает:** автоматический cycle:
- Pick 2 routing strategies → run for week → compare on cost+score → keep winner → start new A/B.

**Effort:** 3-4 дня.

### S6. 🆕 Code self-modification (advanced)

**Что:** AIM может предложить улучшение к собственному коду, тестирует, открывает PR.

**Реализация:**
- `coder_agent` уже есть (Aider wrap).
- Add cron: "scan AIM repo for TODOs, FIXMEs, audit findings → pick one, create branch, attempt fix, run tests, if green → push to `aim-self-improve` branch для review."
- L_CONSENT блокирует merge без user_confirmed=True.

**Effort:** 1 неделя (после S1+S5).

### S7. 🆕 Skill synthesis (named macros)

**Что:** комбинация basic tools под одним именем.
- "publish_paper" = md→docx + cover_letter + email_to_journal + update_NEEDTOWRITE + log
- AIM учится этим pattern'ам из session logs (S4) и регистрирует как named skills.

**Effort:** 1 неделя.

---

## Roadmap по фазам

### Фаза 1: Security parity с CC ✅ ЗАКРЫТА 2026-05-02
- ✅ G1 bash sandbox (Python + Rust)
- ✅ G2 path sandbox (Python `_gate_path`; Rust `sandbox::validate` уже был)
- ✅ G3 permission broker TUI/TG + cache + audit
- 102 новых теста (51 bash + 31 path + 20 permission); регрессия чистая.
- Production deploy unblocked.

### Фаза 2: Project ownership ✅ ЗАКРЫТА 2026-05-03
- ✅ P1 `agents/project_owner.py` + `USER/projects/<name>.yaml` + FCLC pilot config
- ✅ P2 `agents/deadline_scanner.py` (YAML + memory + Calendar adapter)
- ✅ P3 `agents/stakeholder_tracker.py` (SQLite contacts + email hooks + sync_from_yaml)
- ✅ P4 `scripts/daily_brief.py` + systemd `aim-daily-brief.{service,timer}`
- ✅ P5 `agents/project_state_machine.py` (DRAFT→…→ARCHIVED + JSONL audit)
- 81 тест добавлен.

### Фаза 3: Eval foundation ✅ ЗАКРЫТА 2026-05-03
- ✅ S1 `agents/evals.py` + 5 starter cases + 8 rubrics (regex/contains_all/json_keys/forbids/…) + SQLite eval_runs.
- 19 тестов.

### Фаза 4: Self-improvement closed loop ✅ ЗАКРЫТА 2026-05-03 (S6 пропущен — see Risk note)
- ✅ S4 `agents/pattern_miner.py` (5 миннеров: tool_failure_rate, slow_tool, redundant_memory, sequential_pair, error_freq)
- ✅ S5 `agents/ab_router.py` (Welch t-test + cost guard + decision audit)
- ✅ S3 `agents/prompt_evolver.py` (reflexion → mutate → eval → promote/reject + reverts)
- ✅ S2 `agents/tool_synthesis.py` (template-only generation + fixture run + register)
- ⏭ S6 Code self-modification — отложен до накопления реальных eval baseline (per Risk note).
- ✅ S7 `agents/skill_synthesis.py` (N-gram mining + named YAML macros + invoke)
- 70 тестов.

### Фаза 5: Surpass CC features ✅ G4+G6 ЗАКРЫТЫ 2026-05-03
- ✅ G4 `agents/mcp_loader.py` (TOML config + JSON-RPC subprocess + e2e real-subprocess test)
- ✅ G6 delegate_parallel — оказался уже полноценным (не stub); regression test добавлен
- 🔄 G5 Rust-stack streaming — отложен (не блокирующий, Python streaming работает).

**Total:** ~12-16 недель полной работы для законченного «AIM > CC + project-driving + self-improving».

---

## Что брать из Claude Code как референс

| CC capability | Что взять | Применить как |
|---|---|---|
| **Permission prompts** | Interactive Allow/Deny с preview | G3 |
| **MCP servers** | TOML config + subprocess + JSON-RPC | G4 |
| **Skill files** (`.skill/*.md`) | Named macros с triggers | S7 |
| **Hooks** (UserPromptSubmit, PreToolUse, PostToolUse) | Event-driven extensions | Уже есть `agents/hooks.py`, расширить triggers |
| **Background tasks** (run_in_background) | Job queue с notification | Уже есть `agents/job_queue.py`, добавить notification |
| **Worktree isolation** | Git worktree per task для safe experimentation | S6 (self-modification без боязни поломать main) |

---

## Концептуальная разница AIM ←→ CC

| Дименсия | Claude Code | AIM (target) |
|---|---|---|
| **Mode** | reactive (отвечает на user) | proactive (owns projects, инициирует) |
| **Memory** | session + markdown | session + vector + project state machines + reflexions |
| **Improvement** | static (новая версия = новый Anthropic release) | continuous (eval-driven self-modification) |
| **Tool set** | fixed + MCP runtime extension | dynamic (tool synthesis из patterns) |
| **Lifespan** | per-session | per-project (weeks) + per-day (cron briefings) |
| **Domain knowledge** | generic | medical + research + grants + multilingual |
| **Failure mode** | logs + ask user next session | reflexion + auto-patch prompt + eval regression |

---

## Где AIM уже сейчас сильнее CC (документально)

См. `AUDIT_AIM_vs_ClaudeCode_2026-05-02.md` — 5 advantages: tier-chain, semantic memory, domain agents, Asimov kernel, multi-user.

---

## Рекомендуемый порядок прямо сейчас

1. **На этой неделе:** G1 + G2 (security) — 5 часов работы, разблокирует production.
2. **Эта неделя:** P4 Daily stand-up — 1 день, сразу даёт ощутимое value.
3. **Следующие 2 недели:** P1 Project Owner Agent на одном проекте (FCLC) — pilot.
4. **Через месяц:** S1 Eval harness — без него все остальные self-improvement модули остаются blind.
5. **Дальше:** строить S3/S4/S5 на eval-fundament'е.

---

## Один важный риск

**Не строить S6 (code self-modification) до того как S1 (evals) закроют 50+ tasks с baseline.** Иначе AIM может «улучшить» себя в худшую сторону и регрессии будут необнаружимы. Eval harness это foundation для всего closed-loop saberobyhachivania.
