## VERDICT
**MAJOR_REVISION** 
(порог REJECT не перейдён только из-за тщательной декомпозиции проблем Claude и ясного видения целевой архитектуры; однако текущий spec содержит фундаментальные дефекты, не позволяющие принять его как реализуемый дизайн)

---

## SCORES (1–5)

| Критерий | Оценка | Обоснование |
|----------|--------|-------------|
| Соответствие требованиям задачи (3 уровня FS, превосходство над Claude) | 4 | Три уровня выделены чётко, таблица преимуществ над Claude — лучшая часть spec. Минус: явно не доказано превосходство по осям L5 (approval), L8 (scoping), L15 (atomicity) из‑за отсутствия деталей реализации. |
| Архитектурная цельность | 3 | Трёхуровневая модель и sharded index логичны, но смешение inode-подобной структуры (`projects/<slug>/_meta/links.jsonl`) и глобального графа (DuckDB) создаёт дублирование и синхронизационные издержки без объяснения, зачем это нужно. |
| Корректность (race conditions, atomicity, consistency) | 2 | Отсутствует описание стратегии блокировок для concurrent writes (Rust NIF + Phoenix LiveView могут вызывать `approve` одновременно). Упоминается `write-then-rename`, но последовательность `events.jsonl` + `INDEX.json` + `links.jsonl` неатомарна. |
| Производительность (масштабируемость до 10⁵ записей) | 3 | Sharded index — хорошая идея, но нет оценки количества shards, времени загрузки одного sharda, порогов ленивой загрузки. Отсутствует профилирование Tantivy vs. full scan для 10⁵ записей. |
| Безопасность (PII, multi-tenant isolation) | 2 | `identity.toml` назван «immutable PII (encrypted at rest)», но механизм шифрования, управления ключами и доступа внутри multi-tenant не описан. `shared_with` — лишь метка; нет модели авторизации. |
| Простота (нет over-engineering) | 1 | **Критически** завышена сложность для MVP 7–10 дней: DuckDB, Tantivy, HNSW, CAS, JSON Schemas, 3 вида индексов, background workers, NIF — 7 компонентов, каждый из которых требует недельной настройки. |
| Соответствие стеку Rust+Phoenix | 5 | Чёткое разделение Rust core (`aim_fs`) и Phoenix контекста (`AIM.FS`). Указан Rustler NIF. Это сильная сторона. |
| Полнота (дыры в воркфлоу approval, conflict, decay) | 3 | Approval queue описана, но отсутствует обработка офлайн-пользователя (pending висит вечно). Conflict resolution не имеет таймаута. Decay sweeper не объясняет, как влияет на inbox. |
| Реализуемость (за 7–10 дней) | 1 | План (Phase 1–8) предполагает примерно 9–10 дней, но каждая фаза содержит 3–4 нетривиальных компонента. DuckDB, Tantivy, NIF, LiveView с подписками — это реально 3–5 недель для команды из 2 человек. |
| Мерябельность (как поймём, что работает?) | 1 | Нет ни одного теста, метрики или критерия приемки. Даже базовый smoke‑test "after 10 concurrent proposals, inbox size = 10" не указан. |

---

## CRITICAL ISSUES

1. **Race condition в approval flow (sec 4.1 / 10.2)** 
 `AIM.FS.approve/2` вызывает Rust NIF, затем `Phoenix.PubSub.broadcast`. Если два воркера или LiveView-клиента одновременно аппрувят один и тот же proposal, нет блокировки — возможен двойной approve, дважды перемещённый файл, дубли в `events.jsonl`. Нужна блокировка на уровне файловой системы (flock) или optimistic concurrency с условием `cas` для proposal status.

2. **Неатомарная двухфазная операция (sec 4.1 / 10.1)** 
 При approve происходит: (a) перемещение файла из `_inbox/` в место назначения, (b) запись в `events.jsonl`, (c) обновление `INDEX.json`, (d) запись в `links.jsonl`. Если сбой между шагами (a) и (b), файл уже в projects, но событие не записано — потеря трассируемости. Нарушение ACID. Требуется prepare/commit pattern через временную папку + одно атомарное обновление индекса.

3. **Отсутствие обработки офлайн-пользователя (sec 4.1)** 
 Inbox подразумевает интерактивный UI. Если пользователь закрыл сессию или находится в офлайне, pending элементы висят бесконечно. Нужна концепция «автоотклонение через N дней» или «defer‑retry с уведомлением». Без этого поток останавливается.

4. **Nested transaction для conflict resolution (sec 8)** 
 Когда новая запись `contradicts` существующую, создаётся dispute. Но не указано, что происходит с pending proposal, который её породил. Если proposal ещё не утверждён, а уже конфликтует — должен ли conflict resolution блокировать approval? Или разрешаться до approve? Это порождает deadlock.

5. **DuckDB vs. filesystem dual‑write (sec 6)** 
 Граф хранится и в `links.jsonl`, и в DuckDB. Синхронизация основана на `_service/events/`. Нет гарантии eventual consistency: DuckDB может отстать на неопределённое время. Для 10⁵ записей постоянный репликационный лаг делает граф ненадёжным. Лучше отказаться от DuckDB на первом этапе и читать рёбра из файлов с LRU-кэшем.

6. **CAS и retention policy (sec 3.3)** 
 Каждая версия файла копируется в `_service/cas/`. Для 10⁵ записей с версиями (в среднем 2 версии) это ~200к мелких файлов. Нет политики очистки (GC) старых версий. Без неё за неделю диск заполнится. Кроме того, непонятно, как CAS взаимодействует с `svn/` — если файл переписан, старая версия в CAS, новая в рабочей папке; diff через sha256 — это хрупко.

7. **Автосохранение visit‑данных (sec 3.a)** 
 Раздел утверждает, что Tier 3.a (visit intake, CBC) автоматически сохраняется без approval. Но это противоречит L5 (approval queue). Чем рутинные данные отличаются от, скажем, user_fact с confidence 0.95, которое тоже может быть авто‑аппрувлено? Нет критерия. При этом PII-данные пациента записываются сразу — риск GDPR.

8. **Отсутствие метрик и бенчмарков (sec 11)** 
 Утверждается, что AIM_FS превосходит Claude по всем 15 осям, но нет никаких измерений. Какой latency у inbox? Сколько времени занимает approve? Какая пропускная способность событий? Без этого spec остаётся wishlist.

9. **Оценка реализуемости фазы 1 (sec 13)** 
 Фаза 1: «Rust crate минимум: atomic write/read, frontmatter parse/serialize, ULID/sha256, propose/approve/reject API, events.jsonl append». Даже без DuckDB и Tantivy это 5 несвязанных подсистем: разбор YAML frontmatter, JSON‑схемы, работа с файловой системой с блокировками, ULID + SHA256, append‑лог. Реализация за 1–2 дня невозможна.

10. **Партиционирование проектов с тысячами визитов (Открытый вопрос 9)** 
 Для пациента с 2000 визитами (`visits/YYYY-MM-DD-HH-MM/`) структура станет узким местом: миллион файлов, `events.jsonl` размером в гигабайты. Нет никакого решения для шардирования по временному диапазону или использования базы данных для таких записей.

---

## MINOR ISSUES

- **Непоследовательность naming**: в spec используется `aim_fs` (Rust), `AIM.FS` (Elixir), `AIM_FS` (заголовок). Рекомендую единый `AimFs`.
- **Избыточность `_meta/` директорий** – `links.jsonl` и `events.jsonl` дублируют глобальные `_service/..`. Разница не объяснена.
- **Формат `identity.toml`** – почему TOML, а не YAML/JSON, когда остальной frontmatter использует YAML? Единообразие снижает когнитивную нагрузку.
- **Frontmatter содержит `versions` как список** – если каждая версия копируется в CAS, то `versions` в файле не нужен; достаточно события.
- **11-файловое ядро проекта (Tier 2)** – жёстко задано; первые дни пользователь может не захотеть столько файлов. Лучше сделать минимальный набор из 3–4 (CONCEPT, STATE, TODO, README) с опциональным расширением.

---

## STRONG POINTS

- **Таблица 1.2 (15 проблем Claude → решения AIM_FS)** – лучшая часть дизайна. Чётко видно, какая ось как адресуется.
- **Трёхуровневая структура (profile / projects / auto)** – корректно разделяет ответственность: то, что изучает AI, то, что создаёт пользователь, и то, что генерируется автоматически.
- **Выбор Rust + Phoenix** – оправдан для производительности (Rust core) и UI (LiveView). Это не просто фреймворк, а ядро архитектуры.
- **Schard‑индекс** – правильно решает проблему L12 (весь индекс в контексте) и L4 (только скан имён).

---

## SUGGESTED ADDITIONS / SIMPLIFICATIONS

### Что вырезать (для реализуемости)

1. **DuckDB** – заменить на чтение `links.jsonl` в памяти с LRU-кешем. Репликация no‑operation до появления потребности в аналитике.
2. **Tantivy + HNSW embeddings на первом этапе** – заменить на полный scanning по shard-ам с grep/like (10⁵ записей с frontmatter занимают ~50 МБ; full scan на SSD < 100 мс, что приемлемо для MVP).
3. **CAS (`_service/cas/`)** – удалить до появления версионирования (версии можно хранить в самих файлах через git, но без CAS).
4. **Глобальный `_service/` с ротацией** – оставить только `events.jsonl` и `INDEX.json`. Остальное (`disputes/`, `backup/`, `tmp/`) избыточно для первого релиза.

### Что добавить

5. **Блокировочный протокол** – описать `flock` на файле `_service/.lock` для всех мутирующих операций (propose, approve, reject). Это решит race conditions без дополнительной инфраструктуры.
6. **Inbox-таймауты** – для каждого pending элемента: `auto_expire_at` (default 7 days). По expiry → status: `expired` или auto‑reject.
7. **Метрики успеха (SMART)** – например, `p95 latency approve < 500 ms`, `throughput events > 100 events/s`, `inbox pending count < 50` для типичного врача.
8. **Schema для `feedback_v1`** – добавить поле `confidence` (0.0–1.0) для AI‑inferred фактов.
9. **Простой тулчейн тестов** – `make test` с созданием временного `aim_root`, запуском 10 parallel propose/approve/reject и проверкой отсутствия дублей и согласованности счетчиков.

### Рекомендации по порядку имплементации (вместо 8 фаз)

- **День 1–3:** Rust core: файловая структура, frontmatter YAML, ULID, write‑than‑rename с lock, events.jsonl, propose/approve/reject (без DuckDB, CAS, эмбеддингов).
- **День 4–5:** Phoenix контекст `AIM.FS` через Elixir‑Port (Rust binary as child process, stdin/out JSON) + LiveView Inbox (всего 3 компонента: pending, approve, reject).
- **День 6–7:** Sharded INDEX.json + lazy loading; миграция legacy.
- **День 8–10:** Полировка: конфликты (dispute как pending), decay (простое поле `expires_at`), auto‑approve prefs, метрики.

---

## SUFFICIENCY VS CLAUDE

### Заявлено полное превосходство по 15 осям

| Ось | Доказано в spec? | Комментарий |
|-----|------------------|-------------|
| L1 (index) | ✅ – sharded index | Загрузка только релевантного sharda – существенно. |
| L2 (graph) | ✅ – links.jsonl + DuckDB (но последний не нужен) | Типизированные рёбра – улучшение. |
| L3 (versions) | ✅ – CAS + `versions[]` | Принято. |
| L4 (semantic search) | 🔸 – hybrid Tantivy+HNSW | Отсутствует бенчмарк; без Tantivy – только full scan, что не превосходит Claude. |
| L5 (approval) | 🔸 – inbox | Дыры: offline, concurrent approve, нет auto‑approve timer. |
| L6 (decay) | ✅ – TTL + sweeper | Принято. |
| L7 (provenance) | ✅ – `created_by` + events | Полное. |
| L8 (scoping) | ✅ – `scope` field | Чётко. |
| L9 (schemas) | ✅ – JSON Schema | Требуется runtime‑validtion (обещано). |
| L10 (conflict) | 🔸 – dispute log | Нет таймаута для unresolved; нет automatic hint. |
| L11 (multi‑tenant) | 🔸 – user_id namespace | Нет описания auth, key management, isolation. |
| L12 (lazy index) | ✅ – shards | Загрузка sharda – улучшение. |
| L13 (audit‑trail) | ✅ – events.jsonl + replay | Принято. |
| L14 (schema‑driven UI) | 🔸 – LiveView based on schema | Не описано, как UI генерируется из JSON Schema; это не автоматически. |
| L15 (atomicity) | ❌ – не доказано | write‑then‑rename не покрывает multi‑file operations; loss of events на сбое. |

**Вердикт по 15 осям**: 8 осей доказаны полностью, 6 – частично (требуют доработки), 1 (L15) – не доказана.

Для принятия submission необходимо закрыть дыры по L4, L5, L10, L11, L14, L15, либо сократить заявленные преимущества до реалистичного минимума.