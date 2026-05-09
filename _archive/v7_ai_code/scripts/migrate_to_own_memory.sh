#!/usr/bin/env bash
# scripts/migrate_to_own_memory.sh — one-shot migration from Claude Code
# memory autoload to AIM's own LanceDB-backed memory.
#
# Idempotent: safe to re-run; tracks state in ~/.claude/memory_import_log.json
# and creates a versioning snapshot before mutating anything.
#
# Run from AIM root:
#   bash scripts/migrate_to_own_memory.sh

set -euo pipefail
cd "$(dirname "$0")/.."

ts() { date +%Y%m%d_%H%M%S; }

echo "🚀 AIM memory migration"
echo "═══════════════════════════════════════════════════════════════════"

echo
echo "▸ 1/6  Pre-migration audit (analyze_claude_memory)"
python3 -m scripts.analyze_claude_memory

echo
echo "▸ 2/5  Versioning snapshot (pre-migration)"
python3 -c "from agents.memory_versioning import MemoryVersioning; \
print('snapshot:', MemoryVersioning().snapshot('pre-migration $(ts)'))"

# Note: NO separate Desktop backup — original Claude memory dir is NOT touched
# by the importer. The versioning snapshot above is the rollback point.

echo
echo "▸ 3/5  Import Claude memory → AIM user_memories/"
python3 -m scripts.import_claude_memory

echo
echo "▸ 4/5  Build GraphRAG entity graph"
python3 -m agents.graphrag build || echo "   (skipped — networkx missing?)"

echo
echo "▸ 5/5  Status check"
python3 -m agents.memory_cli stats

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "✅ migration done. Test with:"
echo "   aim-graph --memory 'тест памяти AIM'"
echo "   aim-graph --memory 'кто такой Eric Klien?'  # graph + flat"
echo
echo "  rollback:  python3 -m agents.memory_cli rollback <version_id>"
echo "  versions:  python3 -c 'from agents.memory_versioning import MemoryVersioning as V; \
import json; print(json.dumps(V().list_versions(), indent=2, ensure_ascii=False))'"
