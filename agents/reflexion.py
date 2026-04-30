"""agents/reflexion.py — verbal-reflection memory for the generalist.

Reflexion (Shinn et al., 2023; refined 2025) — when a run fails or the
self-critique finds material flaws, generate a brief verbal reflection
("what went wrong, what to try differently") and persist it. On the NEXT
run with a similar task class, retrieve recent reflections and inject
them as a hint.

This is cheap (no fine-tuning) and one of the highest-ROI
non-RLHF techniques for tool-using agents (+10-15% on ReAct tasks).

Public API:
    classify(task)                     → str    (task class key)
    save_reflection(task, summary)
    recent_reflections(task, n=3)      → list[str]
    on_failure(task, error_excerpt)    → None   (auto-summary via LLM)
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import time
from pathlib import Path
from typing import Iterable

log = logging.getLogger("aim.reflexion")

_LOCK_FILE = ".aim_reflexion.lock"


def _store_dir() -> Path:
    sysname = platform.system()
    if sysname == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA",
                                   Path.home() / "AppData" / "Local"))
        d = base / "aim" / "reflexion"
    elif sysname == "Darwin":
        d = Path.home() / "Library" / "Application Support" / "aim" / "reflexion"
    else:
        d = Path(os.environ.get("XDG_DATA_HOME",
                                str(Path.home() / ".local/share"))) / "aim" / "reflexion"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Task classification — coarse keyword bucket ───────────────────────────


_BUCKETS = {
    "code_edit":   ("edit", "refactor", "fix", "patch", "bug", "пофикси", "исправь", "рефактор"),
    "research":    ("research", "find papers", "literature", "PubMed", "PMID", "DOI",
                     "literature review", "обзор", "литератур"),
    "writing":     ("write", "draft", "peer review", "manuscript", "article",
                     "редакт", "напиши", "статья", "рецензир"),
    "diagnosis":   ("diagnose", "diagnos", "treatment", "symptoms", "patient",
                     "диагноз", "лечен", "пациент", "симптом"),
    "ops":         ("deploy", "build", "push", "commit", "git", "test"),
    "email":       ("email", "send", "draft email", "напиши письмо"),
    "general":     (),
}


def classify(task: str) -> str:
    t = task.lower()
    for bucket, kws in _BUCKETS.items():
        if any(k in t for k in kws):
            return bucket
    return "general"


# ── Persistence (JSONL per bucket) ─────────────────────────────────────────


def _bucket_path(bucket: str) -> Path:
    safe = re.sub(r"[^a-z0-9_]", "_", bucket.lower())[:40]
    return _store_dir() / f"{safe}.jsonl"


def save_reflection(task: str, summary: str, *,
                    bucket: str | None = None) -> None:
    bucket = bucket or classify(task)
    rec = {
        "ts": int(time.time()),
        "task_excerpt": task[:200],
        "summary": summary[:1000],
    }
    try:
        with _bucket_path(bucket).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"reflexion save failed: {e}")


def recent_reflections(task: str, n: int = 3, *,
                       bucket: str | None = None,
                       max_age_days: int = 60) -> list[str]:
    bucket = bucket or classify(task)
    p = _bucket_path(bucket)
    if not p.exists():
        return []
    cutoff = time.time() - max_age_days * 86400
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("ts", 0) >= cutoff:
                    out.append(rec)
            except Exception:
                continue
    except Exception:
        return []
    return [r["summary"] for r in out[-n:]]


def on_failure(task: str, error_excerpt: str) -> None:
    """Generate a brief Reflexion summary via cheap LLM and persist it."""
    try:
        from llm import ask_fast
        prompt = (
            "You are writing a one-paragraph (≤80 words) Reflexion entry.\n"
            "An AI agent just FAILED at the task below. Identify the proximate "
            "cause and ONE concrete change of strategy to try next time. Be "
            "concrete, not generic.\n\n"
            f"=== TASK ===\n{task[:600]}\n\n"
            f"=== FAILURE EVIDENCE ===\n{error_excerpt[:1500]}\n"
            "=== Your reflection: ==="
        )
        summary = ask_fast(prompt) or ""
        if summary.strip():
            save_reflection(task, summary)
    except Exception as e:
        log.debug(f"reflexion on_failure skipped: {e}")
