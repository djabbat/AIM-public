"""AI/ai/hive_queen.py — HV2 queen side (2026-05-04).

Queen runs as a single-node aggregator. Workers POST their anonymized
contributions; queen stores them, periodically distills them into
candidate updates (skills, prompt patches, eval cases), gates each
candidate through an eval suite, and publishes approved updates back
to a feed workers pull from.

This module implements the queen-side primitives. HTTP layer is
optional — all functions work in-process for testing/local hive.

Public API:
    accept_contribution(payload) -> str | None  — store, return contribution_id
    list_contributions(*, limit=N) -> list[Contribution]
    distill_candidates() -> list[Candidate]
    publish_update(candidate, *, eval_pass=True) -> Update | None
    list_updates(since=None) -> list[Update]
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.hive_queen")

_LOCK = threading.RLock()


def queen_db_path() -> Path:
    env = os.environ.get("AIM_HIVE_QUEEN_DB")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "aim" / "hive_queen.db"


def _connect() -> sqlite3.Connection:
    p = queen_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contributions (
            id          TEXT PRIMARY KEY,
            ts          TEXT NOT NULL,
            worker_id   TEXT NOT NULL,
            payload     TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contrib_worker "
        "ON contributions(worker_id, ts)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id          TEXT PRIMARY KEY,
            ts          TEXT NOT NULL,
            kind        TEXT NOT NULL,
            body        TEXT NOT NULL,
            source_n    INTEGER NOT NULL,
            eval_delta  REAL,
            signature   TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_updates_ts ON updates(ts)")
    return conn


@dataclasses.dataclass
class Contribution:
    id: str
    ts: str
    worker_id: str
    payload: dict


@dataclasses.dataclass
class Candidate:
    kind: str               # "skill" | "prompt_patch" | "eval_case"
    body: dict              # what to publish
    source_workers: set[str]  # which workers supplied evidence
    rationale: str

    @property
    def source_n(self) -> int:
        return len(self.source_workers)


@dataclasses.dataclass
class Update:
    id: str
    ts: str
    kind: str
    body: dict
    source_n: int
    eval_delta: Optional[float]
    signature: str


# ── accept ──────────────────────────────────────────────────────


def accept_contribution(payload: dict) -> Optional[str]:
    """Validate payload and persist. Returns contribution id, or None
    if rejected."""
    if not isinstance(payload, dict):
        log.warning("rejected non-dict payload")
        return None
    if payload.get("v") != 1:
        log.warning("rejected payload with v=%r", payload.get("v"))
        return None
    worker_id = payload.get("worker_id")
    if not worker_id or len(worker_id) < 8:
        log.warning("rejected payload with missing worker_id")
        return None

    contrib_id = str(uuid.uuid4())
    ts = dt.datetime.now().isoformat(timespec="seconds")
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO contributions(id, ts, worker_id, payload) "
            "VALUES (?, ?, ?, ?)",
            (contrib_id, ts, worker_id, blob),
        )
    return contrib_id


def list_contributions(*, limit: int = 100,
                        worker_id: Optional[str] = None) -> list[Contribution]:
    with _LOCK, contextlib.closing(_connect()) as conn:
        if worker_id:
            cur = conn.execute(
                "SELECT id, ts, worker_id, payload FROM contributions "
                "WHERE worker_id = ? ORDER BY ts DESC LIMIT ?",
                (worker_id, limit),
            )
        else:
            cur = conn.execute(
                "SELECT id, ts, worker_id, payload FROM contributions "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
    return [
        Contribution(id=r[0], ts=r[1], worker_id=r[2],
                       payload=json.loads(r[3]))
        for r in rows
    ]


# ── distill ─────────────────────────────────────────────────────


_MIN_WORKERS_FOR_PATTERN = 2  # distill only if N+ workers showed it


def distill_candidates() -> list[Candidate]:
    """Walk contributions, identify cross-worker patterns, output
    candidate updates. Pure function — does NOT publish."""
    contribs = list_contributions(limit=1000)
    if not contribs:
        return []

    cands: list[Candidate] = []

    # 1. Compliance drift detection.
    by_worker: dict[str, float] = {}
    for c in contribs:
        led = c.payload.get("ledger", {})
        if led.get("n_runs", 0) > 0:
            by_worker[c.worker_id] = led.get("avg_compliance", 0.0)
    if len(by_worker) >= _MIN_WORKERS_FOR_PATTERN:
        avg = sum(by_worker.values()) / len(by_worker)
        if avg < 0.5:
            cands.append(Candidate(
                kind="prompt_patch",
                body={
                    "patch_type": "tighten_compliance_rule",
                    "current_avg": round(avg, 3),
                    "rationale": "Cross-worker compliance ≤50% — prompt rule "
                                  "may not be enforcing path:line",
                },
                source_workers=set(by_worker.keys()),
                rationale=(f"avg compliance {avg:.0%} across "
                            f"{len(by_worker)} workers — consider stronger "
                            "rule wording"),
            ))

    # 2. Reflexion theme convergence — if multiple workers cluster the
    # same theme, that's a pattern worth extracting as a skill.
    theme_workers: dict[tuple[str, ...], set[str]] = {}
    for c in contribs:
        for cl in c.payload.get("reflexion", {}).get("clusters", []):
            theme = tuple(sorted(cl.get("theme", [])))
            if not theme:
                continue
            theme_workers.setdefault(theme, set()).add(c.worker_id)
    for theme, ws in theme_workers.items():
        if len(ws) >= _MIN_WORKERS_FOR_PATTERN:
            cands.append(Candidate(
                kind="skill",
                body={
                    "skill_id": "auto-" + hashlib.sha256(
                        " ".join(theme).encode()
                    ).hexdigest()[:8],
                    "theme": list(theme),
                    "rationale": (f"theme {theme} appeared across "
                                    f"{len(ws)} workers"),
                },
                source_workers=ws,
                rationale=f"theme {theme} clustered across {len(ws)} workers",
            ))

    # 3. Phase E (HW1, 2026-05-06) — patient_followup_drift signal.
    # Workers report `patient_comms.overdue_count` per contribution
    # (anonymized — total count only, no patient_id). When average
    # overdue count ≥ 3 across N workers → drift candidate.
    drift_by_worker: dict[str, int] = {}
    for c in contribs:
        cnt = c.payload.get("patient_comms", {}).get("overdue_count")
        if isinstance(cnt, int) and cnt > 0:
            drift_by_worker[c.worker_id] = cnt
    if len(drift_by_worker) >= _MIN_WORKERS_FOR_PATTERN:
        avg = sum(drift_by_worker.values()) / len(drift_by_worker)
        if avg >= 3.0:
            cands.append(Candidate(
                kind="patient_followup_drift",
                body={
                    "current_avg_overdue": round(avg, 2),
                    "rationale": (
                        "Cross-worker patient follow-up backlog: "
                        f"avg {avg:.1f} overdue per node. "
                        "Suggests workflow gap (no scheduled review of "
                        "patient_comms.overdue) or insufficient capacity."
                    ),
                },
                source_workers=set(drift_by_worker.keys()),
                rationale=(
                    f"avg {avg:.1f} overdue patient follow-ups across "
                    f"{len(drift_by_worker)} workers — process improvement "
                    "candidate"
                ),
            ))

    return cands


# ── publish ─────────────────────────────────────────────────────


def _signature(body: dict) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:24]


def publish_update(candidate: Candidate,
                    *, eval_pass: bool = True,
                    eval_delta: Optional[float] = None) -> Optional[Update]:
    """Convert a candidate into a published update if its eval gate
    passes. eval_pass / eval_delta come from the caller (HV3 eval gate)."""
    if not eval_pass:
        log.info("eval gate refused candidate %s", candidate.kind)
        return None
    update_id = str(uuid.uuid4())
    ts = dt.datetime.now().isoformat(timespec="seconds")
    body = candidate.body
    sig = _signature(body)
    with _LOCK, contextlib.closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO updates(id, ts, kind, body, source_n, "
            "eval_delta, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (update_id, ts, candidate.kind,
             json.dumps(body, ensure_ascii=False),
             candidate.source_n, eval_delta, sig),
        )
    return Update(
        id=update_id, ts=ts, kind=candidate.kind, body=body,
        source_n=candidate.source_n, eval_delta=eval_delta, signature=sig,
    )


def list_updates(since: Optional[str] = None) -> list[Update]:
    """Updates available to workers. `since` = ISO timestamp; only newer."""
    with _LOCK, contextlib.closing(_connect()) as conn:
        if since:
            cur = conn.execute(
                "SELECT id, ts, kind, body, source_n, eval_delta, signature "
                "FROM updates WHERE ts > ? ORDER BY ts ASC",
                (since,),
            )
        else:
            cur = conn.execute(
                "SELECT id, ts, kind, body, source_n, eval_delta, signature "
                "FROM updates ORDER BY ts ASC"
            )
        rows = cur.fetchall()
    return [
        Update(id=r[0], ts=r[1], kind=r[2], body=json.loads(r[3]),
                source_n=r[4], eval_delta=r[5], signature=r[6])
        for r in rows
    ]


def summary() -> str:
    n_contribs = len(list_contributions(limit=10000))
    n_updates = len(list_updates())
    cands = distill_candidates()
    parts = [f"🐝 Hive queen — {n_contribs} contributions, {n_updates} updates"]
    parts.append(f"  candidate updates pending: {len(cands)}")
    for c in cands[:5]:
        parts.append(f"    [{c.kind}] {c.rationale}")
    return "\n".join(parts)
