# AIM Hive Queen — deployment package

This folder contains everything needed to run the Hive Queen
(`AI/ai/hive_queen`) as a public HTTPS service on
`hive.longevity.ge`. Workers (АIM bees) on user laptops post anonymized
signals here; the queen aggregates and publishes back distilled updates.

## Files

```
queen_deploy/
├── README.md ← this file
├── queen_app.py ← FastAPI wrapper around AI.ai.hive_queen
├── config/
│ ├── aim-hive-queen.service ← systemd unit
│ └── nginx-hive.conf ← nginx vhost for hive.longevity.ge
└── scripts/
 ├── deploy.sh ← one-shot bootstrap on server
 └── distill_cron.sh ← daily distill trigger (crontab)
```

## Server prerequisites

- Linux (tested with the existing drjaba.com server stack)
- Python 3.10+
- nginx (already installed for longevity.ge / drjaba.com)
- certbot (already installed)
- DNS: `hive.longevity.ge` A-record pointing at server IP
- User `jaba` with sudo (existing setup)

## One-shot deploy

```bash
# On the server, as user jaba:
git clone git@github.com:djabbat/LongevityCommon.git ~/LongevityCommon
chmod +x ~/LongevityCommon/AIM/AI/queen_deploy/scripts/*.sh
~/LongevityCommon/AIM/AI/queen_deploy/scripts/deploy.sh
sudo certbot --nginx -d hive.longevity.ge

# verify
curl https://hive.longevity.ge/healthz
```

## Resource footprint

| Workers | Disk/year | RAM | CPU |
|---|---|---|---|
| 10 | ~50 MB | 80 MB | <1% |
| 100 | ~500 MB | 150 MB | 2-5% |
| 1000 | ~5 GB | 300 MB | scales w/ distill freq |

The SQLite DB is the only growing artefact. At 100 workers × daily
contribution × 1 year = ~365K rows × ~5KB JSON = ~1.8 GB raw, but with
WAL + INTEGER PRIMARY KEY indexing the DB stays around ~500 MB. Fits
comfortably alongside OJS on the existing server.

## Worker config (after queen is live)

On each worker, add to `~/.aim_env`:

```bash
AIM_HIVE_QUEEN_URL=https://hive.longevity.ge
AIM_USER_TOKEN=aim_xxx # already exists for hub auth
```

Then test:

```bash
aim diag --hive-preview # see anonymized payload
python -c "from AI.ai.hive_telemetry import contribute; print(contribute)"
```

## Daily distillation cron

```bash
# On server:
mkdir -p ~/hive_queen/scripts
ln -sfn ~/LongevityCommon/AIM/AI/queen_deploy/scripts/distill_cron.sh \
 ~/hive_queen/scripts/distill_cron.sh
crontab -e
# Add:
17 4 * * * /home/jaba/hive_queen/scripts/distill_cron.sh
```

This runs `POST /v1/hive/distill` daily at 04:17 UTC, scanning fresh
worker signals and auto-publishing candidate updates that have ≥3
worker support.

## Security model

| Layer | Mechanism |
|---|---|
| HTTPS | nginx + certbot Let's Encrypt |
| Worker auth | Bearer `AIM_USER_TOKEN`, validated via existing `agents.auth` |
| Admin auth | Separate `AIM_HIVE_ADMIN_TOKEN` (32 random bytes), only `/v1/hive/distill` and `/v1/hive/status` |
| Payload sanity | `accept_contribution` rejects malformed payloads (v != 1, missing worker_id, etc.) |
| L_PRIVACY | Worker side strips PII *before* upload (see `AI/ai/hive_telemetry.py`) |
| systemd hardening | `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp` |
| nginx | rate limit fwd to internal port only; `/v1/hive/` whitelist; everything else 404 |

## Operational commands

```bash
# Status
sudo systemctl status aim-hive-queen
sudo journalctl -u aim-hive-queen -f

# Restart after code change
cd ~/LongevityCommon && git pull
sudo systemctl restart aim-hive-queen

# Manual distill
ADMIN=$(grep ADMIN_TOKEN ~/hive_queen/.env | cut -d= -f2)
curl -sX POST -H "Authorization: Bearer $ADMIN" \
 https://hive.longevity.ge/v1/hive/distill | python3 -m json.tool

# Inspect DB
sqlite3 ~/hive_queen/hive_queen.db \
 "SELECT COUNT(*), MIN(ts), MAX(ts) FROM contributions;"
```

## Rollback

```bash
sudo systemctl stop aim-hive-queen
sudo systemctl disable aim-hive-queen
sudo rm /etc/systemd/system/aim-hive-queen.service
sudo rm /etc/nginx/sites-enabled/hive.longevity.ge
sudo systemctl reload nginx
# DB stays in ~/hive_queen/hive_queen.db until manually deleted.
```
