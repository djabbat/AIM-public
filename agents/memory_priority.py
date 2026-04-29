"""agents/memory_priority.py — priority levels + TTL for AIM memory facts.

Stores priority/TTL inside the per-fact frontmatter (no schema migration in
LanceDB needed). At search time, expired facts are filtered out and the
results are re-ordered by priority then semantic distance.

Priority classes:
    CRITICAL   — never delete, always surface
    HIGH       — delete only on space pressure
    NORMAL     — default
    LOW        — delete first; surface only if highly relevant
    EPHEMERAL  — auto-delete after 24h regardless of access count

Usage:
    from agents.memory_priority import Priority, save_with_priority, prune_expired
    save_with_priority("Liz Parrish CONSENTED 2026-04-28",
                       category="project", priority=Priority.HIGH, ttl_hours=720)
    prune_expired()      # called by daily cron / aim-memory dedup
"""

from __future__ import annotations

import enum
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from agents.memory_store import remember, USER_MEMORIES

log = logging.getLogger("aim.memory_priority")


class Priority(enum.IntEnum):
    CRITICAL  = 100
    HIGH      = 70
    NORMAL    = 40
    LOW       = 10
    EPHEMERAL = 1


def save_with_priority(
    fact: str,
    category: str = "general",
    priority: Priority = Priority.NORMAL,
    ttl_hours: Optional[int] = None,
    tags: Optional[list[str]] = None,
) -> Path:
    """Persist a fact with priority + TTL embedded in frontmatter."""
    ttl = ttl_hours
    # EPHEMERAL defaults to 24h if not set
    if priority == Priority.EPHEMERAL and ttl is None:
        ttl = 24

    md = {
        "priority":  priority.name,
        "priority_value": int(priority),
    }
    if ttl is not None:
        md["ttl_hours"] = ttl
        md["expires_at"] = (datetime.now() + timedelta(hours=ttl)).isoformat(timespec="seconds")
    if tags:
        md["tags"] = tags

    return remember(fact, category=category, metadata=md)


# ── Frontmatter scan ───────────────────────────────────────────────────────


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _read_frontmatter(p: Path) -> dict:
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return {}
    m = _FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _is_expired(fm: dict) -> bool:
    exp = fm.get("expires_at")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(exp) < datetime.now()
    except ValueError:
        return False


def _priority_value(fm: dict) -> int:
    try:
        return int(fm.get("priority_value", Priority.NORMAL.value))
    except ValueError:
        return Priority.NORMAL.value


# ── Public ops ─────────────────────────────────────────────────────────────


def prune_expired(dry_run: bool = False, root: Path = USER_MEMORIES) -> dict:
    """Walk user_memories/, delete files where expires_at < now and priority != CRITICAL."""
    deleted: list[str] = []
    kept_critical: list[str] = []
    if not root.exists():
        return {"deleted": [], "kept_critical": []}

    for f in root.rglob("*.md"):
        fm = _read_frontmatter(f)
        if not _is_expired(fm):
            continue
        if _priority_value(fm) >= Priority.CRITICAL.value:
            kept_critical.append(str(f))
            continue
        if dry_run:
            deleted.append(str(f))
        else:
            f.unlink()
            deleted.append(str(f))

    log.info(f"prune: deleted={len(deleted)} kept_critical={len(kept_critical)} (dry_run={dry_run})")
    if not dry_run and deleted:
        try:
            import subprocess
            subprocess.run(["aim-memory-index", "reindex-incremental"],
                           capture_output=True, timeout=300)
        except Exception as e:
            log.info(f"reindex after prune failed: {e}")
    return {"deleted": deleted, "kept_critical": kept_critical}


def filter_and_rank(hits: list[dict]) -> list[dict]:
    """Take retrieval hits, drop expired, re-rank by (priority desc, distance asc)."""
    enriched: list[tuple[int, float, dict]] = []
    for h in hits:
        # h["file"] is a stem like "20260428_…"; locate it under user_memories/
        path = _locate(h["file"])
        fm = _read_frontmatter(path) if path else {}
        if _is_expired(fm):
            continue
        prio = _priority_value(fm)
        enriched.append((prio, h.get("_distance", 1.0), h))
    enriched.sort(key=lambda x: (-x[0], x[1]))
    return [h for _, _, h in enriched]


def _locate(file_name: str) -> Optional[Path]:
    # File names from LanceDB are basenames; user_memories/<cat>/<file>
    for p in USER_MEMORIES.rglob(file_name):
        return p
    p = (USER_MEMORIES.parent / file_name)
    return p if p.exists() else None
