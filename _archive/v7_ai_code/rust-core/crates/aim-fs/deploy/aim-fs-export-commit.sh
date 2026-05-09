#!/usr/bin/env bash
# aim-fs-export-commit.sh — nightly export + git commit.
#
# Runs aim-fs-export to dump the current AIM_FS state into a markdown tree,
# then commits the result to a git repository (creating it if missing).
# Each run produces a "AIM_FS snapshot YYYY-MM-DD" commit so the history of
# the doctor's facts/feedback is observable and diff-able.
#
# Optional: set AIM_FS_EXPORT_PUSH=1 to also `git push` (default: off; force-push
# safety must be opt-in).
#
# systemd-user timer: aim-fs-export-commit.timer (daily 03:50 ± 10min).

set -euo pipefail

EXPORT_DIR="${AIM_FS_EXPORT_DIR:-$HOME/aim_fs_export}"
TENANT="${AIM_FS_TENANT:-djabbat}"
AIM_ROOT="${AIM_FS_ROOT:-$HOME/.aim_fs}"
PUSH="${AIM_FS_EXPORT_PUSH:-0}"

if [ ! -x "$(command -v aim-fs-export)" ]; then
    echo "aim-fs-export-commit: aim-fs-export not on PATH; skipping" >&2
    exit 0
fi

mkdir -p "$EXPORT_DIR"

# Run the export (clean = remove stale entries that were deleted from DB).
aim-fs-export \
    --aim-root "$AIM_ROOT" \
    --tenant-id "$TENANT" \
    --out "$EXPORT_DIR" \
    --clean

# Initialise git repo on first run.
if [ ! -d "$EXPORT_DIR/.git" ]; then
    git -C "$EXPORT_DIR" init -q -b main
    cat > "$EXPORT_DIR/.gitignore" <<'EOF'
# AIM_FS export — auto-generated on systemd timer.
# Do NOT edit files manually; changes are overwritten nightly.
*.tmp
.DS_Store
EOF
    git -C "$EXPORT_DIR" add .gitignore
    git -C "$EXPORT_DIR" -c user.email="aim-fs@local" -c user.name="aim-fs-export" \
        commit -q -m "init: aim-fs-export repo"
fi

# Commit any changes.
cd "$EXPORT_DIR"
git add -A
if git diff --cached --quiet; then
    echo "aim-fs-export-commit: no changes to commit"
    exit 0
fi
COUNT=$(find . -name '*.md' -not -path './.git/*' | wc -l)
git -c user.email="aim-fs@local" -c user.name="aim-fs-export" \
    commit -q -m "AIM_FS snapshot $(date +%Y-%m-%d) — ${COUNT} markdown files"
echo "aim-fs-export-commit: committed snapshot ($COUNT files)"

if [ "$PUSH" = "1" ]; then
    if git remote get-url origin >/dev/null 2>&1; then
        git push --quiet origin main || echo "push failed — leaving local commit"
    else
        echo "AIM_FS_EXPORT_PUSH=1 but no origin configured; skipping push"
    fi
fi
