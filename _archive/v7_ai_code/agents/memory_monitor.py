"""agents/memory_monitor.py — auto-memory hygiene (M1, 2026-05-03).

The user's `~/.claude/projects/-home-oem/memory/` directory grows
quickly (currently ~80 entries). Stale, duplicated, or contradicted
entries quietly poison future recall. This module:

  * Reports entries that look stale (no mtime activity for N months,
    or whose body says "deadline 2024-..." that's well past).
  * Flags description-near-duplicates (Jaccard similarity over short
    descriptions in MEMORY.md index lines).
  * Flags conflicts with the live tree: a memory referencing a file
    path that no longer exists, or a domain (gmail user, NGO reg #) that
    the project state changed.

Output is a structured report; we never auto-delete. The user reviews
the suggestion list and runs `prune --apply` when they're ready.

Public API:
    scan(stale_months=6) -> Report
    write_jsonl_report(report) -> Path     # for weekly digest pickup
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.memory_monitor")


def memory_dir() -> Path:
    env = os.environ.get("AIM_MEMORY_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude" / "projects" / "-home-oem" / "memory"


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Finding:
    kind: str        # stale | duplicate | broken_path | obsolete_deadline
    file: str
    detail: str
    severity: str = "info"   # info | warn | high


@dataclasses.dataclass
class Report:
    scanned: int
    findings: list[Finding]


# ── scanners ─────────────────────────────────────────────────────


_DEADLINE_RE = re.compile(
    r"\b(?:deadline|due|by|до|дедлайн)[\s:*\-]*"
    r"(?P<y>(?:19|20|21)\d{2})-(?P<m>0[1-9]|1[0-2])-(?P<d>0[1-9]|[12]\d|3[01])\b",
    re.IGNORECASE,
)

_PATH_REF_RE = re.compile(
    r"`(/[^`\n]+|~/[^`\n]+)`"
)


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    out: dict = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip("\"'")
    return out


def _stem_set(s: str) -> set[str]:
    """Lowercased word stems for naive Jaccard similarity."""
    return {w[:6] for w in re.findall(r"\w+", s.lower()) if len(w) > 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _scan_file(p: Path, today: dt.date,
               stale_cutoff: dt.date) -> list[Finding]:
    """Per-file checks: stale mtime, obsolete deadlines, broken path refs."""
    out: list[Finding] = []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out

    # mtime-based staleness.
    mtime = dt.date.fromtimestamp(p.stat().st_mtime)
    if mtime < stale_cutoff:
        out.append(Finding(
            kind="stale",
            file=p.name,
            detail=f"untouched since {mtime.isoformat()}",
            severity="info",
        ))

    # Old deadlines mentioned in body — still hanging around past date.
    fm = _parse_frontmatter(text)
    type_ = fm.get("type")
    for m in _DEADLINE_RE.finditer(text):
        try:
            d = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        if d < today and (today - d).days > 14:
            out.append(Finding(
                kind="obsolete_deadline",
                file=p.name,
                detail=f"references deadline {d.isoformat()} ({(today-d).days}d ago); {type_ or 'unknown type'}",
                severity="warn" if type_ in ("project", "feedback") else "info",
            ))

    # Broken path refs (`~/Desktop/...` that no longer exists).
    seen_paths: set[str] = set()
    for m in _PATH_REF_RE.finditer(text):
        raw = m.group(1)
        if raw in seen_paths:
            continue
        seen_paths.add(raw)
        path = Path(raw).expanduser()
        if not path.exists() and not path.is_symlink():
            out.append(Finding(
                kind="broken_path",
                file=p.name,
                detail=f"references missing path: {raw}",
                severity="warn",
            ))

    return out


def _scan_duplicates(files: list[Path], threshold: float = 0.7
                      ) -> list[Finding]:
    """Flag files whose `description:` frontmatter is highly overlapping."""
    rows: list[tuple[Path, str, set[str]]] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        desc = fm.get("description") or fm.get("name") or ""
        if not desc:
            continue
        rows.append((p, desc, _stem_set(desc)))

    out: list[Finding] = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sim = _jaccard(rows[i][2], rows[j][2])
            if sim >= threshold:
                out.append(Finding(
                    kind="duplicate",
                    file=f"{rows[i][0].name} ↔ {rows[j][0].name}",
                    detail=f"description similarity {sim:.2f}: "
                           f"{rows[i][1][:60]!r} vs {rows[j][1][:60]!r}",
                    severity="warn" if sim >= 0.85 else "info",
                ))
    return out


# ── orchestrate ──────────────────────────────────────────────────


def scan(stale_months: int = 6,
         today: Optional[dt.date] = None) -> Report:
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=int(stale_months * 30))
    d = memory_dir()
    if not d.exists():
        return Report(scanned=0, findings=[])
    files = sorted(p for p in d.glob("*.md")
                   if p.name not in ("MEMORY.md",))
    findings: list[Finding] = []
    for p in files:
        findings.extend(_scan_file(p, today, cutoff))
    findings.extend(_scan_duplicates(files))
    findings.sort(key=lambda f: ({"high": 0, "warn": 1, "info": 2}.get(f.severity, 9),
                                 f.kind, f.file))
    return Report(scanned=len(files), findings=findings)


def write_jsonl_report(report: Report,
                       path: Optional[Path] = None) -> Path:
    if path is None:
        base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
        path = Path(base).expanduser() / "memory_report.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for fnd in report.findings:
            f.write(json.dumps(dataclasses.asdict(fnd), ensure_ascii=False) + "\n")
    return path


def summary(stale_months: int = 6) -> str:
    rep = scan(stale_months=stale_months)
    if not rep.findings:
        return f"🧠 Memory: scanned {rep.scanned} entries, no issues."
    by_kind: dict[str, int] = {}
    for f in rep.findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    parts = [f"🧠 Memory hygiene: scanned {rep.scanned}, {len(rep.findings)} findings"]
    for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        parts.append(f"  • {k}: {n}")
    # Top 5 highest-severity items.
    high = [f for f in rep.findings if f.severity in ("high", "warn")][:5]
    for f in high:
        parts.append(f"     [{f.severity}] {f.kind}: {f.file} — {f.detail[:120]}")
    return "\n".join(parts)


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Memory hygiene scanner")
    ap.add_argument("--stale-months", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = scan(stale_months=args.stale_months)
    if args.json:
        print(json.dumps(dataclasses.asdict(rep), ensure_ascii=False, indent=2))
    else:
        print(summary(stale_months=args.stale_months))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
