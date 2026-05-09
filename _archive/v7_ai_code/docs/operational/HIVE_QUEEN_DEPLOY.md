# HIVE_QUEEN_DEPLOY.md — installing aim-hive-queen on a server

**Purpose:** stand up a remote/secondary host as the AIM Hive Queen
(Axum HTTP aggregator on port 8090). Workers (local AIM nodes) point at
it via `AIM_HIVE_QUEEN_URL=https://<host>:8090`.

**Date:** 2026-05-07. **Source-of-truth:** this doc → `scripts/deploy_hive_queen_remote.sh`
→ `deploy/systemd/aim-hive-queen.service`. Drift = update doc.

---

## Pre-flight

### On the local dev machine (where you build)

- Rust toolchain ≥ 1.78 (`cargo --version`)
- ssh access to the queen host
- Built binary at `rust-core/target/release/aim-hive-queen`
 (auto-built by deploy script if missing)

### On the queen host

- Linux x86_64, systemd ≥ 245
- sudo access via your deploy account (or root)
- Open inbound port: TCP 8090 (or whatever `PORT=` you set)
- Recommended: reverse proxy (Caddy/nginx) for TLS termination

---

## One-shot deploy

```bash
# From the local AIM repo:
bash scripts/deploy_hive_queen_remote.sh user@hive.example.com
```

The script:
1. Builds `aim-hive-queen` (release mode) if not already built.
2. Packages binary + systemd unit + env-template + on-host installer
 into `/tmp/aim-hive-queen-bundle-<TS>/`.
3. `scp`'s the bundle to the remote.
4. Runs the on-host installer (`install_remote.sh`) which:
 - Creates system user `aim`
 - Creates `/opt/aim-hive-queen/`, `/var/lib/aim-hive-queen/`, `/etc/aim/`
 - Installs binary + service unit
 - Creates `/etc/aim/hive_queen.env` from template (if missing)
 - `systemctl enable --now aim-hive-queen.service`
 - Smoke test `curl http://127.0.0.1:8090/healthz`

---

## Manual deploy (no scp)

```bash
# 1. Build bundle locally
bash scripts/deploy_hive_queen_remote.sh
# → outputs: /tmp/aim-hive-queen-bundle-<TS>/

# 2. Transfer (any method)
rsync -avz /tmp/aim-hive-queen-bundle-<TS>/ user@host:/tmp/queen-bundle/

# 3. Install on remote
ssh user@host
cd /tmp/queen-bundle
bash install_remote.sh
```

---

## Post-install hardening

### 1. Set admin token

The deploy creates `/etc/aim/hive_queen.env` from a template with a
randomly-generated `AIM_HIVE_ADMIN_TOKEN` placeholder. **Replace it**:

```bash
sudo /usr/bin/openssl rand -hex 32 > /tmp/admin_token
sudo /usr/bin/sed -i "s|^AIM_HIVE_ADMIN_TOKEN=.*|AIM_HIVE_ADMIN_TOKEN=$(/usr/bin/cat /tmp/admin_token)|" /etc/aim/hive_queen.env
sudo /usr/bin/rm /tmp/admin_token
sudo systemctl restart aim-hive-queen
```

Save the token to your local password manager — workers and admin
tooling will need it.

### 2. Worker authentication

For multi-tenant safety set `AIM_HIVE_REQUIRE_AUTH=1` in
`/etc/aim/hive_queen.env`. Then each worker host must set
`AIM_USER_TOKEN=<..>` in `~/.aim_env` (validated against your AIM hub
or by the queen's own token list — see `aim-common::auth`).

### 3. TLS via reverse proxy

Bind queen to loopback and front it with Caddy:

```caddy
# /etc/caddy/Caddyfile
hive.longevity.ge {
 reverse_proxy 127.0.0.1:8090
}
```

Then in `/etc/aim/hive_queen.env`: `HOST=127.0.0.1` (loopback only).

Workers use `AIM_HIVE_QUEEN_URL=https://hive.longevity.ge`.

### 4. Worker token allowlist (P1.7, 2026-05-07)

For multi-tenant safety set `AIM_HIVE_WORKER_TOKENS` in
`/etc/aim/hive_queen.env` to a newline- or comma-separated list of
SHA-256 hex hashes (64 chars each, lowercase). When non-empty, only
matching bearers are accepted; when empty + `AIM_HIVE_REQUIRE_AUTH=1`,
the queen falls back to legacy bootstrap (any non-empty bearer).

Generate a token + hash pair:

```bash
# Per worker — pick any random secret
WORKER_TOKEN=$(openssl rand -hex 32)
WORKER_HASH=$(printf %s "$WORKER_TOKEN" | sha256sum | awk '{print $1}')

# Hand $WORKER_TOKEN to the worker (goes into ~/.aim_env as AIM_USER_TOKEN)
# Append $WORKER_HASH to the queen's allowlist:
sudo /usr/bin/sed -i "/^AIM_HIVE_WORKER_TOKENS=/d" /etc/aim/hive_queen.env
echo "AIM_HIVE_WORKER_TOKENS=$WORKER_HASH" | sudo tee -a /etc/aim/hive_queen.env
sudo systemctl restart aim-hive-queen
```

For multiple workers, keep `WORKER_TOKENS=` as a multi-line value (env
file format supports `KEY="line1\nline2"` if you quote, or use
comma-separation: `KEY=hash1,hash2`).

Comment lines starting with `#` and blank lines are ignored.

### 5. Backup data

Queen state lives in `/var/lib/aim-hive-queen/queen.sqlite`. SQLite's
`.backup` command produces a consistent snapshot even while the queen is
writing — no need to stop the service.

```bash
sudo /usr/bin/install -d -o root -g root -m 0750 /var/backups/aim-hive-queen
sudo /usr/bin/crontab -e
# Add:
0 3 * * * sqlite3 /var/lib/aim-hive-queen/queen.sqlite ".backup /var/backups/aim-hive-queen/queen-$(date +\%F).sqlite" && find /var/backups/aim-hive-queen -name 'queen-*.sqlite' -mtime +14 -delete
```

Notes:
- `0 3 * * *` runs at 03:00 host time. Queen is single-writer so the
 backup blocks writes only briefly (sub-second at our payload sizes).
- `mtime +14 -delete` keeps two weeks of snapshots; tune to taste.
- Verify by listing once a week:
 `sudo ls -lah /var/backups/aim-hive-queen/`.

To restore from a snapshot:

```bash
sudo systemctl stop aim-hive-queen
sudo /usr/bin/cp /var/backups/aim-hive-queen/queen-2026-05-07.sqlite \
 /var/lib/aim-hive-queen/queen.sqlite
sudo /usr/bin/chown aim:aim /var/lib/aim-hive-queen/queen.sqlite
sudo systemctl start aim-hive-queen
```

### 6. Payload size cap (P1.4, 2026-05-07)

Default cap is 1 MiB per contribution (HTTP layer + lib-level). To
override (e.g. for higher-volume reflexion logs):

```
# /etc/aim/hive_queen.env
AIM_HIVE_MAX_PAYLOAD_BYTES=2097152 # 2 MiB
```

Anything above is rejected with `413 Payload Too Large` and a
canonical `{"error": "payload too large", "status": 413,..}` body.

### 7. Distillation threshold (P1.1, 2026-05-07)

Default `MIN_WORKERS_FOR_PATTERN=5` (was 2 — collusion attack vector).
Override only if you understand the trade-off:

```
# /etc/aim/hive_queen.env — risky, lowers collusion resistance
AIM_HIVE_MIN_WORKERS_FOR_PATTERN=3
```

---

## Smoke test

From any machine that can reach the queen:

```bash
# 1. Health check (no auth)
curl https://hive.longevity.ge/healthz
# → {"status":"ok","version":"0.1.0"}

# 2. Status (requires admin Bearer)
curl -H "Authorization: Bearer $AIM_HIVE_ADMIN_TOKEN" \
 https://hive.longevity.ge/v1/hive/status
# → {"contributions": N, "updates": M,..}
```

---

## Wire local AIM as worker

After queen is up, on each worker host:

```bash
# 1. Add queen URL + token to ~/.aim_env
echo 'AIM_HIVE_QUEEN_URL=https://hive.longevity.ge' >> ~/.aim_env
echo 'AIM_USER_TOKEN=<your-token>' >> ~/.aim_env

# 2. Install timer (one-shot service every hour)
bash scripts/deploy_aim_hive_worker.sh --user

# 3. Verify
systemctl --user list-timers aim-hive-worker.timer
journalctl --user -u aim-hive-worker -n 30
```

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `Address already in use :8090` | `ss -tlnp \| grep 8090` | another process bound — change PORT in env |
| `/healthz` 404 | `journalctl -u aim-hive-queen` | binary panicked; check stderr |
| Worker `AIM_HIVE_QUEEN_URL not set` | `cat ~/.aim_env` | add the line |
| 401 from `/v1/hive/contribute` | `AIM_HIVE_REQUIRE_AUTH=1` set | add `AIM_USER_TOKEN` to worker `.aim_env` |
| Queen DB grows fast | `du -sh /var/lib/aim-hive-queen` | compact: `sqlite3.. "VACUUM"` |
| Caddy 502 | `sudo systemctl status aim-hive-queen` | queen down; restart |

---

## Rollback

```bash
sudo systemctl disable --now aim-hive-queen.service
sudo /usr/bin/rm /etc/systemd/system/aim-hive-queen.service
sudo /usr/bin/rm -rf /opt/aim-hive-queen
# Keep /var/lib/aim-hive-queen/ if you want state preserved.
sudo systemctl daemon-reload
```
