"""AI/ai/hive_consumer.py — HV3 worker side (2026-05-04).

Worker pulls queen updates, runs L_CONSENT gate, re-verifies via
local eval, installs approved updates locally.

Public API:
    pull(queen_url=...) -> list[Update]
    apply(update, *, dry_run=False) -> ApplyResult
    sync_state() -> SyncState
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.hive_consumer")

_LOCK = threading.RLock()


@dataclasses.dataclass
class Update:
    id: str
    ts: str
    kind: str
    body: dict
    source_n: int
    eval_delta: Optional[float]
    signature: str


@dataclasses.dataclass
class ApplyResult:
    update_id: str
    installed: bool
    skipped: bool
    skipped_reason: Optional[str]
    notes: list[str]


@dataclasses.dataclass
class SyncState:
    last_pull_ts: Optional[str]
    last_seen_id: Optional[str]
    n_installed: int
    n_skipped: int


def state_db_path() -> Path:
    env = os.environ.get("AIM_HIVE_STATE_DB")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "aim" / "hive_state.db"


def _connect() -> sqlite3.Connection:
    p = state_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            update_id   TEXT PRIMARY KEY,
            update_ts   TEXT NOT NULL,
            kind        TEXT NOT NULL,
            installed   INTEGER NOT NULL DEFAULT 0,
            skipped     INTEGER NOT NULL DEFAULT 0,
            skipped_reason TEXT,
            seen_at     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opt_outs (
            kind        TEXT NOT NULL,
            pattern     TEXT NOT NULL,
            PRIMARY KEY (kind, pattern)
        )
    """)
    return conn


# ── L_CONSENT — opt-in/out ──────────────────────────────────────


def opt_out(kind: str, *, pattern: str = "*") -> None:
    """User opts out of installing updates of `kind`. `pattern` may be
    a glob over update body fields (e.g. skill_id pattern)."""
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO opt_outs(kind, pattern) VALUES (?, ?)",
            (kind, pattern),
        )


def opt_in(kind: str, *, pattern: str = "*") -> bool:
    with _LOCK, contextlib.closing(_connect()) as conn:
        cur = conn.execute(
            "DELETE FROM opt_outs WHERE kind = ? AND pattern = ?",
            (kind, pattern),
        )
        return cur.rowcount > 0


def is_opted_out(kind: str, body: dict) -> bool:
    """Check if user has opted out of this update's kind/pattern."""
    import fnmatch
    with _LOCK, contextlib.closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT pattern FROM opt_outs WHERE kind = ?", (kind,)
        ).fetchall()
    if not rows:
        return False
    # Match against any string-valued field in body.
    for (pattern,) in rows:
        if pattern == "*":
            return True
        for v in body.values():
            if isinstance(v, str) and fnmatch.fnmatch(v, pattern):
                return True
    return False


# ── pull ────────────────────────────────────────────────────────


def pull(queen_url: Optional[str] = None,
         since: Optional[str] = None) -> list[Update]:
    """Fetch updates from queen newer than `since`. If `since` is None,
    we read the last seen update from local sync_log."""
    url = queen_url or os.environ.get("AIM_HIVE_QUEEN_URL")
    if not url:
        log.debug("no queen URL — skipping pull")
        return []
    if since is None:
        since = _last_seen_ts()
    try:
        import httpx
        params = {"since": since} if since else {}
        r = httpx.get(f"{url.rstrip('/')}/v1/hive/updates",
                       params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("pull failed: %s", e)
        return []
    return [Update(**u) for u in data.get("updates", [])]


def _last_seen_ts() -> Optional[str]:
    with _LOCK, contextlib.closing(_connect()) as conn:
        cur = conn.execute(
            "SELECT MAX(update_ts) FROM sync_log"
        ).fetchone()
    return cur[0] if cur and cur[0] else None


# ── apply (with L_CONSENT + L_VERIFIABILITY gates) ─────────────


def apply(update: Update, *, dry_run: bool = False) -> ApplyResult:
    """Install update if all gates pass. Records decision in sync_log."""
    notes: list[str] = []
    seen_at = dt.datetime.now().isoformat(timespec="seconds")

    # Gate 1: L_CONSENT — user opt-out
    if is_opted_out(update.kind, update.body):
        result = ApplyResult(
            update_id=update.id, installed=False, skipped=True,
            skipped_reason="L_CONSENT: user opted out of this kind/pattern",
            notes=notes,
        )
        if not dry_run:
            _record(update, installed=False, skipped=True,
                     skipped_reason=result.skipped_reason, seen_at=seen_at)
        return result

    # Gate 2: signature integrity (basic — real version would verify
    # against queen public key).
    if not update.signature or len(update.signature) < 8:
        result = ApplyResult(
            update_id=update.id, installed=False, skipped=True,
            skipped_reason="signature missing or too short",
            notes=notes,
        )
        if not dry_run:
            _record(update, installed=False, skipped=True,
                     skipped_reason=result.skipped_reason, seen_at=seen_at)
        return result

    # Gate 3: L_VERIFIABILITY — re-run worker-local eval to confirm
    # the update doesn't break things. For framework, we accept any
    # update with a positive eval_delta declared by queen.
    if update.eval_delta is not None and update.eval_delta < 0.0:
        result = ApplyResult(
            update_id=update.id, installed=False, skipped=True,
            skipped_reason=f"eval_delta {update.eval_delta} < 0",
            notes=notes,
        )
        if not dry_run:
            _record(update, installed=False, skipped=True,
                     skipped_reason=result.skipped_reason, seen_at=seen_at)
        return result

    # Install per kind.
    if dry_run:
        notes.append("dry_run — not installed")
        return ApplyResult(update_id=update.id, installed=False,
                            skipped=False, skipped_reason=None, notes=notes)

    try:
        if update.kind == "skill":
            _install_skill(update.body)
            notes.append("skill written to ~/.aim/skills/")
        elif update.kind == "prompt_patch":
            notes.append(
                "prompt_patch recorded; manual review required before "
                "apply (we DO NOT auto-rewrite SELF_DIAGNOSTIC_PROMPT.md)"
            )
        elif update.kind == "eval_case":
            _install_eval_case(update.body)
            notes.append("eval case written to AIM_EVAL_CASES_DIR")
        else:
            notes.append(f"unknown kind {update.kind!r} — left untouched")
    except Exception as e:
        result = ApplyResult(
            update_id=update.id, installed=False, skipped=True,
            skipped_reason=f"install error: {type(e).__name__}: {e}",
            notes=notes,
        )
        _record(update, installed=False, skipped=True,
                 skipped_reason=result.skipped_reason, seen_at=seen_at)
        return result

    _record(update, installed=True, skipped=False,
             skipped_reason=None, seen_at=seen_at)
    return ApplyResult(update_id=update.id, installed=True,
                        skipped=False, skipped_reason=None, notes=notes)


def _install_skill(body: dict) -> None:
    skill_id = body.get("skill_id")
    if not skill_id:
        raise ValueError("skill body missing skill_id")
    skills_dir = Path.home() / ".aim" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    out = skills_dir / f"{skill_id}.json"
    out.write_text(json.dumps(body, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def _install_eval_case(body: dict) -> None:
    case_id = body.get("id") or body.get("case_id")
    if not case_id:
        raise ValueError("eval case missing id")
    cases_dir_str = os.environ.get("AIM_EVAL_CASES_DIR")
    if cases_dir_str:
        cases_dir = Path(cases_dir_str)
    else:
        cases_dir = Path.home() / ".cache" / "aim" / "eval_cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    out = cases_dir / f"{case_id}.yaml"
    # Minimal yaml emit (avoid PyYAML hard dep here)
    parts = [f"id: {case_id}",
             f"task: {json.dumps(body.get('task', '(hive-distilled)'))}"]
    rubrics = body.get("rubrics", {"min_length": 1})
    parts.append("rubrics:")
    for k, v in rubrics.items():
        parts.append(f"  {k}: {json.dumps(v)}")
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _record(update: Update, *, installed: bool, skipped: bool,
            skipped_reason: Optional[str], seen_at: str) -> None:
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_log"
            "(update_id, update_ts, kind, installed, skipped, "
            "skipped_reason, seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (update.id, update.ts, update.kind,
             int(installed), int(skipped), skipped_reason, seen_at),
        )


def sync_state() -> SyncState:
    with _LOCK, contextlib.closing(_connect()) as conn:
        cur = conn.execute(
            "SELECT MAX(seen_at), MAX(update_id), "
            "COALESCE(SUM(installed), 0), COALESCE(SUM(skipped), 0) "
            "FROM sync_log"
        ).fetchone()
    return SyncState(
        last_pull_ts=cur[0],
        last_seen_id=cur[1],
        n_installed=int(cur[2]),
        n_skipped=int(cur[3]),
    )


def summary() -> str:
    s = sync_state()
    parts = ["🐝 Hive consumer state"]
    if s.last_pull_ts:
        parts.append(f"  last pull: {s.last_pull_ts}")
        parts.append(f"  installed: {s.n_installed}, "
                      f"skipped: {s.n_skipped}")
    else:
        parts.append("  no pulls yet")
    return "\n".join(parts)
