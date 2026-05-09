"""agents/recall_cli.py — semantic memory query surface (V1, 2026-05-03).

Thin layer over `agents.memory_index.retrieve` that:

  * normalises queries (strip, dedup against last query)
  * formats hits into a one-line-per-result list
  * caches recent queries in a small JSONL log so the user can audit
    what AIM has been recalling about

Surface area:

    python -m agents.recall_cli "FCLC deadline" --k 5
    python -m agents.recall_cli "publications" --json

Programmatic:
    from agents.recall_cli import recall, recall_top
    hits = recall("EIC submission")     # [{file, text, distance}]
    summary = recall_top("Geiger", k=3)  # multi-line string
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.recall_cli")


def _audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "recall.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclasses.dataclass
class Hit:
    file: str
    text: str
    distance: float


def _audit(query: str, n_hits: int) -> None:
    rec = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "query": query, "n_hits": n_hits,
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("recall audit write failed: %s", e)


def recall(query: str, *, k: int = 5,
           max_chars_per_file: int = 800) -> list[Hit]:
    """Return up to `k` semantic hits. Empty list if index is missing."""
    if not isinstance(query, str) or not query.strip():
        return []
    query = query.strip()
    try:
        from agents import memory_index as mi
    except ImportError:
        return []
    raw = mi.retrieve(query, k=k, max_chars_per_file=max_chars_per_file) or []
    hits = [Hit(file=r.get("file", ""),
                 text=str(r.get("text", "")),
                 distance=float(r.get("_distance", 0.0)))
            for r in raw]
    _audit(query, len(hits))
    return hits


def recall_top(query: str, *, k: int = 5,
                line_max: int = 140) -> str:
    """One-line-per-hit formatted summary."""
    hits = recall(query, k=k)
    if not hits:
        return f"(no recall hits for {query!r})"
    out: list[str] = [f"💭 Recall: {query!r} ({len(hits)} hits)"]
    for h in hits:
        snippet = h.text.replace("\n", " ").strip()
        snippet = snippet[:line_max - len(h.file) - 10]
        out.append(f"  • {Path(h.file).name}  d={h.distance:.3f}  {snippet}")
    return "\n".join(out)


def recall_json(queries: Iterable[str], *, k: int = 5) -> str:
    """JSON list of {query, hits} for batch invocation."""
    out = []
    for q in queries:
        out.append({"query": q,
                    "hits": [dataclasses.asdict(h) for h in recall(q, k=k)]})
    return json.dumps(out, ensure_ascii=False, indent=2)


def history(limit: int = 50) -> list[dict]:
    p = _audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Semantic memory recall")
    ap.add_argument("query", nargs="+", help="search terms (joined with space)")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    q = " ".join(args.query)
    if args.json:
        print(recall_json([q], k=args.k))
    else:
        print(recall_top(q, k=args.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
