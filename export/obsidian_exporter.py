"""export/obsidian_exporter.py — push AIM memory to an Obsidian vault.

Obsidian is just a folder of .md with frontmatter. We mirror AIM's user_memories
into <vault>/AIM/<category>/<file>.md, preserving frontmatter and adding
backlinks (`[[…]]`) for entities that look like proper nouns.

Vault path via env or CLI:
    OBSIDIAN_VAULT=~/Documents/Obsidian/Personal

Usage:
    python -m export.obsidian_exporter export "факт"
    python -m export.obsidian_exporter sync                    # full mirror
    python -m export.obsidian_exporter sync --since 24         # only last 24h
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.obsidian")

VAULT_ENV = "OBSIDIAN_VAULT"
SUBDIR    = "AIM"

# Detect proper nouns (Cyrillic + Latin) — same heuristic as graphrag.py
_ENT_RE = re.compile(
    r"\b("
    r"[A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}(?:[-\s][A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}){0,3}"
    r"|[A-ZА-Я]{3,}"
    r")\b"
)
_STOP = {"The","This","That","Why","How","When","Что","Это","Как","Почему","Если",
         "READ","TODO","DONE","OPEN","CLOSED","TRUE","FALSE"}


def _vault(path: Optional[str] = None) -> Path:
    p = Path(path or os.getenv(VAULT_ENV, "")).expanduser()
    if not p:
        raise RuntimeError(f"set --vault or {VAULT_ENV} env var")
    if not p.exists():
        raise FileNotFoundError(f"vault not found: {p}")
    return p


def _link_entities(text: str) -> str:
    """Wrap Capitalised-entity occurrences in [[backlinks]] (first occurrence only)."""
    seen: set[str] = set()
    def _sub(m: re.Match) -> str:
        ent = m.group(1)
        if ent in _STOP or ent.lower() in seen:
            return ent
        seen.add(ent.lower())
        return f"[[{ent}]]"
    return _ENT_RE.sub(_sub, text)


def export_fact(
    fact: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    vault: Optional[str] = None,
) -> Path:
    v = _vault(vault)
    target_dir = v / SUBDIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    name = f"{ts:%Y%m%d_%H%M%S}_{re.sub(r'[^A-Za-zА-Яа-я0-9_-]+','_', fact[:60])}.md"
    path = target_dir / name

    body = _link_entities(fact)
    header = ["---",
              f"created: {ts.isoformat(timespec='seconds')}",
              f"category: {category}",
              f"source: AIM"]
    if tags:
        header.append(f"tags: [{', '.join(tags)}]")
    header.append("---\n")
    path.write_text("\n".join(header) + "\n" + body + "\n", encoding="utf-8")
    log.info(f"obsidian → {path}")
    return path


def sync(vault: Optional[str] = None, since_hours: Optional[int] = None) -> int:
    """Mirror user_memories/<cat>/*.md to <vault>/AIM/<cat>/."""
    from agents.memory_store import USER_MEMORIES
    v = _vault(vault)
    if not USER_MEMORIES.exists():
        return 0

    cutoff = datetime.now() - timedelta(hours=since_hours) if since_hours else None
    n = 0
    for src in USER_MEMORIES.rglob("*.md"):
        if cutoff and datetime.fromtimestamp(src.stat().st_mtime) < cutoff:
            continue
        cat = src.parent.name
        target_dir = v / SUBDIR / cat
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / src.name
        # Re-write with backlinks instead of plain copy
        text = src.read_text(encoding="utf-8")
        # Keep AIM frontmatter; add backlinks to body only
        m = re.match(r"^(---.*?---\s*\n)(.*)$", text, re.DOTALL)
        if m:
            fm_block, body = m.group(1), m.group(2)
        else:
            fm_block, body = "", text
        dst.write_text(fm_block + _link_entities(body), encoding="utf-8")
        n += 1
    return n


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-export-obsidian")
    p.add_argument("--vault", help=f"vault path (or ${VAULT_ENV})")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("fact")
    e.add_argument("--category", default="general")
    e.add_argument("--tags", help="comma-separated")

    s = sub.add_parser("sync")
    s.add_argument("--since", type=int, default=None,
                   help="only files modified in the last N hours")

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "export":
        tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
        print(export_fact(args.fact, category=args.category, tags=tags, vault=args.vault))
    elif args.cmd == "sync":
        n = sync(vault=args.vault, since_hours=args.since)
        print(f"synced files: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
