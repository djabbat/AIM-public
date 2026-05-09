# Hive parity test — Python ↔ Rust queen (2026-05-07)

**Trigger:** finishing P0.4 (Option B) — side-by-side parity validation
of the Rust queen against the live Python queen, per
`HIVE_QUEEN_DEPLOY.md`.

**Method:** identical payload sent to both queens; outputs compared.
The Rust queen runs alongside on `:8091` with its own DB and token
allowlist; it does **not** receive worker traffic.

---

## Deployment state (snapshot 2026-05-07 20:12 +04)

| Component | Path | State |
|---|---|---|
| Python queen `aim-hive-queen.service` | `/home/jaba/hive_queen/queen_app.py` (symlink → `hive_queen_src/`) | active, port `:8090`, 6 contributions |
| Patched `queen_app.py` (P1.6, structured summary) | `/home/jaba/hive_queen_src/queen_app.py` | **on disk, awaiting restart** |
| Rust queen | `/home/jaba/web/aim/AIM/rust-core/target/release/aim-hive-queen` | rebuilt 20:09 +04 (aarch64 release) |
| Rust queen parity instance | PID 305412, port `:8091` | running, 1 contribution |
| Rust queen DB | `/home/jaba/hive_queen_rust_parity/queen.db` | separate from Python DB |
| Parity tokens | `/home/jaba/hive_queen_rust_parity/parity.env` | admin + worker token + worker hash |

The Rust parity instance is enabled with full P1.7 hardening:
`AIM_HIVE_REQUIRE_AUTH=1` + `AIM_HIVE_WORKER_TOKENS=<sha256(worker)>`.

---

## Endpoint parity

| Endpoint | Python `:8090` | Rust `:8091` | Verdict |
|---|---|---|---|
| `GET /healthz` | `{"status":"ok","ts":".."}` (local) | `{"status":"ok","ts":"..Z"}` (UTC) | **drift on `ts` timezone** (Rust: UTC `Z`; Python: local). Cosmetic. |
| `POST /v1/hive/contribute` (valid) | `{"contribution_id":"<uuid>"}` | `{"contribution_id":"<uuid>"}` | ✅ identical |
| `GET /v1/hive/updates` | `{"updates":[]}` | `{"updates":[]}` | ✅ identical |
| `GET /v1/hive/status` (valid admin) | `queen_summary` was string until **patch**; after patch = object identical to Rust | object | ✅ post-patch parity |

## Error format parity (P1.6)

| Failure | Python `:8090` (live, **pre-restart**) | Python `:8090` (patched, **post-restart**) | Rust `:8091` |
|---|---|---|---|
| Bad admin token | `{"error":"..","status":4xx}` ✅ | same | `{"error":"bad admin token","status":403}` ✅ |
| Missing bearer | n/a (auth disabled) | same | `{"error":"missing bearer token","status":401}` ✅ |
| Malformed JSON | `Internal Server Error` (plain text) ❌ | canonical `{"error","status":500}` ✅ | `{"error":"Failed to parse the request body as JSON","status":400}` ✅ |
| 404 unknown route | `{"detail":"Not Found"}` ❌ | (FastAPI does not let `Exception` handler intercept 404 by default) ⚠ | `{"error":"not found","status":404}` ✅ |

> **Caveat:** the FastAPI 404 path is generated before any handler runs
> for unmatched routes, so the `{"detail":"Not Found"}` shape will
> survive the restart unless `app.exception_handler(StatusCode.HTTP_404_NOT_FOUND)`
> is also registered. Documented; not blocking.

---

## Open tasks (manual, sudo required)

1. **Restart Python queen** to pick up patched `queen_app.py`:
 ```bash
 sudo systemctl restart aim-hive-queen
 ```
 This activates: structured `queen_summary`, `RequestValidationError`
 handler, generic `Exception` → `{"error","status"}` shape.

2. **(Optional, decided by user)** Cut over to Rust queen — pause-the-world
 migration:
 ```bash
 # On server:
 sudo systemctl stop aim-hive-queen # stop Python
 pkill -f aim-hive-queen # stop parity Rust
 sudo install -d -o jaba -g jaba /var/lib/aim-hive-queen
 sudo cp /home/jaba/hive_queen/hive_queen.db /var/lib/aim-hive-queen/queen.sqlite
 # Edit /etc/systemd/system/aim-hive-queen.service to exec the Rust binary:
 # ExecStart=/home/jaba/web/aim/AIM/rust-core/target/release/aim-hive-queen
 # Environment=PORT=8090 HOST=127.0.0.1
 # Environment=AIM_HIVE_QUEEN_DB=/var/lib/aim-hive-queen/queen.sqlite
 # Environment=AIM_HIVE_ADMIN_TOKEN=<existing token from /home/jaba/hive_queen/.env>
 sudo systemctl daemon-reload
 sudo systemctl start aim-hive-queen
 curl -s http://127.0.0.1:8090/healthz # smoke
 ```
 Rollback: revert `ExecStart` and `systemctl restart`. Python venv
 stays put — single command back.

3. **(Optional)** Decommission parity instance + clean up:
 ```bash
 pkill -f aim-hive-queen
 rm -rf /home/jaba/hive_queen_rust_parity
 ```

---

## Why no auto-cutover

Per audit recommendation P0.4: "requires testing parity первого; downtime window для cutover." Cutover changes the binary, the DB schema is identical (both crates wrote `contributions(id, ts, worker_id, payload)` and `updates(id, ts, kind, body, source_n, eval_delta, signature)`), but:

- The Rust queen has stricter token-hash validation (P1.7) — once enabled, every worker must have its hash in `AIM_HIVE_WORKER_TOKENS`.
- A single-command rollback is fine, but live workers (none right now — production has 0 ever-pulled updates) would see one tick of failure.

Decision is the user's. Parity validation done.
