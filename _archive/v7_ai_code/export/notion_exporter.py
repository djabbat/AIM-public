"""export/notion_exporter.py — push AIM memory to a Notion database.

Notion is opt-in: requires `notion-client` (`pip install notion-client`) and
two env vars:

    NOTION_API_KEY      — integration token (Internal integration)
    NOTION_DATABASE_ID  — destination database (32-char UUID)

The target database must have at least a *Title* property; AIM also writes
to optional fields if they exist:
    - Category   (Select)
    - Tags       (Multi-select)
    - Source     (Rich text)
    - Date       (Date)

Usage:
    python -m export.notion_exporter export "факт"
    python -m export.notion_exporter sync-recent --limit 50    # last N AIM memories
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.notion")


def _client():
    try:
        from notion_client import Client
    except ImportError as e:
        raise RuntimeError("pip install notion-client") from e
    key = os.getenv("NOTION_API_KEY")
    if not key:
        raise RuntimeError("set NOTION_API_KEY env var")
    return Client(auth=key)


def _database_id() -> str:
    db = os.getenv("NOTION_DATABASE_ID")
    if not db:
        raise RuntimeError("set NOTION_DATABASE_ID env var")
    return db


# ── Public API ──────────────────────────────────────────────────────────────


def export_fact(
    fact: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    source_note: str = "AIM",
) -> dict:
    cl = _client()
    db_id = _database_id()

    # Discover schema to know which properties exist
    db_meta = cl.databases.retrieve(db_id)
    props_avail = set(db_meta.get("properties", {}).keys())

    title = fact[:80].replace("\n", " ").strip() or "(untitled)"
    properties: dict = {}
    title_prop_name = next(
        (n for n, p in db_meta["properties"].items() if p.get("type") == "title"),
        None,
    )
    if not title_prop_name:
        raise RuntimeError("database has no title property")
    properties[title_prop_name] = {"title": [{"text": {"content": title}}]}

    if "Category" in props_avail:
        properties["Category"] = {"select": {"name": category}}
    if "Tags" in props_avail and tags:
        properties["Tags"] = {"multi_select": [{"name": t} for t in tags]}
    if "Source" in props_avail:
        properties["Source"] = {"rich_text": [{"text": {"content": source_note}}]}
    if "Date" in props_avail:
        properties["Date"] = {"date": {"start": datetime.now().date().isoformat()}}

    page = cl.pages.create(
        parent={"database_id": db_id},
        properties=properties,
        children=[{
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": fact[:1900]}}]},
        }],
    )
    log.info(f"notion page → {page.get('url')}")
    return {"page_id": page["id"], "url": page.get("url")}


def sync_recent(limit: int = 20) -> int:
    """Push last `limit` AIM user_memories to Notion."""
    from agents.memory_store import USER_MEMORIES
    if not USER_MEMORIES.exists():
        log.warning("no user_memories dir")
        return 0
    files = sorted(USER_MEMORIES.rglob("*.md"), key=lambda p: -p.stat().st_mtime)[:limit]
    n = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        # strip frontmatter
        import re
        body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.DOTALL).strip()
        cat = f.parent.name
        try:
            export_fact(body, category=cat, source_note=f"AIM/{f.name}")
            n += 1
        except Exception as e:
            log.warning(f"failed {f.name}: {e}")
    return n


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-export-notion")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("fact")
    e.add_argument("--category", default="general")
    e.add_argument("--tags", help="comma-separated")
    s = sub.add_parser("sync-recent")
    s.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "export":
        tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
        print(export_fact(args.fact, category=args.category, tags=tags))
    elif args.cmd == "sync-recent":
        n = sync_recent(args.limit)
        print(f"synced: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
