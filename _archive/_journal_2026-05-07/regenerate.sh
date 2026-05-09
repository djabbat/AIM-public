#!/bin/bash
# AIM Phase 3 stage journal regenerator.
# Usage: ./regenerate.sh > STAGES.md
set -euo pipefail

cd "$(dirname "$0")/.."

cat <<'EOF'
# AIM Phase 3 — журнал этапов (autonomously)

Каждый этап = один git commit на `main`. Регенерируется
`_journal/regenerate.sh` из `git log`.

EOF

echo "Последнее обновление: **$(date '+%Y-%m-%d %H:%M')**."
echo ""

# Test count
if [ -d rust-core ]; then
    pushd rust-core > /dev/null
    n_crates=$(grep -c '^    "crates/' Cargo.toml || echo 0)
    popd > /dev/null
    echo "Workspace: **${n_crates} крейтов**."
    echo ""
fi

echo "## Phase 3 commits (newest first)"
echo ""
echo "| sha | message |"
echo "|-----|---------|"
git log --no-merges -100 --pretty=format:"| %h | %s |"
echo ""
echo ""
echo "## Текущая ветка"
echo ""
echo '```'
git status --short --branch
echo '```'
