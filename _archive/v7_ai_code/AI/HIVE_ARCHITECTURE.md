# AIM Hive Architecture — Queen + Worker Bees proposal

**Status:** PROPOSAL · 2026-05-03
**Author:** AIM agent (responding to user direction)
**Inspired by:** Hermes Agent (Nous Research), but extended with multi-user federation

## TL;DR

Сегодня AIM — single-tenant tool с hub/node разделением преимущественно
для auth. **Hive architecture** превращает его в federated collective
intelligence:

- **Workers (пчелки):** AIM instances на user local machines. Каждый
 накапливает свой опыт (sessions, reflexions, skills, evals).
- **Queen (матка):** central AIM aggregator, который собирает
 *signals* от workers, distills их в улучшения (new skills, prompt
 patches, eval cases), eval-gates через S1, и распространяет обратно
 workers'ам.
- **Цикл:** local development → harvest → integrate → re-distribute.

Каждый worker остается полностью функционален офлайн. Queen — accelerator,
не dependency.

---

## Текущее состояние AIM

Уже есть:
- ✅ `AIM_ROLE=hub|node` (multi-user auth + token validation)
- ✅ `agents/hub_client.py` — node-side heartbeat to hub
- ✅ Memory/skill synthesis (S7), pattern miner (S4), reflexion cluster (S10)
- ✅ Closed-loop self-improvement infrastructure (DG1+RD1+RA1+FE1+CV1+CA1)
- ✅ S6 framework (currently gated to dry-run — prerequisite ≥4 weeks baseline)

Чего нет (ключевые gaps):
- ❌ Worker → queen anonymized signal upload
- ❌ Queen-side cross-worker pattern aggregation
- ❌ Queen → worker controlled update distribution
- ❌ Worker-side opt-in / opt-out per skill
- ❌ Skill standard for interop с external агентами

---

## Архитектура

### Layer 1 — Worker (бочка/пчелка)

Каждый user запускает локальный AIM (текущий `AIM_ROLE=node`). Дополнения:

**1.1 Telemetry collector** (`agents/hive_telemetry.py`):
- Каждые N часов агрегирует:
 - reflexion themes (anonymized — никаких user task strings, только category labels)
 - skill usage frequencies
 - eval pass/fail rates per case
 - compliance metrics (line:line ratio, retry rate)
 - failure pattern clusters
- Применяет L_PRIVACY gate перед отправкой:
 - дроп: phone numbers, emails, file paths, project names, patient data
 - keep: aggregate counters, hash digests of prompts (not content)
- POST к queen `/v1/hive/contribute`
- Локально хранит timestamped log для debugging

**1.2 Update consumer** (`agents/hive_consumer.py`):
- Periodic GET `/v1/hive/updates?since=<last_sync>`
- Receives queen-distilled updates: new skills, prompt patches, eval cases
- Each update has:
 - `source_n`: across how many workers' signals it was distilled
 - `eval_delta`: measured improvement on queen's synthetic eval set
 - `skill_id` + version
 - `signature`: queen's signing key (verify before applying)
- Worker-side gates per update:
 - **L_CONSENT** — local user can mark `auto-accept` / `manual-only` / `disabled`
 - **L_VERIFIABILITY** — worker re-runs the eval cases the update was gated on
 - Если passes → install in `~/.aim/skills/<skill_id>.yaml`
 - Если fails → log to dashboard, do not install

### Layer 2 — Queen (матка)

Central aggregator (single-node, может быть VPS или Anthropic cloud route).

**2.1 Signal aggregator** (`queen/signal_inbox.py`):
- `/v1/hive/contribute` endpoint
- Validates worker auth token (existing hub auth)
- Stores anonymized signals in queen-side SQLite (`hive_signals` table)
- Per-worker rate limit (e.g., 1 contribution / 10 min)

**2.2 Pattern miner** (`queen/pattern_miner.py`):
- Periodically (daily?) scans across all workers' signals
- Identifies:
 - **Recurring failure modes** — same theme across N+ workers → candidate for new skill
 - **Successful pattern emergence** — workflow used by N+ workers, all succeed → candidate skill
 - **Drift detection** — collective compliance dropping → prompt patch needed
- Outputs candidate updates (skills, prompt patches, eval cases) to staging area

**2.3 Eval gate** (`queen/eval_gate.py`):
- Each candidate update tested on queen's synthetic eval suite (S1-style)
- Required deltas:
 - Δscore ≥ 0.05 (significant)
 - p ≤ 0.05 (statistical)
 - No regression on existing skills
- Updates that pass → published to `/v1/hive/updates` feed
- Updates that fail → archive with rationale

**2.4 Update distributor** (`queen/distributor.py`):
- Sign each approved update with queen's key
- Publish to `/v1/hive/updates` for worker pull
- Track adoption: how many workers pulled / installed / passed local eval

### Layer 3 — Cross-cutting

**3.1 Privacy contract** (`PRIVACY.md`):
- What workers send: aggregate counters, anonymized themes, hashed prompts
- What workers NEVER send: PII, project paths, user content, patient data
- All under L_PRIVACY enforcement (existing in AIM)

**3.2 Skill standard adapter** (`agents/skill_standard.py`):
- Adopt subset of agentskills.io schema for skill interop
- Two modes:
 - `agentskills_export` — emit our S7 skills in agentskills.io format (allows external agents to use them)
 - `agentskills_import` — adopt 3rd-party skills with eval gate before merge
- Gives AIM a foothold in the broader skill ecosystem без отказа от our better infrastructure

**3.3 Hive dashboard** (`agents/hive_status.py`):
- Worker side: `aim hive status` — last sync, pending updates, opt-out list
- Queen side: `aim hive admin` — N workers, contribution rates, candidate updates pipeline

---

## Реализация (phasing)

### Phase 0 — Prerequisites (current state, already done)
- ✅ AIM hub/node split
- ✅ Memory + reflexion + skill synthesis infrastructure
- ✅ Eval harness (S1)
- ✅ Closed-loop self-improvement modules (DG1-FV1)

### Phase 1 — Worker telemetry (1 week)
- `agents/hive_telemetry.py`: anonymized signal collection + L_PRIVACY filter
- `tests/test_hive_telemetry.py`: ensure NO PII leakage
- Add `aim hive contribute` CLI to send manually
- **Gate:** can run on real user without sending personal data

### Phase 2 — Queen-side aggregator (1-2 weeks)
- Queen-side endpoints + SQLite schema
- Pattern miner across worker signals
- Initial eval gate (re-use S1 infrastructure)
- **Gate:** synthesize at least 1 candidate skill from 5+ worker signals on synthetic data

### Phase 3 — Update distribution (1 week)
- Queen → worker pull endpoint
- Worker-side L_CONSENT gates
- Local eval re-verification before install
- **Gate:** end-to-end loop with stub workers in CI

### Phase 4 — Skill standard adapter (1 week)
- Bidirectional agentskills.io ↔ AIM YAML conversion
- Test interop: skill produced by Hermes → load in AIM (with eval gate)
- **Gate:** at least one skill from external standard usable in AIM

### Phase 5 — Multi-channel comm (1 week)
- Add Discord + Signal alongside existing Telegram
- Reuse hub_client auth
- **Gate:** notification arrives via 3 channels for same event

### Phase 6 — Serverless worker mode (optional, later)
- Daytona / Modal hibernating worker template
- Useful for users who run AIM 1-2 days/week (don't pay for idle compute)

---

## Что НЕ делать

- **Не трогать LongevityCommon ecosystem** — AIM/AI инфраструктура отдельная. Hive architecture не изменяет project ownership / FCLC / MCOA / etc.
- **Не сделать queen mandatory** — worker должен полностью функционировать офлайн.
- **Не делать queen single point of failure** — multiple queens возможны (federated, не centralized).
- **Не сливать сырые user data** — only aggregate / hashed / anonymized.

---

## Критика / риски

1. **Worker контента может leak несмотря на filter** — нужен extensive privacy audit на Phase 1 gate. Recommend: each contribution preview-able in `aim hive preview` before send.
2. **Queen может стать echo chamber** — patterns from N workers перепрошивают остальных, дрейф невозможно обнаружить. Mitigation: queen also tracks workers who **deviate** from majority — diverse signal preserved.
3. **Eval gate может миссировать**, если eval suite слишком узкий. Mitigation: queen's eval suite растет вместе с patterns (auto-generated regression cases via FE1).
4. **Skill standard adapter increases attack surface** — внешние skills могут содержать malicious code. Mitigation: agentskills schema только декларативный (no executable code), worker eval gate перед install.
5. **Network round-trip cost** — workers contribute и pull регулярно. Mitigation: Phase 1 sync интервал = days, not minutes; signal payload < 10KB.

---

## Decision

**Recommendation: BUILD Phase 1+2 в течение следующих 2-3 недель.** Низкий
риск (worker side только, queen может сначала быть в-памяти stub),
получаем real signal от 1-2 dev workers, decide on Phase 3+ based on
quality of harvested patterns.

Phase 4 (skill standard) — параллельно, ortogonal.

Phase 5+6 — позже, после первого полного hive cycle на Phase 1-3.
