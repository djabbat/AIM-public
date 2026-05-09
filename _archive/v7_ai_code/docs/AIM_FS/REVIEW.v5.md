## VERDICT

**MAJOR_REVISION** 
Документ демонстрирует глубокую проработку, но содержит несколько неисправленных race conditions и недоговорённостей, которые приведут к неконсистентности данных в production. Без их устранения submission не может быть принят.

## SCORES (1–5)

| Критерий | Оценка | Краткое обоснование |
|----------|--------|---------------------|
| Соответствие требованиям задачи | 5 | Все три уровня, 15 осей превосходства — покрыто. |
| Архитектурная цельность | 4 | Логичная иерархия, но materialized contradicts index вносит излишнюю сложность для MVP. |
| Корректность (race conditions, atomicity, consistency) | 3 | Per-entity lock + prepare/commit — хорошая база, но критические дыры: отсутствие блокировки для входящего approve при уже запущенном sweeper на той же сущности; неопределённость при повторном запросе с idempotency_key пока операция in-flight. |
| Производительность (масштабируемость до 10⁵ записей) | 4 | Lazy sharding — сильно. Но full-scan body без индекса может стать узким местом при 10⁵ записях (p95 approve latency 500ms, но сканирование тела 10⁵ записей ~300ms — при конфликте нескольких approve latency взлетит). |
| Безопасность (PII, multi-tenant isolation) | 4 | Per-user ключи + HSM — хорошо. Side-channel через `/proc` и `flock` не обсуждается. Revocation не отменяет кэш в памяти Rust-core. |
| Простота (нет over-engineering) | 3 | Собственный CAS, materialized contradicts index, топологическая сортировка для decay — можно было проще: SQLite или DuckDB. |
| Соответствие стеку Rust+Phoenix | 4 | Elixir Port — разумно, но сериализация/десериализация JSON для каждой операции — overhead. Не хватает оценки latency этого канала. |
| Полнота (нет ли дыр в воркфлоу approval, conflict, decay) | 3 | Обнаружены дыры: обработка конфликтов с >2 записями (нет алгоритма выбора), каскадный decay глубины >3 приводит к неконсистентности (зависимые остаются active), conflict timeout при одинаковом confidence не специфицирован. |
| Реализуемость (можно ли построить за 7–10 дней?) | 2 | План насчитывает 22 дня (Phase 1–6). За 7–10 дней можно сделать только читаемый index + approval flow без conflict resolution, decay и CAS. |
| Мерябельность (как поймём что работает?) | 4 | Метрики SMART есть, но нет процедуры валидации консистентности данных после каждого approve (например, «сумма active dispute = 0»). |

## CRITICAL ISSUES

1. **Race condition между sweeper и approve (Section 7 + 4.2)** 
 Decay sweeper захватывает per-entity lock в порядке возрастания ID. Однако approve/reject также захватывают тот же lock. Если sweeper уже удерживает lock сущности A и пытается захватить lock B, а approve удерживает B и ждёт A — deadlock. Утверждается, что deadlock prevention через порядок ID, но **sweeper и approve не используют общий глобальный порядок** — sweeper проходит по всем сущностям циклически, а approve может захватить lock в другом порядке. Нет гарантии, что sweeeper не вызовет блокировку на минуты.

2. **Idempotency key при in-flight операции (Section 10.1)** 
 Если клиент отправляет approve с idempotency_key, а Rust-core начал выполнение, но ещё не записал результат в idempotency log, и приходит повторный запрос с тем же ключом — текущая реализация не различает «ещё выполняется» и «не начато». Может произойти double-write. Требуется состояние «processing» в idempotency log с таймаутом.

3. **Conflict resolution при >2 противоречащих записей (Section 8)** 
 Сказано: «создаётся один dispute со списком всех ID. Интерфейс позволяет выбирать один из вариантов или комбинировать.» Не определён **алгоритм автоматического выбора при таймауте** для N>2. Для двух записей есть правило (confidence >, age), для N — нет. Это приведёт к неконсистентному состоянию (dispute `resolved_unresolved`, но ни одна запись не superseded).

4. **Неатомарность batch-операций с блокировками в порядке возрастания ID (Section 4.2)** 
 Batch reject 10 proposals in inbox — захватывает locks в порядке возрастания ID. Но если два batch выполняются с разным набором proposals, порядок may differ (наборы перекрываются частично). Deadlock возможен. Требуется глобальный порядок по типу сущности + ID, либо single global lock для batch.

5. **Файловая блокировка flock не работает на распространённых файловых системах (Section 4.2)** 
 `flock` не поддерживается на FUSE/NFS (как minioclient/NFS) — типичные сценарии для облачного хранения. При использовании NFS lock будет игнорироваться, что приведёт к коррупции данных. Необходимо либо отказаться от flock и использовать advisory lock через `/tmp/.lock` (но это не атомарно), либо архитектурно перейти на SQLite/BoltDB (atomic commit).

6. **Materialized contradicts index не восстанавливается после сбоя (Section 6)** 
 Утверждается, что индекс «обновляется атомарно при каждом approve». Но при падении системы после rename шарда до записи в event log (или наоборот) — индекс может расходиться с event log. Восстановление не описано. Нужна процедура перестроения contradicts index из всех links.jsonl после старта (like `reconstruct_contradicts`).

7. **Decay sweeper не обрабатывает каскад с циклом (Section 7)** 
 Обнаружение циклов при топологической сортировке — хорошо. Но при обнаружении цикла действие не определено: запись в event log — ok, но зависимые записи остаются active. Это создаёт недетектируемое stale состояние, которое может долго влиять на поведение AI.

8. **Глобальный поиск не позволяет искать по всем проектам при указанном scope (Section 5.1)** 
 Утверждается, что глобальный запрос без scope ограничен frontmatter. Если пользователь хочет найти текст во всех своих проектах — нужно передавать `scope: {project_ids: "*"}`. Но в frontmatter поле `scope` может содержать `project_ids: ["*"]`? Не специфицировано, что такое "*". Если да, то index должен поддерживать wildcard — не описано.

9. **Миграция: дедупликация по (SHA, schema, scope) не учитывает конфликты (Section 10.3)** 
 Два файла с одинаковым SHA, schema и scope — это один и тот же факт? Но они могли содержать разные тэги, decay, links. Объединение в одну запись с версиями — потенциально теряем метаданные. Нужна стратегия слияния frontmatter (например, union tags, latest decay). Иначе миграция может привести к потере данных.

## MINOR ISSUES

- **Раздел 4.2**: `"Захват блокировки через flock; при недоступности — повтор через 50ms до 3 попыток, затем ошибка."` — retry 3 раза с 50ms — слишком жёстко. Для batch-операции с N locks вероятность успеха падает экспоненциально. Лучше экспоненциальный backoff до 3 попыток.
- **Раздел 3.1**: Поле `source` имеет значения `"user_message" | "user_command"`. Но нет `"user_command"` в примере. Добавить для ясности.
- **Раздел 10.1**: `"idempotency_key (ULID)"` — ULID не случаен (time-based), может быть предсказан. Лучше UUID v4 или salt + hash.
- **Раздел 5.2**: `"собственный grep на Rust"` — `ripgrep` (rg) быстрее, можно вызывать через Command. Но не критично.
- **Раздел 10.2**: `"Вызов Rust core через Elixir‑Port (запуск Rust binary как child_process, общение по stdin/stdout JSON)."` — нет упоминания о heartbeat/healthcheck. Что если Rust процесс завис (deadlock)? Phoenix не узнает. Добавить watchdog.

## STRONG POINTS

- **Idempotency + fault-tolerance** — ключевое улучшение v4, которое закрывает основную проблему повреждения данных при падении сети.
- **Per-entity lock вместо глобального** — снижает contention, хотя его реализация через flock проблемна (см. critical #5).
- **Глубина каскада decay = 3** — разумный компромисс, предотвращает O(n²).
- **Абсолютный лимит pending (max_absolute_pending_days)** — решает «вечные» proposals для offline-пользователя.
- **Undo-механизм с каскадом** — хорошо проработан, включая циклы.

## SUGGESTED ADDITIONS / SIMPLIFICATIONS

1. **Вырезать materialized contradicts index (Phase 1)**, заменить на full scan links.jsonl целевого шарда при propose. Для MVP (10⁵ записей) scan одного шарда ~1MB займёт <5ms. Это упрощает архитектуру, убирает проблему восстановления индекса и снижает сложность реализации на 2 дня. Оставить как Phase 5.
2. **Заменить flock на advisory locking через отдельный файл `.lock` с `O_CREAT | O_EXCL` + `rename`** — это работает на NFS (с оговорками) и не требует специфичного syscall. Альтернатива — перейти на SQLite (WAL) для всех метаданных, что решает проблемы atomicity и isolation.
3. **Добавить механизм «processing» для idempotency key**:
 - При первом запросе записываем `{"status": "processing", "started_at": timestamp}` в `_service/idempotency/<key>.json`.
 - Если повторный запрос с тем же ключом находит "processing" — возвращаем `202 Accepted` (или retry later).
 - После завершения — обновляем на `{"status": "done", "result":..}`.
 - Таймаут на "processing" — 30 секунд (конфигурируемо).
4. **Для conflict resolution при >2 записях** определить правило: при таймауте выбираем запись с наивысшим confidence; если равны — самую старую (по created_at). Остальные superseded.
5. **Добавить heartbeat между Rust и Phoenix**: Port отправляет каждые 5 секунд `{"type": "ping"}`; если три пинга пропущены — перезапуск child.

## SUFFICIENCY VS CLAUDE (15 осей)

| Ось | Преимущество AIM_FS? | Комментарий |
|-----|----------------------|-------------|
| L1: Lazy loading index | Да | Sharded + lazy — реальное отличие. |
| L2: Граф связей | Да | Typed links, materialized contradicts. |
| L3: Версионирование | Да | CAS + retention (у Claude нет). |
| L4: Поиск | Частично | MVP уступает по полнотекстовому поиску (Claude может использовать Tantivy?). Phase 5 обещает превзойти. |
| L5: Approval queue | Да | Inbox + lock — ключевое преимущество. |
| L6: Decay / staleness | Да | TTL + sweeper — Claude не имеет. |
| L7: Provenance | Да | events.jsonl + created_by — глубже, чем сессия. |
| L8: Scoping | Да | multi-scope (user/project/patient) — у Claude только global. |
| L9: Schema validation | Да | При записи — Claude не проверяет. |
| L10: Conflict resolution | Да | Логирование + таймауты — у Claude нет. |
| L11: Multi-tenant | Да | Per-user ключи, HSM. |
| L12: Lazy memory | Да | Sharded index — win ~10x. |
| L13: Audit trail | Да | Event log + replay. |
| L14: Schema-driven UI | Нет доказано | Упомянуто «в разработке». Нужен хотя бы минимальный прототип (JSON Schema → form) для доказательства. |
| L15: Atomic transactions | Да | Prepare/commit + per-entity lock + idempotency. |

**Вывод по 15 осям**: 13 осей — явное превосходство, 1 — частичное (поиск), 1 — не доказано (schema-driven UI). Чтобы закрыть L14, достаточно в spec добавить пример генерации LiveView формы из `feedback_v1.json` — иначе reviewer не примет утверждение.

---

**Общий вердикт: MAJOR_REVISION** — после исправления critical issues #1–#9 документ можно будет принять. Рекомендуется упростить архитектуру (убрать materialized contradicts index из MVP) и заменить flock на атомарный rename с advisory file lock (или SQLite).