"""scripts/import_claude_memory.py — import Claude Code memory into AIM's own
LanceDB-backed memory.

Strategy:
  • Walk ~/.claude/projects/-home-oem/memory/*.md
  • Parse frontmatter; map type → AIM category (user/feedback/project/reference/general)
  • Write each file as a single AIM memory entry under user_memories/<category>/
    (preserves the original prose; extraction-by-regex is brittle on real-world
     memory files, so we keep the whole body as one fact and let the embedder
     do the rest)
  • Idempotent: skips files already in ~/.claude/memory_import_log.json
  • At the end: triggers `aim-memory-index reindex-incremental` once

Run:
    python -m scripts.import_claude_memory          # incremental
    python -m scripts.import_claude_memory --reset  # ignore log, re-import all
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from agents.memory_store import remember, MEMORY_DIR, USER_MEMORIES

log = logging.getLogger("aim.import_claude_memory")

CLAUDE_MEMORY_DIR = MEMORY_DIR     # ~/.claude/projects/-home-oem/memory/
LOG_PATH = Path("~/.claude/memory_import_log.json").expanduser()


# ── Frontmatter parsing ─────────────────────────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def _classify_category(file_name: str, fm: dict, body: str) -> str:
    """Map source filename + frontmatter to AIM category."""
    n = file_name.lower()
    fm_type = (fm.get("type") or "").lower()
    if fm_type in ("user", "feedback", "project", "reference"):
        return fm_type
    for prefix, cat in (
        ("feedback_",  "feedback"),
        ("project_",   "project"),
        ("user_",      "user"),
        ("contact_",   "reference"),
        ("reference_", "reference"),
        ("fact_",      "user"),
        ("pubmed_",    "reference"),
    ):
        if n.startswith(prefix):
            return cat
    return "general"


# ── Importer ────────────────────────────────────────────────────────────────


class ClaudeMemoryImporter:
    def __init__(self, source: Path = CLAUDE_MEMORY_DIR) -> None:
        self.source = source
        self.imported: set[str] = set()
        if LOG_PATH.exists():
            try:
                self.imported = set(json.loads(LOG_PATH.read_text())["imported_files"])
            except Exception:
                pass

    def reset(self) -> None:
        self.imported.clear()
        if LOG_PATH.exists():
            LOG_PATH.unlink()

    def run(self, reset: bool = False, dry_run: bool = False) -> dict:
        if reset:
            self.reset()
        if not self.source.exists():
            return {"error": f"source not found: {self.source}"}

        # Don't re-import files we ourselves wrote
        # (user_memories/ is under MEMORY_DIR but only at top level scan)
        files = [f for f in sorted(self.source.glob("*.md"))
                 if f.name != "MEMORY.md"
                 and not f.is_relative_to(USER_MEMORIES)]

        new_facts = 0
        skipped = 0
        new_files = 0

        for f in files:
            key = str(f.resolve())
            if key in self.imported:
                skipped += 1
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as e:
                log.warning(f"skip {f}: {e}")
                continue

            fm, body = _parse_frontmatter(content)
            category = _classify_category(f.name, fm, body)

            # The fact text = full body (without frontmatter); name from FM or filename
            fact_text = body.strip() or content.strip()
            if not fact_text:
                continue

            metadata = {
                "source":      f.name,
                "imported_at": datetime.now().isoformat(timespec="seconds"),
                "fm_name":     fm.get("name", f.stem),
                "fm_type":     fm.get("type", ""),
                "fm_description": (fm.get("description") or "")[:200],
            }

            if dry_run:
                print(f"[dry-run] would import {f.name} → category={category}")
            else:
                remember(fact_text, category=category, metadata=metadata, quiet=True)

            self.imported.add(key)
            new_facts += 1
            new_files += 1

        # Persist log
        if not dry_run:
            LOG_PATH.write_text(json.dumps({
                "imported_files": sorted(self.imported),
                "total_facts":    new_facts,
                "import_date":    datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        # Trigger one incremental reindex at the end
        if new_files and not dry_run:
            try:
                subprocess.run(["aim-memory-index", "reindex-incremental"],
                               capture_output=True, timeout=600)
            except Exception as e:
                log.warning(f"reindex failed (non-fatal): {e}")

        return {
            "scanned":     len(files),
            "skipped":     skipped,
            "imported":    new_files,
            "new_facts":   new_facts,
            "log":         str(LOG_PATH),
        }


def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true",
                   help="Ignore existing import log and re-import everything")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be imported without writing")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    res = ClaudeMemoryImporter().run(reset=args.reset, dry_run=args.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
