# AIM — Production Deploy Checklist

State as of 2026-05-02. Stack: 6 Rust crates + 4-app Phoenix umbrella.
**Do NOT skip any item below for live patient data.**

## 0. Pre-flight

- [ ] Backup existing `aim.db` (the new stack reuses it; one bad migration ruins everything).
 ```sh
 cp ~/Desktop/LongevityCommon/AIM/aim.db ~/Desktop/LongevityCommon/AIM/aim.db.backup-$(date +%Y%m%d)
 ```
- [ ] Backup `~/.aim_env` if you'll be editing it.
- [ ] Confirm `cargo` and `mix` toolchains are present:
 `cargo --version && mix --version && elixir --version`

## 1. Secrets

- [ ] Run `scripts/setup_keys.sh` — populates `~/.aim_env` with `chmod 600`.
 Mandatory for prod: at least ONE of `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY`.
- [ ] **Phoenix `SECRET_KEY_BASE`** — generate via `mix phx.gen.secret` and set in `~/.aim_env`.
- [ ] **`PHX_HOST`** — public hostname (e.g. `aim.example.com`).
- [ ] **`AIM_ENV=prod`** — flips Rust services into strict CORS mode.
- [ ] **`AIM_REQUIRE_AUTH=1`** — gateway requires bearer token on all `/api/v1/{chat,diagnose}` calls.
- [ ] **`AIM_CORS_ORIGIN`** — single origin allowed in prod (default `http://127.0.0.1:4002`).

## 2. Database

- [ ] Migrations applied: `cd phoenix-umbrella && mix ecto.migrate`
- [ ] At least one admin token issued:
 ```sh
 mix run -e 'IO.puts(elem(AimMemory.issue_token("admin","admin"),1))'
 ```
 Save the printed token in `~/.aim_env` as `AIM_USER_TOKEN=...`.

## 3. Build

- [ ] `cd rust-core && cargo build --release` (compiles 6 crates).
- [ ] `cd phoenix-umbrella && MIX_ENV=prod mix release` (or run via `mix phx.server` for dev-prod).

## 4. systemd deployment

```sh
sudo cp deploy/systemd/aim-*.service deploy/systemd/aim.target /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aim.target
sudo systemctl start aim.target
journalctl -fu aim-llm aim-doctor aim-phoenix
```

## 5. Health-check

- [ ] `scripts/smoke.sh` — passes with 0 failures.
- [ ] `curl https://aim.example.com/api/v1/system/health` — `overall_status=ok`.
- [ ] `curl http://127.0.0.1:8770/metrics | head` — counters non-empty after a real request.

## 6. Hardening

- [ ] systemd: every unit has `NoNewPrivileges=true`, `ProtectSystem=strict`, `PrivateTmp=true`,
 scoped `ReadWritePaths` (already in `deploy/systemd/`).
- [ ] aim-generalist: `AIM_GENERALIST_ROOT=$HOME/Desktop/LongevityCommon/AIM/Patients` —
 sandbox confines read_file / write_file. Confirmed via `tests/sandbox_tests.rs`.
- [ ] Reverse proxy (nginx/caddy) terminates TLS. Phoenix runs on `127.0.0.1:4002` and
 `127.0.0.1:4003` ONLY in prod (see `runtime.exs`).
- [ ] HSTS, CSP, X-Frame-Options, X-Content-Type-Options applied automatically by
 `AimWeb.Plugs.SecurityHeaders` when `AIM_ENV=prod`.
- [ ] Rate limit: `AIM_RPM_USER=60`, `AIM_RPM_IP=30` (defaults). Tune based on real load.
- [ ] Telegram webhook: set `TELEGRAM_WEBHOOK_SECRET` and configure
 `setWebhook` with the `secret_token` parameter. Without secret, webhook accepts
 any caller (dev mode).

## 7. Monitoring

- [ ] Prometheus scraping `127.0.0.1:8770-8774/metrics`. Add to `prometheus.yml`:
 ```yaml
 scrape_configs:
 - job_name: aim
 static_configs:
 - targets: ['127.0.0.1:8770','127.0.0.1:8771','127.0.0.1:8772',
 '127.0.0.1:8773','127.0.0.1:8774']
 ```
- [ ] Alerts on:
 - `aim_requests_total{status="all_failed"}` rate > 0 over 5min.
 - `aim_upstream_calls_total{outcome="fail"}` rate > 1/min.
 - Health endpoint returning non-200 for 2 consecutive checks.
- [ ] Logs: journalctl + log rotation (default systemd handles).

## 8. Backups

- [ ] Daily `aim.db` snapshot: cron entry copying to off-host storage.
- [ ] Patients/ folder daily rsync to encrypted backup (NEVER push to public git).
- [ ] `aim_rag.db` (vector store) daily snapshot.
- [ ] Test restore quarterly.

## 9. Decision-kernel laws (CLAUDE.md)

- [ ] L_PRIVACY: every AI-generated egress passes `kernel_check action=email_send|...`
 with `text` containing any patient path / phone / DOB ⇒ requires `privacy_consent=true`.
- [ ] L_CONSENT: `gmail_send` requires explicit `user_confirmed=true` arg + valid
 `GMAIL_*` env (see scripts/setup_keys.sh).
- [ ] L_VERIFIABILITY: every PMID/DOI in output must come from `verify_pmid` or
 `verify_doi`. The `kernel_check` tool flags unverified citations.

## 10. Minimum viable smoke test before go-live

```sh
scripts/smoke.sh # 5 health + functional checks
mix test # 37 Phoenix tests
cd rust-core && cargo test # 35+ Rust tests
curl -X POST http://127.0.0.1:4003/api/v1/chat \
 -H "Authorization: Bearer $AIM_USER_TOKEN" \
 -H "content-type: application/json" \
 -d '{"messages":[{"role":"user","content":"ping"}]}'
```

## 11. Rollback

If anything breaks within 24h of deploy:
```sh
sudo systemctl stop aim.target
cp ~/Desktop/LongevityCommon/AIM/aim.db.backup-YYYYMMDD ~/Desktop/LongevityCommon/AIM/aim.db
git -C rust-core checkout <prev-commit>
git -C phoenix-umbrella checkout <prev-commit>
sudo systemctl start aim.target
```

## Known limits (not blockers but track)

- `aim_rag` is in-memory cosine — fine to ~100k vectors, swap for `sqlite-vec` beyond.
- LLM cache (SQLite `llm_cache`) has no TTL pruning yet — manual `DELETE FROM llm_cache WHERE created_at < date('now','-30 days')` periodically.
- No automatic Telegram bot heartbeat — if the bot's webhook endpoint goes down, manually re-set via `curl -X POST https://api.telegram.org/bot$TOKEN/setWebhook -d url=...`.
- `apply_patch` is line-based; no rename detection (use bash + git mv for renames).
