"""agents/memory_cli.py — unified CLI for AIM's own memory.

Subcommands:
    add      Save a fact (calls memory_store.remember)
    search   Semantic search (LanceDB) or GraphRAG hop-expanded
    delete   Remove memory files matching a pattern
    stats    Counts + size + GraphRAG node count
    backup   Snapshot LanceDB + GraphRAG to ~/Desktop/AIM/memory_backup_<ts>/
    snapshot Versioning snapshot (→ memory_versioning.MemoryVersioning.snapshot)
    rollback Roll back to a snapshot version
    diff     Diff two snapshots
    dedup    Find + merge near-duplicates (memory_deduplicate)

Run any subcommand with -h for its options.
Wired up as: python -m agents.memory_cli <cmd> ...
            (and as the `aim-memory` shell wrapper if installed)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from agents.memory_store import remember, recall, forget, USER_MEMORIES, MEMORY_DIR

log = logging.getLogger("aim.memory_cli")


def _cmd_add(args) -> int:
    md = {}
    if args.tags:
        md["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.priority:
        md["priority"] = args.priority
    if args.ttl_hours:
        md["ttl_hours"] = args.ttl_hours
    path = remember(args.fact, category=args.category, metadata=md or None)
    print(f"OK → {path}")
    return 0


def _cmd_search(args) -> int:
    if args.graph:
        from agents.graphrag import query as graphrag_query
        hits = graphrag_query(args.query, k=args.limit, hops=args.hops)
    else:
        from agents.memory_index import retrieve
        hits = retrieve(args.query, k=args.limit)
    if not hits:
        print("(нет совпадений)")
        return 0
    for i, h in enumerate(hits, 1):
        print(f"\n{i}. [{h.get('_distance', 0):.3f}]  {h['file']}")
        preview = h["text"].replace("\n", " ")[:240]
        print(f"   {preview}…")
    return 0


def _cmd_delete(args) -> int:
    if not args.force:
        try:
            ans = input(f"Удалить все memory-файлы, чьё имя содержит {args.pattern!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 1
        if ans not in ("y", "yes", "да"):
            print("отменено")
            return 0
    n = forget(args.pattern)
    print(f"удалено: {n}")
    return 0


def _cmd_stats(args) -> int:
    from agents.memory_index import status
    info = status()
    print("# AIM Memory Stats")
    for k, v in info.items():
        print(f"  {k}: {v}")
    # GraphRAG
    try:
        from agents.graphrag import load_graph
        g = load_graph()
        print(f"  graph_nodes: {g.number_of_nodes()}")
        print(f"  graph_edges: {g.number_of_edges()}")
    except Exception as e:
        print(f"  graph: not built ({e})")
    # User memories
    if USER_MEMORIES.exists():
        n = sum(1 for _ in USER_MEMORIES.rglob("*.md"))
        print(f"  user_memories: {n}")
    return 0


def _cmd_backup(args) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(f"~/Desktop/AIM/memory_backup_{ts}").expanduser()
    out.mkdir(parents=True, exist_ok=True)
    src_idx = Path("~/.claude/memory_index").expanduser()
    if src_idx.exists():
        shutil.copytree(src_idx, out / "memory_index", dirs_exist_ok=True)
    if MEMORY_DIR.exists():
        shutil.copytree(MEMORY_DIR, out / "memory_md", dirs_exist_ok=True)
    print(f"backup → {out}")
    return 0


def _cmd_snapshot(args) -> int:
    from agents.memory_versioning import MemoryVersioning
    v = MemoryVersioning().snapshot(args.description or "")
    print(v)
    return 0


def _cmd_rollback(args) -> int:
    from agents.memory_versioning import MemoryVersioning
    MemoryVersioning().rollback(args.version_id)
    return 0


def _cmd_diff(args) -> int:
    from agents.memory_versioning import MemoryVersioning
    d = MemoryVersioning().diff(args.a, args.b)
    print(json.dumps({
        "added":   d["total_added"],
        "removed": d["total_removed"],
        "first_added":   [m.get("name") for m in d["added"][:5]],
        "first_removed": [m.get("name") for m in d["removed"][:5]],
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_dedup(args) -> int:
    from agents.memory_deduplicate import MemoryDeduplicator
    d = MemoryDeduplicator(threshold=args.threshold)
    pairs = d.scan(dry_run=args.dry_run)
    print(json.dumps({"pairs_found": len(pairs),
                      "preview": pairs[:5]}, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aim-memory", description="AIM memory management CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add a fact")
    a.add_argument("fact")
    a.add_argument("--category", default="general")
    a.add_argument("--tags", help="comma-separated tags")
    a.add_argument("--priority", choices=["critical","high","normal","low","ephemeral"])
    a.add_argument("--ttl-hours", type=int)
    a.set_defaults(fn=_cmd_add)

    s = sub.add_parser("search", help="semantic / graphrag search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--graph", action="store_true", help="use GraphRAG hop expansion")
    s.add_argument("--hops", type=int, default=1)
    s.set_defaults(fn=_cmd_search)

    d = sub.add_parser("delete", help="forget by filename pattern")
    d.add_argument("pattern")
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=_cmd_delete)

    st = sub.add_parser("stats", help="memory statistics")
    st.set_defaults(fn=_cmd_stats)

    b = sub.add_parser("backup", help="full snapshot of LanceDB + memory dir")
    b.set_defaults(fn=_cmd_backup)

    sn = sub.add_parser("snapshot", help="versioning snapshot (git-like)")
    sn.add_argument("description", nargs="?", default="")
    sn.set_defaults(fn=_cmd_snapshot)

    rb = sub.add_parser("rollback", help="revert memory to a snapshot")
    rb.add_argument("version_id")
    rb.set_defaults(fn=_cmd_rollback)

    df = sub.add_parser("diff", help="diff two snapshots")
    df.add_argument("a"); df.add_argument("b")
    df.set_defaults(fn=_cmd_diff)

    dd = sub.add_parser("dedup", help="scan for near-duplicates")
    dd.add_argument("--threshold", type=float, default=0.85)
    dd.add_argument("--dry-run", action="store_true")
    dd.set_defaults(fn=_cmd_dedup)
    return p


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    parser = _build_parser()
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
