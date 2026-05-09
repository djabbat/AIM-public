"""agents/smart_context.py — importance-aware context truncation.

Alternative to LLM-compression (#38): rank chunks by a composite importance
score, then keep top chunks until the budget is filled. Lossless for the
high-priority items, only drops low-importance tail. No LLM calls — all
heuristic.

Composite score (0–200):
    +priority_value     (0/10/40/70/100 from frontmatter)
    +50 × cosine        (semantic relevance from retrieve())
    +recency bonus      (≤30, today=30, 30+ days=0)
    +entity bonus       (≤20, capitalised names + years + IDs)
    +tag-match bonus    (≤30 if tags overlap with task tokens)

Falls back gracefully on missing metadata.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

# regex helpers
_PERSON_RE = re.compile(r"\b[A-ZА-Я][a-zа-яё]+(?:[ -][A-ZА-Я][a-zа-яё]+){1,2}\b")
_YEAR_RE   = re.compile(r"\b(?:19|20|21)\d{2}\b")
_ID_RE     = re.compile(r"\b(?:PMID|DOI|ORCID)\b[:\s]*[\w./-]+")


# ── ranking ────────────────────────────────────────────────────────────────


_PRIORITY_VALUES = {"CRITICAL": 100, "HIGH": 70, "NORMAL": 40, "LOW": 10, "EPHEMERAL": 1}


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def _entity_bonus(text: str) -> int:
    bonus = 0
    bonus += min(len(_PERSON_RE.findall(text)) * 2, 10)
    bonus += min(len(_YEAR_RE.findall(text)),       6)
    bonus += min(len(_ID_RE.findall(text)) * 4,     12)
    return min(bonus, 20)


def _recency_bonus(ts: Optional[str]) -> int:
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts)
        age = (datetime.now() - dt).days
        return max(0, 30 - age)
    except Exception:
        return 0


def _tag_match_bonus(tags: list[str], task_tokens: set[str]) -> int:
    if not tags or not task_tokens:
        return 0
    overlap = len({t.lower() for t in tags} & task_tokens)
    return min(overlap * 6, 30)


def score_chunk(chunk: dict, task_tokens: set[str]) -> int:
    """Composite importance score (higher = keep)."""
    p = chunk.get("priority") or "NORMAL"
    s = _PRIORITY_VALUES.get(p.upper(), 40)
    sim = float(chunk.get("similarity") or chunk.get("relevance") or
                (1.0 - chunk.get("_distance", 1.0)))
    s += int(50 * max(0.0, min(1.0, sim)))
    s += _recency_bonus(chunk.get("created") or chunk.get("date"))
    s += _entity_bonus(chunk.get("text", ""))
    s += _tag_match_bonus(chunk.get("tags", []), task_tokens)
    return s


# ── truncate ───────────────────────────────────────────────────────────────


_TASK_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яёЁ0-9]{3,}")


def _task_tokens(task: str) -> set[str]:
    return {w.lower() for w in _TASK_TOKEN_RE.findall(task or "")}


def truncate(
    chunks: list[dict],
    task: str = "",
    max_tokens: int = 4000,
    reserved_tokens: int = 500,
) -> tuple[str, list[dict]]:
    """Return (formatted_blob, kept_chunks) within `max_tokens`.

    Each input chunk is expected to have a `text` key; optional keys used:
    priority, similarity / _distance, created/date, tags, file.
    """
    if not chunks:
        return "", []
    tt = _task_tokens(task)
    for c in chunks:
        c["importance"] = score_chunk(c, tt)
    chunks.sort(key=lambda c: -c["importance"])

    selected: list[dict] = []
    used = 0
    budget = max_tokens - reserved_tokens

    for c in chunks:
        n = _approx_tokens(c["text"])
        if used + n <= budget:
            selected.append(c)
            used += n
            continue
        # try a soft truncate of the very last chunk to fill remaining budget
        remaining = budget - used
        if remaining * 4 > 200:    # at least ~200 chars worth of context
            soft = _soft_truncate(c["text"], remaining * 4)
            c["text"] = soft
            c["truncated"] = True
            selected.append(c)
            used += _approx_tokens(soft)
        break

    blob = _format(selected)
    return blob, selected


def _soft_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_dot = cut.rfind(".")
    if last_dot > max_chars // 2:
        cut = cut[: last_dot + 1]
    return cut + " […]"


def _format(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        head = f"[file={c.get('file','?')} importance={c.get('importance', 0)} " \
               f"priority={c.get('priority', 'NORMAL')}]"
        parts.append(head + "\n" + c["text"])
    return "\n\n---\n\n".join(parts)
