"""AI/ai/reflexion_cluster.py — thin Python shim over the
`aim-ai-reflexion` Rust binary (Phase 9 Tier 3 #21, 2026-05-07).

Group failure-theme reflexion notes by Jaccard token overlap. The
Rust crate owns tokeniser + filler list + clustering + theme
selection; Python keeps the same Cluster public API and the
memory-source loaders (feedback_*.md + reflexion buckets) — both are
Python-side conventions.

Public API (preserved):
    Cluster dataclass (with .n / .suggestion properties)
    cluster(notes, *, threshold=0.25) -> list[Cluster]
    clusters_from_memory(window_days=180, threshold=0.25) -> list[Cluster]
    summary(threshold=0.25) -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import subprocess
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ai.reflexion_cluster")


@dataclasses.dataclass
class Cluster:
    notes: list[str]
    theme: list[str]
    representative: str
    _suggestion: Optional[str] = None

    @property
    def n(self) -> int:
        return len(self.notes)

    @property
    def suggestion(self) -> str:
        if self._suggestion is not None:
            return self._suggestion
        if not self.theme:
            return self.representative[:200]
        terms = ", ".join(self.theme[:5])
        return (f"Remember when handling {terms}: "
                f"{self.representative.strip()[:200]}")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "rust-core" / "target" / "release" / "aim-ai-reflexion"
    )


def _run(args: list[str], *, stdin: str) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-ai-reflexion binary not built at {bin_path}"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-ai-reflexion {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def cluster(notes: Iterable[str], *,
            threshold: float = 0.25) -> list[Cluster]:
    safe_notes = [n for n in notes if isinstance(n, str)]
    if not safe_notes:
        return []
    payload = "\n".join(json.dumps(n) for n in safe_notes)
    out = _run(["cluster", "--threshold", str(threshold)], stdin=payload)
    res: list[Cluster] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        res.append(Cluster(
            notes=list(j.get("notes", [])),
            theme=list(j.get("theme", [])),
            representative=str(j.get("representative", "")),
            _suggestion=j.get("suggestion"),
        ))
    return res


# ── pull reflexions from memory (Python-only) ──────────────────


def _from_feedback_memory(window_days: int = 180) -> list[str]:
    base = (Path.home() / ".claude" / "projects" /
            "-home-oem" / "memory")
    if not base.exists():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=window_days)
    out: list[str] = []
    for p in base.glob("feedback_*.md"):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4:]
        text = text.strip()
        if len(text) >= 20:
            out.append(text)
    return out


def _from_reflexion_buckets(n_per_bucket: int = 8) -> list[str]:
    try:
        from agents import reflexion as rfx
    except Exception:
        return []
    base = getattr(rfx, "_store_dir", None)
    if base is None:
        return []
    try:
        d = base()
    except Exception:
        return []
    if not d.exists():
        return []
    out: list[str] = []
    for p in d.glob("*.jsonl"):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()[-n_per_bucket:]
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            s = rec.get("summary") or ""
            if isinstance(s, str) and len(s) >= 20:
                out.append(s)
    return out


def clusters_from_memory(window_days: int = 180,
                          threshold: float = 0.25) -> list[Cluster]:
    notes = _from_feedback_memory(window_days=window_days)
    notes += _from_reflexion_buckets()
    return cluster(notes, threshold=threshold)


# ── reporting ────────────────────────────────────────────────────


def summary(threshold: float = 0.25) -> str:
    cls = clusters_from_memory(threshold=threshold)
    if not cls:
        return "(no reflexions to cluster yet)"
    lines = [f"🧩 Reflexion clusters — {len(cls)} themes"]
    for c in cls[:8]:
        theme = ", ".join(c.theme[:4]) if c.theme else "(no shared theme)"
        lines.append(f"  • [{c.n} notes] {theme}")
        lines.append(f"      → suggestion: {c.suggestion[:160]}")
    return "\n".join(lines)
