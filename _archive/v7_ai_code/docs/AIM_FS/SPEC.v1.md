# AIM Filesystem Specification (AIM_FS) — v1 draft

Дата: 2026-05-08
Статус: DRAFT v1 — ожидает peer review через DeepSeek-reasoner

> **Цель:** определить файловую систему AIM, которая:
>
> 1. Хранит профиль пользователя (доктора), который AIM **изучает и поддерживает**.
> 2. Хранит проекты пользователя (которые он явно создаёт и описывает; AIM генерирует ядро).
> 3. Хранит автоматически создаваемые проекты — пациенты, служебные, проект саморазвития AIM.
>
> **И при этом превосходит auto-memory Claude Code по следующим осям:**
> approval queue, версионирование, граф связей, провенанс, decay, схемы, conflict
> resolution, scoping, semantic search, replay, multi-tenant, lazy-loading
> индекса, schema-driven UI.

---

## 1. Постановка задачи

### 1.1 Что есть у Claude Code (baseline)

Локация: `~/.claude/projects/<project>/memory/`

Структура:
```
memory/
├── MEMORY.md # ручной индекс (загружается в контекст КАЖДЫЙ ход)
├── feedback_no_docker.md # frontmatter (name/description/type) + тело
├── feedback_language.md
├── project_xxx.md
├── user_email.md
├──..
└── reference_*.md
```

**Особенности:**
- 157 файлов в одной плоской директории.
- Тип — префикс имени файла (`feedback_*`, `project_*`, `user_*`, `reference_*`, `contact_*`, `fact_*`).
- Frontmatter: `name`, `description`, `type`, `originSessionId`.
- Тело — произвольный markdown.
- Индекс `MEMORY.md` поддерживается вручную параллельно файлам.
- Сохранение auto: AI пишет когда сочтёт нужным.

**Известные проблемы (выявленные на материале аудита 2026-05-08):**

| # | Проблема | Конкретный пример |
|---|----------|-------------------|
| L1 | Индекс может рассинхронизироваться с файлами — ручная синхронизация хрупка | `MEMORY.md` truncates после 200 строк (правило в системном промпте) |
| L2 | Нет графа связей. `fact_no_longer_eic_annals.md` пишет «связанные memory требуют ревизии», но нет автоматического обнаружения зависимых записей | пришлось добавлять явное упоминание |
| L3 | Нет версионирования: обновление перезаписывает; история теряется | нельзя восстановить, как фраза эволюционировала |
| L4 | Нет семантического поиска: AI скан имён файлов | при 157 записях индекс уже у лимита 200 строк |
| L5 | Нет approval queue: AI сам решает что важно, user не контролирует | риск шума и ложноположительных «правил» |
| L6 | Нет decay/TTL: контакты, deadlines, projects устаревают молча | правило «verify before recommending» — компенсация в run-time |
| L7 | Провенанс ограничен `originSessionId` — нельзя проследить _почему_ AI решил сохранить | не видно, было ли это user-confirmed или AI-inferred |
| L8 | Плоский namespace: префиксы типа в имени файла; нельзя scope «feedback для конкретного проекта» | глобальный пул правил — невозможно отключить часть для одного проекта |
| L9 | Нет схем: тело произвольно — поля могут отсутствовать | неконсистентность между однотипными записями |
| L10 | Нет conflict resolution: две противоречащие записи могут сосуществовать | `feedback_deepseek_models_v4_only.md` vs `feedback_deepseek_v4_models.md` — потенциальный дубль/конфликт |
| L11 | Single-user only | для AIM (multi-doctor SaaS) непригодно |
| L12 | Индекс грузится в контекст каждый ход → стоимость токенов | при 157 записях ≈ 12-15K токенов оверхеда |
| L13 | Нет audit-trail: кто/когда/почему создал фраг — `originSessionId` недостаточен | нельзя replay |
| L14 | Нет schema-driven UI: всё через текстовый CLI | пользователю не показать структурированный inbox |
| L15 | Нет atomic transactions: пишем файл + правим индекс — может рваться посередине | если AI убит между двумя write — drift |

### 1.2 Что должна решать AIM_FS

AIM_FS = persistence layer для агента AIM. Должна обеспечить:

1. **Безопасность** — atomic writes, ACID semantics для пары (fact + index + links).
2. **Прозрачность** — provenance каждого факта, full event log для replay.
3. **Масштабируемость** — single-user (Jaba) → multi-tenant (clinic with N doctors).
4. **Производительность** — лениво-загружаемый индекс, hybrid поиск (keyword + semantic).
5. **Контроль user'а** — approval queue для всего, что AIM хочет сохранить автоматически.
6. **Эволюционируемость** — версии, conflict log, supersession, time-travel.
7. **Соблюдение правила стека:** реализация Rust (ядро) + Phoenix LiveView (UI).

---

## 2. Архитектура: три уровня

### Уровень 1 — User profile (AIM-curated)
**Назначение:** AIM непрерывно изучает пользователя и поддерживает структурированное представление: роль, цели, предпочтения, ритмы работы, история ключевых решений.

**Корень:** `<aim_root>/users/<user_id>/profile/`

Содержимое:
```
profile/
├── identity.toml # immutable: имя, DOB, контакты, ORCID, паспорт
├── role.md # роль/специализация/уровень экспертизы
├── preferences.md # стиль работы (language, autonomy, terseness)
├── workflows.md # как user обычно работает (день, циклы)
├── history.jsonl # append-only лог ключевых решений / событий
├── facts/ # отдельные факты о user (вроде Claude-memory user_*)
│ ├── <fact_id>.md # каждый — отдельный файл с frontmatter + телом
│ └── _meta.jsonl # append-only: provenance, decay, version
└── feedback/ # collaboration rules from user
 ├── <feedback_id>.md
 └── _meta.jsonl
```

**Ключевое отличие от Claude:**
- `identity.toml` — immutable singleton (паспорт, ORCID нельзя «сохранить дважды»).
- `_meta.jsonl` параллельно `facts/` — provenance, decay, версии.
- AI не пишет напрямую в `facts/` — все новые факты идут в **inbox** (см. раздел 4).

### Уровень 2 — User-defined projects

**Назначение:** user объясняет идею проекта; AIM генерирует **полное ядро** (11-file core, согласно `feedback_project_core.md`).

**Корень:** `<aim_root>/users/<user_id>/projects/<project_slug>/`

Содержимое (11-file core + расширения):
```
<project_slug>/
├── CONCEPT.md # источник истины (что и зачем)
├── THEORY.md # immutable, теоретическое обоснование
├── PARAMETERS.md # числовые параметры/конфиг
├── KNOWLEDGE.md # ссылки + verified citations (через PubMed/Crossref)
├── MAP.md # карта файлов проекта
├── UPGRADE.md # план улучшений; ✅ после реализации
├── TODO.md # рабочие задачи
├── README.md # public-facing
├── CLAUDE.md # instructions для AI
├── STATE.md # текущий статус
├── EVIDENCE.md # доказательная база
├── data/ # артефакты, бинарники,.docx (не в git)
├── code/ # Rust + Phoenix only (правило стека)
└── _meta/
 ├── created_at # ISO timestamp
 ├── created_by # user_id
 ├── tags.json # классификация
 ├── links.jsonl # связи: depends_on, references, supersedes
 └── events.jsonl # full audit log
```

**Воркфлоу создания:**
1. User: «AIM, создай проект X — это [описание]».
2. AIM генерирует draft всех 11 файлов, кладёт в `_inbox/projects/<slug>/`.
3. User reviews в Phoenix LiveView, edits, approves.
4. AIM перемещает в `projects/<slug>/`, добавляет в индекс, отправляет события в `events.jsonl`.

### Уровень 3 — Auto-created folders

**Назначение:** проекты, которые AIM создаёт **сам** в ходе работы:
- (a) папка пациента после первого осмотра,
- (b) служебные папки (бэкапы, логи, indices, tmp),
- (c) проект саморазвития AIM (proposals для апгрейдов AIM).

#### 3.a Patient folders

Корень: `<aim_root>/users/<doctor_id>/patients/<patient_id>/`

```
<patient_id>/ # формат: <Surname>_<Name>_<YYYY_MM_DD>
├── ANAMNESIS.md # анамнез (структурированный по schema patient_anamnesis_v1)
├── visits/
│ └── <YYYY-MM-DD-HH-MM>/
│ ├── intake.md
│ ├── cbc.csv
│ ├── differential.md
│ └── report.md
├── recipes/
│ └── <recipe_id>.md # каждый рецепт — schema recipe_v1
├── notes/
│ └── <note_id>.md
├── _meta/
│ ├── identity.toml # immutable PII (encrypted at rest)
│ ├── consent.json # GDPR-style consent log
│ ├── links.jsonl
│ └── events.jsonl
└── _inbox/ # AIM-предложенные диагнозы/рецепты ждут approval
 └── <proposal_id>.md
```

**Воркфлоу:**
- AIM завершает осмотр → пишет `differential.md` и proposed `recipe.md` в `_inbox/`.
- Doctor открывает Phoenix LiveView → одобряет/редактирует/отклоняет.
- При approve: AIM переносит в `recipes/`, добавляет в `events.jsonl`, отсылает Telegram-сообщение пациенту (если разрешено в `consent.json`).

#### 3.b Service folders

Корень: `<aim_root>/_service/`

```
_service/
├── INDEX.json # глобальный sharded index (см. раздел 5)
├── tantivy/ # keyword search index
├── vec/ # embeddings index (voyage-3-lite или local)
├── events/ # event log (sharded по неделям)
│ └── 2026-W19.jsonl
├── disputes/ # conflict log (когда два факта противоречат)
│ └── <dispute_id>.md
├── inbox/ # глобальный inbox (всё что ждёт approval)
│ ├── pending/<id>.md
│ ├── approved/<id>.md (kept for audit, then archived)
│ └── rejected/<id>.md
├── tmp/ # ephemeral
└── backup/
 └── 2026-05-08T02-00.tar.zst
```

#### 3.c AIM self-development project

Корень: `<aim_root>/_self_dev/`

```
_self_dev/
├── CONCEPT.md # что такое AIM, какие свойства поддерживаем
├── INVARIANTS.md # immutable: L0–L3 + extended kernel laws (нельзя править без user)
├── UPGRADE.md # план улучшений (✅ после реализации)
├── proposals/ # AIM предлагает улучшения (новые правила, скиллы, рефакторинги)
│ ├── pending/<id>.md
│ ├── approved/<id>.md
│ └── rejected/<id>.md
├── eval/ # самодиагностика (eval harness results)
│ └── <YYYY-MM-DD>.json
└── _meta/
 ├── links.jsonl
 └── events.jsonl
```

**Воркфлоу:**
- AIM running daily self-diagnostic → находит slowdown / regression / opportunity.
- Пишет `proposals/pending/<id>.md` со схемой `proposal_v1`:
 ```yaml
 ---
 schema: proposal_v1
 type: rule|skill|refactor|param_tune|new_feature
 priority: P0|P1|P2
 rationale: "Eval показал -3.2% на gap_detector"
 blast_radius: low|medium|high
 rollback: "git revert <hash>"
 ---
 ## Что предлагаю..
 ## Доказательства..
 ## Риски..
 ```
- User reviews в Phoenix LiveView, approves/edits/rejects.
- При approve: AIM применяет (создаёт PR / правит файлы), пишет в `events.jsonl`.

---

## 3. Слой содержимого: формат файлов

### 3.1 Все «memory-like» файлы имеют унифицированный frontmatter

```yaml
---
id: "01HZAB12CDEF34GH56JK78MN90" # ULID — стабильный
schema: "feedback_v1" # ссылка на схему в _schemas/
title: "DeepSeek-first rule"
description: "Маршрутизация writing/QA через DeepSeek API"
created_at: "2026-05-08T02:00:00Z"
created_by:
 agent: "aim"
 user: "djabbat@gmail.com"
 source: "user_message" | "tool_output" | "ai_inferred"
 session_id: ".."
 llm_model: "deepseek-reasoner" | null
versions: # immutable — append-only
 - hash: "sha256:abcd…"
 at: "2026-05-08T02:00:00Z"
status: "active" | "superseded" | "rejected" | "deprecated"
decay:
 ttl_days: 90 | null # null = invariant
 expires_at: "2026-08-06T02:00:00Z"
scope: # к чему применимо
 global: false
 user_ids: ["djabbat@gmail.com"]
 project_ids: ["LC_AIM", "LC_CDATA"] | "*"
 patient_ids: []
links:
 depends_on: ["01HX…"]
 refines: ["01HY…"]
 supersedes: ["01HW…"] # старая запись → status: superseded
 contradicts: []
tags: ["llm", "routing", "deepseek"]
---
<тело файла в markdown, валидируется по schemas/feedback_v1.json>
```

### 3.2 Schema registry

`<aim_root>/_schemas/`:
```
_schemas/
├── feedback_v1.json # JSON Schema
├── fact_v1.json
├── project_core_v1.json # 11-file project shape
├── patient_anamnesis_v1.json
├── recipe_v1.json
├── proposal_v1.json
├── user_profile_v1.json
└──..
```

При записи AIM **обязан** валидировать тело по схеме. Невалидный draft → в `_service/inbox/pending/` с пометкой `schema_violation`.

### 3.3 Content-addressable storage (CAS)

Каждая версия файла дополнительно копируется в `<aim_root>/_service/cas/sha256/ab/cd/abcdef…` (git-like). Это позволяет:
- Восстановить любую версию.
- Дедуплицировать одинаковые тела.
- Подписывать `events.jsonl` хешем содержимого (immutable trail).

### 3.4 Event log

`<aim_root>/_service/events/<YYYY-WNN>.jsonl` (append-only):
```jsonl
{"id":"01HZ..","at":"2026-05-08T02:00:00Z","actor":{..},"op":"create","entity":"feedback:01HZAB..","hash":"sha256:.."}
{"id":"01HZ..","at":"2026-05-08T02:01:30Z","actor":{..},"op":"approve","entity":"proposal:01HZCD..","prev_status":"pending","new_status":"approved"}
{"id":"01HZ..","at":"2026-05-08T02:02:10Z","actor":{..},"op":"supersede","entity":"feedback:01HZEF..","by":"01HZAB.."}
```

Любое CRUD = новое событие. Состояние реконструируется replay'ом.

---

## 4. Approval queue (главное отличие от Claude)

**Принцип:** AIM никогда не сохраняет ничего автоматически в Tier 1/2/3 без явного approval, **кроме**:

1. Tier 3.a: данные _текущего_ visit пациента (intake, CBC, differential) — рутина.
2. Tier 3.b: служебные индексы, бэкапы, события — system.
3. Tier 1: при `created_by.source == "user_message"` и пользователь _напрямую_ сказал «запомни X» — auto-approve.

Всё остальное (выводы AI о пользователе, новые «feedback», proposed улучшения, рецепты, диагнозы) → **inbox**.

### 4.1 Inbox UI (Phoenix LiveView)

Маршрут: `/inbox` в `aim_web`.

```
┌─ AIM Inbox (12 pending) ──────────────────────────────────────┐
│ filter: [all] [user-facts] [patient-rec] [self-dev] [project] │
├───────────────────────────────────────────────────────────────┤
│ ▸ proposal · 5m ago · self_dev │
│ "Add LLM fallback to Anthropic on DeepSeek 429" │
│ priority: P1 · blast_radius: low │
│ [▶ Open] [✓ Approve] [✎ Edit] [✗ Reject] [⏸ Defer] │
│ ▸ user_fact · 12m ago · profile │
│ "User prefers 'gabro' nickname (heard 3× in session)" │
│ confidence: 0.92 │
│ [▶ Open] [✓] [✎] [✗] │
│ ▸ patient_recipe · 1h ago · pt:Beridze_Keti_2026_03_12 │
│ "Vitamin D 5000 IU/day × 8 weeks" │
│ [▶ Open] [✓] [✎] [✗] │
└───────────────────────────────────────────────────────────────┘
```

Каждый элемент имеет:
- **Source/rationale** — почему AIM это предложил.
- **Schema** — определяет форму тела.
- **Diff (если supersedes)** — показать, что меняется.
- **Approve/Edit/Reject/Defer** кнопки.

Defer = «вернуться позже»; AIM не считает молчание за согласие.

### 4.2 Auto-approve правила (опционально, per-user)

В `users/<user_id>/preferences.md`:
```toml
[approval]
auto_approve_user_facts_with_confidence_above = 0.95
auto_approve_service_events = true
auto_approve_patient_intake_data = true
require_approval_for = ["feedback", "proposal", "recipe", "diagnosis"]
```

---

## 5. Индексирование и поиск

### 5.1 Sharded index (не как Claude — не грузим всё в контекст)

`_service/INDEX.json`:
```json
{
 "version": 1,
 "shards": [
 {"name":"user_profile", "path":"_service/idx/user_profile.json","size":24},
 {"name":"feedback_global", "path":"_service/idx/feedback_global.json","size":89},
 {"name":"projects", "path":"_service/idx/projects.json","size":17},
 {"name":"patients", "path":"_service/idx/patients.json","size":42},
 {"name":"self_dev_proposals", "path":"_service/idx/self_dev.json","size":7}
 ],
 "updated_at": "2026-05-08T02:13:00Z"
}
```

AIM грузит только **релевантный shard** (а не весь индекс).

### 5.2 Tantivy + embeddings

- `_service/tantivy/` — Tantivy keyword index (поле `body`, `title`, `tags`).
- `_service/vec/` — embeddings (HNSW; voyage-3-lite или local sentence-transformers).
- Hybrid search: BM25 ⊕ cosine с RRF (Reciprocal Rank Fusion).

Запрос: `aim_fs.search("сидячий образ жизни", scope="patients/Beridze_Keti", k=5)`.

### 5.3 Auto-update triggers

Любое event в `_service/events/` → background worker (Phoenix `:queue`) обновляет shard, Tantivy, embeddings.

---

## 6. Граф связей

`<entity>/_meta/links.jsonl` (per entity) + global `_service/graph.duckdb`:

Типы рёбер:
- `depends_on` — для технических зависимостей.
- `refines` — уточнение (X refines Y).
- `supersedes` — замена (X supersedes Y → Y становится `superseded`).
- `contradicts` — антагонизм (требует resolution).
- `references` — упоминание в теле/аргументации.
- `produced_by` — какой proposal породил какой fact.

Запросы: «дай все feedback, которые применимы к проекту LC_CDATA и не contradicted ни одним более новым».

Граф хранится дублировано (ребра в файлах для git, агрегат в DuckDB для query). Sync по событиям.

---

## 7. Decay / staleness

Каждая запись имеет `decay.ttl_days`:
- `null` — invariant (passport, ORCID, immutable physical fact).
- `90` (default) — рабочие правила.
- `7` — короткие deadlines (TODO).
- `30` — project state.

Background `:decay_sweeper`:
- За N дней до expiry → создаёт review-задачу в inbox: «правило X истекает; продлить или отказаться?»
- После expiry → `status: deprecated`, не показывается в стандартных запросах, но не удаляется.

---

## 8. Conflict / dispute resolution

Когда новая запись `contradicts` существующую:
1. Обе помечаются `disputed`.
2. Создаётся `_service/disputes/<id>.md` с обоими телами + diff + rationale.
3. AIM в inbox показывает: «Конфликт: A vs B — выбери, что оставить».
4. После решения — победитель `active`, проигравший `superseded`, dispute → `resolved`.

Это решает L10 (Claude memory дубли).

---

## 9. Multi-tenant

Корень `users/<user_id>/` — namespace per user.
Дополнительно `_org/<org_id>/` — общие на организацию (например, GLA-wide protocols).

Видимость:
- AIM по умолчанию видит свой user namespace.
- Через `org` claim в auth — видит `_org/<auth.org_id>/`.
- Между users — только через явный share (link `shared_with`).

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

Расположение: `rust-core/crates/aim_fs/`.

Публичный API:
```rust
pub struct AimFs { root: PathBuf, /* … */ }

impl AimFs {
 pub fn open(root: impl AsRef<Path>) -> Result<Self>;

 // Tier 1
 pub fn user_profile(&self, user_id: &str) -> Result<UserProfile>;
 pub fn upsert_user_fact(&self, user_id: &str, fact: NewFact) -> Result<EntryId>;

 // Tier 2 — user-defined projects
 pub fn scaffold_project(&self, user_id: &str, slug: &str, concept: &str) -> Result<ProjectId>;

 // Tier 3 — auto
 pub fn create_patient(&self, doctor_id: &str, patient_id: PatientKey) -> Result<>;
 pub fn add_visit(&self, patient_id: &str, visit: Visit) -> Result<VisitId>;
 pub fn propose(&self, scope: Scope, body: Body, schema: SchemaId) -> Result<ProposalId>;
 pub fn approve(&self, proposal_id: ProposalId, by: Actor) -> Result<EntryId>;
 pub fn reject(&self, proposal_id: ProposalId, by: Actor, reason: String) -> Result<>;

 // Search / index
 pub fn search(&self, q: &str, scope: Scope, k: usize) -> Result<Vec<Hit>>;
 pub fn graph(&self) -> &Graph;
 pub fn replay(&self, until: DateTime<Utc>) -> Result<Snapshot>;

 // Maintenance
 pub fn validate_schema(&self, body: &str, schema: SchemaId) -> Result<>;
 pub fn run_decay_sweep(&self) -> Result<usize>;
}
```

Внутри:
- `atomic.rs` — write-then-rename, fsync; cross-platform.
- `cas.rs` — content-addressable store.
- `event_log.rs` — append-only jsonl с rotation по неделям.
- `graph.rs` — DuckDB-backed, edges from `links.jsonl`.
- `index.rs` — Tantivy + HNSW для embeddings.
- `schema.rs` — JSON Schema validation.
- `decay.rs` — background sweeper.

Зависимости: `tantivy`, `serde`, `serde_json`, `jsonschema`, `duckdb`, `ulid`, `sha2`, `tokio`.

### 10.2 Phoenix context `AIM.FS`

Расположение: `phoenix-umbrella/apps/aim_memory/lib/aim/fs/`.

Слой над Rustler NIF:
```elixir
defmodule AIM.FS do
 @moduledoc "High-level FS API; calls Rust via NIF"

 def user_profile(user_id), do: AIM.FS.NIF.user_profile(user_id)

 def propose(%Proposal{} = p, actor), do: AIM.FS.NIF.propose(p, actor)

 def approve(proposal_id, actor) do
 with {:ok, entry_id} <- AIM.FS.NIF.approve(proposal_id, actor) do
 Phoenix.PubSub.broadcast(AIM.PubSub, "inbox", {:approved, proposal_id, entry_id})
 {:ok, entry_id}
 end
 end

 def search(q, scope \\ :user, k \\ 5), do: AIM.FS.NIF.search(q, scope, k)
end
```

LiveView `AIMWeb.InboxLive`:
- subscribe к `Phoenix.PubSub.AIM.PubSub:inbox`.
- table с pending proposals.
- approve/reject buttons → call AIM.FS.

### 10.3 Миграция существующих данных

`scripts/aim_fs_migrate.exs`:
1. Читает текущие `~/Desktop/LongevityCommon/AIM/USER/*.md`, `Patients/*`, `AI/*`.
2. Преобразует во frontmatter v1 (выводит ULID, ставит `created_at` из mtime, `created_by.source = "imported"`).
3. Кладёт в новый layout под `<aim_root>/users/djabbat/..`.
4. Старая директория переименовывается в `_legacy_pre_aim_fs_v1/` (не удаляется).

---

## 11. Преимущества над Claude (сводная таблица)

| Lim. | Claude | AIM_FS | Как |
|------|--------|--------|-----|
| L1 | Index ручной, грузится весь | Sharded, lazy | `_service/INDEX.json` + per-shard файлы |
| L2 | Нет графа | Типизированный граф | `links.jsonl` + DuckDB |
| L3 | Нет версий | Append-only CAS | `_service/cas/sha256/..` + `versions[]` в frontmatter |
| L4 | Скан имён файлов | Hybrid Tantivy + HNSW | RRF |
| L5 | Auto-save | Approval queue | inbox + LiveView UI |
| L6 | Verify-on-use | TTL + decay sweeper | `decay.ttl_days` + background |
| L7 | Только session_id | Полный provenance | `created_by` + `events.jsonl` |
| L8 | Глобальный namespace | Scoping | `scope.{global,user,project,patient}` |
| L9 | Нет схем | JSON Schema registry | `_schemas/*.json`, валидация при write |
| L10 | Дубли молча | Conflict log | `_service/disputes/` |
| L11 | Single-user | Multi-tenant | `users/<id>/` + `_org/<id>/` |
| L12 | Тяжёлый индекс в контексте | Lazy shards | загружаем по запросу |
| L13 | Нет audit-trail | Event log + replay | `events.jsonl` + `replay(until)` |
| L14 | CLI only | Schema-driven UI | LiveView, поля авто из JSON Schema |
| L15 | Не atomic | Atomic transactions | write-then-rename + единая `commit_event` |

---

## 12. Открытые вопросы (для peer review)

1. **CAS: использовать git напрямую vs custom?** Git даёт diff, history, но усложняет inbox/approval. Custom CAS проще для approval flow, но переизобретение.
2. **DuckDB vs SQLite для графа?** DuckDB лучше для аналитики; SQLite — для надёжных транзакций.
3. **Embeddings — local vs API?** Local (sentence-transformers) — приватность; voyage — качество. Default: local fallback на API.
4. **Авто-confidence для user_facts:** как считать? heuristic vs LLM-rated?
5. **TTL значений по умолчанию.** 90 дней — обоснованно? Может быть type-specific (feedback ∞, project 30, deadline 7).
6. **Retention для rejected proposals.** Хранить? Если да, как долго (для обучения decay-sweeper)?
7. **Multi-tenant и encryption.** PII пациентов — шифрование at-rest? Per-user key?
8. **Какой формат identity.toml.** TOML vs JSON vs YAML?
9. **Как обрабатывать партиционирование больших проектов** (pacient'ов с тысячами визитов)?
10. **Concurrent writes** между Rust core и Phoenix LiveView — locking strategy?

---

## 13. План реализации (после ACCEPT)

**Phase 1 (1-2 дня):** Rust crate `aim_fs` минимум:
- atomic write/read
- frontmatter parse/serialize
- ULID/sha256
- propose/approve/reject API
- events.jsonl append

**Phase 2 (1 день):** JSON Schemas (8 базовых типов).

**Phase 3 (1 день):** Phoenix `AIM.FS` context + Rustler NIF mapping.

**Phase 4 (2 дня):** LiveView Inbox UI + auto-approve preferences.

**Phase 5 (1 день):** Tantivy + embeddings index.

**Phase 6 (1 день):** Graph (DuckDB) + decay sweeper.

**Phase 7 (1 день):** Migration script (legacy → new layout).

**Phase 8 (continuous):** Audit fixes из P0 (отдельная очередь).

---

**Конец draft v1. Идёт в peer review через DeepSeek-reasoner до вердикта ACCEPT.**
