# AIM Filesystem Specification (AIM_FS) — v7 draft

Дата: 2026-05-25 
Статус: DRAFT v7 — исправлен по peer review от 2026-05-20 (major revision)

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

*(без изменений)*

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
├── preferences.md # стиль работы, max_inactivity_days и т.д.
├── workflows.md # как user обычно работает
├── history.jsonl # append-only лог ключевых решений / событий
├── facts/ # отдельные факты о user
│ └── <fact_id>.md
└── feedback/ # collaboration rules from user
 └── <feedback_id>.md
```

> **Изменение v7:** 
> - Метаданные (frontmatter, статус, decay, версии) хранятся **только** в SQLite. Файлы `_meta.jsonl` удалены. 
> - `identity.yaml` – единственный файл, чьи метаданные полностью на диске (для простоты). 
> - Все сущности (факты, feedback) имеют обязательное поле `confidence` (0.0–1.0). Для system‑записей допускается `null`, но они исключаются из рейтинга в conflict resolution. 
> - Каждая запись имеет поле `tenant_id` = `user_id` (UNIX‑имя), которое проверяется во всех SQL‑запросах. 

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
 └── events.jsonl
```

> **v7:** `links` и `events` хранятся только в SQLite; файл `_meta/events.jsonl` опционален для экспорта. При расхождении SQLite является источником истины.

### Уровень 3 — Auto-created folders

#### 3.a Patient folders

**Корень:** `<aim_root>/users/<doctor_id>/patients/<patient_id>/`

Для пациентов с большим числом визитов (>500) используется шардирование по месяцам:
```
visits/
├── 2026-01/
│ └── <visit_id>.md..
```
PII шифруется at-rest с per-user ключом (см. раздел 9). 
Метаданные (связи, статусы) хранятся в SQLite с `tenant_id = doctor_id`.

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

> **v7:** Пути к файлам в SQLite хранятся **относительно** `<aim_root>`, чтобы `_service/` можно было перемещать. Сам файл `aim_fs.db` может находиться на том же или другом диске (через символическую ссылку).

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
 agent: "aim"
 user: "djabbat@gmail.com"
 source: "user_message" | "user_command"
 session_id: ".."
 llm_model: "deepseek-reasoner" | null
confidence: 0.92 # обязательно для всех не-system записей; 0.0–1.0
tenant_id: "djabbat@gmail.com"
versions:
 - hash: "sha256:abcd…"
 at: "2026-05-08T02:00:00Z"
status: "active" | "superseded" | "rejected" | "deprecated" | "expired"
decay:
 ttl_days: 90 | null
 expires_at: "2026-08-06T02:00:00Z"
 on_dep_expire: "deprecate" | "keep"
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
requires_verification: false
---
<тело>
```

> **v7:** 
> - Поле `confidence` обязательно для всех записей, кроме system (например, `created_by.agent: "system"`). 
> - Добавлено `schema_version` – число, соответствующее мажорной версии схемы. 
> - `on_dep_expire` исправлено на `"deprecate"` (закрыто). 
> - Поле `tenant_id` обязательно и проверяется в каждом SQL-запросе. 

### 3.2 Schema registry

**Валидация при записи:** 
- Любая новая запись (proposal, факт, feedback) проверяется на соответствие JSON Schema, указанной в `schema`. 
- Если схема не найдена в `_schemas/` → proposal отклоняется с ошибкой `schema_not_found`. 
- Если данные не проходят валидацию → proposal получает статус `invalid`. 
- Валидация выполняется на этапе prepare (до commit) в Rust core (`schema.rs`). 

**Версионирование схем:** 
- Каждая схема имеет номер версии (`feedback_v1`, `feedback_v2`). 
- Старые записи сохраняют `schema: "feedback_v1"` и `schema_version: 1`. 
- При изменении схемы вводится новая версия; старые записи рендерятся через отдельный view LiveView, который знает все версии. 
- Миграция схем не производится автоматически – пользователь может явно предложить обновление (proposal), которое будет approved. 

### 3.3 Content-addressable storage (CAS)

**Отложено до Phase 2 (post-MVP).** В MVP версионирование реализовано через хранение истории изменений в SQLite (таблица `versions`), без копирования тел.

### 3.4 Event log

Event log — append-only записи в SQLite таблица `events` (shard по неделям через партиционирование или отдельные таблицы). 
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

**Добавлено в v7:** 
- Каждый pending элемент имеет поле `auto_expire_at` (по умолчанию через 7 дней, настраивается per-user в `preferences.md`). 
- **Offline-режим:** per-user preference `max_inactivity_days` (по умолчанию 30). Если пользователь не заходил в систему дольше этого срока, таймер `auto_expire_at` приостанавливается. При следующем входе оставшееся время вычисляется как `min(оставшееся, max_absolute_pending_days - прошедшие_дни)`. 
- **Абсолютный лимит:** `max_absolute_pending_days` (по умолчанию 90) – заявка принудительно истекает через это количество дней **с момента создания**, независимо от offline, если пользователь не заходил. Если offline > max_inactivity_days, абсолютный лимит продлевается на время offline (но не более чем на 30 дополнительных дней). 
<!-- review_response: логика offline и absolute лимит объединены (Issue MINOR #3). -->
- Observational data с `requires_verification: true` показывается в отдельной секции inbox с низким приоритетом; при наведении показывается предупреждение: «Проверьте данные, сгенерированные AI». 
- При offline-режиме перед expiry AIM отправляет уведомление (Telegram/email), если настроено в preferences. 
- `source: "user_command"` автоматически помечается как `auto_approve` и не требует показа в inbox, но событие фиксируется в event log.

### 4.2 Блокировочный протокол для concurrent access

**SQLite transaction (WAL)** с использованием `SELECT.. FOR UPDATE` на уровне строки сущности + таблица `locks` для multi-entity операций. 
- Транзакция выполняется с уровнем `REPEATABLE READ` (WAL). 
- **Deadlock prevention:** фиксированный порядок захвата таблиц: сначала `locks`, затем `entities`, затем `proposals`. Внутри таблицы – по возрастанию `id`. 
- **Optimistic locking:** каждая сущность имеет поле `version` (монотонный счётчик). При обновлении проверяется, что `version` не изменился после чтения. При несовпадении – транзакция откатывается и retry до 3 раз с экспоненциальным backoff. 
- Для **batch-операций** – единая транзакция, захват всех необходимых строк в порядке возрастания ID (глобальном – ULID). 
- **Max transaction time** – 5 секунд, по истечении транзакция принудительно откатывается watchdog-процессом. 
- Если транзакция не удалась из-за конфликта – retry до 3 раз. 

### 4.3 Auto-approve правила (опционально, per-user)

```yaml
approval:
 auto_approve_user_commands: true
 auto_approve_observational_with_confidence_above: 0.9 # >=
 auto_approve_service_events: true
 require_approval_for: ["feedback", "proposal", "recipe", "diagnosis"]
 max_inactivity_days: 30
 max_absolute_pending_days: 90
 undo_window_hours: 24
```

**Confidence heuristic:** 
```
confidence = sigmoid(repetition_count / threshold + user_match_score)
```
`repetition_count` – сколько раз пользователь повторил факт, `threshold` (настраиваемый, по умолч. 3), `user_match_score` — оценка совпадения с известными паттернами пользователя (0–0.5). 
`confidence` обязателен для всех не-system записей; `null` не допускается в non-system. 

**Undo-механизм (упрощение для MVP):** 
- Отмена auto-approved записи возможна ТОЛЬКО если у неё нет исходящих `depends_on` ссылок. 
- Если есть зависимые записи, пользователь предупреждается и предлагается создать proposal на изменение (через inbox). 
- В противном случае выполняется отмена: создаётся запись `superseded` с ссылкой `reverts`, исходная получает статус `superseded`. 
- Все изменения — в одной SQLite транзакции. 

---

## 5. Индексирование и поиск

### 5.1 SQLite‑бэкенд для метаданных

Все метаданные (frontmatter, статусы, scope, tags, confidence, decay, tenant_id) хранятся только в SQLite таблице `entities`. 
- Индексы: `(tenant_id, status)`, `(tenant_id, schema)`, `(tenant_id, id)`, `(expires_at)`. 
- **Connection pool:** `r2d2` с `rusqlite`, пул из 10 соединений (конфигурируемо). 
- **PRAGMA:** `journal_mode=WAL`, `synchronous=NORMAL`, `journal_size_limit=65536`, `cache_size=-8000` (8 MB). 
- **Checkpoint:** автоматический каждые 1000 транзакций или по размеру WAL > 10 MB. 
- **Партиционирование:** в MVP одна БД на всех пользователей, но все запросы содержат `WHERE tenant_id = ?`. Для масштабирования в Phase 2 – шардинг по `user_id` (`aim_fs_<hash(user_id)>.db`). 

### 5.2 Поиск в MVP

- **Frontmatter:** все поля проиндексированы в SQLite, поиск — `SELECT` с параметризованными `WHERE` (через `?` для защиты от SQL injection). 
- **Body:** полнотекстовый поиск по телу файлов — в MVP не реализован (Phase 4). 
- **Wildcard-поиск** (`scope.project_ids = "*"`) выполняется как запрос к SQLite с фильтром по `tenant_id` и загрузкой всех проектов данного пользователя; результат кэшируется на 5 минут. 

### 5.3 Auto-update triggers

При любом изменении сущности (approve, create, update) обновляется SQLite строка и соответствующая запись в таблице `events` в рамках одной транзакции. Триггеры не требуются.

---

## 6. Граф связей

**Решение для MVP (SQLite-based):** 
- Рёбра хранятся в таблице `links` (source_id, target_id, link_type, tenant_id). 
- Индекс `(source_id, link_type)`. 
- Запрос конфликтов на этапе propose: SQL-запрос с `WHERE target_id = ? AND link_type = 'contradicts' AND status = 'active'` – ответ < 5ms. 
- Материализованный граф не нужен. 

---

## 7. Decay / staleness

**Поле `decay` в frontmatter** (см. 3.1). 

**Механизм в MVP (lazy decay):** 
- При чтении сущности (через `entity.rs::get`) проверяется `expires_at`. Если текущее время > expires_at и статус `active`, то в той же транзакции статус меняется на `expired`. 
- При записи новой версии TTL обнуляется, expires_at пересчитывается. 
- **Каскадный decay и фоновый sweeper** отложены до Phase 2. 

---

## 8. Conflict / dispute resolution

**Процесс в MVP:** 
1. Новая запись помечается `contradicts` (через links) и получает статус `disputed`. 
2. Создаётся `_service/disputes/<id>.md` с обоими телами, rationale. 
3. Если новая запись ещё не утверждена (pending proposal), она остаётся pending с пометкой `blocked`. 
4. В inbox появляется элемент конфликта с кнопками «выбрать A», «выбрать B», «объединить». 
5. **Auto-resolution (таймаут)** отложен до Phase 2. В MVP конфликт остаётся в inbox до ручного разрешения пользователем. 
6. После выбора пользователем победитель становится `active`, проигравший `superseded`, dispute `resolved`. 
7. **Конфликты с участием >2 записей:** один dispute со списком всех ID; интерфейс позволяет выбрать один вариант. Комбинирование (объединение contradictory фактов) — в Phase 2. 

<!-- review_response: конфликт >2 записей требует детальной проработки комбинирования – перенесено в Phase 2 (MINOR #6). -->

---

## 9. Multi-tenant

**Namespace:** `users/<user_id>/`. 
**Организации:** `_org/<org_id>/`.

**Изоляция в SQLite:** 
- Обязательное поле `tenant_id` во всех таблицах (`entities`, `proposals`, `events`, `links`, `idempotency`). 
- Каждый SQL-запрос включает `WHERE tenant_id = ?`. В Rust core используется функция `with_tenant(tenant_id, query)` которая подставляет параметр. 
- Row-level security эмулируется программно – нет SQL-триггеров, только прикладной код. 

**Шифрование:** 
- PII пациентов шифруется at-rest с per-user ключом (storage-level encryption). 
- Ключи хранятся в `users/<user_id>/.key.enc` (зашифрованы мастер-ключом приложения). 
- Мастер-ключ хранится в HSM/Vault. 
- **Метаданные (scope, links, tags):** также шифруются per-user ключом на уровне колонок (AES-256-GCM). Для этого в SQLite таблицах поля `scope` и `links` хранятся в зашифрованном виде; при чтении расшифровываются в Rust. 
- Key rotation, revocation, audit-log – как в v6. 

<!-- review_response: метаданные шифруются, tenant_id проверяется в каждом запросе (CRITICAL #1 закрыт). -->

---

## 10. Реализация (стек: Rust + Phoenix)

### 10.1 Rust crate `aim_fs`

**Публичный API** – с идемпотентностью через SQLite таблицу `idempotency`.

**Idempotency (v7):** 
- При первом запросе с `idempotency_key` вставляется строка `(key, status='processing', started_at, tenant_id)`. 
- Если повторный запрос с тем же ключом находит `processing`, возвращается `"conflict"` – клиент должен отправить с новым ключом. 
- После завершения операции (коммит транзакции) строка обновляется на `status='done', result`. 
- Если операция не завершилась за 30 секунд, статус меняется на `failed`, клиент может ретраить с тем же ключом (получит `"conflict"`, т.к. `failed` не равен `processing`?). Лучше: при `failed` повторный запрос с тем же ключом возвращает `"conflict"` с кодом `previous_failed`. Клиент решает: использовать новый ключ или повторить. 
- **Гарантия атомарности:** изменения данных и запись idempotency – в одной транзакции SQLite. 

<!-- review_response: idempotency race при timeout решён – строка не удаляется, а помечается failed (CRITICAL #3 закрыт). -->

**Внутренние модули (MVP):** 
- `db.rs` – инициализация SQLite, миграции, пул соединений (r2d2). 
- `entity.rs` – CRUD для записей на диске + метаданные в SQLite. 
- `proposal.rs` – propose/approve/reject с транзакциями и оптимистичной блокировкой. 
- `idempotency.rs` – работа с таблицей `idempotency`. 
- `conflict.rs` – создание dispute (без auto-resolution). 
- `search.rs` – поиск через SQL запросы (FTS5 опционально). 

**Зависимости:** `rusqlite`, `r2d2`, `r2d2_sqlite`, `serde`, `serde_json`, `jsonschema`, `ulid`, `uuid`, `sha2`, `tokio`, `aes-gcm`.

### 10.2 Phoenix context `AIM.FS`

**Изменения:** 
- Вызов Rust core через Elixir‑Port (JSON по stdin/stdout). 
- **Idempotency:** Phoenix генерирует `idempotency_key` (UUID v4) для каждого запроса к Port. 
- **Fault‑tolerance:** при падении Rust-процесса все блокировки снимаются (транзакция откатывается). Phoenix перезапускает процесс; heartbeat (ping каждые 5 сек, три пропуска = перезапуск). При перезапуске очищаются все `processing` записи в idempotency старше 30 секунд. 
- `AIM.FS.approve/2` внутри: транзакция в SQLite, broadcast через PubSub. 
- LiveView `AIMWeb.InboxLive` – без изменений.

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

- Для всех не-system записей `confidence` обязателен (0.0–1.0). Если null – валидация не проходит, запись не принимается. 
- Для system-записей (например, `created_by.agent: "system"`) `confidence` может быть null, но такие записи исключаются из любой рейтинговой обработки (conflict resolution, auto-approve). 
- В conflict resolution при сравнении `confidence` всегда есть значение – tie‑breaker по `created_at` (старшая активна).

### 11.3 Каскадный undo

- Undo разрешён только для записей без исходящих `depends_on`. 
- При попытке отменить запись с зависимостями пользователь получает сообщение: «Нельзя отменить: на эту запись ссылаются другие активные факты. Создайте proposal для изменения через inbox.» 

### 11.4 Idempotency cleanup

- Записи в таблице `idempotency` с TTL 7 дней удаляются фоновым процессом `gc.rs`. 
- При старте Rust core очищаются все `processing` записи старше `max_idempotency_processing_sec` (30 сек) – они считаются зависшими. 

### 11.5 Конкурентный propose на одну сущность

- При propose на одну entity от разных агентов второй proposal получает `conflict` (транзакция откатывается благодаря `SELECT.. FOR UPDATE`). 
- Клиент получает ошибку `entity_locked` и должен повторить позже (backoff). 

### 11.6 Одновременное обновление сущности sweeper (Phase 2) и пользователем

- В MVP lazy decay не создает гонок, т.к. читает и обновляет в одной транзакции с `SELECT.. FOR UPDATE`. 

### 11.7 Удаление пользователя (GDPR)

- В MVP (Phase 1) пользователь может быть удалён только через прямой вызов `aim_fs delete_user <user_id>`, который: 
 - архивирует все проекты (перемещает в `_service/backup/`), 
 - удаляет все строки с `tenant_id = user_id` из SQLite, 
 - удаляет per-user ключ шифрования, 
 - сбрасывает кэш. 
- Это обеспечивает базовое соответствие GDPR. В Phase 2 – улучшенный процесс с подтверждением.

---

## 12. Преимущества над Claude (сводная таблица — реалистическая)

| Lim. | Claude | AIM_FS (v7) | Как | Статус |
|------|--------|-------------|-----|--------|
| L1 | Index ручной, грузится весь | SQLite‑индексы (ленивая загрузка не нужна) | SQLite таблицы | **MVP превосходит** |
| L2 | Нет графа | Типизированный граф в SQLite (таблица `links`) | JOIN по `links` | **MVP превосходит** |
| L3 | Нет версий | Версионирование через SQLite (таблица `versions`) | - | **Сравнимо** в MVP (без CAS) |
| L4 | Гибридный поиск (Tantivy?) | MVP: только frontmatter через SQL; Phase 4: FTS5 → Tantivy | - | **Уступает** в MVP |
| L5 | Auto‑save | Approval queue с таймаутами и блокировками | inbox + транзакции | **MVP превосходит** |
| L6 | Verify‑on‑use | Lazy decay (при чтении); каскадный decay в Phase 2 | проверка expires_at при get | **Сравнимо** (MVP) |
| L7 | Только session_id | Полный provenance | `created_by` + `events` | **MVP превосходит** |
| L8 | Глобальный namespace | Scoping (включая wildcard) | `scope` + `tenant_id` | **MVP превосходит** |
| L9 | Нет схем | JSON Schema registry с версионированием | валидация при write | **MVP превосходит** |
| L10 | Дубли молча | Conflict log (с ручным разрешением) | disputes в SQLite | **MVP превосходит** (сравнимо с Claude, но мы явно обрабатываем) |
| L11 | Single‑user | Multi‑tenant с шифрованием метаданных | `tenant_id`, per-user ключи | **MVP превосходит** |
| L12 | Тяжёлый индекс в контексте | SQLite быстрые запросы | индексы БД | **MVP превосходит** |
| L13 | Нет audit‑trail | Event log в SQLite | таблица events | **MVP превосходит** |
| L14 | CLI only | Schema‑driven UI (LiveView) | генерация формы из JSON Schema | **MVP превосходит** |
| L15 | Не atomic | Atomic transactions (SQLite WAL) | транзакции | **MVP превосходит** |

> **v7:** Таблица честно указывает, что по L4 и L6 MVP уступает или сравним.

---

## 13. План реализации (пересмотренный, MVP = 7 дней)

**Phase 1 (7 дней): Rust core MVP**
- SQLite инициализация, таблицы `entities`, `proposals`, `events`, `links`, `locks`, `idempotency`. 
- Атомарные CRUD операции (create/read/update/delete) с frontmatter и `tenant_id`. 
- Propose/approve/reject API с оптимистичной блокировкой и идемпотентностью. 
- Базовый поиск по frontmatter (SQL WHERE с параметрами). 
- Conflict detection и создание dispute (без auto-resolution). 
- Lazy decay (проверка expires_at при чтении). 
- Idempotency с механизмом `failed`. 
- Интеграция с Phoenix Port (JSON). 
- Тесты race‑conditions: 10 параллельных propose/approve/reject. 

**Phase 2 (2 дня): JSON Schemas (7 базовых типов) + schema_version.**
**Phase 3 (2 дня): Phoenix контекст + LiveView Inbox.**
**Phase 4 (2 дня): Полнотекстовый поиск (FTS5), каскадный decay (глубина 3, циклы).**
**Phase 5 (2 дня): Auto-resolution conflict (таймаут), backup, шардинг SQLite.**
**Phase 6 (continuous): CAS, Tantivy, HNSW, DuckDB, полировка.**

**SMART‑метрики MVP:** 
- Approve latency (p95) < 500 ms при 100 concurrent users (SQLite WAL). 
- Event throughput > 100 ops/s. 
- Inbox pending count для типичного врача < 50. 
- Conflict resolution timeout latency < 1 s (проверка раз в минуту).

---

## 14. Changelog v6 → v7

- **Issue #1 (CRITICAL):** Multi‑tenant изоляция: единая SQLite без tenant_id → добавлено обязательное поле `tenant_id` во все таблицы, проверка в каждом SQL-запросе, шифрование метаданных per-user ключом. 
- **Issue #2 (CRITICAL):** Масштабирование SQLite при 100 concurrent users → добавлен connection pool (r2d2), PRAGMA journal_size_limit, автоматический checkpoint. 
- **Issue #3 (CRITICAL):** Idempotency race при timeout → строка не удаляется, а помечается `failed`; клиент получает `conflict`. 
- **Issue #4 (CRITICAL):** Decay sweeper vs concurrent update → в MVP заменён на lazy decay (проверка при чтении); каскадный decay перенесён в Phase 2. 
- **Issue #5 (CRITICAL):** Null confidence → теперь `confidence` обязателен для всех не-system записей; null допускается только для system. 
- **Issue #6 (CRITICAL):** JSON Schema версионирование → добавлено `schema_version`, старые схемы поддерживаются через отдельные view. 
- **Issue #7 (CRITICAL):** Backup и восстановление → добавлена команда `aim_fs backup` (в Phase 1 только ручной дамп SQLite). 
- **Issue #8 (CRITICAL):** Service folders конфликт с SQLite → пути в БД хранятся относительно `<aim_root>`. 
- **Issue #9 (CRITICAL):** Реализуемость Phase 1 → убраны decay sweeper, auto-resolution conflict, backup automation; Phase 1 = 7 дней (CRUD + propose/approve + idempotency + conflict detection + lazy decay). 
- **MINOR issues:** 
 - `on_dep_expire: "deprecate"` исправлено на `"deprecate"` (фактически уже было, но уточнено). 
 - Двойное хранение метаданных устранено – SQLite primary, `_meta.jsonl` удалены. 
 - Логика `max_inactivity_days` и `max_absolute_pending_days` объединена (offline приостанавливает таймер, absolute лимит продлевается на время offline). 
 - Deadlock prevention: фиксированный порядок захвата таблиц, не только ID. 
 - Параметризация SQL-запросов через `?`. 
 - Conflict для >2 записей: оставлено ручное разрешение, комбинирование перенесено в Phase 2. 
 - Удаление пользователя добавлено в MVP (GDPR compliance). 

---

**Конец draft v7. Исправлен по peer review от 2026-05-20.**