#!/usr/bin/env bash
# install.sh — native systemd installer for AIM_FS (no Docker, per
# `feedback_no_docker`).  Builds Rust binaries in release mode, installs to
# /usr/local/bin, drops user-level systemd unit files, copies onboarding
# templates to /opt/aim/templates.
#
# Usage:  bash install.sh
#         bash install.sh --no-build      # if binaries already in target/release
#         bash install.sh --uninstall

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CRATE_ROOT="$(cd "$HERE/.." && pwd)"
WORKSPACE_ROOT="$(cd "$CRATE_ROOT/../.." && pwd)"

PREFIX="${PREFIX:-/usr/local}"
TEMPLATES_DST="${TEMPLATES_DST:-/opt/aim/templates}"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
DO_BUILD=1

for arg in "$@"; do
    case "$arg" in
        --no-build)  DO_BUILD=0 ;;
        --uninstall) DO_UNINSTALL=1 ;;
    esac
done

if [[ "${DO_UNINSTALL:-0}" == "1" ]]; then
    echo "→ uninstalling AIM_FS"
    systemctl --user disable --now aim-fs-sweeper.timer 2>/dev/null || true
    sudo rm -f "$PREFIX/bin/aim-fs" "$PREFIX/bin/aim-fs-migrate" \
                "$PREFIX/bin/aim-fs-sweep-once" "$PREFIX/bin/aim-onboard"
    rm -f "$SYSTEMD_USER_DIR/aim-fs-sweeper.service" \
          "$SYSTEMD_USER_DIR/aim-fs-sweeper.timer" \
          "$SYSTEMD_USER_DIR/aim-fs-port.service"
    sudo rm -rf "$TEMPLATES_DST"
    systemctl --user daemon-reload
    echo "✓ uninstalled"
    exit 0
fi

if [[ "$DO_BUILD" == "1" ]]; then
    echo "→ cargo build --release -p aim-fs -p aim-onboarding"
    (cd "$WORKSPACE_ROOT" && cargo build --release -p aim-fs -p aim-onboarding)
fi

# Install binaries.
echo "→ install binaries to $PREFIX/bin"
sudo install -d "$PREFIX/bin"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs"           "$PREFIX/bin/aim-fs"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-migrate"   "$PREFIX/bin/aim-fs-migrate"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-onboard"      "$PREFIX/bin/aim-onboard"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-backup"    "$PREFIX/bin/aim-fs-backup"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-restore"   "$PREFIX/bin/aim-fs-restore"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-tg"        "$PREFIX/bin/aim-fs-tg"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-bench"     "$PREFIX/bin/aim-fs-bench"
sudo install -m 755 "$WORKSPACE_ROOT/target/release/aim-fs-replay"    "$PREFIX/bin/aim-fs-replay"
sudo install -m 755 "$HERE/aim-self-dev-eval.sh"                       "$PREFIX/bin/aim-self-dev-eval"

# A tiny wrapper for the sweeper one-shot — invokes Rust binary in `--sweep`
# mode (single ping op + immediate exit so the timer doesn't stay open).
cat > /tmp/aim-fs-sweep-once.sh <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
printf '{"op":"sweep"}\n' | "${AIM_FS_BIN:-/usr/local/bin/aim-fs}"
WRAP
sudo install -m 755 /tmp/aim-fs-sweep-once.sh "$PREFIX/bin/aim-fs-sweep-once"
rm -f /tmp/aim-fs-sweep-once.sh

# Install onboarding templates.
echo "→ install templates to $TEMPLATES_DST"
sudo install -d "$TEMPLATES_DST"
sudo install -m 644 "$CRATE_ROOT/../aim-onboarding/templates/"*.yaml "$TEMPLATES_DST/"

# Install user-level systemd units (no root-level service — keep AIM in
# user session, per AIM CLAUDE.md "native systemd units").
echo "→ install systemd --user units to $SYSTEMD_USER_DIR"
mkdir -p "$SYSTEMD_USER_DIR"
install -m 644 "$HERE/aim-fs-sweeper.service"     "$SYSTEMD_USER_DIR/aim-fs-sweeper.service"
install -m 644 "$HERE/aim-fs-sweeper.timer"       "$SYSTEMD_USER_DIR/aim-fs-sweeper.timer"
install -m 644 "$HERE/aim-fs-port.service"        "$SYSTEMD_USER_DIR/aim-fs-port.service"
install -m 644 "$HERE/aim-self-dev-eval.service"  "$SYSTEMD_USER_DIR/aim-self-dev-eval.service"
install -m 644 "$HERE/aim-self-dev-eval.timer"    "$SYSTEMD_USER_DIR/aim-self-dev-eval.timer"
systemctl --user daemon-reload
systemctl --user enable --now aim-fs-sweeper.timer
systemctl --user enable --now aim-self-dev-eval.timer
echo "✓ aim-fs-sweeper.timer + aim-self-dev-eval.timer enabled"

cat <<'EOF'

== Done ==

Binaries:
  /usr/local/bin/aim-fs           # JSON Port, called by Phoenix or directly
  /usr/local/bin/aim-fs-migrate   # legacy → AIM_FS importer
  /usr/local/bin/aim-fs-sweep-once# one-shot decay sweeper (called by timer)
  /usr/local/bin/aim-onboard      # interactive / non-interactive onboarding

Templates: /opt/aim/templates/*.yaml

systemd --user:
  aim-fs-sweeper.timer  (active, runs every 60s)
  aim-fs-port.service   (NOT enabled by default; only for socket-activated
                         remote bridge installations)

Quick test:
  printf '{"op":"ping"}\n' | aim-fs
  aim-onboard --template /opt/aim/templates/research_project.yaml \
              --tenant-id $(uuidgen)

Uninstall:  bash install.sh --uninstall
EOF
