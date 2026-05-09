"""AI/ai/gap_detector.py — thin Python shim over the
`aim-ai-gap-detector` Rust binary (Phase 9 Tier 3 #20, 2026-05-07).

Walks session JSONL logs and finds tasks where AIM gave up — the
final answer matches a surrender pattern. Clusters surrenders into
capability gaps. The Rust crate owns regex set + tokeniser + Jaccard
clustering; Python keeps the same public dataclass-shaped API and
the `window_days` filter (binary doesn't natively filter, so we
post-process by ts).

Public API (preserved):
    sessions_dir() -> Path
    Surrender / Gap dataclasses (Gap.n property)
    surrenders(window_days=14) -> list[Surrender]
    gaps(window_days=14, threshold=0.20, *, surrender_list=None) -> list[Gap]
    summary(window_days=14) -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("ai.gap_detector")


def sessions_dir() -> Path:
    env = os.environ.get("AIM_SESSIONS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "aim" / "sessions"


@dataclasses.dataclass
class Surrender:
    session: str
    task: str
    answer: str
    ts: Optional[str]


@dataclasses.dataclass
class Gap:
    theme: list[str]
    surrenders: list[Surrender]
    representative: str
    suggestion: str

    @property
    def n(self) -> int:
        return len(self.surrenders)


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-gap-detector"
    )


def _run(args: list[str], *, stdin: Optional[str] = None) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-gap-detector binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-gap-detector {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _surrender_from_json(j: dict) -> Surrender:
    return Surrender(
        session=str(j.get("session", "")),
        task=str(j.get("task", "")),
        answer=str(j.get("answer", "")),
        ts=j.get("ts"),
    )


def _filter_by_window(rows: list[Surrender], window_days: int) -> list[Surrender]:
    cutoff = dt.datetime.now() - dt.timedelta(days=window_days)
    out: list[Surrender] = []
    for s in rows:
        if not s.ts:
            out.append(s)
            continue
        try:
            evt = dt.datetime.fromisoformat(s.ts.replace("Z", "+00:00"))
        except ValueError:
            out.append(s)
            continue
        if evt.tzinfo is not None:
            evt = evt.astimezone().replace(tzinfo=None)
        if evt >= cutoff:
            out.append(s)
    return out


def surrenders(window_days: int = 14) -> list[Surrender]:
    out = _run(["surrenders"])
    raw = [_surrender_from_json(json.loads(line))
           for line in out.splitlines() if line.strip()]
    return _filter_by_window(raw, window_days)


def gaps(window_days: int = 14,
          threshold: float = 0.20,
          *,
          surrender_list: Optional[list[Surrender]] = None) -> list[Gap]:
    surr = (list(surrender_list)
            if surrender_list is not None
            else surrenders(window_days=window_days))
    if not surr:
        return []
    payload = "\n".join(
        json.dumps({
            "session": s.session,
            "task": s.task,
            "answer": s.answer,
            "ts": s.ts,
        })
        for s in surr
    )
    out = _run(["gaps", "--threshold", str(threshold)], stdin=payload)
    res: list[Gap] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        res.append(Gap(
            theme=list(j.get("theme", [])),
            surrenders=[_surrender_from_json(s)
                        for s in j.get("surrenders", [])],
            representative=str(j.get("representative", "")),
            suggestion=str(j.get("suggestion", "")),
        ))
    return res


def summary(window_days: int = 14) -> str:
    g = gaps(window_days=window_days)
    if not g:
        return f"(no capability gaps detected over last {window_days}d)"
    lines = [f"🕳 Capability gaps — {len(g)} clusters / "
             f"{sum(x.n for x in g)} surrenders / last {window_days}d"]
    for cluster in g[:8]:
        theme = ", ".join(cluster.theme[:4]) if cluster.theme else "(no theme)"
        lines.append(f"  • [{cluster.n} surrenders] {theme}")
        lines.append(f"      → {cluster.suggestion[:140]}")
    return "\n".join(lines)
