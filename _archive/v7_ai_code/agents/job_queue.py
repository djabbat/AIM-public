"""agents/job_queue.py — in-process async job queue with persistent state.

No Redis/Celery dependency. Jobs run on a ThreadPoolExecutor; state is
mirrored to ~/.claude/aim_jobs.db (SQLite) so callers can poll status across
processes (e.g. CLI submits, web UI polls).

Use cases:
    • aim-memory-index reindex --async   → returns job_id immediately
    • aim-graph "...long task..." --async
    • Web UI shows live status across requests

API:
    from agents.job_queue import submit, get, list_jobs, cancel
    job_id = submit("reindex", lambda: reindex(), tags=["memory"])
    info = get(job_id)
    # {'id':..., 'status':'running'|'completed'|'failed'|'cancelled', ...}
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("aim.job_queue")

DB_PATH = Path("~/.claude/aim_jobs.db").expanduser()
MAX_WORKERS = 4

# Status values
PENDING, RUNNING, COMPLETED, FAILED, CANCELLED = "pending", "running", "completed", "failed", "cancelled"


# ── Persistent state ────────────────────────────────────────────────────────


_DB_LOCK = threading.Lock()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            tags TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            error TEXT,
            duration_s REAL
        )
    """)
    return conn


def _persist(job_id: str, **fields) -> None:
    cols = ",".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with _DB_LOCK:
        c = _db()
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)


def _insert(job_id: str, name: str, tags: list[str]) -> None:
    with _DB_LOCK:
        c = _db()
        c.execute(
            "INSERT OR REPLACE INTO jobs (id,name,status,tags,created_at) VALUES (?,?,?,?,?)",
            (job_id, name, PENDING, ",".join(tags or []), datetime.now().isoformat(timespec="seconds")),
        )


def _row(job_id: str) -> Optional[dict]:
    with _DB_LOCK:
        c = _db()
        cur = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
    if not row:
        return None
    out = dict(zip(cols, row))
    if out.get("tags"):
        out["tags"] = out["tags"].split(",")
    return out


# ── Worker pool ────────────────────────────────────────────────────────────


class _JobRunner:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aim-job")
        self.cancelled: set[str] = set()
        self.futures: dict[str, Future] = {}

    def submit(self, name: str, fn: Callable, *args, tags: list[str] | None = None, **kwargs) -> str:
        job_id = uuid.uuid4().hex[:12]
        _insert(job_id, name, tags or [])

        def _run():
            if job_id in self.cancelled:
                _persist(job_id, status=CANCELLED,
                         completed_at=datetime.now().isoformat(timespec="seconds"))
                return
            t0 = time.time()
            _persist(job_id, status=RUNNING,
                     started_at=datetime.now().isoformat(timespec="seconds"))
            try:
                result = fn(*args, **kwargs)
                _persist(job_id, status=COMPLETED,
                         completed_at=datetime.now().isoformat(timespec="seconds"),
                         duration_s=round(time.time() - t0, 3),
                         result=_safe_json(result))
            except Exception as e:
                tb = traceback.format_exc()
                _persist(job_id, status=FAILED,
                         completed_at=datetime.now().isoformat(timespec="seconds"),
                         duration_s=round(time.time() - t0, 3),
                         error=f"{e}\n\n{tb}"[:4000])

        self.futures[job_id] = self.pool.submit(_run)
        return job_id

    def cancel(self, job_id: str) -> bool:
        f = self.futures.get(job_id)
        if f and not f.done():
            ok = f.cancel()
            if ok:
                self.cancelled.add(job_id)
                _persist(job_id, status=CANCELLED,
                         completed_at=datetime.now().isoformat(timespec="seconds"))
            return ok
        self.cancelled.add(job_id)
        return False


_RUNNER: _JobRunner | None = None


def _runner() -> _JobRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = _JobRunner()
    return _RUNNER


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:8000]
    except Exception:
        return str(obj)[:8000]


# ── Public API ─────────────────────────────────────────────────────────────


def submit(name: str, fn: Callable, *args, tags: list[str] | None = None, **kwargs) -> str:
    return _runner().submit(name, fn, *args, tags=tags, **kwargs)


def get(job_id: str) -> Optional[dict]:
    return _row(job_id)


def cancel(job_id: str) -> bool:
    return _runner().cancel(job_id)


def list_jobs(limit: int = 50, status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM jobs"
    args: tuple = ()
    if status:
        sql += " WHERE status=?"
        args = (status,)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args = (*args, limit)
    with _DB_LOCK:
        c = _db()
        cur = c.execute(sql, args)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def wait(job_id: str, timeout_s: float = 600.0, poll_s: float = 0.5) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        info = _row(job_id)
        if info and info["status"] in (COMPLETED, FAILED, CANCELLED):
            return info
        time.sleep(poll_s)
    return _row(job_id) or {"id": job_id, "status": "timeout"}


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(prog="aim-jobs")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=[PENDING, RUNNING, COMPLETED, FAILED, CANCELLED])
    ls.add_argument("--limit", type=int, default=50)

    g = sub.add_parser("get")
    g.add_argument("job_id")

    cn = sub.add_parser("cancel")
    cn.add_argument("job_id")

    args = p.parse_args()
    if args.cmd == "list":
        for j in list_jobs(limit=args.limit, status=args.status):
            print(f"  {j['status']:<10} {j['id']}  {j['name']}  ({j.get('duration_s') or '-'}s)")
    elif args.cmd == "get":
        info = get(args.job_id)
        print(json.dumps(info, ensure_ascii=False, indent=2) if info else "not found")
    elif args.cmd == "cancel":
        print("cancelled" if cancel(args.job_id) else "not cancellable")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
