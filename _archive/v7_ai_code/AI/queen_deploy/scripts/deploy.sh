#!/bin/bash
# deploy.sh — bootstrap AIM Hive Queen on the drjaba server.
#
# Run on server (jaba@server) as the `jaba` user, NOT root.
# Steps that need root are explicit `sudo` calls below.
#
# Pre-requisites on server:
#   - Python 3.10+
#   - nginx + certbot already installed (existing setup for longevity.ge)
#   - User `jaba` has SSH + sudo
#
# Idempotent: re-running upgrades the venv + restarts the service.

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/hive_queen}"
REPO_DIR="${REPO_DIR:-$HOME/LongevityCommon}"   # cloned djabbat/LongevityCommon
ADMIN_TOKEN="${AIM_HIVE_ADMIN_TOKEN:-}"

echo "→ deploy dir: $DEPLOY_DIR"
echo "→ repo dir:   $REPO_DIR (must contain AIM/AI/queen_deploy/)"

if [[ ! -d "$REPO_DIR/AIM/AI/queen_deploy" ]]; then
  echo "ERROR: $REPO_DIR/AIM/AI/queen_deploy not found."
  echo "Clone djabbat/LongevityCommon into \$REPO_DIR first:"
  echo "    git clone git@github.com:djabbat/LongevityCommon.git ~/LongevityCommon"
  exit 2
fi

mkdir -p "$DEPLOY_DIR"

# 1. Symlink the queen app + module tree (so updates from git pull
#    flow without re-deploy).
ln -sfn "$REPO_DIR/AIM/AI/queen_deploy/queen_app.py" "$DEPLOY_DIR/queen_app.py"
ln -sfn "$REPO_DIR/AIM/AI"         "$DEPLOY_DIR/AI"     # for AI.ai.hive_queen import
ln -sfn "$REPO_DIR/AIM/agents"     "$DEPLOY_DIR/agents" # for agents.auth import

# 2. venv
if [[ ! -d "$DEPLOY_DIR/venv" ]]; then
  echo "→ creating venv"
  python3 -m venv "$DEPLOY_DIR/venv"
fi
"$DEPLOY_DIR/venv/bin/pip" install --upgrade pip
"$DEPLOY_DIR/venv/bin/pip" install fastapi 'uvicorn[standard]' httpx

# 3. .env file (admin token + queen DB path).
if [[ ! -f "$DEPLOY_DIR/.env" ]]; then
  if [[ -z "$ADMIN_TOKEN" ]]; then
    ADMIN_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    echo "→ generated AIM_HIVE_ADMIN_TOKEN: $ADMIN_TOKEN"
    echo "  (save this — needed for /v1/hive/distill calls)"
  fi
  cat > "$DEPLOY_DIR/.env" <<EOF
AIM_HIVE_QUEEN_DB=$DEPLOY_DIR/hive_queen.db
AIM_HIVE_ADMIN_TOKEN=$ADMIN_TOKEN
PYTHONPATH=$DEPLOY_DIR
EOF
  chmod 600 "$DEPLOY_DIR/.env"
  echo "→ wrote $DEPLOY_DIR/.env"
fi

# 4. systemd unit (root needed).
echo "→ installing systemd unit (sudo)"
sudo cp "$REPO_DIR/AIM/AI/queen_deploy/config/aim-hive-queen.service" \
        /etc/systemd/system/aim-hive-queen.service
sudo systemctl daemon-reload
sudo systemctl enable --now aim-hive-queen.service

# 5. Wait for service to come up + smoke test
sleep 2
echo "→ healthz:"
curl -sf http://127.0.0.1:8080/healthz | python3 -m json.tool || {
  echo "ERROR: queen not responding. Check:  sudo journalctl -u aim-hive-queen -n 50"
  exit 3
}

# 6. nginx + certbot (root needed).
echo "→ installing nginx vhost (sudo)"
sudo cp "$REPO_DIR/AIM/AI/queen_deploy/config/nginx-hive.conf" \
        /etc/nginx/sites-available/hive.longevity.ge
sudo ln -sfn /etc/nginx/sites-available/hive.longevity.ge \
             /etc/nginx/sites-enabled/hive.longevity.ge
sudo nginx -t
sudo systemctl reload nginx

cat <<'EOF'

✅ Queen process running on 127.0.0.1:8080.
✅ nginx vhost installed (HTTP only — HTTPS step below).

NEXT (one-time, requires DNS A-record for hive.longevity.ge → server IP):

  sudo certbot --nginx -d hive.longevity.ge

Verify worker → queen path:

  curl -s https://hive.longevity.ge/healthz

To check status (admin):

  ADMIN=$(grep AIM_HIVE_ADMIN_TOKEN ~/hive_queen/.env | cut -d= -f2)
  curl -sH "Authorization: Bearer $ADMIN" \
    https://hive.longevity.ge/v1/hive/status | python3 -m json.tool

To trigger distill manually:

  curl -sX POST -H "Authorization: Bearer $ADMIN" \
    https://hive.longevity.ge/v1/hive/distill | python3 -m json.tool

UPGRADES (after future git pulls):

  cd ~/LongevityCommon && git pull
  ~/hive_queen/venv/bin/pip install --upgrade fastapi uvicorn httpx
  sudo systemctl restart aim-hive-queen

EOF
