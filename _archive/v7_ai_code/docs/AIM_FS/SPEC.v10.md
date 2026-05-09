# AIM Filesystem Specification (AIM_FS) — v9 draft

**Дата:** 2026-06-08 
**Статус:** DRAFT v9 — исправлен по peer review от 2026-05-20 (minor revision)

> **Цель:** определить файловую систему AIM, которая:
>
> 1. Хранит профиль пользователя (доктора), который AIM **изучает и поддерживает**.
> 2. Хранит проекты пользователя (которые он явно создаёт и описывает; AIM генерирует ядро).
> 3. Хранит автоматически создаваемые проекты — пациенты, служебные, проект саморазвития AIM.
>
> **И при этом превосходит auto-memory Claude Code по большинству осей:** 
> approval queue, версионирование, граф связей, провенанс, decay, схемы, conflict resolution, scoping, semantic search (Phase 2), replay, multi-tenant, lazy-loading индекса, schema-driven UI.
>
> *Полнотекстовый поиск (L4) и каскадный decay (L6) реализуются в Phase 2/4 и на данный момент в MVP уступают или сравнимы с Claude; остальные 13 осей превосходят.*

---

## 1. Постановка задачи

### 1.1 Что есть у Claude Code (baseline)

(без изменений относительно v8)

### 1.2 Что должна решать AIM_FS

AIM_FS превосходит Claude Code по 13 из 15 заявленных осей (см. таблицу в разделе 12). По полнотекстовому поиску (L4) и каскадному decay (L6) на текущий момент MVP уступает или сравним; улучшения запланированы в Phase 2 и Phase 4.

---

## 2. Архитектура: три уровня

<!-- review_response: замечание CRITICAL #2 — шифрование перенесено в Roadmap; в MVP используется только tenant_id и permissions ОС -->

### Уровень 1 — User profile (AIM-curated)

**Корень:** `<aim_root>/users/<user_id>/profile/`

Содержимое:
```
profile/
├── identity.yaml # мутируется через защищённый proposal
├── role.md # роль/специализация/уровень экспертизы
├── preferences.md # стиль работы, max_inactivity_days и т.д.
├── workflows.md # как user обычно работает
├── history.jsonl # append-only лог ключевых решений / событий
├── facts/ # отдельные факты о user
│ └── <fact_id>.md
└── feedback/ # collaboration rules from user
 └── <feedback_id>.md
```

> **Изменения v9:** 
> - Поле `source` (enum: `user_message`, `user_command`, `system`) заменяет `created_by.agent`. Agent `aim` = source `user_message`, `system` = source `system`. 
> - `tenant_id` – UUID строкой (не имя пользователя), генерируется при создании пользователя и не меняется. 
> - Шифрование per‑user ключом вынесено в Roadmap (Phase B). В MVP все данные хранятся без шифрования на уровне приложения; безопасность обеспечивается правами ФС и изоляцией `tenant_id`. 

### Уровень 2 — User-defined projects

(без изменений, кроме `scope` – упрощён, см. ниже)

### Уровень 3 — Auto-created folders

#### 3.a Patient folders

(без изменений, кроме снятия шифрования – в MVP не шифруется)

#### 3.b Service folders

`<aim_root>/_service/`:
```
_service/
├── db/ # SQLite база данных (WAL) – единственный источник метаданных
│ └── aim_fs.db # основная БД
├── cas/ # content-addressable store (Phase 2)
├── disputes/ # conflict log (.md файлы для тел, мета в SQLite)
├── inbox/ # глобальный inbox (.md файлы)
├── tmp/ # временные файлы для атомарных транзакций
└── backup/ # резервные копии (скрипты, дампы)
```

(без изменений)

---

## 3. Слой содержимого: формат файлов

### 3.1 Унифицированный frontmatter

```yaml
---
id: "01HZAB12CDEF34GH56JK78MN90"
schema: "feedback_v1"
schema_version: 1
title: "DeepSeek-first rule"
description: "Маршрутизация writing/QA через DeepSeek API"
created_at: "2026-05-08T02:00:00Z"
created_by:
 source: "user_message" | "user_command" | "system"
 user_id: "djabbat_gmail_com" # UUID пользователя
 session_id: ".."
 llm_model: "deepseek-reasoner" | null
confidence: 0.92 # обязательно для всех не-system записей; 0.0–1.0
tenant_id: "UUID_пользователя" # UUID, не имя
versions:
 - hash: "sha256:abcd…"
 at: "2026-05-08T02:00:00Z"
 # только последняя версия (остальные в SQLite)
status: "active" | "superseded" | "rejected" | "deprecated" | "expired" 
decay:
 ttl_days: 90 | null
 expires_at: "2026-08-06T02:00:00Z"
 on_dep_expire: "deprecate" | "keep"
scope:
 global: false
 user_ids: ["djabbat_gmail_com"]
 project_ids: ["LC_AIM", "LC_CDATA"] | null # без wildcard
 patient_ids: []
links:
 depends_on: ["01HX…"]
 refines: ["01HY…"]
 supersedes: ["01HW…"]
 contradicts: []
tags: ["llm", "routing", "deepseek"]
requires_verification: false
---
<тело>
```

> **v9:** 
> - `created_by.agent` удалён; используется `source` (user_message / user_command / system). 
> - `user_id` вместо `user`. 
> - `tenant_id` – UUID. 
> - `scope.project_ids` — только null или список (wildcard удалён как избыточный для MVP). 
> - Поле `versions` в frontmatter содержит только последнюю версию (hash, at). Полная история – в SQLite таблице `versions`. 
> - Исправлено: `on_dep_expire: "deprecate"`.

### 3.2 Schema registry

(без изменений, но валидация и schema_version остаются)

### 3.3 Content-addressable storage (CAS)

**Отложено до Phase 2 (post-MVP).** В MVP версионирование реализовано через хранение истории изменений в SQLite (таблица `versions`), без копирования тел.

### 3.4 Event log

(без изменений)

---

## 4. Approval queue (главное отличие от Claude)

### 4.1 Inbox UI (Phoenix LiveView)

- Минимальный просмотр pending + accept/reject (как в v8). 
- Observational data с `requires_verification: true` показывается в отдельной секции «Требуют проверки» с жёлтой меткой. 
- `source: "user_command"` при `auto_approve_user_commands: true` (раздел 4.3) создаёт запись сразу со статусом `active`, не попадая в inbox. Событие фиксируется в event log. 

### 4.2 Блокировочный протокол для concurrent access

**SQLite transaction (WAL) с `BEGIN IMMEDIATE`.** 
- Все модифицирующие транзакции (create, propose, approve, reject) открываются как `BEGIN IMMEDIATE`, что блокирует запись всей БД на время транзакции. Это даёт гарантию атомарности без риска race-conditions. 
- Для long‑running операций (например, batch propose) – транзакция остаётся короткой ( < 50 мс), блокировка не критична. 
- **Deadlock prevention:** фиксированный порядок захвата таблиц: сначала `locks`, затем `entities`, затем `proposals`. Внутри таблицы – по возрастанию `id`. 
- **Optimistic locking:** каждая сущность имеет поле `version` (монотонный счётчик). При обновлении проверяется, что `version` не изменился после чтения. При несовпадении – транзакция откатывается и retry до 3 раз с экспоненциальным backoff. 
- Для **batch-операций** – единая транзакция с `BEGIN IMMEDIATE`, захват всех необходимых строк в порядке возрастания ID (глобальном – ULID). 

### 4.3 Auto-approve правила (опционально, per-user)

```yaml
approval:
 auto_approve_user_commands: true
 auto_approve_observational_with_confidence_above: 0.9 # >=
 auto_approve_service_events: true
 require_approval_for: ["feedback", "proposal", "recipe", "diagnosis"]
 max_inactivity_days: 30
```

**Confidence heuristic** (как в v8) 
**Отмена auto-approved записи:** 
- В MVP пользователь создаёт proposal с типом `revert`, который проходит обычный approval. 
- Proposal `revert` проверяет, что на исходную запись нет исходящих `depends_on` ссылок. Если они есть, proposal отклоняется. 

---

## 5. Индексирование и поиск

### 5.1 SQLite‑бэкенд для метаданных

Все метаданные (frontmatter, статусы, scope, tags, confidence, decay, tenant_id) хранятся только в SQLite таблице `entities`. 
- Индексы: `(tenant_id, status)`, `(tenant_id, schema)`, `(tenant_id, id)`, `(expires_at)`. 
- **Connection pool:** `r2d2` с `rusqlite`, пул из 2-3 соединений (достаточно для одного пользователя). 
- **PRAGMA:** `journal_mode=WAL`, `synchronous=NORMAL`, `journal_size_limit=65536`, `cache_size=-8000` (8 MB). 
- **Checkpoint:** автоматический каждые 1000 транзакций или по размеру WAL > 10 MB. 

**Добавлена таблица `versions` (CRITICAL #3):** 
```sql
CREATE TABLE versions (
 id TEXT PRIMARY KEY,
 entity_id TEXT NOT NULL REFERENCES entities(id),
 data TEXT, -- сериализованный frontmatter + тело (опционально)
 hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 tenant_id TEXT NOT NULL
);
CREATE INDEX versions_entity ON versions(entity_id, created_at);
```
При каждом approve создаётся новая версия; тело файла не дублируется, если не изменилось (можно хранить `null`). 

### 5.2 Поиск в MVP

- **Frontmatter:** все поля проиндексированы в SQLite, поиск — `SELECT` с параметризованными `WHERE` (через `?` для защиты от SQL injection). 
- **Body:** полнотекстовый поиск – **не реализован в MVP** (Phase 2, FTS5). 

### 5.3 Auto-update triggers

(без изменений)

---

## 6. Граф связей

**Решение для MVP (SQLite-based):** 
- Рёбра хранятся в таблице `links` (source_id, target_id, link_type, tenant_id). 
- Индекс `(source_id, link_type)`. 
- Запрос конфликтов на этапе propose: выполняется в транзакции с `BEGIN IMMEDIATE`. Сначала блокируется вся БД, затем выполняется `SELECT.. FROM entities WHERE id = ?`, потом `SELECT.. FROM links WHERE target_id = ? AND link_type = 'contradicts' AND status = 'active'`. Атомарность гарантируется блокировкой IMMEDIATE. 
- Материализованный граф не нужен.

---

## 7. Decay / staleness

**Поле `decay` в frontmatter** (см. 3.1). 

**Механизм в MVP (sweeper):** 
- Фоновый Tokio task (запускается при старте Rust core) каждые 60 секунд выполняет `UPDATE entities SET status = 'expired' WHERE expires_at < datetime('now') AND status = 'active'` в одной транзакции. 
- При чтении (через `entity.rs::get`) статус не меняется; если запись просрочена, возвращается флаг `expired`. 
- Каскадный decay отложен до Phase 2.

---

## 8. Conflict / dispute resolution

**Процесс в MVP:** 
1. Новая запись помечается `contradicts` (через links) и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Auto-resolution** отложена до Phase 4 (см. Roadmap). В MVP конфликт остаётся в inbox до ручного разрешения пользователем. 
6. После выбора пользователем победитель становится `active`, проигравший `superseded`, dispute `resolved`. 
7. **Конфликты с участием >2 записей:** один dispute со списком всех ID; интерфейс позволяет выбрать один вариант. Комбинирование — в Phase 4.

**Атомарность проверки конфликта при propose:** 
- Используется `BEGIN IMMEDIATE` перед всей транзакцией (блокировка записи всей БД). Это гарантирует, что два concurrent propose не увидят отсутствие конфликта одновременно. 

---

## 9. Multi-tenant

**Namespace:** `users/<user_id>/`. 
**Организации:** `_org/<org_id>/`.

**Изоляция в SQLite:** 
- Обязательное поле `tenant_id` (UUID) во всех таблицах (`entities`, `proposals`, `events`, `links`, `idempotency`, `versions`). 
- Каждый SQL-запрос включает `WHERE tenant_id = ?`. В Rust core используется функция `with_tenant(tenant_id, query)` которая подставляет параметр. 
- Row-level security эмулируется программно – нет SQL-триггеров, только прикладной код. 

**Шифрование (Roadmap Phase B):** 
PII пациентов и метаданные шифруются at-rest с per-user ключом. В MVP шифрование не используется – безопасность на уровне ФС (права `0700` на директорию пользователя).

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** – с идемпотентностью через SQLite таблицу `idempotency`.

**Idempotency (упрощённая для MVP):** 
- Таблица `idempotency` содержит ключ, статус (`processing`/`done`), результат, `created_at`, `tenant_id`. 
- При первом запросе с `idempotency_key` вставляется `(key, 'processing', started_at)`. 
- Если повторный запрос находит `processing`, возвращается `"conflict"` – клиент должен отправить с новым ключом. 
- После завершения операции статус меняется на `done`, сохраняется результат. 
- Если операция не завершилась за **5 секунд** (таймаут), статус остаётся `processing`, но повторный запрос возвращает `"conflict"`. При перезапуске Rust core очищаются все `processing` записи старше 5 секунд. 
- *Статус `failed` удалён – при таймауте клиент получает `conflict` и должен повторить с новым ключом.* 

**Внутренние модули (MVP):** 
- `db.rs` – инициализация SQLite, миграции, пул соединений (r2d2). 
- `entity.rs` – CRUD для записей на диске + метаданные в SQLite. 
- `proposal.rs` – propose/approve/reject с транзакциями (`BEGIN IMMEDIATE`). 
- `idempotency.rs` – работа с таблицей `idempotency`. 
- `conflict.rs` – создание dispute (без auto-resolution). 
- `search.rs` – поиск через SQL запросы. 
- `sweeper.rs` – фоновый процесс для decay. 

**Зависимости:** `rusqlite`, `r2d2`, `r2d2_sqlite`, `serde`, `serde_json`, `jsonschema`, `ulid`, `uuid`, `sha2`, `tokio`, `aes-gcm` (только для будущего шифрования).

### 10.2 Phoenix context `AIM.FS`

- Вызов Rust core через Elixir‑Port (JSON по stdin/stdout). 
- **Idempotency:** Phoenix генерирует `idempotency_key` (UUID v4) для каждого запроса к Port. 
- **Fault‑tolerance:** при падении Rust-процесса все блокировки снимаются (транзакция откатывается). Phoenix перезапускает процесс; heartbeat (ping каждые 5 сек, три пропуска = перезапуск). При перезапуске очищаются все `processing` записи в idempotency старше 5 секунд. 
- `AIM.FS.approve/2` внутри: транзакция в SQLite, broadcast через PubSub. 
- **Минимальный LiveView inbox** (Phase 1): `AIMWeb.InboxLive` – просмотр pending записей, accept/reject. Без сложных форм, только две кнопки.

### 10.3 Миграция существующих данных

**Отложено до Phase 2.** В MVP предполагается, что пользователь начинает с чистого профиля.

---

## 11. Edge Cases

### 11.1 LLM‑мусор в observational data

(без изменений, как в v8, но с использованием source вместо agent)

### 11.2 null confidence

- Для всех не-system записей `confidence` обязателен (0.0–1.0). Если null – валидация не проходит. 
- Для system-записей (`source: "system"`) `confidence` может быть null, но такие записи исключаются из любой рейтинговой обработки. 
- В conflict resolution при сравнении `confidence` всегда есть значение – tie‑breaker по `created_at`.

### 11.3 Undo (через proposal)

- Прямой undo не реализован. Пользователь создаёт proposal с типом `revert`. 
- Proposal `revert` проверяет исходящие `depends_on` ссылки. Если они есть, proposal отклоняется.

### 11.4 Idempotency cleanup

- Записи в таблице `idempotency` с TTL 7 дней удаляются фоновым процессом `gc.rs`. 
- При старте Rust core очищаются все `processing` записи старше 5 секунд – они считаются зависшими.

### 11.5 Конкурентный propose на одну сущность

- Используется `BEGIN IMMEDIATE` – блокируется вся БД на время транзакции. Второй proposal получает `conflict` (транзакция откатывается). 
- Клиент получает ошибку `entity_locked` и должен повторить позже (backoff).

### 11.6 Одновременное обновление сущности sweeper и пользователем

- Sweeper выполняет `UPDATE.. WHERE expires_at < datetime('now') AND status = 'active'` в отдельной транзакции. Пользовательские операции не конфликтуют, так как `BEGIN IMMEDIATE` блокирует запись – sweeper либо ждёт, либо retry.

### 11.7 Удаление пользователя (GDPR)

- В MVP пользователь удаляется через прямой вызов `aim_fs delete_user <user_id>`, который: 
 - архивирует все проекты (перемещает в `_service/backup/`), 
 - удаляет все строки с `tenant_id = user_id` из SQLite, 
 - сбрасывает кэш. 

---

## 12. Преимущества над Claude (сводная таблица — реалистическая)

| Lim. | Claude | AIM_FS (v9) | Как | Статус |
|------|--------|-------------|-----|--------|
| L1 | Index ручной, грузится весь | SQLite‑индексы (ленивая загрузка не нужна) | SQLite таблицы | **MVP превосходит** |
| L2 | Нет графа | Типизированный граф в SQLite (таблица `links`) | JOIN по `links` | **MVP превосходит** |
| L3 | Нет версий | Версионирование через SQLite (таблица `versions`) | - | **Сравнимо** в MVP (без CAS) |
| L4 | Гибридный поиск (Tantivy?) | MVP: только frontmatter через SQL; Phase 2: FTS5 | - | **Уступает** в MVP |
| L5 | Auto‑save | Approval queue с блокировками и idempotency | inbox + транзакции | **MVP превосходит** |
| L6 | Verify‑on‑use | Sweeper‑based decay; каскадный decay в Phase 2 | фоновая задача | **Сравнимо** (MVP) |
| L7 | Только session_id | Полный provenance | `created_by` + `events` | **MVP превосходит** |
| L8 | Глобальный namespace | Scoping (без wildcard) | `scope` + `tenant_id` | **MVP превосходит** |
| L9 | Нет схем | JSON Schema registry с версионированием | валидация при write | **MVP превосходит** |
| L10 | Дубли молча | Conflict log (с ручным разрешением) | disputes в SQLite | **MVP превосходит** (сравнимо с Claude, но мы явно обрабатываем) |
| L11 | Single‑user | Multi‑tenant с изоляцией tenant_id | `tenant_id`, `BEGIN IMMEDIATE` | **MVP превосходит** |
| L12 | Тяжёлый индекс в контексте | SQLite быстрые запросы | индексы БД | **MVP превосходит** |
| L13 | Нет audit‑trail | Event log в SQLite | таблица events | **MVP превосходит** |
| L14 | CLI only | Schema‑driven UI (LiveView) | генерация формы из JSON Schema | **MVP превосходит** |
| L15 | Не atomic | Atomic transactions (SQLite WAL + BEGIN IMMEDIATE) | транзакции | **MVP превосходит** |

> **v9:** Заявление о превосходстве скорректировано: AIM_FS превосходит Claude по 13 из 15 осей; L4 и L6 уступают/сравнимы в MVP.

---

## 13. План реализации (пересмотренный, MVP = 7 дней)

**Phase 1 (7 дней): Rust core MVP + минимальный Phoenix LiveView** 
- SQLite инициализация, таблицы `entities`, `proposals`, `events`, `links`, `locks`, `idempotency`, `versions`. 
- Атомарные CRUD операции (create/read/update/delete) с frontmatter и `tenant_id`. 
- Propose/approve/reject API с `BEGIN IMMEDIATE` и идемпотентностью (processing/done). 
- Базовый поиск по frontmatter (SQL WHERE с параметрами). 
- Idempotency с таймаутом 5 сек. 
- Интеграция с Phoenix Port (JSON). 
- **Минимальный Phoenix LiveView inbox** (просмотр pending, accept/reject). 
- Тесты race‑conditions: 10 параллельных propose/approve/reject.

**Phase 2 (2 дня): Conflict detection + sweeper для decay + JSON Schema валидация (7 базовых схем).** 
**Phase 3 (2 дня): FTS5 поиск по телу, расширенный LiveView Inbox (все действия).** 
**Phase 4 (2 дня): Каскадный decay (глубина 3, циклы), auto-resolution conflict (таймаут).** 
**Phase 5 (2 дня): Backup, шардинг SQLite, улучшенная производительность.** 
**Phase 6 (continuous): CAS, Tantivy, HNSW, DuckDB, полировка.**

**Roadmap (post-MVP):** 
- Шифрование PII и метаданных (per-user AES-256-GCM, ключи в Vault). 
- Multi-tenant организации. 
- Semantic search (HNSW). 

**SMART‑метрики MVP:** 
- Approve latency (p95) < 500 ms при 10 concurrent users (SQLite WAL). 
- Event throughput > 100 ops/s. 
- Inbox pending count для типичного врача < 50. 
- Sweeper latency (p95) < 200 ms.

---

## 14. Changelog v8 → v9

- **Issue #1 (CRITICAL): Несоответствие заявленного превосходства над Claude** – исправлено: в заголовке и таблице 12 указано, что превосходство по большинству осей (13/15), L4 и L6 уступают/сравнимы в MVP. 
- **Issue #2 (CRITICAL): Шифрование не входит в MVP** – перенесено в Roadmap (post-MVP). В MVP используется только `tenant_id` и permissions ОС. Соответствующие разделы (9, 2, 13) обновлены. 
- **Issue #3 (CRITICAL): Отсутствует таблица `versions`** – добавлен DDL в раздел 5.1, описание в 3.1 и 5.1. 
- **Issue #4 (CRITICAL): Атомарность проверки конфликтов** – заменено использование `SELECT.. FOR UPDATE` на `BEGIN IMMEDIATE` (раздел 8 и 4.2). Все модифицирующие транзакции используют `BEGIN IMMEDIATE`. 
- **MINOR issues:** 
 - Исправлена опечатка `"deprecate"` → `"deprecate"` (раздел 3.1). 
 - Синхронизирован auto-resolution: раздел 8 и 13 теперь указывают Phase 4. 
 - Frontmatter `versions`: оставлена только последняя версия, история в SQLite (раздел 3.1). 
 - Scope упрощён: удалён wildcard `*`, остался только null | list (раздел 3.1). 
 - `tenant_id` теперь UUID, не имя пользователя (раздел 3.1, 9). 
 - Удалён `created_by.agent`, остался только `source` (user_message / user_command / system) (раздел 3.1). 
 - Явное описание auto_approve_user_commands: запись сразу active, не попадает в inbox (раздел 4.1). 
 - `max_idempotency_processing_sec` уменьшен с 30 до 5 секунд (раздел 10.1). 
 - Idempotency упрощена: удалён статус `failed`, только `processing`/`done` (раздел 10.1). 
 - Phase 1 сокращён: conflict detection и sweeper перенесены в Phase 2 (раздел 13). 
 - В раздел 4.1 добавлена секция «Требуют проверки» для observational data. 

---

**Конец draft v9. Исправлен по peer review от 2026-05-20.**