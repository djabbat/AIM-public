# Аудит AIM v7.0 vs Claude Code — глубокое сравнение

**Дата:** 2026-05-02
**Метод:** read-only сканирование `~/Desktop/LongevityCommon/AIM/` (17.6K Python LoC, 66 файлов в `agents/`, 5 Rust crates) + сопоставление с возможностями Claude Code (CLI-агент Anthropic c tool-use harness).

---

## Резюме одной строкой

**AIM = амбициозный medical-grade framework с production-уровнем архитектурой (tier-chain + ensemble + Asimov-kernel + multi-user hub/node) и critical security bugs (bash sandbox обходится, path-sandbox отсутствует). Claude Code = более скромный, но robust generic CLI-agent с MCP-расширяемостью.**

---

## Топ-5 ПРЕИМУЩЕСТВ AIM над Claude Code

1. **LLM tier-chain + 3-model ensemble adjudication** (`llm.py`, `agents/ensemble.py`)
 `ask_critical` → Claude Opus → Gemini 2.5 Pro → DS-V4-pro → Ollama r1 + Jaccard-consensus 0.35 threshold.
 CC использует одну модель.

2. **Semantic memory с LanceDB + cross-project indexing** (`agents/memory_index.py`)
 Vector DB с sentence-transformers (384-dim, all-MiniLM-L6-v2), индексирует CONCEPT/STATE/THEORY из всех `~/Desktop/<project>/`.
 CC = grep по markdown файлам.

3. **Domain-specific agents** — doctor, intake (OCR), lang (9 языков), writer (md→docx), researcher (zero-hallucination DOI), coder (Aider wrap), email (Gmail с L_CONSENT gate).
 CC = generic skills + MCP.

4. **Asimov decision kernel** (`agents/kernel.py`, 41K LoC) — L0-L3 + L_PRIVACY + L_CONSENT + L_VERIFIABILITY как код-уровневые gates перед side-effects.
 CC = неявные permission prompts.

5. **Multi-user hub/node архитектура** (`agents/auth.py`, `agents/hub_client.py`) — JWT + opaque API tokens + Telegram /link + 7-дневный offline grace + audit trail.
 CC = single-user CLI.

---

## Топ-5 ПРОБЕЛОВ AIM относительно Claude Code

1. **🔴 Bash sandbox обходится (A1 CRIT)** — whitelist проверяет `head=python`, но `python -c "os.system('rm -rf /')"` проходит. `find / -delete`, `cargo run --bin evil` тоже. CC делает full shell parsing + permission hooks.
 *Fix: 2-3ч, agents/generalist.py:_gate_bash + filter_args.*

2. **🔴 Path-sandbox отсутствует (A2 CRIT)** — `read_file`/`write_file` принимают любой абсолютный путь → утечка `~/.aim_env`, `/etc/passwd`; перезапись `~/.ssh/authorized_keys`. CC всё через permission prompts на каждый Read/Write вне рабочей папки.
 *Fix: 1-2ч, AIM_GENERALIST_ROOT env + canonicalize prefix-check + whitelist расширений.*

3. **🟡 Tier-chain не реализован в Rust-стэке (B1+B2 CRIT)** — CLAUDE.md обещает `ask_critical/ask_deep/ask_long`; новый Rust `aim-llm` игнорирует `model_hint`, fallback-chain нет.
 *Fix: 4-5ч, crates/aim-llm/src/router.rs.*

4. **🟡 Sub-agent fan-out (`delegate_parallel`) — стаб** — заявлен, но синтез через ask_critical не реализован полноценно. CC композирует через `/loop` + Task tool.

5. **🟡 Citation verification есть в коде, но не используется на практике** — `verify_pmid/doi`, `L_VERIFIABILITY` написаны, но `lab_reference.py` (59 аналитов) идёт без PMID. Audit 2026-04-21 это уже отметил, не починили. CC вообще не проверяет цитаты.

---

## Топ-3 over-engineered компонента — выпилить

1. **Cross-project memory indexing** (`AIM_INDEX_DESKTOP_PROJECTS=1` default) — индексирует FCLC + Ze + CDATA + 25 других проектов; I/O-blocks при reindex. **Рекомендация:** off-by-default, on-demand. *–50 LoC.*

2. **Jaccard k-shingle similarity** в `ensemble.py:30-50` — переусложнён; токен-overlap или embedding cosine дают тот же эффект x10 быстрее. *–100 LoC.*

3. **Adaptive rate limiter** (`agents/adaptive_limiter.py`) — почти всегда off (`AIM_RATE_ADAPTIVE` опционально); базовый TokenBucket работает. *–150 LoC.*

---

## Топ-3 missing critical features — добавить срочно

1. **Bash sandbox**: canonicalize + flag-filter (`-c`, `-e`, `--delete`, shell metachars `;|&`).
 Priority: Ø1 security. Effort: 2-3ч.

2. **Tier-chain в Rust aim-llm**: routing table + retry loop + provider fallback.
 Priority: Ø2 correctness. Effort: 4-5ч.

3. **Path sandbox** для read_file/write_file: `AIM_GENERALIST_ROOT` (default Patients/) + extension whitelist.
 Priority: Ø1 security. Effort: 1-2ч.

---

## Полные таблицы сравнения

### 1. Agent loop & tool-use

| Feature | AIM | Claude Code | Кто сильнее |
|---|---|---|---|
| ReAct loop | `generalist.py:200-350`, max_iters default 12 | Harness orchestrator, token-budget driven | AIM (контроль) |
| Tool call format | `{"tool":"name","args":{...}}` | `Tool` dataclass + register_tool | паритет |
| Tool results persistence | D1: messages table, full restore | transcripts/, не-structured | **AIM** |
| Parallel tool calls | `parallel:[{...},{...}]` → ThreadPoolExecutor | Только batch через separate tool calls | **AIM** |
| Tool examples in prompt | F1: `examples=[...]` injected into system | Limited, init-time embedded | **AIM** |
| Bash sandbox | Whitelist (broken!) | Full shell parsing + hooks | **CC** |

### 2. Доступные инструменты

| Категория | AIM | Claude Code |
|---|---|---|
| File I/O | read/write/edit_file + apply_patch (atomic multi-edit) | Read/Edit/Write |
| Search | glob/grep + ripgrep | Bash(grep/find) + WebSearch/WebFetch |
| Memory | memory_recall/save (LanceDB) | `.claude/memory/*.md` |
| Vision | view_image (PNG/JPG/PDF, claude/DS-V4/OCR fallback) | None (нужен MCP) |
| Citation verify | verify_pmid/doi, search_pubmed | None |
| Domain delegates | doctor/writer/researcher/coder/email/parallel | Skills + MCP |
| Bash async | bash_async/status/output/kill (job_id) | run_in_background + Monitor |
| Scratchpad | note(k,v)/recall(k) per-session | `.claude/memory/` persistent |

**Итого: AIM 33 tools (medical-specific) vs CC 8-10 + MCP (general-purpose extensible).**

### 3. LLM routing

| Tier | AIM chain | CC |
|---|---|---|
| critical | Claude Opus → Gemini 2.5 Pro → DS-V4-pro → Ollama r1 | Single Opus |
| reasoning | DS-V4-pro → Claude Opus → Gemini → Ollama r1 | Sonnet (no reasoning tier) |
| long-context | DS-V4-flash 1M → Gemini → Ollama | Native model limit |
| fast | Groq llama-3.1-8b → DS-V4-flash → Ollama 3b | Haiku |
| ensemble | 3-model + Jaccard 0.35 + adjudicator | None |
| circuit breaker | 3-state CLOSED/OPEN/HALF_OPEN | None |

### 4. Parallelism & speculation

| Feature | AIM | CC |
|---|---|---|
| Parallel tool calls | LLM в одном response → batch | Sequential within turn |
| Speculative prefetch | speculative_prefetch.py — фоновый thread, читает paths/PMIDs заранее | None |
| Sub-agent fan-out | delegate_parallel + ask_critical synthesis | Task tool subagents |
| Embed daemon | embed_daemon.py — bg SentenceTransformer | None |

### 5. Память

| Аспект | AIM | CC |
|---|---|---|
| Semantic recall | LanceDB + sentence-transformers 384-dim | grep по markdown |
| Chunking | 1500/200 chars | full files |
| Indexing | manual + async updates | continuous |
| Cross-project | DESKTOP_PROJECT_GLOB | только .claude/projects/ |
| Persistence | SQLite + LanceDB + jsonl | markdown файлы |
| Scratchpad | per-session in-memory | persistent files |

### 6. Session management

| Опция | AIM | CC |
|---|---|---|
| Session picker | start_or_resume interactive 5 recent | One per shell |
| Resume | full tool trace from messages table | grep transcripts |
| Auto-update STATE.md | finalize detects project mention | manual write |
| JSONL log | ~/.cache/aim/sessions/<run_id>.jsonl | markdown transcripts |
| Offline grace | 7 days hub-cache | online required |

### 7. Safety / Asimov laws

| Закон | AIM | CC |
|---|---|---|
| L0 (Zeroth) | evaluate_l0 deterministic + LLM-judge edge | implicit permissions |
| L1-L3 | explicit balancing | implicit |
| L_PRIVACY | блок Patients/ без consent + PII redaction | project-structure based |
| L_CONSENT | email/git_push/web_publish требуют user_confirmed=True | tool-specific permissions |
| L_VERIFIABILITY | каждый PMID/DOI должен resolve | None |

### 8-15. Streaming, Vision, Citations, Multi-user, Domain agents, Self-critique, Native messages, Bash sandbox, Тесты

См. полную версию в conversation transcript (audit от 2026-05-02).

---

## Где AIM реально сильнее

Для **medical decision support + multi-user clinic deployment** AIM — серьёзный шаг вперёд: tier-chain, ensemble, Asimov kernel, OCR pipeline, 9 языков, hub/node.

## Где Claude Code реально сильнее

Для **generic coding + research** CC проще, безопаснее (по дефолту), и расширяем через MCP. AIM пока не догнал permission model и shell-парсинг.

---

## Что брать из AIM в Claude-Code-style работу

- **L_VERIFIABILITY pattern** — gate перед `git push public` / `email send` для проверки цитат.
- **Ensemble adjudication для критичных решений** — `is_critical(prompt)` детектор + 3-model consensus.
- **Session JSONL log** — машинно-парсимый event stream для retro debugging.

## Что брать из Claude Code в AIM

- **Full shell parsing для bash whitelist** — закрыть A1.
- **Permission-prompt model** для path access — закрыть A2.
- **MCP-расширяемость** вместо hard-coded delegate агентов.

---

**Verdict для EIC Pathfinder demo:** A1+A2+B1+B2 ДОЛЖНЫ быть закрыты до показа reviewers. Без этого AIM выглядит как research prototype, а не deployable medical platform.
