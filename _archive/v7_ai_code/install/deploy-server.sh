#!/usr/bin/env bash
# AIM server deployment — runs on the remote server (jaba@server pattern).
#
# Used to deploy the public-facing AIM instance behind nginx, like Ze /
# BioSense / FCLC. No Docker. Native systemd. Per CLAUDE.md HARD CONSTRAINT.
#
# Expects to be run AS root on the server (or with sudo) after `git pull`
# under /home/jaba/web/aim/.
#
# Usage on the server:
#   sudo /home/jaba/web/aim/AIM/install/deploy-server.sh

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/jaba/web/aim}"
PREFIX="${PREFIX:-/opt/aim}"
SERVICE_USER="${SERVICE_USER:-jaba}"
NGINX_HOST="${NGINX_HOST:-aim.longevity.ge}"
PHX_PORT="${PHX_PORT:-4000}"
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --host)       NGINX_HOST="$2"; shift 2 ;;
    --port)       PHX_PORT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

log() { printf '\033[1;36m[aim-deploy]\033[0m %s\n' "$*"; }

if [[ "$EUID" -ne 0 ]]; then
  log "re-exec with sudo"
  exec sudo -E "$0" "$@"
fi

[[ -d "$REPO_ROOT/AIM/rust-core" ]] || { echo "no checkout at $REPO_ROOT" >&2; exit 1; }

# ── build as service user (so target/ owned correctly) ──────────────────
if [[ "$SKIP_BUILD" -eq 1 ]]; then
  log "skipping build (--skip-build); using existing target/ + _build/"
else
  log "building Rust + Phoenix as $SERVICE_USER"
  sudo -u "$SERVICE_USER" -i bash -c "
    set -e
    [[ -f \$HOME/.asdf/asdf.sh ]] && source \$HOME/.asdf/asdf.sh
    [[ -f \$HOME/.cargo/env    ]] && source \$HOME/.cargo/env
    cd '$REPO_ROOT/AIM/rust-core' && cargo build --release --workspace &&
    cd '$REPO_ROOT/AIM/phoenix-umbrella' &&
      MIX_ENV=prod mix deps.get --only prod &&
      MIX_ENV=prod mix compile &&
      MIX_ENV=prod mix release --overwrite
  "
fi

# ── stage ────────────────────────────────────────────────────────────────
log "staging into $PREFIX"
mkdir -p "$PREFIX"/{bin,phoenix,etc,logs}
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

# ── SECRET_KEY_BASE — required by Phoenix in :prod ──────────────────────
USER_ENV="/home/$SERVICE_USER/.aim_env"
if ! sudo -u "$SERVICE_USER" grep -q SECRET_KEY_BASE "$USER_ENV" 2>/dev/null; then
  log "generating SECRET_KEY_BASE in $USER_ENV"
  SECRET=$(openssl rand -hex 64)
  sudo -u "$SERVICE_USER" bash -c "echo 'SECRET_KEY_BASE=$SECRET' >> '$USER_ENV' && chmod 600 '$USER_ENV'"
fi

cp -f "$REPO_ROOT/AIM/rust-core/target/release/aim-llm" "$PREFIX/bin/" 2>/dev/null || true
# The umbrella build produces multiple dirs called `rel` (templates per
# child app + the actual release under _build/prod/rel/<name>). The
# release we want lives at _build/prod/rel/aim_web/.
PHX_REL="$REPO_ROOT/AIM/phoenix-umbrella/_build/prod/rel/aim_web"
if [[ -d "$PHX_REL" ]]; then
  rm -rf "$PREFIX/phoenix"
  cp -r "$PHX_REL" "$PREFIX/phoenix"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

# ── system-wide systemd units ────────────────────────────────────────────
log "writing /etc/systemd/system/aim-{orchestrator,phoenix}.service"

cat > /etc/systemd/system/aim-orchestrator.service <<EOF
[Unit]
Description=AIM Rust orchestrator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PREFIX
EnvironmentFile=-/home/$SERVICE_USER/.aim_env
ExecStart=$PREFIX/bin/aim-llm serve
Restart=on-failure
RestartSec=5
StandardOutput=append:$PREFIX/logs/orchestrator.log
StandardError=append:$PREFIX/logs/orchestrator.err.log
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/aim-phoenix.service <<EOF
[Unit]
Description=AIM Phoenix LiveView
After=network-online.target aim-orchestrator.service
Wants=aim-orchestrator.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PREFIX/phoenix
EnvironmentFile=-/home/$SERVICE_USER/.aim_env
Environment=MIX_ENV=prod
Environment=PHX_SERVER=true
Environment=AIM_WEB_PORT=$PHX_PORT
Environment=AIM_GATEWAY_PORT=$((PHX_PORT + 2))
ExecStart=$PREFIX/phoenix/bin/aim_web start
Restart=on-failure
RestartSec=5
StandardOutput=append:$PREFIX/logs/phoenix.log
StandardError=append:$PREFIX/logs/phoenix.err.log
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ── nginx vhost ──────────────────────────────────────────────────────────
NGINX_CONF="/etc/nginx/sites-available/$NGINX_HOST"
if [[ ! -f "$NGINX_CONF" ]]; then
  log "writing nginx vhost: $NGINX_CONF"
  cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $NGINX_HOST;

    # Let's Encrypt webroot
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:$PHX_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           \$http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
    }

    client_max_body_size 50M;
}
EOF
  ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/$NGINX_HOST"
  nginx -t && systemctl reload nginx
fi

# ── start ────────────────────────────────────────────────────────────────
log "enabling + starting services"
systemctl enable --now aim-orchestrator aim-phoenix

log "done"
cat <<HINT

✅ AIM deployed
   prefix: $PREFIX
   user:   $SERVICE_USER
   url:    http://$NGINX_HOST/  (then certbot --nginx -d $NGINX_HOST)
   logs:   journalctl -u aim-orchestrator -u aim-phoenix -f

HINT
