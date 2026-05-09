#!/usr/bin/env bash
# scripts/deploy_hive_queen_remote.sh — package + ship hive queen to a server.
#
# Builds aim-hive-queen Rust binary, packages with systemd unit + minimal
# README into a tarball, and (optionally) scp+install on a remote host.
#
# Usage:
#   bash scripts/deploy_hive_queen_remote.sh                    # build tarball only
#   bash scripts/deploy_hive_queen_remote.sh user@hive.example  # build + ship
#
# The remote installer does:
#   1. useradd -r aim (if missing)
#   2. mkdir -p /opt/aim-hive-queen /var/lib/aim-hive-queen /etc/aim
#   3. install binary + service file
#   4. systemctl enable --now aim-hive-queen
#
# Pre-req on remote: systemd, ssh access, sudo for non-root deploy account.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${1:-}"

OUT_DIR="/tmp/aim-hive-queen-bundle-$(/usr/bin/date +%Y%m%dT%H%M%S)"
BIN="$REPO_ROOT/rust-core/target/release/aim-hive-queen"
SERVICE="$REPO_ROOT/deploy/systemd/aim-hive-queen.service"

echo "==> 1. Build Rust binary (release mode)"
if [[ ! -x "$BIN" ]]; then
    (cd "$REPO_ROOT/rust-core" && cargo build -p aim-hive-queen --release)
fi
[[ -x "$BIN" ]] || { echo "ERROR: build failed — $BIN missing"; exit 1; }
echo "    $(/usr/bin/file "$BIN" | /usr/bin/cut -d: -f2-)"

echo "==> 2. Package bundle into $OUT_DIR/"
/usr/bin/mkdir -p "$OUT_DIR"
/usr/bin/cp "$BIN" "$OUT_DIR/aim-hive-queen"
/usr/bin/cp "$SERVICE" "$OUT_DIR/aim-hive-queen.service"

# Sample env file
/usr/bin/cat > "$OUT_DIR/hive_queen.env.example" <<'EOF'
# /etc/aim/hive_queen.env — environment for aim-hive-queen.service
# Copy to /etc/aim/hive_queen.env, edit values, chmod 600.

PORT=8090
HOST=0.0.0.0
RUST_LOG=info

# sqlite DB lives in $XDG_CACHE_HOME/aim/hive_queen.db.
# Service user `aim` has home=/opt/aim-hive-queen which is read-only under
# ProtectSystem=strict — point XDG_CACHE_HOME at the unit's ReadWritePaths.
XDG_CACHE_HOME=/var/lib/aim-hive-queen

# Admin operations (POST /v1/hive/distill, GET /v1/hive/status) require this:
AIM_HIVE_ADMIN_TOKEN=CHANGE_ME_$(/usr/bin/openssl rand -hex 16)

# Set 1 to require Bearer token from workers (POST /v1/hive/contribute).
# In bootstrap migration leave 0 to accept anonymous contributions.
AIM_HIVE_REQUIRE_AUTH=0
EOF

# Remote installer — runs ON the remote host
/usr/bin/cat > "$OUT_DIR/install_remote.sh" <<'INSTALL_EOF'
#!/usr/bin/env bash
# install_remote.sh — runs ON the queen host.
set -euo pipefail
echo "==> Installing aim-hive-queen on $(hostname)"

# 1. system user
if ! /usr/bin/id aim &>/dev/null; then
    sudo /usr/sbin/useradd -r -s /usr/sbin/nologin -d /opt/aim-hive-queen aim
fi

# 2. dirs (include /var/lib/aim-hive-queen/aim so $XDG_CACHE_HOME/aim is writable)
sudo /usr/bin/mkdir -p /opt/aim-hive-queen /var/lib/aim-hive-queen/aim /etc/aim
sudo /usr/bin/chown -R aim:aim /opt/aim-hive-queen /var/lib/aim-hive-queen
sudo /usr/bin/chown root:aim /etc/aim
sudo /usr/bin/chmod 750 /etc/aim

# 3. binary
sudo /usr/bin/install -o aim -g aim -m 755 \
    "$(dirname "$0")/aim-hive-queen" /opt/aim-hive-queen/aim-hive-queen

# 4. service unit
sudo /usr/bin/install -o root -g root -m 644 \
    "$(dirname "$0")/aim-hive-queen.service" /etc/systemd/system/aim-hive-queen.service

# 5. env file (only if missing — never overwrite secrets)
if [[ ! -f /etc/aim/hive_queen.env ]]; then
    sudo /usr/bin/install -o root -g aim -m 640 \
        "$(dirname "$0")/hive_queen.env.example" /etc/aim/hive_queen.env
    echo "    [!] /etc/aim/hive_queen.env created from example."
    echo "    [!] EDIT IT: replace AIM_HIVE_ADMIN_TOKEN, set AIM_HIVE_REQUIRE_AUTH."
fi

# 6. enable + start
sudo /usr/bin/systemctl daemon-reload
sudo /usr/bin/systemctl enable --now aim-hive-queen.service

# 7. smoke
/usr/bin/sleep 2
if /usr/bin/curl -m 3 -sSf http://127.0.0.1:8090/healthz >/dev/null; then
    echo "==> ✓ aim-hive-queen healthy on :8090"
else
    echo "==> ⚠ /healthz not responding — check journalctl -u aim-hive-queen"
fi

echo ""
echo "Useful commands:"
echo "  sudo systemctl status aim-hive-queen"
echo "  sudo journalctl -u aim-hive-queen -f"
echo "  curl http://127.0.0.1:8090/healthz"
echo "  curl http://127.0.0.1:8090/v1/hive/status \\"
echo "       -H 'Authorization: Bearer \$AIM_HIVE_ADMIN_TOKEN'"
INSTALL_EOF
/usr/bin/chmod +x "$OUT_DIR/install_remote.sh"

# README inside bundle
/usr/bin/cat > "$OUT_DIR/README.md" <<EOF
# aim-hive-queen — deployment bundle

Generated: $(/usr/bin/date)
From repo: $REPO_ROOT

## Files

| File | Purpose |
|---|---|
| \`aim-hive-queen\`           | Rust binary (musl-not, x86_64 Linux) |
| \`aim-hive-queen.service\`   | systemd unit (copies to /etc/systemd/system/) |
| \`hive_queen.env.example\`   | env template (copies to /etc/aim/hive_queen.env) |
| \`install_remote.sh\`        | On-host installer — run as user with sudo |

## Install on remote

    cd $(/usr/bin/basename "$OUT_DIR")
    bash install_remote.sh

After install:
- Edit /etc/aim/hive_queen.env — set AIM_HIVE_ADMIN_TOKEN
- Open firewall port 8090 (UFW: \`sudo ufw allow 8090/tcp\`)
- Recommended: terminate TLS via Caddy/nginx in front, restrict 8090 to loopback

## API surface

- \`GET  /healthz\`             — health check (no auth)
- \`POST /v1/hive/contribute\`  — worker submits anonymized signal
- \`GET  /v1/hive/updates\`     — worker pulls eval-gated updates
- \`POST /v1/hive/distill\`     — admin trigger: scan + publish (Bearer admin)
- \`GET  /v1/hive/status\`      — queen state summary (Bearer admin)

Workers point to this server via \`AIM_HIVE_QUEEN_URL=http(s)://<host>:8090\`.
EOF

echo "==> 3. Bundle ready: $OUT_DIR/"
/usr/bin/ls -la "$OUT_DIR/"

if [[ -z "$REMOTE" ]]; then
    echo ""
    echo "==> No remote host given — bundle ready for manual transfer."
    echo "    Next: scp -r $OUT_DIR <user>@<host>:~/ && ssh <user>@<host> 'bash ~/$(/usr/bin/basename "$OUT_DIR")/install_remote.sh'"
    exit 0
fi

echo ""
echo "==> 4. Ship to $REMOTE"
/usr/bin/scp -r "$OUT_DIR" "$REMOTE:/tmp/" || {
    echo "ERROR: scp failed"
    exit 1
}
REMOTE_DIR="/tmp/$(/usr/bin/basename "$OUT_DIR")"
echo "==> 5. Run installer on $REMOTE"
/usr/bin/ssh "$REMOTE" "bash $REMOTE_DIR/install_remote.sh"
