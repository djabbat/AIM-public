"""migrations/migrator.py — schema migration manager for AIM SQLite databases.

Lightweight alternative to Alembic. Each DB tracks its own version in a
`_aim_schema_version` table. Migrations are pure-Python functions registered
per database name. A migration is `def upgrade(conn): ...` returning None.

Why not Alembic?  Our DBs are created lazily by their respective modules
(no Base/MetaData declared upfront), and we need migrations that run
idempotently at process startup, not as a separate command.

Registered databases:
    graph_state    ~/.claude/aim_graph_state.db
    job_queue      ~/.claude/aim_jobs.db
    llm_cache      ~/.claude/llm_cache.db
    cost_monitor   ~/.claude/cost_monitor.db

Add a new migration:
    @register("llm_cache", version=2,
              description="add 'lang' column to cache rows")
    def m_llm_cache_002(conn):
        conn.execute("ALTER TABLE cache ADD COLUMN lang TEXT")

Run:
    python -m migrations.migrator status
    python -m migrations.migrator migrate          # apply all pending
    python -m migrations.migrator migrate --db cost_monitor
    aim-migrate                                    # wrapper

Programmatic:
    from migrations.migrator import migrate_all
    migrate_all()                                  # at process startup
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger("aim.migrator")


# ── DB registry ────────────────────────────────────────────────────────────


def _path(env: str, default: str) -> Path:
    return Path(os.getenv(env, default)).expanduser()


DATABASES: dict[str, Path] = {
    "graph_state":  _path("AIM_GRAPH_STATE_DB", "~/.claude/aim_graph_state.db"),
    "job_queue":    _path("AIM_JOBS_DB",        "~/.claude/aim_jobs.db"),
    "llm_cache":    _path("AIM_LLM_CACHE_DB",   "~/.claude/llm_cache.db"),
    "cost_monitor": Path("~/.claude/cost_monitor.db").expanduser(),
}

VERSION_TABLE = "_aim_schema_version"


# ── migration registry ─────────────────────────────────────────────────────


@dataclass
class Migration:
    db_name:    str
    version:    int
    description: str
    upgrade_fn: Callable[[sqlite3.Connection], None]


_REGISTRY: list[Migration] = []


def register(db_name: str, version: int, description: str = "") -> Callable:
    def deco(fn: Callable) -> Callable:
        _REGISTRY.append(Migration(db_name, version, description, fn))
        return fn
    return deco


def _migrations_for(db_name: str) -> list[Migration]:
    return sorted([m for m in _REGISTRY if m.db_name == db_name], key=lambda m: m.version)


# ── version table helpers ──────────────────────────────────────────────────


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT,
            description TEXT
        )
    """)


def _current_version(conn: sqlite3.Connection) -> int:
    _ensure_version_table(conn)
    row = conn.execute(
        f"SELECT MAX(version) FROM {VERSION_TABLE}"
    ).fetchone()
    return row[0] or 0


def _record_applied(conn: sqlite3.Connection, m: Migration) -> None:
    conn.execute(
        f"INSERT INTO {VERSION_TABLE} (version, applied_at, description) VALUES (?,?,?)",
        (m.version, datetime.now().isoformat(timespec="seconds"), m.description),
    )


# ── public API ─────────────────────────────────────────────────────────────


def status() -> dict:
    out: dict[str, dict] = {}
    for name, path in DATABASES.items():
        if not path.exists():
            out[name] = {"path": str(path), "exists": False, "current": 0,
                         "pending": [m.version for m in _migrations_for(name)]}
            continue
        conn = sqlite3.connect(str(path))
        try:
            cur = _current_version(conn)
        finally:
            conn.close()
        all_migs = _migrations_for(name)
        out[name] = {
            "path":     str(path),
            "exists":   True,
            "current":  cur,
            "latest":   all_migs[-1].version if all_migs else cur,
            "pending":  [m.version for m in all_migs if m.version > cur],
        }
    return out


def migrate(db_name: str | None = None) -> dict:
    """Apply pending migrations to one or all DBs. Idempotent."""
    targets = [db_name] if db_name else list(DATABASES.keys())
    results: dict[str, list[dict]] = {}
    for name in targets:
        if name not in DATABASES:
            results[name] = [{"error": "unknown database"}]
            continue
        path = DATABASES[name]
        if not path.exists():
            results[name] = [{"skipped": "database not yet created"}]
            continue
        results[name] = _apply_one(name, path)
    return results


def _apply_one(name: str, path: Path) -> list[dict]:
    out: list[dict] = []
    conn = sqlite3.connect(str(path))
    try:
        cur = _current_version(conn)
        for m in _migrations_for(name):
            if m.version <= cur:
                continue
            try:
                with conn:
                    m.upgrade_fn(conn)
                    _record_applied(conn, m)
                out.append({"applied": m.version, "description": m.description})
                log.info(f"{name}: applied v{m.version} ({m.description})")
            except Exception as e:
                log.exception(f"{name}: v{m.version} FAILED")
                out.append({"failed": m.version, "error": str(e)})
                break
    finally:
        conn.close()
    return out


def migrate_all() -> dict:
    return migrate(None)


# ─────────────────────────────────────────────────────────────────────────
# Migration definitions (declared here so they auto-register on import)
# Each migration:
#   • is idempotent (uses IF NOT EXISTS / try-except for ALTER)
#   • wraps in conn.execute (autocommit via `with conn:`)
# ─────────────────────────────────────────────────────────────────────────


# graph_state — LangGraph SqliteSaver creates its own schema.
# We add an analytics index on top.
@register("graph_state", version=1, description="index on checkpoints (thread_id)")
def _gs_001(conn: sqlite3.Connection) -> None:
    # SqliteSaver in 0.x uses table 'checkpoints'; in 1.x — same name.
    tabs = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "checkpoints" in tabs:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_thread "
                     "ON checkpoints(thread_id)")


@register("job_queue", version=1, description="index on jobs(status,created_at)")
def _jq_001(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created "
                 "ON jobs(status, created_at)")


@register("job_queue", version=2, description="add 'progress' integer column to jobs")
def _jq_002(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "progress" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0")


@register("llm_cache", version=1, description="index on cache.created_at")
def _lc_001(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created "
                 "ON cache(created_at)")


@register("llm_cache", version=2, description="add 'lang' column for per-language cache")
def _lc_002(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cache)").fetchall()}
    if "lang" not in cols:
        conn.execute("ALTER TABLE cache ADD COLUMN lang TEXT")


@register("cost_monitor", version=1, description="index on costs.ts (date prefix)")
def _cm_001(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_costs_ts ON costs(ts)")


@register("cost_monitor", version=2, description="add 'task_id' index on costs")
def _cm_002(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_costs_task ON costs(task_id)")


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-migrate")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    m = sub.add_parser("migrate")
    m.add_argument("--db", default=None,
                   help="apply only to this database (default: all)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.cmd == "migrate":
        print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
