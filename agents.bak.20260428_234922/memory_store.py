"""agents/memory_store.py — long-term cross-session memory.

Writes one .md per fact under ~/.claude/projects/-home-oem/memory/user_memories/<category>/
in the same format the auto-memory system already uses, then triggers an
incremental reindex so the next agent run can semantically retrieve it.

CLI:
    python3 -m agents.memory_store remember "мой любимый цвет синий"
    python3 -m agents.memory_store remember "TSU PhD контакт Trapaidze" --category contacts
    python3 -m agents.memory_store recall "любимый цвет"
    python3 -m agents.memory_store forget "цвет"
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger("aim.memory_store")

MEMORY_DIR    = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
USER_MEMORIES = MEMORY_DIR / "user_memories"


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\-_.\s]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s[:max_len] or "memory"


def remember(fact: str, category: str = "general") -> Path:
    """Persist `fact` as a memory file. Returns the path written."""
    USER_MEMORIES.mkdir(parents=True, exist_ok=True)
    cat_dir = USER_MEMORIES / category
    cat_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now()
    slug = _slugify(fact)
    name = f"{ts.strftime('%Y%m%d_%H%M%S')}_{slug}.md"
    path = cat_dir / name

    body = (
        f"---\n"
        f"name: {slug}\n"
        f"description: {fact[:200]}\n"
        f"type: user\n"
        f"category: {category}\n"
        f"created: {ts.isoformat(timespec='seconds')}\n"
        f"---\n\n"
        f"{fact}\n"
    )
    path.write_text(body, encoding="utf-8")
    print(f"✅ запомнено: {path}")

    # Trigger incremental reindex
    try:
        subprocess.run(["aim-memory-index", "reindex-incremental"],
                       capture_output=True, timeout=120)
    except Exception as e:
        log.info(f"reindex failed (non-fatal): {e}")

    return path


def recall(query: str, k: int = 5) -> list[dict]:
    """Semantic search over the auto-memory index. Returns hits."""
    try:
        from agents.memory_index import retrieve
        hits = retrieve(query, k=k)
    except Exception as e:
        print(f"⚠️  recall failed: {e}", file=sys.stderr)
        return []

    if not hits:
        print("(нет совпадений)")
        return []

    print(f"\nтоп-{len(hits)} для запроса: {query!r}")
    print("─" * 70)
    for h in hits:
        print(f"  {h['_distance']:.3f}  {h['file']}")
        preview = h["text"].replace("\n", " ")[:200]
        print(f"         {preview}…\n")
    return hits


def forget(pattern: str) -> int:
    """Delete user memory files whose name matches `pattern`. Returns count."""
    if not USER_MEMORIES.exists():
        print("(хранилище пустое)")
        return 0
    n = 0
    for path in USER_MEMORIES.rglob(f"*{pattern}*"):
        if path.is_file():
            path.unlink()
            print(f"🗑  {path}")
            n += 1
    if n == 0:
        print(f"(не найдено: {pattern})")
    else:
        try:
            subprocess.run(["aim-memory-index", "reindex-incremental"],
                           capture_output=True, timeout=120)
        except Exception:
            pass
    return n


def _main() -> int:
    p = argparse.ArgumentParser(description="AIM long-term cross-session memory")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("remember")
    r.add_argument("fact")
    r.add_argument("--category", default="general")

    rc = sub.add_parser("recall")
    rc.add_argument("query")
    rc.add_argument("-k", type=int, default=5)

    f = sub.add_parser("forget")
    f.add_argument("pattern")

    args = p.parse_args()
    if args.cmd == "remember":
        remember(args.fact, args.category)
    elif args.cmd == "recall":
        recall(args.query, args.k)
    elif args.cmd == "forget":
        forget(args.pattern)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
