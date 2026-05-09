#!/usr/bin/env bash
# scripts/deploy_aim_to_server.sh — deploy AIM Phoenix umbrella to longevity.ge
# server so /about + cornerstone routes are publicly reachable.
#
# Prerequisites on local machine:
#   * ssh access to jaba@server with key auth
#   * Rust binaries pre-built: cargo build --workspace --release
#
# Prerequisites on server (one-time, manual):
#   * Elixir 1.17 + Erlang/OTP 27 installed
#   * sudo nginx + sudo certbot for TLS
#   * /home/jaba/.aim_env with API keys (mode 600)
#
# Usage:
#   bash scripts/deploy_aim_to_server.sh                       # full deploy
#   bash scripts/deploy_aim_to_server.sh --skip-rsync          # only restart
#   bash scripts/deploy_aim_to_server.sh --skip-nginx          # skip nginx

set -euo pipefail

SERVER_USER="${SERVER_USER:-jaba}"
SERVER_HOST="${SERVER_HOST:-server}"          # ssh alias for longevity.ge box
SERVER_PATH="${SERVER_PATH:-/home/jaba/web/aim}"
PHX_PORT="${PHX_PORT:-4002}"
PUBLIC_HOST="${PUBLIC_HOST:-aim.longevity.ge}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SKIP_RSYNC=0
SKIP_NGINX=0
for arg in "$@"; do
    case "$arg" in
        --skip-rsync) SKIP_RSYNC=1 ;;
        --skip-nginx) SKIP_NGINX=1 ;;
        *) echo "unknown arg: $arg"; exit 1 ;;
    esac
done

echo "==> deploying AIM to $SERVER_USER@$SERVER_HOST:$SERVER_PATH"

# ─── Step 1: rsync source tree ─────────────────────────────────────────────

if [[ $SKIP_RSYNC -eq 0 ]]; then
    echo "==> rsync source (excluding venv, target, node_modules, _build, deps, Patients/)"
    rsync -av --delete \
        --exclude 'venv/' \
        --exclude 'rust-core/target/' \
        --exclude 'phoenix-umbrella/_build/' \
        --exclude 'phoenix-umbrella/deps/' \
        --exclude 'node_modules/' \
        --exclude '__pycache__/' \
        --exclude '.git/' \
        --exclude 'Patients/' \
        --exclude '_archive/' \
        "$REPO_ROOT/" "$SERVER_USER@$SERVER_HOST:$SERVER_PATH/"
fi

# ─── Step 2: build Rust binaries on the server ─────────────────────────────

echo "==> building Rust release binaries on server"
ssh "$SERVER_USER@$SERVER_HOST" "cd $SERVER_PATH/rust-core && cargo build --workspace --release"

# ─── Step 3: build Phoenix release on the server ───────────────────────────

echo "==> building Phoenix release on server"
ssh "$SERVER_USER@$SERVER_HOST" "cd $SERVER_PATH/phoenix-umbrella && \
    MIX_ENV=prod mix deps.get --only prod && \
    MIX_ENV=prod mix compile"

# ─── Step 4: install + restart systemd unit ────────────────────────────────

echo "==> installing systemd user unit"
ssh "$SERVER_USER@$SERVER_HOST" "
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/aim-phoenix.service <<EOF
[Unit]
Description=AIM Phoenix LiveView frontend (port $PHX_PORT)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$SERVER_PATH/phoenix-umbrella
EnvironmentFile=/home/$SERVER_USER/.aim_env
Environment=\"PHX_SERVER=true\"
Environment=\"AIM_WEB_PORT=$PHX_PORT\"
Environment=\"MIX_ENV=prod\"
Environment=\"PHX_HOST=$PUBLIC_HOST\"
Environment=\"AIM_ROOT=$SERVER_PATH\"
ExecStart=/usr/bin/mix phx.server
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable aim-phoenix.service
systemctl --user restart aim-phoenix.service
sleep 4
ss -tln | grep $PHX_PORT || echo 'WARNING: not bound'
"

# ─── Step 5: nginx vhost (idempotent) ──────────────────────────────────────

if [[ $SKIP_NGINX -eq 0 ]]; then
    echo "==> writing nginx vhost for $PUBLIC_HOST"
    ssh "$SERVER_USER@$SERVER_HOST" "sudo tee /etc/nginx/sites-available/$PUBLIC_HOST > /dev/null <<EOF
server {
    listen 80;
    server_name $PUBLIC_HOST;

    # Phoenix LiveView WebSocket support
    location / {
        proxy_pass http://127.0.0.1:$PHX_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade        \\\$http_upgrade;
        proxy_set_header Connection     \\\"upgrade\\\";
        proxy_set_header Host           \\\$host;
        proxy_set_header X-Real-IP      \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_read_timeout 90;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/$PUBLIC_HOST /etc/nginx/sites-enabled/$PUBLIC_HOST
sudo nginx -t && sudo systemctl reload nginx
"

    echo "==> certbot for TLS (run manually if first deploy):"
    echo "    ssh $SERVER_USER@$SERVER_HOST 'sudo certbot --nginx -d $PUBLIC_HOST'"
fi

# ─── Step 6: smoke ─────────────────────────────────────────────────────────

echo "==> smoke from server"
ssh "$SERVER_USER@$SERVER_HOST" "
curl -s -m 5 -o /dev/null -w 'HTTP %{http_code}  bytes %{size_download}\n' http://127.0.0.1:$PHX_PORT/about
curl -s -m 5 -o /dev/null -w 'HTTP %{http_code}  bytes %{size_download}\n' http://127.0.0.1:$PHX_PORT/
"

echo ""
echo "==> deployment complete"
echo "    public URL:  https://$PUBLIC_HOST/about  (after DNS + certbot)"
echo "    local URL:   http://127.0.0.1:$PHX_PORT/about (on server)"
echo "    logs:        ssh $SERVER_USER@$SERVER_HOST journalctl --user -u aim-phoenix -f"
