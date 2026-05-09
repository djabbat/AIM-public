```markdown
# AIM Filesystem Specification (AIM_FS) — v3 (fixed per peer review)

Дата: 2026-05-14 
Статус: DRAFT v3 — исправлен по peer review от 2026-05-09 

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
├── identity.yaml # изменяемый (через proposal) — см. workflow ниже
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

> **Изменение v3:** 
> `identity.yaml` — не singleton immutable, а защищённый proposal-механизмом. 
> `_meta.jsonl` параллельно `facts/`. 
> AI не пишет напрямую в `facts/` — все новые факты идут в **inbox**.

**Workflow для identity.yaml:** 
- `identity.yaml` не является полностью immutable; он может быть обновлён через специальный proposal типа `change_identity`. 
- Proposal создаётся AIM или пользователем, проходит стандартный approval (inbox). 
- После утверждения старый `identity.yaml` архивируется в `_service/cas` (как версия), новый записывается атомарно. 
- Для большинства пользователей это редкое событие, поэтому «immutable» подразумевает защиту от случайных изменений, не от намеренных.

**Ключевое отличие от Claude:** 
- `identity.yaml` — защищённый proposal-механизмом. 
- `_meta.jsonl` параллельно `facts/`. 
- AI не пишет напрямую в `facts/` — все новые факты идут в **inbox**.

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
 source: "user_message" | "user_command" | "tool_output" | "ai_inferred"
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

> **v3:** 
> - Поле `source` расширено: `"user_message"` — любое сообщение, `"user_command"` — явная команда «запомни X» (переименовано из `"user_explicit"` для ясности). 
> - Добавлено поле `confidence` для AI-извлечённых фактов. 
> - Добавлено поле `on_dep_expire` для каскадного decay. 

<!-- review_response: переименование `user_explicit` → `user_command` принято. -->

### 3.2 Schema registry

**Валидация при записи:** 
- Любая новая запись (proposal, факт, feedback) проверяется на соответствие JSON Schema, указанной в `schema`. 
- Если схема не найдена в `_schemas/` → proposal отклоняется с ошибкой `schema_not_found`. 
- Если данные не проходят валидацию → proposal получает статус `invalid` и не попадает в inbox (возвращается автору с описанием ошибки). 
- Валидация выполняется на этапе prepare (до commit) в Rust core (`schema.rs`).

**Обязательные поля для базовых схем (`_schemas/feedback_v1.json`, `_schemas/fact_v1.json`, и т.д.):** 
- `id`, `schema`, `created_at`, `created_by`, `status`, `scope`, `links`. 
- Остальные поля (confidence, decay, tags) опциональны. 
- Каждая схема определяет свой набор обязательных полей (например, для `proposal_v1` обязательно `target_id` и `change_description`). 
<!-- review_response: добавлено краткое описание обязательных полей для схем. -->

### 3.3 Content-addressable storage (CAS)

Каждая версия файла копируется в `<aim_root>/_service/cas/sha256/ab/cd/abcdef…`. 
**Retention policy:** 
- По умолчанию хранятся последние `retain_versions` версий (согласно `schema.*.json` — default=3). 
- Старые версии автоматически архивируются (tar.zst) при превышении лимита; запись об архиве в `_service/cas/manifest.json`. 
- Политика может быть переопределена per-schema. 
- Для `identity.yaml` версии хранятся в CAS независимо (retain_versions = ∞). 
<!-- review_response: уточнение для identity.yaml. -->

### 3.4 Event log

*(без изменений)*

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

**Добавлено:** 
- Каждый pending элемент имеет поле `auto_expire_at` (по умолчанию через 7 дней, настраивается per-user в `preferences.md`). 
- **Offline-режим:** per-user preference `max_inactivity_days` (по умолчанию 30). Если пользователь не заходил в систему дольше этого срока, `auto_expire_at` не срабатывает — proposal остаётся pending до возвращения пользователя. При возвращении таймер возобновляется с оставшимся временем. 
- Если пользователь не принял решение до expiry → статус `expired`, элемент перемещается в `_service/inbox/expired/`. 
- Defer: возвращается в pending с увеличенным `auto_expire_at` (ещё 7 дней). 
- При offline-режиме пользователя перед expiry AIM отправляет уведомление (Telegram/email), если настроено в preferences. 
- Источник `"user_command"` (прямая команда) автоматически помечается как `auto_approve` и не требует показа в inbox, но событие фиксируется в event log. 
<!-- review_response: добавлен параметр max_inactivity_days и продление таймаута при offline. -->

### 4.2 Блокировочный протокол для concurrent access

**Per-entity lock (вместо глобального):** 
- Для каждой мутирующей операции блокируется файл `.lock` в корне соответствующей сущности (например, `_service/inbox/.lock` для операций с предложениями, `_service/cas/.lock` для CAS, `profile/facts/.lock` для фактов). 
- Операции, затрагивающие несколько сущностей (например, разрешение конфликта между двумя фактами), захватывают оба lock в порядке возрастания ID (deadlock prevention). 
- Глобальная блокировка (`_service/.lock`) используется только для операций, которые модифицируют несколько scope (например, межпользовательский dispute). 
- Захват блокировки через `flock`; при недоступности — повтор через 50ms до 3 попыток, затем ошибка. 
- **Batch-операции** (например, reject all): захватывают locks всех затронутых сущностей в порядке возрастания ID, выполняя одну транзакцию (prepare/commit). Если какой-либо lock не получен, вся операция откатывается. 
<!-- review_response: batch-операции описаны – решает CRITICAL 1. -->

**Атомарный коммит изменений:** 
1. Все файлы (move, events, index) готовятся во временной директории `_service/tmp/<commit_id>/`. 
2. Финальный шаг — `rename` временной директории на целевую (`rename` атомарен на одной файловой системе). 
3. Если rename удался → commit; если нет → rollback (удалить tmp). 
4. Запись в `events.jsonl` происходит до rename (во временной папке), так что потеря невозможна.

**Дополнительно для INDEX:** 
- Обновление шарда INDEX происходит под блокировкой этого шарда (например, `_service/shards/<shard_id>.lock`). 
- Если два concurrent approve затрагивают один шард, второй ждёт освобождения блокировки и перечитывает актуальное состояние шарда перед модификацией. 
- После обновления шарда записывается его SHA256-хеш в `_service/shards/manifest.json`. При загрузке проверяется; если хеш не совпадает, шард перестраивается из event log. 
<!-- review_response: добавлен checksum и восстановление – решает CRITICAL 9. -->

### 4.3 Auto-approve правила (опционально, per-user)

```yaml
# auto-approve rules → YAML для единообразия с frontmatter
approval:
 auto_approve_user_facts_with_confidence_above: 0.95
 auto_approve_service_events: true
 auto_approve_patient_intake_data: true
 require_approval_for: ["feedback", "proposal", "recipe", "diagnosis"]
 max_inactivity_days: 30 # override таймаута при offline
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
- Если отмена происходит после `undo_window_hours`, она обрабатывается как обычный proposal (через inbox). 
<!-- review_response: добавлен undo-механизм – решает CRITICAL 6. -->

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
**Глобальные запросы** (без указания scope) ограничены полями frontmatter (id, schema, status, tags, scope). Для них строится агрегатный индекс `_service/global_frontmatter_index.json` (хеш-таблицы по полям). Полнотекстовый поиск по телу для глобального scope не поддерживается (требует указания scope). 
<!-- review_response: глобальные запросы ограничены frontmatter – решает CRITICAL 10. -->

### 5.2 Поиск в MVP

На первом этапе (до внедрения Tantivy + HNSW) поиск реализован как **in-memory мульти-мап для frontmatter** + **full scan body**:

- **Frontmatter:** при загрузке шарда в память строятся хеш-таблицы `HashMap<field_value, list_of_ids>` для ключевых полей (title, tags, status, scope и т.д.). 
- **Body:** для полнотекстового поиска по содержимому используется итерация по записям шарда с фильтром (собственный grep на Rust). 
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

**Решение для MVP:** 
- Рёбра хранятся только в `links.jsonl` (per entity). 
- Глобальный граф не материализуется отдельно. 
- Для запросов «найти все feedback, применимые к проекту X» читаем links.jsonl всех релевантных шардов и строим ответ в памяти с LRU‑кешем.

**Обнаружение конфликтов на этапе propose:** 
- При создании proposal (новой записи) система проверяет наличие противоречий с существующими записями через **materialized inverted index для `contradicts`** (`_service/contradicts_index.json`). 
- Индекс обновляется атомарно при каждом approve (добавляются/удаляются рёбра). 
- Если обнаружен конфликт, proposal получает статус `disputed` и создаётся dispute (раздел 8). 
- Индекс хранится в том же шарде, что и соответствующие записи, обеспечивая консистентность. 
<!-- review_response: добавлен materialized index для contradicts – решает CRITICAL 3. -->

DuckDB исключён из первого релиза (сложность не оправдана).

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
- **Порядок захвата локов:** все locks захватываются в порядке возрастания ID сущностей (как и approve/reject), чтобы избежать deadlock. 
- Не может выполняться одновременно с approve/reject на той же сущности (блокировка). 
<!-- review_response: deadlock prevention добавлен – решает CRITICAL 2. -->

**Каскадный decay:** 
- Для каждого факта A, у которого в `links.depends_on` указан факт B, sweeper проверяет статус B. 
- Если B стал `deprecated` или `expired`, sweeper применяет правило `on_dep_expire`:
 - `"deprecate"`: A получает статус `deprecated`, запись в events.jsonl, создаётся или обновляется dispute (если есть противоречие). 
 - `"keep"`: A остаётся `active`, но в `_meta/events.jsonl` фиксируется, что зависимость истекла. 
- По умолчанию для фактов без `on_dep_expire` используется `"deprecate"`. 
- Рекурсия реализована через **топологическую сортировку** графа зависимостей с обнаружением циклов (циклы не обрабатываются, `on_dep_expire` игнорируется, запись в event log). 
<!-- review_response: топологическая сортировка вместо ограничения глубины – решает CRITICAL 4. -->

**Decay для обновлённых фактов:** 
- Если факт был обновлён (новая версия), его TTL обнуляется и `expires_at` пересчитывается от даты новой версии. 
- Старая версия в CAS сохраняет свой исходный `expires_at` (но не активна). 
<!-- review_response: добавлено уточнение для обновлённых фактов. -->

---

## 8. Conflict / dispute resolution

**Процесс:** 
1. Новая запись помечается `contradicts` и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, diff, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Таймаут (настраиваемый параметр `dispute_timeout_days` в конфиге, по умолчанию 7 дней):** 
 - Если решение не принято за `dispute_timeout_days`, dispute автоматически получает статус `resolved_unresolved`. 
 - Затронутые записи **не меняют статус** – активная остаётся `active`, pending proposal переходит в `expired`. 
 - Ни одна запись не помечается `superseded` без явного действия пользователя. 
 - В event log фиксируется факт таймаута. 
6. После выбора победитель становится `active`, проигравший `superseded`, dispute `resolved`. Proposal (если есть) автоматически approved или rejected в зависимости от выбора (если был блокирован — разблокируется). 
7. **Конфликты с участием >2 записей:** создаётся один dispute со списком всех противоречащих ID. Интерфейс позволяет выбирать один из вариантов или комбинировать. 
<!-- review_response: добавлена поддержка >2 contradicting записей – решает CRITICAL 1 (дыра 1). -->

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
- Audit-log доступа к ключам: каждый доступ к `.key.enc` фиксируется в `_service/events/` с указанием agent и timestamp. 
- Доступ к данным другого пользователя — только при явном `shared_with` в `links.jsonl` и проверке авторизации в Phoenix (JWT с claim `user_id` и `org_id`). 
- Организационные данные (`_org/`) видны всем пользователям организации. 
- **Side-channel утечка через временные файлы:** `_service/tmp/` очищается после commit; права доступа к tmp-файлам устанавливаются 600. 
<!-- review_response: уточнён механизм ротации мастер-ключа и защита от side-channel – решает CRITICAL 7. -->

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** — без изменений в сигнатурах. 
**Внутренние модули:**
- `atomic.rs` — write-then-rename с prepare/commit через tmp, per-entity flock на `.lock` в корне сущности.
- `cas.rs` — content-addressable store + GC (retain last N версий).
- `event_log.rs` — append-only jsonl с ротацией по неделям.
- `graph.rs` — только чтение `links.jsonl` с LRU; поддержка materialized contradicts index.
- `index.rs` — обновление `INDEX.json` с per-shard блокировкой, поиск через in-memory мульти-мап.
- `schema.rs` — JSON Schema validation (reject proposal при невалидности).
- `decay.rs` — background sweeper с per-entity lock и каскадным обходом (топологическая сортировка).
- `conflict.rs` — создание dispute, разрешение, таймауты.
- `migration.rs` — дедупликация legacy данных.

**Зависимости (сокращённые):** `serde`, `serde_json`, `jsonschema`, `ulid`, `sha2`, `tokio`, `flock` (через `fs2`), `regex` (для body search).

### 10.2 Phoenix context `AIM.FS`

**Изменения:** 
- Вызов Rust core через Elixir‑Port (запуск Rust binary как child_process, общение по stdin/stdout JSON). 
- **Fault-tolerance:** при падении Rust-процесса orphan locks не возникает, т.к. flock автоматически снимается при закрытии файла. Потеря сообщений – проблема at-most-once: после перезапуска порта необработанные запросы возвращают ошибку `{:error, :port_crashed}`, клиент повторяет. Для write-операций это допустимо (блокировка не удерживается). 
- `AIM.FS.approve/2` внутри: 
 - Сериализует запрос → JSON → Port → Rust core (с блокировкой per-entity). 
 - После успеха → `Phoenix.PubSub.broadcast(AIM.PubSub, "inbox", {:approved, proposal_id})`. 
 - Если ошибка (lock timeout, невалидный schema) → возврат `{:error, reason}`. 
- LiveView `AIMWeb.InboxLive` — без изменений.

### 10.3 Миграция существующих данных

**Детали (v3):** 
- Legacy проекты (если есть) переносятся в `users/<user_id>/projects/legacy_<slug>/`. 
- Для каждого файла генерируется frontmatter на основе метаданных (дата, автор, теги). 
- **Дедупликация:** перед миграцией вычисляется SHA-256 содержимого каждого файла; дубликаты (одинаковый SHA) объединяются в одну запись с версиями. 
- Создаются `_meta/links.jsonl` и `_meta/events.jsonl` с минимальными записями (created). 
- После миграции legacy проекты помечаются status `legacy` и не участвуют в decay/conflict resolution автоматически. 
- Миграция запускается одноразово при первом старте с флагом `--migrate`.

---

## 11. Преимущества над Claude (сводная таблица)

| Lim. | Claude | AIM_FS (v3) | Как |
|------|--------|-------------|-----|
| L1 | Index ручной, грузится весь | Sharded, lazy | `_service/INDEX.json` + per-shard файлы |
| L2 | Нет графа | Типизированный граф + materialized contradicts | `links.jsonl` per entity, LRU‑кэш, `_service/contradicts_index.json` |
| L3 | Нет версий | CAS + GC | `_service/cas/sha256/..` + `retain_versions` |
| L4 | Гибридный поиск (Tantivy?) | MVP: in-memory frontmatter + full scan; Phase 5: Tantivy+HNSW | MVP уступает по скорости, но превосходит по гибкости; Phase 5 превосходит |
| L5 | Auto-save | Approval queue с таймаутами и блокировками | inbox + lock + auto_expire + offline handling |
| L6 | Verify-on-use | TTL + decay sweeper + каскадный decay (топологическая сортировка) | `decay.ttl_days` + background |
| L7 | Только session_id | Полный provenance | `created_by` + `events.jsonl` |
| L8 | Глобальный namespace | Scoping | `scope.{global,user,project,patient}` |
| L9 | Нет схем | JSON Schema registry | `_schemas/*.json`, валидация при write |
| L10 | Дубли молча | Conflict log с таймаутом, поддержка >2 записей | `_service/disputes/` + blocked proposals + unresolved при таймауте |
| L11 | Single-user | Multi-tenant с шифрованием, key rotation, revocation, audit | `users/<id>/` + `_org/<id>/` + per-user key + HSM |
| L12 | Тяжёлый индекс в контексте | Lazy shards (выигрыш в памяти ~10x) | загружаем по запросу, p95 < 100ms |
| L13 | Нет audit-trail | Event log + replay + checksum recovery | `events.jsonl` + `replay(until)` |
| L14 | CLI only | Schema-driven UI (LiveView, поля авто из JSON Schema) | В разработке, но архитектура позволяет |
| L15 | Не atomic | Atomic transactions + per-entity lock + batch | prepare/commit через tmp + per-entity flock |

> **v3 (изменения по сравнению с peer review):** 
> - L1: уточнён lazy loading с агрегатным индексом для глобальных запросов. 
> - L2: добавлен materialized contradicts index, DuckDB отложен. 
> - L4: уточнено состояние (MVP уступает, Phase 5 превосходит). 
> - L5: добавлен offline handling (max_inactivity_days). 
> - L6: каскадный decay через топологическую сортировку. 
> - L10: поддержка >2 contradicting записей, параметризованный таймаут. 
> - L11: HSM для мастер-ключа, rotation batch job. 
> - L12: заявлен выигрыш 10x (будет измерен). 
> - L15: batch-операции с захватом всех locks.

---

## 12. Открытые вопросы (для peer review)

1. **CAS — git vs custom:** оставлен custom CAS с GC для простоты интеграции с approval flow. 
2. **DuckDB vs SQLite:** отложено; на MVP граф читается из links.jsonl + materialized contradicts index. 
3. **Embeddings — local vs API:** отложено до phase 5; локальный fallback на API. 
4. **Авто-confidence для user_facts:** вычисляется как `confidence = sigmoid(repetition_count / threshold + user_match_score)`, где `threshold` (default=3) настраивается, `user_match_score` (0–0.5) оценивает соответствие паттернам пользователя. LLM-оценка при необходимости. 
5. **TTL значений:** type‑specific (feedback ∞, project 30, deadline 7, proposal 7). Задаётся в schema. 
6. **Retention для rejected proposals:** хранятся 30 дней, затем архивируются. Используются для обучения decay‑sweeper. 
7. **Multi-tenant encryption:** per‑user key, storage‑level. Key rotation и revocation описаны в разделе 9. 
8. **Формат identity:** YAML (единообразие). 
9. **Партиционирование больших проектов:** для пациентов с >500 визитов — шардирование по месяцам (секция 3.a). 
10. **Concurrent writes:** per-entity lock + prepare/commit (секция 4.2). 
11. **Каскадный decay:** топологическая сортировка (секция 7). 
12. **Поиск MVP:** in-memory мульти-мап для frontmatter (раздел 5.2). 
13. **Confidence heuristic:** формула sigmoid выше (пункт 4). 
14. **Глобальные запросы:** ограничены frontmatter (раздел 5.1). 
15. **Undo-механизм для auto-approve:** окно отмены 24 часа (раздел 4.3).

---

## 13. План реализации (пересмотренный)

**Phase 1 (7 дней):** Rust core (`aim_fs`) 
- атомарные write/read с per-entity lock и prepare/commit 
- frontmatter YAML, ULID, SHA256 
- propose/approve/reject API с атомарностью; batch-операции 
- events.jsonl append 
- in-memory frontmatter index + full-scan body search 
- CAS + retention (хранить 3 версии) 
- materialized contradicts index 
- тесты на race conditions: 10 параллельных propose/approve/reject с проверкой консистентности 

**Phase 2 (2 дня):** JSON Schemas (7 базовых типов: `feedback_v1`, `fact_v1`, `recipe_v1`, `proposal_v1`, `project_v1`, `patient_v1`, `user_profile_v1`). 

**Phase 3 (2 дня):** Phoenix контекст `AIM.FS` через Elixir‑Port + LiveView Inbox (pending, approve, reject, defer, batch). 

**Phase 4 (2 дня):** Sharded INDEX.json + lazy loading; миграция legacy с дедупликацией. 

**Phase 5 (3 дня):** Conflict resolution UI, таймауты (параметризованные), auto‑approve preferences, decay sweeper (топологическая сортировка, обнаружение циклов). 

**Phase 6 (2 дня):** Метрики и тесты: 
- p95 latency approve < 500 ms (100 concurrent users, per-entity lock, batch до 10 items) 
- throughput events > 100 events/s 
- inbox pending count < 50 
- decay sweeper latency < 200 ms на 1000 фактов 
- `make test` с 10 параллельными propose/approve/reject, проверка отсутствия дублей и согласованности. 

**Phase 7 (continuous):** Tantivy + HNSW (опционально), DuckDB (при необходимости), полировка.

---

**Metrics (SMART):** 
- Approve latency (p95) < 500 ms при 100 concurrent users (per-entity lock, batch). 
- Event throughput > 100 ops/s. 
- Index recovery time после сбоя < 1 s (replay последнего коммита с проверкой checksum). 
- Inbox pending count для типичного врача < 50 (настраиваемый таймаут). 
- Decay sweeper latency < 200 ms на 1000 фактов. 
- Conflict resolution timeout latency < 1 s (проверка таймаутов раз в минуту).

---

**Конец draft v3. Исправлен по peer review от 2026-05-09.**
```