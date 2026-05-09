```markdown
# AIM Filesystem Specification (AIM_FS) — v5 (исправлен по peer review)

Дата: 2026-05-18 
Статус: DRAFT v5 — исправлен по peer review от 2026-05-14 

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
├── identity.yaml # мутируется через защищённый proposal — см. workflow ниже
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

> **Изменение v5:** 
> `identity.yaml` — мутируется только через защищённый proposal (не immutable, но защищён от случайных изменений). 
> `_meta.jsonl` параллельно `facts/`. 
> AI не пишет напрямую в `facts/` — все новые факты идут в **inbox**. 

<!-- review_response: формулировка "mutated via protected proposal" уточнена. -->

**Workflow для identity.yaml:** 
- `identity.yaml` может быть обновлён через proposal типа `change_identity`. 
- Proposal создаётся AIM или пользователем, проходит стандартный approval (inbox). 
- После утверждения старый `identity.yaml` архивируется в `_service/cas` (как версия), новый записывается атомарно. 
- Для большинства пользователей это редкое событие, поэтому «immutable» подразумевает защиту от случайных изменений, не от намеренных.

### Уровень 2 — User-defined projects

**Корень:** `<aim_root>/users/<user_id>/projects/<project_slug>/`

**Минимальный набор ядра** (для MVP): 
`CONCEPT.md`, `STATE.md`, `TODO.md`, `README.md`.

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
 ├── links.jsonl # <-- полный путь _meta/links.jsonl
 └── events.jsonl # <-- полный путь _meta/events.jsonl
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
├── idempotency/ # log idempotency ключей (см. раздел 10.1)
├── shards/ # per‑scope шарды (см. раздел 5.1)
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
 source: "user_message" | "user_command"
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
 on_dep_expire: "deprecate" | "keep" # поведение при истечении зависимости – см. раздел 7
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

> **v5:** 
> - Поле `source` расширено: `"user_message"` — любое сообщение, `"user_command"` — явная команда. 
> - Добавлено поле `confidence` для AI-извлечённых фактов. 
> - Добавлено поле `on_dep_expire` для каскадного decay. 
> - В примере указан source `"user_command"` для ясности. 
> - Поле `scope.project_ids` может принимать значение `"*"` для обозначения всех проектов пользователя (см. раздел 5.1). 

<!-- review_response: исправление опечатки принято; добавлен wildcard для scope. -->

### 3.2 Schema registry

**Валидация при записи:** 
- Любая новая запись (proposal, факт, feedback) проверяется на соответствие JSON Schema, указанной в `schema`. 
- Если схема не найдена в `_schemas/` → proposal отклоняется с ошибкой `schema_not_found`. 
- Если данные не проходят валидацию → proposal получает статус `invalid` и не попадает в inbox (возвращается автору с описанием ошибки). 
- Валидация выполняется на этапе prepare (до commit) в Rust core (`schema.rs`).

**Обязательные поля для базовых схем (`_schemas/feedback_v1.json`, `_schemas/fact_v1.json`, `_schemas/proposal_v1.json` и т.д.):** 
- `id`, `schema`, `created_at`, `created_by`, `status`, `scope`, `links`. 
- Остальные поля (confidence, decay, tags) опциональны. 
- Каждая схема определяет свой набор обязательных полей (например, для `proposal_v1` обязательно `target_id` и `change_description`).

### 3.3 Content-addressable storage (CAS)

Каждая версия файла копируется в `<aim_root>/_service/cas/sha256/ab/cd/abcdef…`. 
**Retention policy:** 
- По умолчанию хранятся последние `retain_versions` версий (согласно `schema.*.json` — default=3). 
- Старые версии автоматически архивируются (tar.zst) при превышении лимита; запись об архиве в `_service/cas/manifest.json`. 
- Политика может быть переопределена per-schema. 
- Для `identity.yaml` версии хранятся в CAS независимо (retain_versions = ∞). 
- **GC‑sweeper:** фоновый процесс (`cas_gc.rs`), запускается раз в сутки, сканирует `_service/cas/` и архивирует/удаляет версии, превышающие лимит. При старте Rust core очищаются orphan tmp-файлы старше 1 часа. 

<!-- review_response: добавлен GC‑sweeper и cleanup orphan tmp. -->

### 3.4 Event log

Event log — append-only `.jsonl` файлы, шардированные по неделям (`_service/events/2026-W19.jsonl`). 
**Блокировка:** каждый шард event log защищается per-shard блокировкой (`.lock` в корне шарда) при записи. 
Чтение не блокируется (используется репликация через rename). 

<!-- review_response: добавлена блокировка для concurrent write. -->

---

## 4. Approval queue (главное отличие от Claude)

**Принцип:** AIM никогда не сохраняет ничего автоматически в Tier 1/2/3 без явного approval, **кроме**:

1. Tier 3.a: данные _текущего_ visit пациента (intake, CBC, differential) — **observational data** (фактические измерения, жалобы, анамнез). 
 *AI-inferred выводы (диагнозы, рецепты) — только через inbox.* 
 Все PII‑данные шифруются at-rest согласно consent.
2. Tier 3.b: служебные индексы, бэкапы, события — system.
3. Tier 1: при `created_by.source == "user_command"` (пользователь напрямую сказал «запомни X») — auto-approve.

### 4.1 Inbox UI (Phoenix LiveView)

*(без изменений описания UI)*

**Добавлено в v5:** 
- Каждый pending элемент имеет поле `auto_expire_at` (по умолчанию через 7 дней, настраивается per-user в `preferences.md`). 
- **Offline-режим:** per-user preference `max_inactivity_days` (по умолчанию 30). Если пользователь не заходил в систему дольше этого срока, `auto_expire_at` не срабатывает — proposal остаётся pending до возвращения пользователя. При возвращении таймер возобновляется с оставшимся временем. 
- **Абсолютный лимит:** параметр `max_absolute_pending_days` (по умолчанию 90). Если proposal pending дольше этого срока (даже при offline), он автоматически переводится в статус `expired` и перемещается в `_service/inbox/expired/`. Это предотвращает вечное ожидание. 
- Кроме того, если пользователь не принял решение до `auto_expire_at`, при отсутствии offline-режима — статус `expired`. 
- Defer: возвращается в pending с увеличенным `auto_expire_at` (ещё 7 дней). 
- При offline-режиме пользователя перед expiry (как обычным, так и абсолютным) AIM отправляет уведомление (Telegram/email), если настроено в preferences. 
- Источник `"user_command"` (прямая команда) автоматически помечается как `auto_approve` и не требует показа в inbox, но событие фиксируется в event log. 
- В схеме `preferences.md` добавлен default `max_inactivity_days: 30, max_absolute_pending_days: 90`. 

<!-- review_response: абсолютный лимит добавлен, default уточнён. -->

### 4.2 Блокировочный протокол для concurrent access

**Per-entity lock (вместо глобального):** 
- Для каждой мутирующей операции блокируется файл `.lock` в корне соответствующей сущности (например, `_service/inbox/.lock` для операций с предложениями, `_service/cas/.lock` для CAS, `profile/facts/.lock` для фактов). 
- Для event log — per-shard блокировка (`_service/events/2026-W19.lock`). 
- Операции, затрагивающие несколько сущностей (например, разрешение конфликта между двумя фактами), захватывают оба lock в порядке возрастания ID (deadlock prevention). 
- Глобальная блокировка (`_service/.lock`) используется только для операций, которые модифицируют несколько scope (например, межпользовательский dispute). 
- Захват блокировки через `flock`; при недоступности — экспоненциальный backoff (50ms, 100ms, 200ms), затем ошибка. 
- **Batch-операции** (например, reject all): захватывают locks всех затронутых сущностей в едином глобальном порядке (сначала все locks типа inbox, затем cas, затем events и т.д., внутри каждого типа — по возрастанию ID), выполняя одну транзакцию (prepare/commit). Если какой-либо lock не получен, вся операция откатывается. 
- **Предупреждение:** `flock` может не работать на NFS/FUSE. В production рекомендуется использовать SQLite (WAL) для всех метаданных (блокировка, events, index). В MVP flock допустим на локальных файловых системах. В будущем планируется переход на SQLite-бэкенд (Phase 6). 

<!-- review_response: добавлен экспоненциальный backoff и оговорка про NFS (CRITICAL 5). -->

**Атомарный коммит изменений:** 
1. Все файлы (move, events, index) готовятся во временной директории `_service/tmp/<commit_id>/`. 
2. Финальный шаг — `rename` временной директории на целевую (`rename` атомарен на одной файловой системе). 
3. Если rename удался → commit; если нет → rollback (удалить tmp). 
4. Запись в events.jsonl происходит до rename (во временной папке), так что потеря невозможна.

**Дополнительно для INDEX:** 
- Обновление шарда INDEX происходит под блокировкой этого шарда (например, `_service/shards/<shard_id>.lock`). 
- Если два concurrent approve затрагивают один шард, второй ждёт освобождения блокировки и перечитывает актуальное состояние шарда перед модификацией. 
- После обновления шарда записывается его SHA256-хеш в `_service/shards/manifest.json`. При загрузке проверяется; если хеш не совпадает, шард перестраивается из event log. 

**Единый порядок захвата блокировок для deadlock prevention:** 
Все операции (approve, reject, decay sweeper, conflict resolution, undo) захватывают locks в едином глобальном порядке: 
1. Тип сущности (алфавитный порядок: "cas", "events", "facts", "inbox", "profile", "projects", "shards", "tmp"). 
2. Внутри типа — по возрастанию ID сущности (для шардов — по имени шарда, для inbox — по proposal ID). 
Это гарантирует отсутствие deadlock между sweeper и approve (CRITICAL 1). 

<!-- review_response: введён единый порядок захвата lock, закрывающий deadlock между sweeper и approve. -->

### 4.3 Auto-approve правила (опционально, per-user)

```yaml
# auto-approve rules → YAML для единообразия с frontmatter
approval:
 auto_approve_user_facts_with_confidence_above: 0.95
 auto_approve_service_events: true
 auto_approve_patient_intake_data: true
 require_approval_for: ["feedback", "proposal", "recipe", "diagnosis"]
 max_inactivity_days: 30 # override таймаута при offline
 max_absolute_pending_days: 90
 undo_window_hours: 24 # время, в течение которого пользователь может откатить auto-approved запись
```

**Confidence heuristic:** 
```
confidence = sigmoid(repetition_count / threshold + user_match_score)
```
где `repetition_count` – сколько раз пользователь повторил факт, `threshold` (настраиваемый, по умолч. 3), `user_match_score` — оценка совпадения с известными паттернами пользователя (0–0.5). 

**Undo-механизм:** 
- Любая запись, попавшая в active через auto-approve, может быть отменена пользователем в течение `undo_window_hours` (по умолчанию 24 часа). 
- Отмена создаёт запись `superseded` с теми же данными и ссылкой `reverts: [<original_id>]`. 
- Исходная запись получает статус `superseded`. 
- **Каскад:** если отменяемая запись имеет исходящие ссылки `depends_on` (на неё ссылаются другие записи), undo не разрешается напрямую. Вместо этого пользователь предупреждается, что потребуется каскадное superseding всех зависимых записей (которые также будут отменены). Если пользователь подтверждает, выполняется каскад (с блокировками в порядке возрастания ID). Если есть циклы — операция отклоняется. 
- Если отмена происходит после `undo_window_hours`, она обрабатывается как обычный proposal (через inbox). 

<!-- review_response: добавлен каскад для undo (CRITICAL 4). -->

---

## 5. Индексирование и поиск

### 5.1 Sharded index (ленивая загрузка)

`_service/INDEX.json` — содержит список шардов:
```json
[
 {"shard_id": "users_djabbat", "path": "_service/shards/users_djabbat.json", "hash": "sha256:.."},
 {"shard_id": "org_acme", "path": "_service/shards/org_acme.json", "hash": "sha256:.."}
]
```

Каждый шард загружается в память только при запросе, затрагивающем его scope. 
**Глобальные запросы** (без указания scope) ограничены полями frontmatter (id, schema, status, tags, scope). Для них строится агрегатный индекс `_service/global_frontmatter_index.json` (хеш-таблицы по полям). Полнотекстовый поиск по телу для глобального scope не поддерживается; при попытке выполнить такой запрос UI показывает сообщение: «Полнотекстовый поиск по содержанию доступен только в рамках указанного scope (проект, пациент, профиль). Укажите scope для поиска». 

**Поддержка wildcard scope:** Если пользователь указывает `scope: { project_ids: "*" }`, это означает все проекты данного пользователя. Индекс хранит отдельный агрегат `global_user_projects_index`, который при запросе загружает все шарды проектов пользователя и позволяет выполнять полнотекстовый поиск по их содержимому. Этот агрегат перестраивается лениво при первом таком запросе и кэшируется. 

<!-- review_response: уточнено ограничение глобального поиска (CRITICAL 8). -->

### 5.2 Поиск в MVP

На первом этапе (до внедрения Tantivy + HNSW) поиск реализован как **in-memory мульти-мап для frontmatter** + **full scan body**:

- **Frontmatter:** при загрузке шарда в память строятся хеш-таблицы `HashMap<field_value, list_of_ids>` для ключевых полей (title, tags, status, scope и т.д.). 
- **Body:** для полнотекстового поиска по содержимому используется итерация по записям шарда с фильтром (собственный grep на Rust; может быть заменён вызовом `ripgrep` через `Command` при необходимости). 
- Размер типового шарда < 1 MB, поэтому full scan одного шарда быстрее вызова внешнего `rg`. 
- Для 10⁵ записей (~50 MB) total scan может занимать до 200–300 ms, что приемлемо для MVP (p95 approve latency не страдает, т.к. поиск вызывается только при proposal или request). 
- Если latency станет проблемой — переходим к Phase 5 (Tantivy + HNSW).

### 5.3 Auto-update triggers (с блокировкой шарда)

Любое событие из `_service/events/` → немедленное обновление соответствующего шарда в `INDEX.json` (incremental, без перестроения всех шардов). 
**Атомарность:** обновление шарда происходит под блокировкой `.lock` этого шарда (per-shard lock). Перед модификацией читается актуальная версия шарда, вносятся изменения, записывается временный файл и rename. 
После обновления вычисляется SHA256 шарда и обновляется `manifest.json`. 
При загрузке шарда сверяется хеш; если не совпадает, шард перестраивается из event log за соответствующий период.

---

## 6. Граф связей

**Решение для MVP (v5, упрощённое по сравнению с v4):** 
- Рёбра хранятся только в `links.jsonl` (per entity). 
- Глобальный граф не материализуется отдельно. 
- Для запросов «найти все feedback, применимые к проекту X» читаем links.jsonl всех релевантных шардов и строим ответ в памяти с LRU‑кешем. 

**Обнаружение конфликтов на этапе propose (v5):** 
- При создании proposal выполняется full scan `links.jsonl` целевого шарда (ожидаемое время <5ms для шарда ~1MB). Проверяется наличие `contradicts` ссылок на новую запись. 
- Материализованный contradicts index **исключён из MVP** для упрощения архитектуры и избежания проблем восстановления после сбоя. Если производительность full scan станет проблемой (например, при 10⁶ записей в одном шарде), он будет добавлен в Phase 5. 

<!-- review_response: materialized contradicts index заменён на full scan links.jsonl (CRITICAL 6). -->

---

## 7. Decay / staleness

**Поле `decay` в frontmatter** (см. 3.1):
```yaml
decay:
 ttl_days: 90 | null
 expires_at: "2026-08-06T02:00:00Z"
 on_dep_expire: "deprecate" | "keep" # поведение при истечении зависимости
```

**Фоновый sweeper (`decay.rs`):**
- Проходит по всем сущностям с `decay.ttl_days != null` и проверяет `expires_at`. 
- Использует **per-entity lock** (`.lock` в корневой папке сущности) перед изменением статуса. 
- **Порядок захвата локов:** единый глобальный порядок (как в разделе 4.2). Sweeper обрабатывает сущности последовательно, захватывая lock только для одной сущности за раз, что исключает deadlock с concurrent approve. 
- Не может выполняться одновременно с approve/reject на той же сущности (блокировка). 

**Каскадный decay:** 
- Для каждого факта A, у которого в `links.depends_on` указан факт B, sweeper проверяет статус B. 
- Если B стал `deprecated` или `expired`, sweeper применяет правило `on_dep_expire`:
 - `"deprecate"`: A получает статус `deprecated`, запись в events.jsonl, создаётся или обновляется dispute (если есть противоречие). 
 - `"keep"`: A остаётся `active`, но в `_meta/events.jsonl` фиксируется, что зависимость истекла. 
- По умолчанию для фактов без `on_dep_expire` используется `"deprecate"`. 
- **Ограничение глубины каскада:** обход выполняется не более чем на 3 уровня (параметр `max_decay_depth`, настраиваемый в конфигурации, по умолчанию 3). Для более глубоких цепочек (если после 3 уровней остаются необработанные зависимые записи) они не трогаются, а в event log заносится предупреждение. Это предотвращает O(n²) обход и сохраняет производительность. 
- Рекурсия реализована через топологическую сортировку подграфа зависимостей глубиной до `max_decay_depth`. Циклы обнаруживаются. 
- **При обнаружении цикла** (в графе зависимостей не удаётся построить топологический порядок из-за цикла) все записи, участвующие в цикле, получают статус `deprecated`, так как невозможно определить порядок устаревания. В event log фиксируется цикл и принятое решение. 

<!-- review_response: добавлено ограничение глубины и обработка циклов (CRITICAL 7). -->

**Decay для обновлённых фактов:** 
- Если факт был обновлён (новая версия), его TTL обнуляется и `expires_at` пересчитывается от даты новой версии. 
- Старая версия в CAS сохраняет свой исходный `expires_at` (но не активна). 

**Восстановление contradicts index после сбоя (v5):** 
- В MVP contradicts index не материализован, поэтому проблема восстановления неактуальна. При добавлении в Phase 5 будет реализована процедура `reconstruct_contradicts`, перестраивающая индекс из всех `links.jsonl` при старте Rust core. 

---

## 8. Conflict / dispute resolution

**Процесс:** 
1. Новая запись помечается `contradicts` и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, diff, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Таймаут (настраиваемый параметр `dispute_timeout_days` в конфиге, по умолчанию 7 дней):** 
 - Если решение не принято за `dispute_timeout_days`, dispute автоматически получает статус `resolved_unresolved`. 
 - **Поведение при таймауте:** 
 - Если в конфликте 2 записи: запись с более высоким `confidence` остаётся `active`, другая — `superseded`. При равенстве `confidence` — более старая (по `created_at`) остаётся `active`. 
 - Если в конфликте >2 записей: выбирается запись с наивысшим `confidence`; при равенстве — самая старая. Все остальные получают статус `superseded`. 
 - Ни одна запись не остаётся в неконсистентном состоянии (обе `active`). 
 - В event log фиксируется факт таймаута и принятое автоматическое решение. 
6. После выбора пользователем победитель становится `active`, проигравший `superseded`, dispute `resolved`. Proposal (если есть) автоматически approved или rejected в зависимости от выбора (если был блокирован — разблокируется). 
7. **Конфликты с участием >2 записей:** создаётся один dispute со списком всех противоречащих ID. Интерфейс позволяет выбирать один из вариантов или комбинировать. При таймауте применяется правило выше (CRITICAL 3). 

<!-- review_response: при таймауте для N>2 определён алгоритм выбора, неконсистентность устранена (CRITICAL 3). -->

---

## 9. Multi-tenant

**Namespace:** `users/<user_id>/`. 
**Организации:** `_org/<org_id>/`.

**Изоляция и шифрование:** 
- PII пациентов шифруется at-rest с per-user ключом (storage-level encryption). 
- Механизм управления ключами: ключи хранятся в `users/<user_id>/.key.enc` (зашифрованы мастер-ключом приложения). 
- **Мастер-ключ** хранится в HSM/Vault. При компрометации мастер-ключа все per-user ключи могут быть расшифрованы. 
- **Key rotation:** 
 - Мастер-ключ может быть сменён; старый мастер-ключ остаётся доступен только для дешифровки существующих `.key.enc` до момента их перешифровки. 
 - Перешифровка всех `.key.enc` новым мастер-ключом выполняется как batch background job (с захватом глобального лока `_service/.lock`). 
 - Окно уязвимости отсутствует: старый мастер-ключ удаляется только после успешного завершения перешифровки. 
 - При необходимости принудительной ротации per-user ключей (например, утечка) запускается отдельная процедура перегенерации. 
- **Revocation:** при отзыве доступа пользователя его per-user ключ удаляется из хранилища; все его данные становятся недоступны (невозможно расшифровать). Сами зашифрованные данные остаются на диске. 
- **Очистка кэша при revocation:** Rust core после отзыва ключа сбрасывает in-memory кэш расшифрованных данных для этого пользователя (если используется кэш). 
- Audit-log доступа к ключам: каждый доступ к `.key.enc` фиксируется в `_service/events/` с указанием agent и timestamp. 
- Доступ к данным другого пользователя — только при явном `shared_with` в `links.jsonl` и проверке авторизации в Phoenix (JWT с claim `user_id` и `org_id`). 
- Организационные данные (`_org/`) видны всем пользователям организации. 
- **Side-channel утечка через временные файлы:** `_service/tmp/` очищается после commit; права доступа к tmp-файлам устанавливаются 600. 

<!-- review_response: упомянута очистка кэша при revocation. -->

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** — с дополнением: все мутирующие операции (`propose`, `approve`, `reject`, `undo`, `resolve_dispute`) принимают опциональный `idempotency_key` (UUID v4). Если ключ передан и операция уже была выполнена (ключ найден в логе idempotency), возвращается предыдущий результат без повторного выполнения. Если ключ не передан, операция выполняется как обычно (без идемпотентности). 

**Idempotency с защитой in-flight:** 
- При первом запросе с idempotency_key записывается `{"status": "processing", "started_at": timestamp}` в `_service/idempotency/<key>.json`. 
- Если повторный запрос с тем же ключом находит "processing", возвращается `"status": "retry_later"` (клиент должен повторить с экспоненциальным backoff). 
- После завершения операции запись обновляется на `{"status": "done", "result":..}`. 
- Таймаут на "processing" — 30 секунд (конфигурируемо). Если операция не завершилась за это время, запись удаляется (как зависшая), и следующий запрос может начать заново. 

<!-- review_response: добавлено состояние "processing" (CRITICAL 2). -->

**Внутренние модули:**
- `atomic.rs` — write-then-rename с prepare/commit через tmp, per-entity flock на `.lock` в корне сущности (с фоллбэком на O_EXCL-advise для NFS, если flock недоступен). 
- `idempotency.rs` — хранение idempotency_key → результат в `_service/idempotency/` (с TTL 7 дней, затем архивация). 
- `cas.rs` — content-addressable store + GC (retain last N версий) + фоновый sweeper. 
- `event_log.rs` — append-only jsonl с ротацией по неделям и per-shard блокировкой. 
- `graph.rs` — только чтение `links.jsonl` с LRU; обнаружение конфликтов через full scan links.jsonl. 
- `index.rs` — обновление `INDEX.json` с per-shard блокировкой, поиск через in-memory мульти-мап. 
- `schema.rs` — JSON Schema validation (reject proposal при невалидности). 
- `decay.rs` — background sweeper с per-entity lock, единым порядком захвата, каскадным обходом (топологическая сортировка, ограничение глубины 3, обработка циклов). 
- `conflict.rs` — создание dispute, разрешение, таймауты (алгоритм выбора для N записей). 
- `gc.rs` — очистка CAS, tmp-файлов, старых idempotency записей. 
- `migration.rs` — дедупликация legacy данных. 

**Зависимости (сокращённые):** `serde`, `serde_json`, `jsonschema`, `ulid` (для генерации ID), `uuid` (для idempotency_key), `sha2`, `tokio`, `flock` (через `fs2`), `regex` (для body search).

### 10.2 Phoenix context `AIM.FS`

**Изменения:** 
- Вызов Rust core через Elixir‑Port (запуск Rust binary как child_process, общение по stdin/stdout JSON). 
- **Идемпотентность:** Phoenix генерирует `idempotency_key` (UUID v4) для каждого запроса к Port. При сетевой ошибке или таймауте клиент повторяет запрос с тем же ключом; Rust возвращает ранее сохранённый результат, если операция уже выполнена. 
- **Fault-tolerance:** при падении Rust-процесса orphan locks не возникает, т.к. flock автоматически снимается при закрытии всех fd ядром. Потеря сообщения обрабатывается через idempotency: если запрос не дошёл, клиент повторяет; если результат не был отправлен, повтор с тем же ключом вернёт `"status": "processing"` (если операция ещё не завершилась), либо результат после завершения. 
- `AIM.FS.approve/2` внутри: 
 - Генерирует `idempotency_key`. 
 - Сериализует запрос → JSON → Port → Rust core (с блокировкой per-entity). 
 - После успеха → `Phoenix.PubSub.broadcast(AIM.PubSub, "inbox", {:approved, proposal_id})`. 
 - Если ошибка (lock timeout, невалидный schema) → возврат `{:error, reason}`. 
- Heartbeat между Rust и Phoenix: Rust процесс отправляет каждые 5 секунд `{"type":"ping"}`; Phoenix ожидает пинг; если три пинга пропущены — перезапуск child-процесса. 

<!-- review_response: добавлен watchdog для Rust (MINOR). -->

- LiveView `AIMWeb.InboxLive` — без изменений. 

**Пример schema-driven UI (для доказательства L14):** 
Схема `_schemas/feedback_v1.json`:
```json
{
 "type": "object",
 "properties": {
 "title": {"type": "string"},
 "description": {"type": "string"},
 "tags": {"type": "array", "items": {"type": "string"}},
 "confidence": {"type": "number", "minimum": 0, "maximum": 1}
 },
 "required": ["title", "description"]
}
```
На её основе Phoenix LiveView автоматически генерирует форму с полями `title` (text), `description` (textarea), `tags` (multi-select), `confidence` (slider). Валидация на стороне клиента и сервера использует ту же схему. 
Этот подход будет применён ко всем типам записей в phase 3 (см. план реализации).

### 10.3 Миграция существующих данных

**Детали (v5):** 
- Legacy проекты (если есть) переносятся в `users/<user_id>/projects/legacy_<slug>/`. 
- Для каждого файла генерируется frontmatter на основе метаданных (дата, автор, теги). 
- **Дедупликация:** перед миграцией вычисляется SHA-256 содержимого каждого файла; дубликаты (одинаковый SHA и одинаковая схема и одинаковый scope) объединяются в одну запись с версиями. 
 - **Стратегия слияния frontmatter:** 
 - `tags`: union всех тегов. 
 - `links`: union всех ссылок; при дублировании берётся последняя версия (по created_at). 
 - `decay`: берётся самое позднее `expires_at` (максимальный TTL). 
 - `scope`: если различается, создаётся отдельная запись (разные scope считаются разными записями). 
 - Все остальные поля (confidence, status) — от самой последней версии. 
 - Если файлы имеют разные значения обязательных полей (например, разные `title`), они не объединяются, а создаются как отдельные записи со связью `supersedes` (на усмотрение пользователя). 
- Создаются `_meta/links.jsonl` и `_meta/events.jsonl` с минимальными записями (created). 
- После миграции legacy проекты помечаются status `legacy` и не участвуют в decay/conflict resolution автоматически. 
- Миграция запускается одноразово при первом старте с флагом `--migrate`. 

<!-- review_response: дедупликация с уточнённой стратегией слияния (CRITICAL 9). -->

---

## 11. Преимущества над Claude (сводная таблица)

| Lim. | Claude | AIM_FS (v5) | Как |
|------|--------|-------------|-----|
| L1 | Index ручной, грузится весь | Sharded, lazy | `_service/INDEX.json` + per-shard файлы |
| L2 | Нет графа | Типизированный граф (links.jsonl + full scan для detection) | `links.jsonl` per entity, LRU‑кэш |
| L3 | Нет версий | CAS + GC | `_service/cas/sha256/..` + `retain_versions` |
| L4 | Гибридный поиск (Tantivy?) | MVP: in-memory frontmatter + full scan; Phase 5: Tantivy+HNSW | MVP уступает по скорости (нет полнотекстового глобального поиска), но превосходит по гибкости (любые поля frontmatter). Phase 5 превосходит по всем параметрам. |
| L5 | Auto-save | Approval queue с таймаутами и блокировками | inbox + lock + auto_expire + offline handling + абсолютный лимит |
| L6 | Verify-on-use | TTL + decay sweeper + каскадный decay (топологическая сортировка, макс. глубина 3, обработка циклов) | `decay.ttl_days` + background |
| L7 | Только session_id | Полный provenance | `created_by` + `events.jsonl` |
| L8 | Глобальный namespace | Scoping (включая wildcard `*`) | `scope.{global,user,project,patient}` |
| L9 | Нет схем | JSON Schema registry | `_schemas/*.json`, валидация при write |
| L10 | Дубли молча | Conflict log с таймаутом, авто-выбор при таймауте (для N≥2), поддержка >2 записей | `_service/disputes/` + blocked proposals + superseded при таймауте |
| L11 | Single-user | Multi-tenant с шифрованием, key rotation, revocation, audit, очистка кэша | `users/<id>/` + `_org/<id>/` + per-user key + HSM |
| L12 | Тяжёлый индекс в контексте | Lazy shards (выигрыш в памяти ~10x) | загружаем по запросу, p95 < 100ms |
| L13 | Нет audit-trail | Event log + replay + checksum recovery | `events.jsonl` + `replay(until)` |
| L14 | CLI only | Schema-driven UI (LiveView, поля авто из JSON Schema) | Пример: feedback_v1 → форма (раздел 10.2) |
| L15 | Не atomic | Atomic transactions + per-entity lock + batch + idempotency (с защитой in-flight) | prepare/commit через tmp + per-entity flock + idempotency key |

> **v5 (изменения по сравнению с peer review):** 
> - L2: materialized index убран, DuckDB отложен. 
> - L4: уточнено ограничение глобального поиска. 
> - L5: абсолютный лимит pending, offline-режим. 
> - L6: ограничена глубина каскадного decay (3), обработка циклов. 
> - L10: при таймауте для N≥2 определён алгоритм. 
> - L15: добавлена идемпотентность с защитой in-flight. 
> - L14: добавлен пример генерации формы из JSON Schema. 

---

## 12. Открытые вопросы (для peer review)

1. **CAS — git vs custom:** оставлен custom CAS с GC для простоты интеграции с approval flow. *(RESOLVED)* 
2. **DuckDB vs SQLite:** отложено; на MVP граф читается из links.jsonl без materialized индекса. *(RESOLVED)* 
3. **Embeddings — local vs API:** отложено до phase 5; локальный fallback на API. *(RESOLVED)* 
4. **Авто-confidence для user_facts:** вычисляется как `confidence = sigmoid(repetition_count / threshold + user_match_score)`. *(RESOLVED)* 
5. **TTL значений:** type‑specific (feedback ∞, project 30, deadline 7, proposal 7). Задаётся в schema. *(RESOLVED)* 
6. **Retention для rejected proposals:** хранятся 30 дней, затем архивируются. *(RESOLVED)* 
7. **Multi-tenant encryption:** per‑user key, storage‑level. Key rotation и revocation описаны в разделе 9. *(RESOLVED)* 
8. **Формат identity:** YAML (единообразие). *(RESOLVED)* 
9. **Партиционирование больших проектов:** для пациентов с >500 визитов — шардирование по месяцам (секция 3.a). *(RESOLVED)* 
10. **Concurrent writes:** per-entity lock + prepare/commit + единый порядок захвата (секция 4.2). *(RESOLVED)* 
11. **Каскадный decay:** топологическая сортировка с ограничением глубины и обработкой циклов (секция 7). *(RESOLVED)* 
12. **Поиск MVP:** in-memory мульти-мап для frontmatter (раздел 5.2). *(RESOLVED)* 
13. **Confidence heuristic:** формула sigmoid выше (пункт 4). *(RESOLVED)* 
14. **Глобальные запросы:** ограничены frontmatter; wildcard `*` разрешает полнотекстовый поиск по всем проектам (раздел 5.1). *(RESOLVED)* 
15. **Undo-механизм для auto-approve:** окно отмены 24 часа с каскадом (раздел 4.3). *(RESOLVED)* 

**Новые открытые вопросы:** 
- Оптимизация full scan links.jsonl для очень больших шардов (возможный переход на материализованный индекс в Phase 5). 
- Интеграция с Vault/HSM для мастер-ключа — детали реализации deferred до Phase 5. 
- Возможный переход на SQLite (WAL) для всех метаданных в Phase 6 для решения проблем с flock на NFS.

---

## 13. План реализации (пересмотренный)

**Phase 1 (10 дней):** Rust core (`aim_fs`) 
- атомарные write/read с per-entity lock (flock + O_EXCL fallback) и prepare/commit 
- frontmatter YAML, ULID, SHA256 
- propose/approve/reject API с атомарностью, идемпотентностью (с защитой in-flight), batch-операции 
- events.jsonl append с per-shard блокировкой 
- in-memory frontmatter index + full-scan body search 
- CAS + retention + GC‑sweeper (ежедневный) 
- полный scan links.jsonl для обнаружения конфликтов (без материализованного индекса) 
- idempotency log с TTL 
- cleanup orphan tmp при старте 
- тесты на race conditions: 10 параллельных propose/approve/reject с проверкой консистентности 

**Phase 2 (2 дня):** JSON Schemas (7 базовых типов). 

**Phase 3 (2 дня):** Phoenix контекст `AIM.FS` через Elixir‑Port + LiveView Inbox (pending, approve, reject, defer, batch) + heartbeat. 

**Phase 4 (2 дня):** Sharded INDEX.json + lazy loading; миграция legacy с дедупликацией (по SHA, schema, scope + слияние frontmatter). 

**Phase 5 (4 дня):** Conflict resolution UI, таймауты (параметризованные), auto‑approve preferences, decay sweeper (топологическая сортировка с ограничением глубины, обнаружение циклов, обработка). 

**Phase 6 (2 дня):** Метрики и тесты: 
- p95 latency approve < 500 ms (100 concurrent users, per-entity lock, batch до 10 items) 
- throughput events > 100 events/s 
- inbox pending count < 50 
- decay sweeper latency < 200 ms на 1000 фактов 
- `make test` с 10 параллельными propose/approve/reject, проверка отсутствия дублей и согласованности. 

**Phase 7 (continuous):** Tantivy + HNSW (опционально), DuckDB (при необходимости), материализованный contradicts index, полировка. 

---

**Metrics (SMART):** 
- Approve latency (p95) < 500 ms при 100 concurrent users (per-entity lock, batch). 
- Event throughput > 100 ops/s. 
- Index recovery time после сбоя < 1 s (replay последнего коммита с проверкой checksum). 
- Inbox pending count для типичного врача < 50 (настраиваемый таймаут + абсолютный лимит). 
- Decay sweeper latency < 200 ms на 1000 фактов. 
- Conflict resolution timeout latency < 1 s (проверка таймаутов раз в минуту). 

---

**Конец draft v5. Исправлен по peer review от 2026-05-14.**
```