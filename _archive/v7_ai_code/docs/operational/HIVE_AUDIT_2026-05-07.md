# Hive deep audit — 2026-05-07

**Scope:** worker / queen / consumer / protocol / storage / production state.
**Trigger:** user request «глубокий аудит сistemnosti, strukturnosti, logiki,
sootvetstvia, algoritmov, koda — включая queen серверную часть».

---

## Production reality (verified 2026-05-07 19:08 UTC+04)

| Item | Status | Evidence |
|---|---|---|
| `aim-hive-queen.service` (systemd) | active 3 days | `systemctl status` |
| Queen process | Python uvicorn (NOT Rust) | `ps -o cmd $MAINPID` |
| `https://hive.longevity.ge/healthz` | 200 OK | curl |
| `/v1/hive/contribute` | **401 missing bearer** (workers blocked) | curl probe |
| `/v1/hive/contribute` w/ admin token | **503 auth backend unavailable** | curl probe |
| `/v1/hive/status` w/ admin token | OK, **0 contributions / 0 updates** | curl probe |
| Queen DB на disk | **не существует** (нечего persist — никто не contribute) | `find /home/jaba ... -name *queen*db*` |
| Rust `aim-hive-queen` binary on server | built but **never deployed** | `ls /home/jaba/web/aim/AIM/rust-core/target/release/aim-hive-queen` |
| Worker auth backend | **broken** (responds 503 для worker tokens) | symptom: 503 above |
| `/` landing page | **broken** (404 — мой commit удалил queen_deploy/web/) | curl `/` |
| `queen_app.py` source | **deleted by overnight commit, RECOVERED 2026-05-07 19:10 в `/home/jaba/hive_queen_src/`** | symlink fix |

**Summary:** Hive подсистема formally live 3 days, но **0 contributions** обработано. Production is empty shell. Worker auth backend broken — даже если worker попытается, получит 503.

---

## Critical incidents (from this audit)

### Incident 1 — Inadvertent removal of queen sources (during overnight commit)

**Cause:** commit `db0dd3f` archived `AI/queen_deploy/` → `_archive/queen_deploy_2026-05-07/` локально, но **только в private clone**. Server pulled this commit; symlinks `/home/jaba/hive_queen/queen_app.py` + `web` стали dangling.

**Impact:**
- Queen process НЕ упал (Python loaded queen_app в memory before pull) → `/healthz` continues working
- Static `/` landing → 404 (StaticFiles middleware re-resolves directory dynamically)
- **На любом restart queen would fail to start** (queen_app.py source missing).

**Fix applied (2026-05-07 19:10):**
- Restored `queen_app.py` (200 LoC) from git commit `5d345f2` → `/home/jaba/hive_queen_src/queen_app.py`
- Restored `web/index.html` + `web/style.css` → `/home/jaba/hive_queen_src/web/`
- Updated symlinks `/home/jaba/hive_queen/queen_app.py` + `web` → new locations
- Verified `from queen_app import app` works (9 routes loaded)

**Still pending (requires sudo):**
- `sudo systemctl restart aim-hive-queen` — to pick up new symlinks (landing page back to 200)
- Without restart: API works (process held old refs); static `/` stays 404.

### Incident 2 — Worker auth backend down

**Symptom:** `POST /v1/hive/contribute` with valid admin Bearer token →
`{"error":"auth backend unavailable","status":503}`.

**Cause:** Python queen validates worker tokens via external auth backend
(хаб?), backend URL не configured / unreachable.

**Impact:** **NO worker can ever submit a contribution**. Auth-not-required
mode не активирован (`AIM_HIVE_REQUIRE_AUTH=0` отсутствует в `.env`).

**Fix path (manual, sudo required):**
```bash
echo 'AIM_HIVE_REQUIRE_AUTH=0' | sudo tee -a /home/jaba/hive_queen/.env
sudo systemctl restart aim-hive-queen
# Verify:
curl -X POST https://hive.longevity.ge/v1/hive/contribute \
 -H 'Content-Type: application/json' \
 -d '{"v":1,"worker_id":"WIRE_TEST_PROBE_8765","ledger":{"n_runs":0}}'
```
Expected: `{"id":"<uuid>"}` and queen DB created.

---

## Audit findings (with priority)

### P0 — Blocking

**P0.1 — Queen sources orphan-recovered, production restart will fail**
- Status: ✅ recovered 2026-05-07 19:10
- Verify with `sudo systemctl restart aim-hive-queen` after pulling fix on server.

**P0.2 — Worker auth backend broken; 0 workers can ever contribute**
- Status: documented, manual fix required (set `AIM_HIVE_REQUIRE_AUTH=0` or
 fix backend URL).
- Без этого — Hive — vapor: 0 contributions ever.

**P0.3 — Consumer crate имеет no binary**
- `aim-hive-consumer` — lib + state, but no `src/bin/`. Significa: nothing
 consumes published updates на worker side. Cycle разомкнут.
- Fix: добавить `src/bin/consumer.rs` (long-poll `/v1/hive/updates` + apply
 to local state).

**P0.4 — Python ↔ Rust queen drift**
- 2 implementations, only Python deployed; Rust binary built but unused.
- Fix path в `docs/operational/HIVE_QUEEN_DEPLOY.md` (existing). Migration
 → 1-week focused session, не overnight.

### P1 — Important

**P1.1 — `MIN_WORKERS_FOR_PATTERN = 2` (collusion attack vector)**
- File: `rust-core/crates/aim-hive-queen/src/distill.rs:18`
- 2 fake workers могут продавить `prompt_patch` candidate. Eval gate
 manual, но может быть автоматизирован.
- Fix: bump to `5`, make configurable via `AIM_HIVE_MIN_WORKERS_FOR_PATTERN`.

**P1.2 — `name_pair` PII pattern hard rejects legitimate data**
- File: `rust-core/crates/aim-hive-worker/src/scrub.rs:41`
- Regex `\b[A-Z][a-z]+ [A-Z][a-z]+\b` catches **any** Title Case bigram
 (e.g. "User Activity", "Linux Kernel" в reflexion themes). Hard reject =
 contribution lost.
- Fix: redact instead of reject; OR bump threshold (require ≥3 such matches
 before reject); OR semantic check (only reject если pattern в `notes`
 field, не в `theme` words).

**P1.3 — PII pattern gaps**
- Missing: IPv4 `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`, dates
 `\b\d{4}-\d{2}-\d{2}\b`, IDs `\b\d{9,12}\b` (SSN/INN/passport).
- Fix: extend `PATTERNS` in `scrub.rs`.

**P1.4 — No payload size limit на queen side**
- `accept_contribution` accepts arbitrary JSON. ⇒ DoS via large payload.
- Fix: cap `payload.len` ≤ 1 MB before INSERT.

**P1.5 — No queen DB backup strategy**
- DB single-file SQLite (`hive_queen.db`). No replication, no snapshot.
- Fix: cron `sqlite3 ... .backup` nightly; document в HIVE_QUEEN_DEPLOY.md.

**P1.6 — Error response format Python ↔ Rust differ**
- Python (FastAPI): `{"detail": "..."}`
- Rust: `{"error": "...", "status": N}`
- Workers parsing one format break on other. Pick canonical, port.

**P1.7 — Auth backend integration ill-defined**
- Worker token validation via "external auth backend" (currently 503).
- Should be: simple env-configured token list `AIM_HIVE_WORKER_TOKENS=`
 (newline-separated SHA-256 hashes), validated locally без external call.
- Eliminates `auth backend unavailable` failure mode.

### P2 — Cosmetic / future

**P2.1 — Update signature 24 hex chars (96 bits)**
- For 10⁶ updates: collision probability ~10⁻¹². OK.
- Could move to 32 hex (128 bits) for paranoid future-proof. Low ROI.

**P2.2 — Compliance drift threshold `0.5` magic number**
- File: `distill.rs:60`. Make configurable.

**P2.3 — DP linear basic-composition**
- ε=0.05/call × 1.0 budget = 20 calls. For hourly worker = 20 hours
 exhaustion, no recovery.
- Consider Rényi DP composition or daily refresh. Low urgency: 0 actual
 workers active.

**P2.4 — SQLite Mutex<Connection> bottleneck**
- Single-threaded queen. На low QPS (currently 0) — non-issue. На future
 >50 QPS — replace с `r2d2::Pool`.

**P2.5 — DiffDiagnosis + SSA not workers**
- Could contribute pattern signals (но нужно integration work).

---

## Production deployment options

### Option A — Stay on Python (current), apply minimal fixes

Pros: zero downtime risk, minimal complexity.
Cons: Python ↔ Rust drift continues; миграция откладывается indefinitely.

Steps (manual, sudo required):
```bash
# 1. Restart queen to pick up restored sources
sudo systemctl restart aim-hive-queen
# 2. Enable bootstrap auth mode (allow workers без external backend)
echo 'AIM_HIVE_REQUIRE_AUTH=0' | sudo tee -a /home/jaba/hive_queen/.env
sudo systemctl restart aim-hive-queen
# 3. Smoke
curl -X POST https://hive.longevity.ge/v1/hive/contribute \
 -H 'Content-Type: application/json' \
 -d '{"v":1,"worker_id":"WIRE_TEST_PROBE_8765","ledger":{"n_runs":0}}'
# Expected: {"id":"<uuid>"}
ls -la /home/jaba/hive_queen/hive_queen.db # DB now exists
```

### Option B — Migrate to Rust queen

Pros: end Python/Rust drift; better performance (Axum); fewer dependencies.
Cons: requires testing parity первого; downtime window для cutover.

Steps detailed в `docs/operational/HIVE_QUEEN_DEPLOY.md`. Summary:
1. Build Rust binary on server (already done).
2. Side-by-side deploy on alternate port (e.g. 8091) for parity validation.
3. Cutover via swap nginx upstream + restart workers.
4. Decommission Python queen.

---

## Action plan

### Manual (user, sudo required)

1. **Restart queen** to pick up restored symlinks: `sudo systemctl restart aim-hive-queen`
2. **Enable bootstrap auth**: `echo 'AIM_HIVE_REQUIRE_AUTH=0' | sudo tee -a /home/jaba/hive_queen/.env && sudo systemctl restart aim-hive-queen`
3. **Configure local worker**: `echo 'AIM_HIVE_QUEEN_URL=https://hive.longevity.ge' >> ~/.aim_env && bash scripts/deploy_aim_hive_worker.sh --user`
4. **Verify cycle**: see queen DB created + contribution accepted.

### Code-level (closed 2026-05-07, autonomous code session)

5. ✅ P0.3 — `aim-hive-consumer/src/bin/consumer.rs` (190 LoC, 5 subcommands).
6. ✅ P1.1 — `MIN_WORKERS_FOR_PATTERN` 2 → 5, env override `AIM_HIVE_MIN_WORKERS_FOR_PATTERN`.
7. ✅ P1.2 — `name_pair` switched to redact (`[redacted]` placeholder).
8. ✅ P1.3 — `ipv4` (Reject), `iso_date` (Redact), `long_id` 9-12 digits (Reject).
9. ✅ P1.4 — 1 MiB cap (env `AIM_HIVE_MAX_PAYLOAD_BYTES`); HTTP 413 + canonical body.
10. ✅ P1.5 — `HIVE_QUEEN_DEPLOY.md` § 5 — `sqlite3 .backup` cron + 14-day retention + restore.
11. ✅ P1.6 — Rust `JsonRejection` mapped + fallback 404; Python `RequestValidationError` + Exception handlers.
12. ✅ P1.7 — `AIM_HIVE_WORKER_TOKENS` SHA-256 hex allowlist; `require_worker_bearer` / `require_admin_bearer` helpers.

**Tests added:** 71 hive crate tests (was 0 binary, +everything).
**Regression:** ALL 3 BLOCKS PASS (Python 167 + 34 subtests · Rust 216 across 11 crates · Phoenix 23).

### Strategic (future)

13. P0.4 — Python → Rust queen migration (Option B). Requires 1-week
 focused session: side-by-side parity validation on alt port,
 nginx upstream cutover, decommission Python queen.
14. Evaluate если Hive subsystem worth keeping at all (3 дня live, 0
 contributions; if никто никогда не contribute → закрыть как vapor по
 аналогии с aim-media v7.2). Decision deferred until ≥1 real worker
 completes a full cycle (contribute → queen distill ≥5 workers →
 consumer pull → install).

---

## DeepSeek-reasoner findings (raw)

Saved at `/tmp/hive_audit_output.md` (server-side). 5 of 22 DeepSeek
findings were verified false-positive:
- **WRONG:** "auth disabled, anyone can POST" — actually 401 enforced.
- **WRONG:** "DP spend before scrub" — actual order: build (with scrub
 inside) → DP → POST. If scrub fails, return early до DP spend.
- Adjusted findings reflected above.
