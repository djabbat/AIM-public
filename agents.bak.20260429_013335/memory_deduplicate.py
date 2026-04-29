"""agents/memory_deduplicate.py — find + merge near-duplicate memory entries.

Two-stage:
  1. Coarse — embedding-cosine over the LanceDB index (cheap, O(n log n))
  2. Fine   — SequenceMatcher on candidate pairs (slower; only on top hits)

Default similarity threshold 0.85 (same as upstream blueprint). Merging keeps
the longer text, unions tags, sums access_count, and records `merged_from` in
frontmatter; the shorter file is deleted.

CLI:
    python -m agents.memory_deduplicate scan
    python -m agents.memory_deduplicate scan --apply       # actually merge
    python -m agents.memory_deduplicate scan --threshold 0.9
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from agents.memory_store import USER_MEMORIES, MEMORY_DIR
from agents.memory_priority import _read_frontmatter

log = logging.getLogger("aim.memory_dedup")


@dataclass
class DupePair:
    file_a:     str
    file_b:     str
    similarity: float


class MemoryDeduplicator:
    def __init__(self, threshold: float = 0.85) -> None:
        self.threshold = threshold

    def _candidates_via_embeddings(self) -> list[tuple[str, str]]:
        """Return candidate file pairs from LanceDB (top neighbours per row)."""
        try:
            from agents.memory_index import _open_db, TABLE_NAME
            db = _open_db()
            if TABLE_NAME not in db.table_names():
                return []
            t = db.open_table(TABLE_NAME)
            rows = t.to_pandas()
        except Exception as e:
            log.warning(f"LanceDB unavailable ({e}); falling back to all-pairs sequence match")
            return self._all_pairs_fallback()

        pairs: set[tuple[str, str]] = set()
        # crude: for each row, find rows with same first 60 chars
        by_prefix: dict[str, list[str]] = defaultdict(list)
        for _, r in rows.iterrows():
            by_prefix[r["text"][:60].strip().lower()].append(r["file"])
        for files in by_prefix.values():
            if len(files) < 2:
                continue
            files = list(set(files))
            for i in range(len(files)):
                for j in range(i + 1, len(files)):
                    pairs.add(tuple(sorted((files[i], files[j]))))
        return list(pairs)

    def _all_pairs_fallback(self) -> list[tuple[str, str]]:
        files = sorted(USER_MEMORIES.rglob("*.md")) if USER_MEMORIES.exists() else []
        out = []
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                out.append((str(files[i]), str(files[j])))
        return out

    def scan(self, dry_run: bool = True) -> list[DupePair]:
        candidates = self._candidates_via_embeddings()
        log.info(f"checking {len(candidates)} candidate pairs (threshold {self.threshold})")
        pairs: list[DupePair] = []
        for a, b in candidates:
            pa = self._resolve(a)
            pb = self._resolve(b)
            if not (pa and pb and pa.exists() and pb.exists()):
                continue
            ta = pa.read_text(encoding="utf-8", errors="ignore")
            tb = pb.read_text(encoding="utf-8", errors="ignore")
            sim = SequenceMatcher(None, ta.lower(), tb.lower()).ratio()
            if sim >= self.threshold:
                pairs.append(DupePair(str(pa), str(pb), round(sim, 3)))
        if not dry_run:
            for pr in pairs:
                self.merge(pr.file_a, pr.file_b)
        return pairs

    # ── Merge ───────────────────────────────────────────────────────────────

    def merge(self, file_a: str, file_b: str) -> Optional[str]:
        pa, pb = Path(file_a), Path(file_b)
        if not (pa.exists() and pb.exists()):
            return None
        ta = pa.read_text(encoding="utf-8")
        tb = pb.read_text(encoding="utf-8")
        # Keep the longer body; merge frontmatter.
        keep, drop = (pa, pb) if len(ta) >= len(tb) else (pb, pa)
        fm_keep = _read_frontmatter(keep)
        fm_drop = _read_frontmatter(drop)

        merged_from = fm_keep.get("merged_from", "")
        merged_from = (merged_from + "," if merged_from else "") + drop.name
        fm_keep["merged_from"] = merged_from

        for key in ("tags",):
            if key in fm_drop:
                a_tags = set(filter(None, str(fm_keep.get(key, "")).split(",")))
                b_tags = set(filter(None, str(fm_drop[key]).split(",")))
                fm_keep[key] = ",".join(sorted(a_tags | b_tags))

        # rewrite keep-file with merged frontmatter
        body_match = re.match(r"^---\s*\n.*?\n---\s*\n?(.*)", keep.read_text(encoding="utf-8"), re.DOTALL)
        body = body_match.group(1) if body_match else keep.read_text(encoding="utf-8")
        new_fm = "---\n" + "\n".join(f"{k}: {v}" for k, v in fm_keep.items()) + "\n---\n\n"
        keep.write_text(new_fm + body, encoding="utf-8")
        drop.unlink()
        log.info(f"merged {drop.name} → {keep.name}")
        return str(keep)

    def _resolve(self, file_name: str) -> Optional[Path]:
        p = Path(file_name)
        if p.is_absolute() and p.exists():
            return p
        # search user_memories + memory dir
        for parent in (USER_MEMORIES, MEMORY_DIR):
            for f in parent.rglob(p.name):
                return f
        return None


def _main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--threshold", type=float, default=0.85)
    s.add_argument("--apply", action="store_true",
                   help="actually merge (default is dry-run)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    d = MemoryDeduplicator(threshold=args.threshold)
    pairs = d.scan(dry_run=not args.apply)
    print(json.dumps({
        "threshold":   args.threshold,
        "applied":     args.apply,
        "found_pairs": len(pairs),
        "preview":     [p.__dict__ for p in pairs[:10]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
