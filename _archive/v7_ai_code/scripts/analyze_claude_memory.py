"""scripts/analyze_claude_memory.py — pre-migration audit of Claude Code memory.

Inventories ~/.claude/projects/-home-oem/memory/, classifies files by prefix
(feedback_, project_, user_, contact_, reference_, fact_, …) and writes a
JSON report + a human-readable summary.

Run:
    python -m scripts.analyze_claude_memory
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

CLAUDE_MEMORY_DIR = Path("~/.claude/projects/-home-oem/memory/").expanduser()
OUT_JSON = Path("~/Desktop/AIM/claude_memory_analysis.json").expanduser()
OUT_TXT  = Path("~/Desktop/AIM/claude_memory_analysis.txt").expanduser()


def _classify(name: str) -> str:
    n = name.lower()
    for prefix in ("feedback_", "project_", "user_", "contact_", "reference_",
                   "fact_", "pubmed_"):
        if n.startswith(prefix):
            return prefix.rstrip("_")
    if n == "memory.md":
        return "index"
    return "other"


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def analyze() -> dict:
    if not CLAUDE_MEMORY_DIR.exists():
        return {"error": f"directory not found: {CLAUDE_MEMORY_DIR}"}

    files = sorted(CLAUDE_MEMORY_DIR.glob("*.md"))
    stats = {
        "scanned_at":    datetime.now().isoformat(timespec="seconds"),
        "source_dir":    str(CLAUDE_MEMORY_DIR),
        "total_files":   0,
        "total_size_kb": 0.0,
        "categories":    Counter(),
        "types":         Counter(),       # frontmatter `type:` field
        "with_frontmatter": 0,
        "files":         [],
        "samples":       [],
    }

    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
        except Exception as e:
            stats["files"].append({"file": f.name, "error": str(e)})
            continue
        stats["total_files"] += 1
        stats["total_size_kb"] += f.stat().st_size / 1024
        cat = _classify(f.name)
        stats["categories"][cat] += 1

        fm = _frontmatter(content)
        if fm:
            stats["with_frontmatter"] += 1
            stats["types"][fm.get("type", "unknown")] += 1

        stats["files"].append({
            "file":     f.name,
            "size_kb":  round(f.stat().st_size / 1024, 2),
            "mtime":    datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            "category": cat,
            "type":     fm.get("type", ""),
            "name":     fm.get("name", ""),
            "description": fm.get("description", "")[:160],
        })
        if len(stats["samples"]) < 5:
            stats["samples"].append({
                "file": f.name,
                "first_500_chars": content[:500],
            })

    stats["categories"] = dict(stats["categories"])
    stats["types"] = dict(stats["types"])

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        f"AIM — Claude memory audit ({stats['scanned_at']})",
        f"  source:        {stats['source_dir']}",
        f"  files:         {stats['total_files']}",
        f"  size:          {stats['total_size_kb']:.1f} KB",
        f"  frontmatter:   {stats['with_frontmatter']} of {stats['total_files']}",
        "",
        "  by category (filename prefix):",
        *[f"    {k:<12} {v}" for k, v in sorted(stats['categories'].items(), key=lambda x: -x[1])],
        "",
        "  by type (frontmatter):",
        *[f"    {k:<12} {v}" for k, v in sorted(stats['types'].items(), key=lambda x: -x[1])],
    ]
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print()
    print(f"📄 JSON  → {OUT_JSON}")
    print(f"📄 TXT   → {OUT_TXT}")
    return stats


if __name__ == "__main__":
    analyze()
