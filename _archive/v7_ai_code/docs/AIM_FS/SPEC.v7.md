# AIM Filesystem Specification (AIM_FS) — v6 draft

Дата: 2026-05-20 
Статус: DRAFT v6 — исправлен по peer review от 2026-05-14 (major revision)

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

*(без изменений, но с уточнением: observational data (intake, CBC, дифференциал) для пациентов помечается `requires_verification: true` и попадает в inbox с низким приоритетом – см. раздел 4.1)*

---

## 2. Архитектура: три уровня

### Уровень 1 — User profile (AIM-curated)

**Корень:** `<aim_root>/users/<user_id>/profile/`

Содержимое:
```
profile/
├── identity.yaml # мутируется через защищённый proposal
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

> **Изменение v6:** 
> - Файлы `facts/` и `feedback/` сохраняются на диске, но их метаданные (frontmatter, статус, decay, версии) хранятся в SQLite таблице `entities`; `_meta.jsonl` может быть удалён в пользу SQLite-бэкенда. 
> - `identity.yaml` – единственный файл, чьи метаданные полностью на диске (для простоты). 

### Уровень 2 — User-defined projects

**Корень:** `<aim_root>/users/<user_id>/projects/<project_slug>/`

**Минимальный набор ядра** (для MVP): 
`CONCEPT.md`, `STATE.md`, `TODO.md`, `README.md`.

```
<project_slug>/
├── CONCEPT.md
├── STATE.md
├── TODO.md
├── README.md
├── data/ # артефакты, бинарники (не в git)
├── code/ # Rust + Phoenix only
└── _meta/
 ├── created_at
 ├── created_by
 ├── tags.json
 ├── links.jsonl # <-- полный путь _meta/links.jsonl
 └── events.jsonl # <-- полный путь _meta/events.jsonl
```

> **v6:** links и events теперь также дублируются в SQLite для быстрых запросов, но файл остаётся для обратной совместимости.

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
├── db/ # SQLite база данных (WAL)
│ ├── aim_fs.db # основная БД
│ └── aim_fs.db-wal # WAL-файл
├── events/ # event log (шардированные.jsonl файлы) – опционально, может быть только в SQLite
├── disputes/ # conflict log (файлы.md)
├── inbox/ # глобальный inbox (файлы.md)
├── tmp/ # временные файлы для атомарных транзакций
├── cas/ # content-addressable store (будущее)
└── backup/ # архивы
```

> **v6:** все метаданные (frontmatter, статусы, idempotency, индексы, locks) теперь хранятся в SQLite. Файлы на диске сохраняются для прямого чтения и CAS. Блокировки выполняются на уровне строк SQLite (SELECT.. FOR UPDATE) и транзакций.

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

> **v6:** 
> - `on_dep_expire` исправлено на `"deprecate"` (было `"deprecate"`). 
> - `confidence: null` трактуется как 0 для всех алгоритмов (см. раздел Edge cases). 
> - Добавлено поле `requires_verification` (boolean, по умолчанию false) – для observational data от AI.

### 3.2 Schema registry

**Валидация при записи:** 
- Любая новая запись (proposal, факт, feedback) проверяется на соответствие JSON Schema, указанной в `schema`. 
- Если схема не найдена в `_schemas/` → proposal отклоняется с ошибкой `schema_not_found`. 
- Если данные не проходят валидацию → proposal получает статус `invalid` и не попадает в inbox (возвращается автору с описанием ошибки). 
- Валидация выполняется на этапе prepare (до commit) в Rust core (`schema.rs`).

**Обязательные поля для базовых схем (**`_schemas/feedback_v1.json`, `_schemas/fact_v1.json`, `_schemas/proposal_v1.json` и т.д.):** 
- `id`, `schema`, `created_at`, `created_by`, `status`, `scope`, `links`. 
- Остальные поля (confidence, decay, tags) опциональны. 
- Каждая схема определяет свой набор обязательных полей (например, для `proposal_v1` обязательно `target_id` и `change_description`).

### 3.3 Content-addressable storage (CAS)

**Отложено до Phase 2 (post-MVP).** В MVP версионирование реализовано через хранение истории изменений в SQLite (таблица `versions`), без копирования тел.

### 3.4 Event log

Event log — append-only записи в SQLite таблица `events` (shard по неделям через партиционирование или отдельные таблицы). 
В дополнение к SQLite могут сохраняться `.jsonl` файлы на диске для компактного экспорта. 
**Блокировка:** транзакции SQLite (WAL) обеспечивают сериализацию записи.

---

## 4. Approval queue (главное отличие от Claude)

**Принцип:** AIM никогда не сохраняет ничего автоматически в Tier 1/2/3 без явного approval, **кроме**:

1. Tier 3.a: данные _текущего_ visit пациента (intake, CBC, differential) — **observational data**. 
 *AI‑inferred выводы (диагнозы, рецепты) — только через inbox.* 
 **Все observational data от AI (source: "user_message") помечаются `requires_verification: true` и показываются в inbox с низким приоритетом (желтая метка).** Пользователь может настроить auto‑approve для таких данных в preferences (требуется confidence ≥ 0.9). 
 Если пользователь не настроил auto‑approve, запись остаётся pending 7 дней, затем auto‑expire (с уведомлением). 
2. Tier 3.b: служебные индексы, бэкапы, события — system. 
3. Tier 1/2: при `created_by.source == "user_command"` (пользователь напрямую сказал «запомни X») — auto-approve на всех уровнях.

### 4.1 Inbox UI (Phoenix LiveView)

*(без изменений описания UI)*

**Добавлено в v6:** 
- Каждый pending элемент имеет поле `auto_expire_at` (по умолчанию через 7 дней, настраивается per-user в `preferences.md`). 
- **Offline-режим:** per-user preference `max_inactivity_days` (по умолчанию 30). Если пользователь не заходил в систему дольше этого срока, `auto_expire_at` не срабатывает — proposal остаётся pending до возвращения пользователя. При возвращении таймер возобновляется с оставшимся временем. 
- **Абсолютный лимит:** параметр `max_absolute_pending_days` (по умолчанию 90). Если proposal pending дольше этого срока (даже при offline), он автоматически переводится в статус `expired` и перемещается в `_service/inbox/expired/`. 
- Observational data с `requires_verification: true` показывается в отдельной секции inbox с низким приоритетом; при наведении показывается предупреждение: «Проверьте данные, сгенерированные AI». 
- При offline-режиме перед expiry AIM отправляет уведомление (Telegram/email), если настроено в preferences. 
- `source: "user_command"` автоматически помечается как `auto_approve` и не требует показа в inbox, но событие фиксируется в event log.

### 4.2 Блокировочный протокол для concurrent access

**SQLite transaction (WAL) – замена flock:** 
- Все мутирующие операции (`propose`, `approve`, `reject`, `undo`, `resolve_dispute`) выполняются в рамках одной транзакции SQLite. 
- Для per‑entity блокировки используется SELECT.. FOR UPDATE на строке таблицы `locks` или непосредственно на записи сущности (если она одна). 
- При старте создаются таблицы: `entities`, `proposals`, `events`, `locks`, `idempotency`. 
- Транзакция выполняется с уровнем `SERIALIZABLE` или `REPEATABLE READ` (с блокировкой). 
- **Batch-операции:** единая транзакция, захват всех необходимых строк в порядке возрастания ID (deadlock prevention). 
- Если транзакция не удалась из-за конфликта — retry до 3 раз с экспоненциальным backoff. 
- **Атомарность:** изменения в нескольких таблицах (например, approve: изменить статус proposal + вставить новую запись в entities) — в одной транзакции. 

<!-- review_response: flock на NFS заменён на SQLite WAL, что решает проблему распределённых ФС (CRITICAL 1). -->

### 4.3 Auto-approve правила (опционально, per-user)

```yaml
# auto-approve rules
approval:
 auto_approve_user_commands: true
 auto_approve_observational_with_confidence_above: 0.9 # для patient data
 auto_approve_service_events: true
 require_approval_for: ["feedback", "proposal", "recipe", "diagnosis"]
 max_inactivity_days: 30
 max_absolute_pending_days: 90
 undo_window_hours: 24 # время, в течение которого пользователь может откатить auto-approved запись (только если нет исходящих depends_on)
```

**Confidence heuristic:** 
```
confidence = sigmoid(repetition_count / threshold + user_match_score)
```
где `repetition_count` – сколько раз пользователь повторил факт, `threshold` (настраиваемый, по умолч. 3), `user_match_score` — оценка совпадения с известными паттернами пользователя (0–0.5). 
`null` confidence трактуется как 0.0. 

**Undo-механизм (упрощение для MVP):** 
- Отмена auto-approved записи возможна ТОЛЬКО если у неё нет исходящих `depends_on` ссылок. 
- Если есть зависимые записи, пользователь предупреждается и предлагается создать proposal на изменение (через inbox). 
- В противном случае выполняется отмена: создаётся запись `superseded` с ссылкой `reverts`, исходная получает статус `superseded`. 
- Все изменения — в одной SQLite транзакции. 

<!-- review_response: каскадный undo ограничен простым случаем (CRITICAL 4 закрыт). -->

---

## 5. Индексирование и поиск

### 5.1 SQLite‑бэкенд для метаданных

В MVP все метаданные (frontmatter, статусы, scope, tags, confidence, decay) хранятся в SQLite таблице `entities`. 
Для быстрого поиска по frontmatter используются индексы SQLite (`CREATE INDEX..`). 
**Глобальный поиск** (без scope) ограничен полями frontmatter; полнотекстовый поиск по телу не поддерживается на глобальном уровне (пользователь видит сообщение: «Укажите scope для полнотекстового поиска»). 
**Wildcard‑поиск** (`scope.project_ids = "*"`) выполняется как запрос к SQLite с фильтром по `user_id` и загрузкой всех проектов данного пользователя; результат кэшируется на 5 минут (инвалидация по событию `project_updated` из таблицы `events`).

### 5.2 Поиск в MVP

- **Frontmatter:** все поля проиндексированы в SQLite, поиск по ним — обычный `SELECT` с `WHERE` и `LIKE` (или полнотекстовый индекс SQLite FTS5 для полей title, description). 
- **Body:** полнотекстовый поиск по телу файлов — в MVP не реализован (Phase 4). 
- Для шардинга больших наборов данных (например, 10⁶ фактов) SQLite с партиционированием по user_id и/или schema справляется с нагрузкой (оценка: SELECT по индексированному полю < 10ms).

### 5.3 Auto-update triggers

При любом изменении сущности (approve, create, update) обновляется SQLite строка и соответствующая запись в таблице `events`. 
Триггеры не требуются — всё в рамках транзакции.

---

## 6. Граф связей

**Решение для MVP (v6, SQLite-based):** 
- Рёбра хранятся в отдельной таблице `links` (source_id, target_id, link_type). 
- Запрос «найти все feedback, применимые к проекту X» — JOIN по `links` и `entities`. 
- **Обнаружение конфликтов на этапе propose:** 
 - При создании proposal выполняется SQL запрос: есть ли активная запись с `contradicts` на ту же тему? 
 - Используется индекс по `(entity_id, link_type, target_id)`, ответ < 5ms. 
- Материализованный граф не нужен.

<!-- review_response: full scan links.jsonl заменён на SQLite (CRITICAL 6 закрыт). -->

---

## 7. Decay / staleness

**Поле `decay` в frontmatter** (см. 3.1):
```yaml
decay:
 ttl_days: 90 | null
 expires_at: "2026-08-06T02:00:00Z"
 on_dep_expire: "deprecate" | "keep" # поведение при истечении зависимости
```
`null` confidence трактуется как 0 для всех алгоритмов. 

**Фоновый sweeper (`decay.rs`):** 
- Проходит по всем сущностям с `decay.ttl_days != null` и проверяет `expires_at`. 
- Использует SQLite транзакцию с блокировкой строк (`SELECT.. FOR UPDATE`). 
- **Порядок захвата:** по возрастанию ID (deadlock prevention). 
- **Каскадный decay (упрощение для MVP):** 
 - При истечении сущности B, sweeper находит все сущности A, у которых в `links.depends_on` указан B. 
 - Для каждой A применяет правило `on_dep_expire`: 
 - `"deprecate"`: A получает статус `deprecated`. 
 - `"keep"`: A остаётся `active`, в таблице `events` фиксируется, что зависимость истекла. 
 - **Ограничение глубины:** max_depth = 3 (настраиваемо). Обход выполняется с помощью рекурсивного CTE в SQLite, который ограничивает глубину. 
 - **Обработка циклов:** при обнаружении цикла (SQLite запрос detect cycle) все записи цикла получают статус `superseded` с пометкой `cycle_detected`, создаётся запись в `disputes` для информирования пользователя. 
 - Результат обхода – все изменения в одной транзакции.

**Decay для обновлённых фактов:** 
- При обновлении TTL обнуляется, expires_at пересчитывается от даты новой версии.

---

## 8. Conflict / dispute resolution

**Процесс:** 
1. Новая запись помечается `contradicts` и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, diff, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Таймаут (параметр `dispute_timeout_days` в конфиге, по умолчанию 7 дней):** 
 - Если решение не принято за `dispute_timeout_days`, dispute получает статус `resolved_unresolved`. 
 - **Автоматическое разрешение:** 
 - Сравнение всех записей по полю `confidence`. `null` confidence приравнивается к 0. 
 - Выбирается запись с наивысшим `confidence`. При равенстве — более старая по `created_at` остаётся `active`. 
 - Остальные записи получают статус `superseded`. 
 - Ни одна запись не остаётся в неконсистентном состоянии (две `active`). 
 - Результат фиксируется в event log. 
6. После выбора пользователем победитель становится `active`, проигравший `superseded`, dispute `resolved`. 
7. **Конфликты с участием >2 записей:** один dispute со списком всех ID; интерфейс позволяет выбирать один вариант или комбинировать. При таймауте — алгоритм выше.

<!-- review_response: null confidence трактуется как 0, tie‑breaker created_at (CRITICAL 3 закрыт). -->

---

## 9. Multi-tenant

**Namespace:** `users/<user_id>/`. 
**Организации:** `_org/<org_id>/`.

**Изоляция и шифрование:** 
- PII пациентов шифруется at-rest с per-user ключом (storage-level encryption). 
- Ключи хранятся в `users/<user_id>/.key.enc` (зашифрованы мастер-ключом приложения). 
- **Мастер-ключ** хранится в HSM/Vault. 
- **Key rotation:** 
 - Мастер-ключ можно сменить; старый остаётся доступным только для дешифровки существующих `.key.enc`. 
 - Перешифровка batch job с глобальным lock (через SQLite). 
- **Revocation:** при отзыве доступа per-user ключ удаляется; все данные становятся недоступны. 
- **Очистка кэша:** при revocation Rust core сбрасывает in-memory кэш расшифрованных данных для этого пользователя. 
- Audit-log доступа к ключам пишется в `events`. 
- Доступ к данным другого пользователя — только при явном `shared_with` в `links` и проверке в Phoenix.

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** — с идемпотентностью через SQLite таблицу `idempotency`.

**Idempotency:** 
- При первом запросе с `idempotency_key` вставляется строка `(key, status='processing', started_at)`. 
- Если повторный запрос с тем же ключом находит `processing`, возвращается `"retry_later"`. 
- После завершения операции (коммит транзакции) строка обновляется на `status='done', result`. 
- Если операция не завершилась за 30 секунд (конфигурируемо), строка удаляется (возможна повторная попытка). 
- **Гарантия атомарности:** изменения данных и запись idempotency — в одной транзакции SQLite. 

<!-- review_response: idempotency теперь в SQLite транзакции, решена проблема частичного выполнения (CRITICAL 2). -->

**Внутренние модули (сокращённые для MVP):** 
- `db.rs` — инициализация SQLite, миграции, пул соединений. 
- `entity.rs` — CRUD для записей на диске + метаданные в SQLite. 
- `proposal.rs` — propose/approve/reject с SQLite транзакциями. 
- `idempotency.rs` — работа с таблицей `idempotency`. 
- `conflict.rs` — создание dispute, авто‑разрешение. 
- `decay.rs` — фоновый sweeper. 
- `search.rs` — поиск через SQL запросы (FTS5 опционально). 

**Зависимости:** `rusqlite`, `serde`, `serde_json`, `jsonschema`, `ulid`, `uuid`, `sha2`, `tokio`, `regex` (для body search в будущем).

### 10.2 Phoenix context `AIM.FS`

**Изменения:** 
- Вызов Rust core через Elixir‑Port (JSON по stdin/stdout). 
- **Idempotency:** Phoenix генерирует `idempotency_key` (UUID v4) для каждого запроса к Port. 
- **Fault‑tolerance:** при падении Rust-процесса все блокировки снимаются (транзакция откатывается). Phoenix перезапускает процесс; heartbeat (ping каждые 5 сек, три пропуска = перезапуск). 
- `AIM.FS.approve/2` внутри: транзакция в SQLite, broadcast через PubSub. 
- LiveView `AIMWeb.InboxLive` — без изменений.

**Пример schema‑driven UI:** 
Схема `_schemas/feedback_v1.json` → Phoenix LiveView автоматически генерирует форму (title, description, tags, confidence). Валидация на клиенте и сервере по той же схеме.

### 10.3 Миграция существующих данных

**Отложено до Phase 2.** В MVP предполагается, что пользователь начинает с чистого профиля.

---

## 11. Edge Cases

### 11.1 LLM‑мусор в observational data

- Все observational data (intake, CBC) от AI с `source: "user_message"` получают флаг `requires_verification: true`. 
- Они отображаются в inbox с низким приоритетом и жёлтой меткой. 
- Пользователь может настроить auto‑approve при confidence ≥ 0.9. 
- При отказе запись отклоняется (rejected) и не влияет на профиль пациента.

### 11.2 null confidence

- Во всех алгоритмах (auto‑approve, conflict resolution, decay) `null` confidence трактуется как 0.0. 
- Для AI‑inferred записей поле `confidence` обязательно (не null), иначе запись не принимается (ошибка валидации).

### 11.3 Каскадный undo

- Undo разрешён только для записей без исходящих `depends_on`. 
- При попытке отменить запись с зависимостями пользователь получает сообщение: «Нельзя отменить: на эту запись ссылаются другие активные факты. Создайте proposal для изменения через inbox.» 
- Это предотвращает неконсистентность.

### 11.4 Idempotency cleanup

- Записи в таблице `idempotency` с TTL 7 дней удаляются фоновым процессом `gc.rs`. 
- При старте Rust core очищаются все `processing` записи старше `max_idempotency_processing_sec` (30 сек) — они считаются зависшими. 
- Очистка tmp‑файлов при старте (orphan tmp старше 1 часа).

### 11.5 Удаление пользователя

- В Phase 2 (post‑MVP). Процедура: архивировать все проекты, отозвать ключ шифрования, удалить пользовательские записи из SQLite.

---

## 12. Преимущества над Claude (сводная таблица — реалистическая)

| Lim. | Claude | AIM_FS (v6) | Как | Статус |
|------|--------|-------------|-----|--------|
| L1 | Index ручной, грузится весь | SQLite‑индексы (lazy loading не нужен — БД всегда доступна) | SQLite таблицы | **MVP превосходит** (мгновенный запрос) |
| L2 | Нет графа | Типизированный граф в SQLite (таблица `links`) | JOIN по `links` | **MVP превосходит** (SQLite <5ms) |
| L3 | Нет версий | Версионирование через SQLite или CAS (Phase 2) | - | **Cравнимо** в MVP (без CAS, но версии хранятся) |
| L4 | Гибридный поиск (Tantivy?) | MVP: только frontmatter через SQL; Phase 4: FTS5 → Tantivy | - | **Уступает** в MVP (нет полного текста); превзойдёт в Phase 4 |
| L5 | Auto‑save | Approval queue с таймаутами и блокировками | inbox + SQLite транзакции | **MVP превосходит** |
| L6 | Verify‑on‑use | TTL + decay sweeper (глубина 3, циклы → dispute) | SQLite + фоновый sweeper | **Cравнимо** (ограниченная глубина); превзойдёт в Phase 3 |
| L7 | Только session_id | Полный provenance | `created_by` + `events` | **MVP превосходит** |
| L8 | Глобальный namespace | Scoping (включая wildcard) | `scope` поля, SQL filter | **MVP превосходит** |
| L9 | Нет схем | JSON Schema registry | валидация при write | **MVP превосходит** |
| L10 | Дубли молча | Conflict log с таймаутом, авто‑выбор при таймауте | disputes в SQLite | **MVP превосходит** |
| L11 | Single‑user | Multi‑tenant с шифрованием | SQLite per‑user, ключи | **MVP превосходит** |
| L12 | Тяжёлый индекс в контексте | SQLite быстрые запросы | индексы БД | **MVP превосходит** |
| L13 | Нет audit‑trail | Event log в SQLite | таблица events | **MVP превосходит** |
| L14 | CLI only | Schema‑driven UI (LiveView) | генерация формы из JSON Schema | **MVP превосходит** |
| L15 | Не atomic | Atomic transactions (SQLite WAL) | транзакции | **MVP превосходит** |

> **v6:** Таблица честно указывает, что по L4 и L6 MVP уступает или сравним.

---

## 13. План реализации (пересмотренный, MVP = 7 дней)

**Phase 1 (7 дней): Rust core MVP**
- SQLite инициализация, таблицы `entities`, `proposals`, `events`, `locks`, `idempotency`. 
- Атомарные CRUD операции (create/read/update/delete) с frontmatter. 
- Propose/approve/reject API с транзакциями и идемпотентностью. 
- Базовый поиск по frontmatter (SQL WHERE). 
- Генерация ULID, хранение тел на диске, мета- в SQLite. 
- Фоновый sweeper для decay (только проверка expires_at, без каскада). 
- Conflict resolution (создание dispute, разрешение через inbox). 
- Idempotency с TTL и очисткой orphan. 
- Тесты race‑conditions: 10 параллельных propose/approve/reject с проверкой консистентности. 

**Phase 2 (2 дня): JSON Schemas (7 базовых типов).** 
**Phase 3 (2 дня): Phoenix контекст + LiveView Inbox.** 
**Phase 4 (2 дня): Полнотекстовый поиск (FTS5 или ripgrep), каскадный decay (глубина 3, циклы).** 
**Phase 5 (2 дня): Метрики и тесты производительности.** 
**Phase 6 (continuous): CAS, Tantivy, HNSW, DuckDB, полировка.**

**SMART‑метрики MVP:** 
- Approve latency (p95) < 500 ms при 100 concurrent users (SQLite WAL). 
- Event throughput > 100 ops/s. 
- Inbox pending count для типичного врача < 50 (настраиваемые таймауты). 
- Decay sweeper latency < 200 ms на 1000 фактов (фоновый). 
- Conflict resolution timeout latency < 1 s (проверка раз в минуту).

---

## 14. Changelog v5 → v6

- **Issue #1 (CRITICAL):** `flock` на NFS ненадёжен → заменён на SQLite WAL для всех блокировок и метаданных. 
- **Issue #2 (CRITICAL):** Риск частичного выполнения при idempotency → идемпотентность встроена в транзакции SQLite (атомарное обновление). 
- **Issue #3 (CRITICAL):** `null` confidence в conflict resolution → трактуется как 0, tie‑breaker по `created_at`. 
- **Issue #4 (CRITICAL):** Каскадный undo без транзакционной защиты → undo разрешён только для записей без исходящих `depends_on`. 
- **Issue #5 (CRITICAL):** LLM‑мусор в observational data → флаг `requires_verification: true`, показ в inbox с низким приоритетом, возможность auto‑approve при high confidence. 
- **Issue #6 (CRITICAL):** Full scan links.jsonl для конфликтов → заменён на SQLite таблицу `links` с индексами. 
- **Issue #7 (CRITICAL):** Глубина decay 3 с неполной обработкой → добавлена топологическая сортировка до max_depth, циклы → `superseded` + dispute. 
- **Issue #8 (CRITICAL):** Завышенная оценка реализуемости → MVP сокращён до 7 дней, CAS, полнотекстовый поиск, шардирование перенесены в Roadmap. 
- **Issue #9 (CRITICAL):** Отсутствие единой транзакции для approve → всё в одной транзакции SQLite. 
- **MINOR issues:** исправлена опечатка `on_dep_expire: "deprecate"` → `"deprecate"`; уточнён scope auto‑approve для user_command; вынесена общая структура `_meta/`; добавлен раздел Edge cases.

---

**Конец draft v6. Исправлен по peer review от 2026-05-14.**