# AIM_FS hub-mode design

**Дата:** 2026-05-08
**Статус:** DRAFT (post-MVP, deferred until clinic deployment with N≥2 doctors)
**Цель:** запустить AIM_FS в multi-tenant конфигурации на shared hub, где каждый
доктор видит только свои данные, но org-shared protocols/feedback rules
доступны всем.

---

## 1. Текущее состояние (Phase A, single-user)

- `AimFs::open(path)` → одна SQLite БД, файлы под одним user/.
- Tenant_id во всех таблицах, но в single-user mode tenant_id = user_id == "djabbat".
- Phoenix `AimMemory.FS.Port` запускается на машине пользователя.
- `aim-fs-http` есть с Bearer-token, но один глобальный токен.

---

## 2. Hub mode — целевая топология

```
┌─ clinic.aim.example ─────────────────────────────┐
│ nginx (TLS termination) │
│ ├─ / → Phoenix AIM (LiveView UI) │
│ ├─ /api/v1/ → aim-fs-http (port 8770) │
│ └─ /telegram/ → aim-telegram-bot │
│ │
│ systemd --system services: │
│ ├─ aim-fs-http.service (Bearer auth) │
│ ├─ aim-fs-sweeper.timer (60s, all) │
│ ├─ aim-fs-backup.timer (daily) │
│ └─ aim-fs-self-dev-eval.timer (daily) │
│ │
│ Storage: │
│ /var/lib/aim_fs/ │
│ ├─ _service/db/aim_fs.db (shared SQLite WAL) │
│ ├─ _service/inbox/ │
│ ├─ _org/<org_id>/ │
│ └─ users/<doctor_uuid>/ │
└──────────────────────────────────────────────────┘
 ↑ ↑ ↑
 │ Bearer JWT │ Bearer JWT │ Bearer JWT
 │ │ │
 ┌────┴────┐ ┌─────┴────┐ ┌─────┴────┐
 │ Doctor A│ │ Doctor B │ │ Doctor C │
 │ laptop │ │ phone TG │ │ web UI │
 │ AIM CLI │ │ aim-fs-tg│ │ Phoenix │
 └─────────┘ └──────────┘ └──────────┘
```

---

## 3. Изменения относительно single-user

### 3.1 Auth
**Сейчас:** один `AIM_FS_HTTP_TOKEN` shared.
**Hub:** JWT per doctor, signed by hub. Phoenix wraps requests с
`Authorization: Bearer <jwt>` containing claims:
```json
{
 "sub": "djabbat", // tenant_id
 "org": "gla_clinic", // optional org membership
 "iss": "aim-hub",
 "exp": 1715200000,
 "scopes": ["aim_fs:read", "aim_fs:write", "aim_fs:approve"]
}
```

`aim-fs-http` валидирует:
- подпись (HS256 с shared secret OR RS256 с hub public key);
- `exp` не истёк;
- `scopes` содержит required для endpoint'а;
- `sub` совпадает с `tenant_id` в request body (предотвращает doctor A
 написать в storage doctor B).

### 3.2 Org-shared scope
Новый префикс `_org/<org_id>/` под `<aim_root>` для shared materials:
- protocols (общие SOP клиники);
- feedback_v1 правила org-wide ("все рецепты ≥ 14 days в advance");
- contact_v1 для общих контактов (lab, imaging center).

В SQLite: новая колонка `org_id TEXT` (NULL = не org-shared). Phase A
оставляет null. Hub mode populates её для `_org/` сущностей.

WHERE clause при чтении: `WHERE (tenant_id = ? OR (org_id = ? AND scope_org = 1))`.

### 3.3 Per-tenant rate limit
`aim-fs-http` добавляет middleware:
- 10 propose/sec per tenant (token bucket в memory)
- 100 search/sec per tenant
- 5 approve/sec per tenant

Превышение → HTTP 429 + `Retry-After`.

### 3.4 Connection pool
SQLite WAL → multi-reader, single-writer. Текущий r2d2 max=3
достаточен для single-user. Hub: **max=20**, write через global
mutex (BEGIN IMMEDIATE serializes в SQLite anyway; pool оптимизирует
read latency).

### 3.5 Audit log (org-level)
`_service/audit.jsonl` (append-only) логирует:
```jsonl
{"at":"..", "actor":"djabbat", "op":"approve", "tenant":"djabbat", "entity":"01HZ.."}
{"at":"..", "actor":"hub_admin", "op":"revoke_user", "tenant":"djabbat", "by":"admin@gla.org"}
{"at":"..", "actor":"system", "op":"sweeper_run", "expired":4, "stale":7}
```

Read-only endpoint `GET /v1/audit?since=<rfc3339>` для compliance.

### 3.6 Per-tenant DB option (Phase B)
Если PII-sensitive → `--per-tenant-db` flag: каждый tenant получает
свою sqlite файл в `<aim_root>/_dbs/<tenant>.db`. Tradeoff:
- (+) Cryptographic isolation (one PII breach != all)
- (–) Cross-tenant queries impossible (org-shared invariants harder)
- (–) DB count growth — N doctors = N pools

Default остаётся **single shared DB** с `tenant_id` enforcement.

---

## 4. Deployment topology

### 4.1 Single-machine (clinic с 2-5 docs)
- Один сервер (4 vCPU, 8 GB RAM, NVMe);
- nginx + systemd --system;
- `aim-fs-http.service` слушает на 127.0.0.1:8770;
- nginx proxy на :443;
- Phoenix запускается тоже на этой машине.

### 4.2 Distributed (clinic с 20+ docs)
- Hub server (Phoenix + aim-fs-http + nginx);
- DB server (SQLite на NVMe; WAL остаётся локально);
- Доступ к DB через SSH-tunnel + IP allowlist.

⚠ **Важно:** SQLite WAL не работает поверх NFS. Phase B encryption + per-tenant DBs снимают это ограничение, но в Phase A держим DB локально с
hub-server, не на сетевом storage.

### 4.3 HA / failover
SQLite не поддерживает sync replication out of the box. Hub mode HA:
- (a) Litestream → S3 / Hetzner storage box (replays WAL chunks);
- (b) `rsync --inplace` каждые 60s к standby;
- (c) `aim-fs-backup.timer` daily + manual recover.

Для Phase A (clinic): (b) или (c) достаточно. (a) для cloud deploy.

---

## 5. Phoenix `AimMemory.FS.Port` в hub mode

Сейчас один Port owned application supervisor на доктора (single-user).

Hub mode вариант: **per-request tenant** через HTTP, не через Port.
Phoenix в hub mode:
1. Получает `:authenticated_user_id` из JWT в plug.
2. Делает `HTTPoison.post(aim_fs_http, payload, [{"Authorization", "Bearer #{user_jwt}"}])`.
3. Никакого Port — `aim-fs-http` уже балансирует.

Plus: WebSocket inbox notifications через Phoenix.PubSub остаются —
hub Phoenix subscribes to `inbox:<tenant_id>` channel; aim-fs-http
сам бродкастит при подтверждениях, через Phoenix Channel back.

---

## 6. Migration single-user → hub

Шаги:
1. `aim-fs-backup` — снимок текущего ~/.aim_fs.
2. Установка hub (cargo build + systemd + nginx + Phoenix).
3. Восстановление: `aim-fs-restore --tar backup.tar --into /var/lib/aim_fs`.
4. JWT issuance: hub admin создаёт первого doctor user через `aim-fs-admin add-user djabbat`.
5. Update Phoenix config на доктора: указывает hub URL + JWT вместо
 локального Port.
6. systemd --user timers на машине доктора отключаются — hub'овые
 систем-мега-таймеры берут на себя sweeper / backup / self-dev.

Откат: `aim-fs-backup` в hub'е → `aim-fs-restore` обратно в `~/.aim_fs`.

---

## 7. Roadmap

| Фаза | Задача | Effort |
|---|---|---|
| H.1 | JWT auth в `aim-fs-http` + admin CLI | 2 дня |
| H.2 | `_org/` префикс + WHERE-расширение | 1.5 дня |
| H.3 | Per-tenant rate-limit middleware | 0.5 дня |
| H.4 | Audit log endpoint + SQL view | 1 день |
| H.5 | systemd --system units + nginx config | 1 день |
| H.6 | Phoenix hub-aware HTTP client (заменить Port на доктора) | 1.5 дня |
| H.7 | Litestream / standby (опционально) | 1.5 дня |
| H.8 | Migration playbook + tests | 1 день |
| H.9 | Documentation: ops runbook, JWT bootstrap, recovery drills | 1 день |

**Итого:** ~11 дней одного fullstack разработчика. Можно совместить
с Phase B (encryption) для clinic-grade deployment.

---

## 8. Open questions

1. **JWT signing key** — HS256 (shared secret simpler) или RS256
 (key rotation cleaner). Recommendation: **RS256 с rotated key
 в OS keyring** (совместимо с Phase B).

2. **Org membership lookup** — hardcoded в JWT claims или таблица
 `org_members` в hub'овой DB? Recommendation: **отдельная таблица**
 (revoke без re-issue JWT всем pacient'ам).

3. **Cross-org sharing** — врач A в org1 ссылается на feedback из
 org2's `_org/`. Phase A: запрещён. Phase B: explicit grant через
 admin UI.

4. **Patient PII в hub** — должен ли каждый doctor видеть всех
 пациентов клиники, или только своих? Default: **только своих**
 через `scope_user_ids = [doctor]`. Org-wide patients — отдельный
 sharing flow.

5. **Read replicas для analytics** — для Ze·Profile агрегатов и
 eval. Litestream → read-only replica, ZeAggregator читает
 replica, AIM_FS прод писать туда не пытается.
