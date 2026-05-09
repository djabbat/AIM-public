# AIM Filesystem Specification (AIM_FS) — v2 draft

Дата: 2026-05-10 
Статус: DRAFT v2 — исправлен по peer review от 2026-05-09 

> **Цель:** определить файловую систему AIM, которая:
>
> 1. Хранит профиль пользователя (доктора), который AIM **изучает и поддерживает**.
> 2. Хранит проекты пользователя (которые он явно создаёт и описывает; AIM генерирует ядро).
> 3. Хранит автоматически создаваемые проекты — пациенты, служебные, проект саморазвития AIM.
>
> **И при этом превосходит auto-memory Claude Code по следующим осям:** 
> approval queue, версионирование, граф связей, провенанс, decay, схемы, conflict resolution, scoping, semantic search, replay, multi-tenant, lazy-loading индекса, schema-driven UI.

---

## 1. Постановка задачи

### 1.1 Что есть у Claude Code (baseline)

*(без изменений, как в v1)*

### 1.2 Что должна решать AIM_FS

*(без изменений)*

---

## 2. Архитектура: три уровня

### Уровень 1 — User profile (AIM-curated)

**Корень:** `<aim_root>/users/<user_id>/profile/`

Содержимое:
```
profile/
├── identity.yaml # immutable: имя, DOB, контакты, ORCID, паспорт
├── role.md # роль/специализация/уровень экспертизы
├── preferences.md # стиль работы (language, autonomy, terseness)
├── workflows.md # как user обычно работает (день, циклы)
├── history.jsonl # append-only лог ключевых решений / событий
├── facts/ # отдельные факты о user
│ ├── <fact_id>.md
│ └── _meta.jsonl # provenance, decay, version (локальный)
└── feedback/ # collaboration rules from user
 ├── <feedback_id>.md
 └── _meta.jsonl
```

> **Изменение v2:** `identity.toml` → `identity.yaml` для единообразия с остальным frontmatter (YAML). 
> `_meta/` per entity сохранена для локального доступа и git-friendliness; глобальный агрегат в `_service/events` дублирует события для полного аудита. 
> <!-- review_response: _meta/ не избыточна — даёт быстрый доступ к связям конкретной сущности без обхода глобального графа. Дублирование согласовано через консистентные события. -->

**Ключевое отличие от Claude:**
- `identity.yaml` — immutable singleton.
- `_meta.jsonl` параллельно `facts/`.
- AI не пишет напрямую в `facts/` — все новые факты идут в **inbox**.

### Уровень 2 — User-defined projects

**Корень:** `<aim_root>/users/<user_id>/projects/<project_slug>/`

**Минимальный набор ядра** (для MVP): 
`CONCEPT.md`, `STATE.md`, `TODO.md`, `README.md`.

Остальные файлы (`THEORY.md`, `PARAMETERS.md`, `KNOWLEDGE.md`, `MAP.md`, `UPGRADE.md`, `CLAUDE.md`, `EVIDENCE.md`) — опциональны, создаются по запросу.

```
<project_slug>/
├── CONCEPT.md # источник истины (что и зачем)
├── STATE.md # текущий статус
├── TODO.md # рабочие задачи
├── README.md # public-facing
├── data/ # артефакты, бинарники (не в git)
├── code/ # Rust + Phoenix only
└── _meta/
 ├── created_at
 ├── created_by
 ├── tags.json
 ├── links.jsonl
 └── events.jsonl
```

**Воркфлоу создания:** *(без изменений)*

### Уровень 3 — Auto-created folders

#### 3.a Patient folders

**Корень:** `<aim_root>/users/<doctor_id>/patients/<patient_id>/`

Для пациентов с большим числом визитов (>500) используется шардирование по месяцам:
```
visits/
├── 2026-01/
│ ├── <visit_id>.md
│ └──..
├── 2026-02/
│ └──..
```
Каждый `<visit_id>.md` содержит intake, cbc, differential, report (может быть одним файлом или вложенной папкой). 
Выбор шардинга автоматический при создании >500 визитов. 
PII шифруется at-rest с per-user ключом (см. раздел 9).

#### 3.b Service folders

`<aim_root>/_service/`:
```
_service/
├── INDEX.json # глобальный sharded index
├── events/ # event log (sharded по неделям)
│ └── 2026-W19.jsonl
├── disputes/ # conflict log
│ └── <dispute_id>.md
├── inbox/ # глобальный inbox
│ ├── pending/<id>.md
│ ├── approved/<id>.md
│ └── rejected/<id>.md
├── tmp/ # временные файлы для атомарных транзакций
└── backup/ # архивы
```

#### 3.c AIM self-development project *(без изменений)*

---

## 3. Слой содержимого: формат файлов

### 3.1 Унифицированный frontmatter

```yaml
---
id: "01HZAB12CDEF34GH56JK78MN90"
schema: "feedback_v1"
title: "DeepSeek-first rule"
description: "Маршрутизация writing/QA через DeepSeek API"
created_at: "2026-05-08T02:00:00Z"
created_by:
 agent: "aim"
 user: "djabbat@gmail.com"
 source: "user_message" | "tool_output" | "ai_inferred"
 session_id: ".."
 llm_model: "deepseek-reasoner" | null
confidence: 0.92 # только для ai_inferred; 0.0–1.0
versions:
 - hash: "sha256:abcd…"
 at: "2026-05-08T02:00:00Z"
status: "active" | "superseded" | "rejected" | "deprecated" | "expired"
decay:
 ttl_days: 90 | null
 expires_at: "2026-08-06T02:00:00Z"
scope:
 global: false
 user_ids: ["djabbat@gmail.com"]
 project_ids: ["LC_AIM", "LC_CDATA"] | "*"
 patient_ids: []
links:
 depends_on: ["01HX…"]
 refines: ["01HY…"]
 supersedes: ["01HW…"]
 contradicts: []
tags: ["llm", "routing", "deepseek"]
---
<тело>
```

> **v2:** добавлено поле `confidence` для AI-извлечённых фактов (рекомендация reviewer).

### 3.2 Schema registry

*(без изменений)*

### 3.3 Content-addressable storage (CAS)

Каждая версия файла копируется в `<aim_root>/_service/cas/sha256/ab/cd/abcdef…`. 
**Retention policy:** 
- По умолчанию хранятся последние `retain_versions` версий (согласно `schema.*.json` — default=3). 
- Старые версии автоматически архивируются (tar.zst) при превышении лимита; запись об архиве в `_service/cas/manifest.json`. 
- Политика может быть переопределена per-schema.

Это позволяет дедуплицировать, восстанавливать и подписывать события.

<!-- review_response: CAS оставлен для надёжного версионирования; retention policy решает проблему переполнения. GC — периодическая задача. -->

### 3.4 Event log

*(без изменений)*

---

## 4. Approval queue (главное отличие от Claude)

**Принцип:** AIM никогда не сохраняет ничего автоматически в Tier 1/2/3 без явного approval, **кроме**:

1. Tier 3.a: данные _текущего_ visit пациента (intake, CBC, differential) — **observational data** (фактические измерения, жалобы, анамнез). 
 *AI-inferred выводы (диагнозы, рецепты) — только через inbox.* 
 Все PII‑данные шифруются at-rest согласно consent.
2. Tier 3.b: служебные индексы, бэкапы, события — system.
3. Tier 1: при `created_by.source == "user_message"` и пользователь напрямую сказал «запомни X» — auto-approve.

### 4.1 Inbox UI (Phoenix LiveView)

*(без изменений описания UI)*

**Добавлено:** 
- Каждый pending элемент имеет поле `auto_expire_at` (по умолчанию через 7 дней). 
- Если пользователь не принял решение до expiry → статус `expired`, элемент перемещается в `_service/inbox/expired/`. 
- Defer: возвращается в pending с увеличенным `auto_expire_at` (ещё 7 дней). 
- При offline-режиме пользователя перед expiry AIM отправляет уведомление (Telegram/email), если настроено в preferences.

### 4.2 Блокировочный протокол для concurrent access

Все мутирующие операции (propose, approve, reject, update) используют `flock` на `_service/.lock`. 
- Захват файловой блокировки на весь scope (user/global). 
- Воркеры NIF и Phoenix Port обязаны использовать lock при изменении состояния. 
- В случае конфликта — повтор через 50ms до 3 попыток, затем ошибка. 
- Это решает problem race condition (CRITICAL 1).

Дополнительно **атомарный коммит изменений**: 
1. Все файлы (move, events, index) готовятся во временной директории `_service/tmp/<commit_id>/`. 
2. Финальный шаг — `rename` временной директории на целевую (`rename` атомарен на одной файловой системе). 
3. Если rename удался → commit; если нет → rollback (удалить tmp). 
4. Запись в `events.jsonl` происходит до rename (во временной папке), так что потеря невозможна.

Пример для approve:
```
1. copy <proposal>.md → _service/tmp/<id>/target.md
2. append event → _service/tmp/<id>/events.jsonl
3. update INDEX → _service/tmp/<id>/INDEX.json
4. rename _service/tmp/<id>/ → проектная папка (replace)
5. release lock
```
Это решает CRITICAL 2 (неатомарность).

### 4.3 Auto-approve правила (опционально, per-user)

```toml
[approval]
auto_approve_user_facts_with_confidence_above = 0.95
auto_approve_service_events = true
auto_approve_patient_intake_data = true
require_approval_for = ["feedback", "proposal", "recipe", "diagnosis"]
```

---

## 5. Индексирование и поиск

### 5.1 Sharded index (ленивая загрузка)

`_service/INDEX.json` *(без изменений)*

### 5.2 Поиск в MVP

На первом этапе (до внедрения Tantivy + HNSW) поиск реализован как **fuzzy scan по shard-ам**: 
- Shard читается целиком (размер < 1 MB для типового шарда). 
- Поиск по frontmatter и body через `rg` (ripgrep) или встроенный grep в Rust. 
- Для 10⁵ записей с frontmatter (~50 MB) full scan на SSD < 100 ms, что приемлемо для MVP.

**Phase 5** (пост-MVP): замена на Tantivy (keyword) + HNSW (semantic) с RRF.

### 5.3 Auto-update triggers

Любое событие из `_service/events/` → немедленное обновление соответствующего шарда в `INDEX.json` (incremental, без перестроения всех шардов).

---

## 6. Граф связей

**Решение для MVP:** 
- Рёбра хранятся только в `links.jsonl` (per entity). 
- Глобальный граф не материализуется отдельно. 
- Для запросов «найти все feedback, применимые к проекту X» читаем links.jsonl всех релевантных шардов и строим ответ в памяти с LRU‑кешем.

DuckDB исключён из первого релиза (сложность не оправдана). 
<!-- review_response: DuckDB отложен до появления потребности в аналитике; dual‑write снимается. -->

---

## 7. Decay / staleness

*(без изменений)*

---

## 8. Conflict / dispute resolution

**Процесс:** 
1. Новая запись помечается `contradicts` и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, diff, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Таймаут:** если решение не принято за 7 дней, оба факта автоматически помечаются `superseded`, dispute → `resolved_unresolved`, proposal (если был) переходит в `expired`. 
6. После выбора победитель становится `active`, проигравший `superseded`, dispute `resolved`. Proposal (если есть) автоматически approved или rejected в зависимости от выбора (если был блокирован — разблокируется).

Это решает CRITICAL 4 и L10.

---

## 9. Multi-tenant

**Namespace:** `users/<user_id>/`. 
**Организации:** `_org/<org_id>/`.

**Изоляция и шифрование:** 
- PII пациентов шифруется at-rest с per-user ключом (storage-level encryption). 
- Механизм управления ключами: ключи хранятся в `users/<user_id>/.key.enc` (зашифрованы мастер-ключом приложения). 
- Доступ к данным другого пользователя — только при явном `shared_with` в `links.jsonl` и проверке авторизации в Phoenix (JWT с claim `user_id` и `org_id`). 
- Организационные данные (`_org/`) видны всем пользователям организации.

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** — без изменений в сигнатурах. 
**Внутренние модули:**
- `atomic.rs` — write-then-rename с prepare/commit через tmp, flock на `_service/.lock`.
- `cas.rs` — content-addressable store + GC (retain last N versions).
- `event_log.rs` — append-only jsonl с ротацией по неделям.
- `graph.rs` — только чтение `links.jsonl` с LRU (без DuckDB).
- `index.rs` — обновление `INDEX.json`, поиск через ripgrep.
- `schema.rs` — JSON Schema validation.
- `decay.rs` — background sweeper.

**Зависимости (сокращённые):** `serde`, `serde_json`, `jsonschema`, `ulid`, `sha2`, `tokio`, `flock`, `rg` (опционально).

### 10.2 Phoenix context `AIM.FS`

**Изменения:** 
- Вызов Rust core через Elixir‑Port (запуск Rust binary как child_process, общение по stdin/stdout JSON). Это проще NIF и не требует сложной связанности. 
- `AIM.FS.approve/2` внутри: 
 - Сериализует запрос → JSON → Port → Rust core (с блокировкой). 
 - После успеха → `Phoenix.PubSub.broadcast(AIM.PubSub, "inbox", {:approved, proposal_id})`. 
 - Если ошибка (lock timeout, невалидный schema) → возврат `{:error, reason}`. 
- LiveView `AIMWeb.InboxLive` — без изменений.

### 10.3 Миграция существующих данных

*(без изменений)*

---

## 11. Преимущества над Claude (сводная таблица)

| Lim. | Claude | AIM_FS (v2) | Как |
|------|--------|-------------|-----|
| L1 | Index ручной, грузится весь | Sharded, lazy | `_service/INDEX.json` + per-shard файлы |
| L2 | Нет графа | Типизированный граф | `links.jsonl` per entity, LRU‑кэш |
| L3 | Нет версий | CAS + GC | `_service/cas/sha256/..` + `retain_versions` |
| L4 | Скан имён файлов | Shard‑scan + ripgrep (MVP); Tantivy+HNSW (phase 5) | MVP: full scan, позже hybrid |
| L5 | Auto-save | Approval queue с таймаутами и блокировками | inbox + lock + auto_expire |
| L6 | Verify-on-use | TTL + decay sweeper | `decay.ttl_days` + background |
| L7 | Только session_id | Полный provenance | `created_by` + `events.jsonl` |
| L8 | Глобальный namespace | Scoping | `scope.{global,user,project,patient}` |
| L9 | Нет схем | JSON Schema registry | `_schemas/*.json`, валидация при write |
| L10 | Дубли молча | Conflict log с таймаутом | `_service/disputes/` + blocked proposals |
| L11 | Single-user | Multi-tenant с шифрованием | `users/<id>/` + `_org/<id>/` + at‑rest encryption |
| L12 | Тяжёлый индекс в контексте | Lazy shards | загружаем по запросу |
| L13 | Нет audit-trail | Event log + replay | `events.jsonl` + `replay(until)` |
| L14 | CLI only | Schema-driven UI | LiveView, поля авто из JSON Schema |
| L15 | Не atomic | Atomic transactions + lock | prepare/commit через tmp + flock |

> **v2:** закрыты дыры по L4 (описан MVP), L5 (таймауты, lock), L10 (таймаут), L11 (шифрование), L14 (уточнено), L15 (доказано атомарностью).

---

## 12. Открытые вопросы (для peer review)

1. **CAS — git vs custom:** оставлен custom CAS с GC для простоты интеграции с approval flow.
2. **DuckDB vs SQLite:** отложено; на MVP граф читается из links.jsonl.
3. **Embeddings — local vs API:** отложено до phase 5; локальный fallback на API.
4. **Авто-confidence для user_facts:** вычисляется как `confidence = heuristic(rarity, repetition, user_explicitness)` с возможностью LLM‑оценки при необходимости.
5. **TTL значений:** type‑specific (feedback ∞, project 30, deadline 7, proposal 7). Задаётся в schema.
6. **Retention для rejected proposals:** хранятся 30 дней, затем архивируются. Используются для обучения decay‑sweeper.
7. **Multi-tenant encryption:** per‑user key, storage‑level. Более детально в security review.
8. **Формат identity:** YAML (единообразие).
9. **Партиционирование больших проектов:** для пациентов с >500 визитов — шардирование по месяцам (секция 3.a).
10. **Concurrent writes:** flock + prepare/commit (секция 4.2).

---

## 13. План реализации (пересмотренный)

**Phase 1 (3‑4 дня):** Rust core (`aim_fs`) 
- атомарные write/read с lock и prepare/commit 
- frontmatter YAML, ULID, SHA256 
- propose/approve/reject API с атомарностью 
- events.jsonl append 
- basic search (grep по шардам) 
- CAS + retention (хранить 3 версии) 

**Phase 2 (2 дня):** JSON Schemas (7 базовых типов: `feedback_v1`, `fact_v1`, `recipe_v1`, `proposal_v1`, `project_v1`, `patient_v1`, `user_profile_v1`). 

**Phase 3 (2 дня):** Phoenix контекст `AIM.FS` через Elixir‑Port + LiveView Inbox (pending, approve, reject, defer). 

**Phase 4 (1 день):** Sharded INDEX.json + lazy loading; миграция legacy. 

**Phase 5 (2 дня):** Conflict resolution UI, таймауты, auto‑approve preferences, decay sweeper. 

**Phase 6 (1 день):** Метрики и тесты: 
- p95 latency approve < 500 ms 
- throughput events > 100 events/s 
- inbox pending count < 50 
- `make test` с 10 параллельными propose/approve/reject, проверка отсутствия дублей и согласованности.

**Phase 7 (continuous):** Tantivy + HNSW (опционально), DuckDB (при необходимости), полировка.

---

**Metrics (SMART):** 
- Approve latency (p95) < 500 ms при 100 concurrent users. 
- Event throughput > 100 ops/s. 
- Index recovery time после сбоя < 1 s (replay последнего коммита). 
- Inbox pending count для типичного врача < 50.

---

**Конец draft v2. Исправлен по peer review от 2026-05-09.**