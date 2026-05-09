# AIM_FS Phase B — per-user PII encryption

**Дата:** 2026-05-08
**Статус:** DRAFT (deferred from MVP per SPEC v11 §9 / §13)
**Скоп:** только PII полей пациентов; metadata (scope/links/tags) остаётся открытой.
**Triggers implementation:** multi-tenant rollout, GDPR compliance audit, или
clinical-data-sharing с external partner.

---

## 1. Постановка задачи

В MVP (SPEC v11) PII пациентов лежит в `users/<doctor>/patients/<key>/identity.toml`
открытым текстом. Изоляция между tenant'ами обеспечивается:
- правами FS (`0700` на user-папку);
- обязательным `WHERE tenant_id = ?` во всех SQL-запросах.

Этого достаточно для single-doctor / single-machine. Для:
- многопользовательского hub'а (Phase B),
- хранения на разделяемом диске,
- compliance-аудита (HIPAA / GDPR Art. 32 «pseudonymisation and encryption»),

нужно добавить шифрование at-rest для PII-фрагментов **без** ломая существующий
read-path AIM_FS.

---

## 2. Threat model

| Атакующий | Что защищаем | Что НЕ защищаем |
|-----------|--------------|-----------------|
| Backup / disk theft | identity.toml тел пациентов, ANAMNESIS.md, recipes, visits | metadata (scope_patient_ids, tags, схему) |
| Misconfigured `_org/` share | PII tenant A не должен быть доступен tenant B | граф связей (если оба tenant добавили cross-org link, факт связи виден) |
| Operator с root | НЕ защищаем (root читает память процесса) | — |
| Compromised master key | per-user keys — теряем всех; **mitigation:** rotation + revoke | — |

**Out of scope для Phase B:** memory-side encryption (root-resistant TEEs / SGX) —
требует отдельного проекта.

---

## 3. Архитектура

### 3.1 Ключевая иерархия

```
master_key (32 байта; в OS keyring через `secret-tool` / `keyring-rs`)
 │
 ├── seal(per_user_key_A) → users/A/_meta/key.enc
 ├── seal(per_user_key_B) → users/B/_meta/key.enc
 └── seal(per_user_key_C) → users/C/_meta/key.enc
```

- `master_key` хранится **только** в OS keyring (Linux: GNOME Keyring /
 Secret Service; macOS: Keychain; Windows: Credential Manager).
- `per_user_key` (32 байт AES-256) генерируется при создании user'а; шифрует
 все PII записи этого tenant'а.
- `key.enc` = `master_key` ⊕ (AES-GCM-256 wrap of per_user_key); дешифруется
 на старте Rust core; распакованный per_user_key живёт в RAM до завершения
 процесса (zeroize-on-drop через `secrecy` crate).

### 3.2 Что шифруется

**Шифруется:**
- `identity.toml` body
- `ANAMNESIS.md` body
- `consent.json` body
- `visits/*/intake.md` / `report.md` / `differential.md` body
- `recipes/*.md` body
- В SQLite: `entities.body` колонка для записей с `scope_patient_ids != []`

**Не шифруется:**
- Имена файлов / папок (folder name `Surname_Name_DOB` — ⚠ это PII, см. ниже)
- `entities.title` (используется в FTS5 search index)
- `entities.tags`, `scope.*`, `created_at`, `status`
- Event log (содержит entity_id, не body)
- `_service/db/aim_fs.db` schema/indexes

### 3.3 Folder name PII problem

Папка `Beridze_Keti_2026_03_12` уже содержит PII в имени. Phase B меняет
схему: при создании пациента вычисляется `patient_pseudonym = HMAC-SHA256(
master_key, surname + name + dob)[:16]` (128 бит, hex). Используется как
имя папки. Реальные имена живут только в шифрованном `identity.toml`.

Migration:
```bash
aim-fs-migrate-encrypt --aim-root ~/.aim_fs
# → переименовывает каждую papку в pseudonym, шифрует identity.toml,
# обновляет scope_patient_ids в SQLite на новые pseudonym'ы.
```

### 3.4 Шифр

- **AES-256-GCM** (RustCrypto `aes-gcm` crate; `aead::NewAead`)
- nonce: 12 байт случайных (per-message)
- tag: 16 байт
- AD: tenant_id || schema || entity_id (binds ciphertext to its row)

Wire format одной зашифрованной строки:
```
| magic(4) | version(1) | nonce(12) | ciphertext(N) | tag(16) |
| AENC | 01 |.. |.. |.. |
```

Magic `AENC` (0x41 0x45 0x4E 0x43) отличает зашифрованный body от plain
text при чтении (миграция читает оба формата).

### 3.5 SQLite-сторона

Колонка `entities.body` — `BLOB`-совместимый TEXT. При propose:
1. Если `scope_patient_ids != []` → шифруем body, кладём BLOB.
2. Иначе → plain text (как сейчас).

При чтении: проверяем magic; если `AENC`, расшифровываем; иначе plaintext.

FTS5 индексирует только title/description (которые остаются открытыми) +
плейсхолдер `[ENCRYPTED]` для body — search по PII не работает (это
сознательное trade-off; для PII-search нужен encrypted-search like CryptDB
в Phase C).

---

## 4. Key rotation

```
rotation:
 1. Generate new master_key_v2 (не трогая v1)
 2. Для каждого user:
 a. Decrypt key.enc (с master_key_v1) → per_user_key
 b. Re-seal: encrypt(per_user_key) с master_key_v2 → key.enc.v2
 3. Atomic swap: key.enc.v2 → key.enc (per user, файл-rename)
 4. Remove master_key_v1 from keyring
```

per_user_keys **не** меняются при ротации мастера — только их обёртка.
Это означает: тела файлов не нужно переписывать.

**Ротация per_user_key** (после revoke / compromise):
```
 1. Generate per_user_key_v2
 2. Re-encrypt every PII row of this tenant with key_v2
 (background job, single transaction per row)
 3. Update key.enc with v2 wrap
 4. Old key.enc.v1 retained for 30 days в _service/keys/archive/
 (для recovery от человеческой ошибки), затем удаляется
```

---

## 5. Revocation

User revoke (offboarding doctor leaving clinic):
```
 1. Mark tenant_id as revoked in `_service/revocations.jsonl`
 с timestamp + reason.
 2. Background job: re-encrypt все PII строки этого tenant'а с
 **fresh per_user_key_revoked**, ключ от которого НЕ сохраняется
 нигде → данные становятся недоступными (cryptographic erasure).
 3. SQLite строки помечаются status=`tenant_revoked` (не удаляются —
 нужны для аудита).
```

GDPR «right to be forgotten» implementation: revocation = cryptographic
erasure без физического удаления (audit trail сохраняется).

---

## 6. Audit

`_service/key_access.jsonl` (append-only, не шифруется — нужен для security
audit):
```jsonl
{"at":"2026-05-08T..", "op":"unwrap_user_key", "tenant":"A", "actor":"aim-fs-port", "ok":true}
{"at":"2026-05-08T..", "op":"decrypt_pii", "tenant":"A", "entity":"01HZ..", "actor":"InboxLive", "ok":true}
{"at":"2026-05-08T..", "op":"unwrap_user_key", "tenant":"B", "actor":"aim-fs-port", "ok":false, "reason":"tenant revoked"}
```

При >100 декриптов в минуту от одного process — `notify` warning (потенциальный
data exfil).

---

## 7. Rust crate: `aim-fs-crypto`

Новый under-crate (внутренний), отдельно от `aim-fs`:

```rust
pub struct CryptoCtx {
 pub master: secrecy::SecretBox<[u8; 32]>,
 pub user_keys: dashmap::DashMap<TenantId, secrecy::SecretBox<[u8; 32]>>,
}

impl CryptoCtx {
 pub fn open(aim_root: &Path) -> Result<Self> {
 let master = read_master_from_keyring?;
 Ok(Self { master, user_keys: Default::default })
 }

 pub fn user_key(&self, tenant: &str) -> Result<&secrecy::SecretBox<[u8; 32]>> {
 if let Some(k) = self.user_keys.get(tenant) {
 return Ok(k.value);
 }
 let wrapped = read_user_key_file(tenant)?;
 let key = unseal(&self.master, &wrapped)?;
 Ok(self.user_keys.entry(tenant.into).or_insert(key).value)
 }

 pub fn encrypt_pii(&self, tenant: &str, plaintext: &[u8], ad: &[u8]) -> Result<Vec<u8>>;
 pub fn decrypt_pii(&self, tenant: &str, ciphertext: &[u8], ad: &[u8]) -> Result<Vec<u8>>;
}
```

Зависимости (новые):
- `aes-gcm` 0.10
- `secrecy` 0.10
- `keyring` 3.x (Linux Secret Service / macOS Keychain / Windows Credential)
- `dashmap` 6.x
- `subtle` 2.6 (constant-time comparisons)

Размер: ~400 KB добавится к binary; в release с LTO.

---

## 8. SPEC.md изменения для Phase B

Один новый раздел:

> ### §9.1 Encryption (Phase B)
>
> Включается флагом `[encryption] enabled = true` в `_service/config.toml`.
> При первом старте после флага: aim-fs sets up master key in keyring,
> generates per_user_keys для всех существующих tenant'ов, шифрует
> существующие PII в-place via aim-fs-migrate-encrypt.
>
> После миграции: все новые PII шифруются автоматически. Старые plain-text
> body остаются читаемыми (магия AENC vs plaintext).

---

## 9. Reading-path performance

Encryption overhead для одного entity:
- AES-GCM-256 на современных x86_64 (AES-NI): ~1 GB/s → 5 KB body decryption ≈ 5 µs.
- Keyring read: amortized к 0 (DashMap cache, hit на 2-й запрос).

Без перекрытия с FTS5 search (search не трогает шифрованный body).

Ожидаемая регрессия: < 5 % p95 latency на propose/approve. SMART metrics
из SPEC §11 остаются достижимыми.

---

## 10. Roadmap

| Фаза | Задача | Effort |
|------|--------|--------|
| B.1 | aim-fs-crypto crate + smoke tests | 3 дня |
| B.2 | Wire encrypt/decrypt в propose / get_entity | 2 дня |
| B.3 | aim-fs-migrate-encrypt binary (in-place encryption) | 2 дня |
| B.4 | Pseudonym folder rename migration | 1 день |
| B.5 | Key rotation flow + audit log | 2 дня |
| B.6 | User revocation flow + cryptographic erasure | 1 день |
| B.7 | systemd unit для master-key bootstrap | 0.5 дня |
| B.8 | Documentation update (SPEC §9.1, README, ops runbook) | 1 день |

**Итого:** ~12.5 дней одного fullstack-разработчика.

---

## 11. Open questions

1. **Master key bootstrapping без интерактивности.** systemd-user сервис
 запускается без терминала; keyring запрос пароля невозможен. Решения:
 - (a) `pam-keyring` для авто-разблокировки на login;
 - (b) hardware token (Yubikey + PKCS#11);
 - (c) start-on-demand: aim-fs-port запускается из Phoenix-сессии
 (которая уже user-authenticated), а не как long-running daemon.
 Рекомендация: **(c)** для single-doctor; **(b)** для clinic.

2. **Cross-tenant search без расшифровки.** В Phase B полнотекстовый поиск
 по PII невозможен. Если нужен — Phase C / encrypted-search.

3. **Ze-Profile агрегация анонимных stats.** Если хотим отдавать в
 LongevityCommon агрегированные метрики (без PII), нужен слой
 anonymisation поверх decrypt. Не входит в Phase B; нужен отдельный
 crate `aim-anon-export`.

4. **Migration безопасность.** В момент `aim-fs-migrate-encrypt` старый
 plaintext и новый ciphertext оба на диске. Атомарность через
 `_service/tmp/` стэйджинг + atomic rename. Recovery: если миграция
 прервана — продолжается с последнего успешного entity_id (idempotent
 table).
