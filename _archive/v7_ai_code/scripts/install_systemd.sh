#!/usr/bin/env bash
# AIM — install systemd units (run as root or via sudo).
# Idempotent: safe to re-run.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "must run as root: sudo bash $0"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/deploy/systemd"

echo "Copying unit files from $SRC → /etc/systemd/system/"
install -m 0644 "$SRC"/aim-*.service /etc/systemd/system/
install -m 0644 "$SRC"/aim.target    /etc/systemd/system/

systemctl daemon-reload

echo "Enabling aim.target on boot"
systemctl enable aim.target

cat <<EOF

Done. Now you can:
  sudo systemctl start aim.target              # start everything
  sudo systemctl status aim-llm                # one service
  journalctl -fu aim-doctor                    # logs
  sudo systemctl stop  aim.target              # stop all

To remove later:
  sudo systemctl disable --now aim.target
  sudo rm /etc/systemd/system/aim-*.service /etc/systemd/system/aim.target
  sudo systemctl daemon-reload
EOF
