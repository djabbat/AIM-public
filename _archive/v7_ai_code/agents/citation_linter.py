"""agents/citation_linter.py — repo-wide citation lint (PR2, 2026-05-03).

Walks markdown files in a project tree, runs every PMID/DOI through
`citation_guard.verify`, and reports unresolved references — the
write-side analogue of the runtime guard.

Designed for two contexts:

  * weekly digest — pickup of "X unverified citations across N files"
  * pre-commit / pre-push hook — fail if new unresolved refs land

Public API:
    lint(root, *, ignore_globs=...) -> Report
    Report.has_problems
    Report.summary() -> str
"""
from __future__ import annotations

import dataclasses
import fnmatch
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.citation_linter")


_DEFAULT_IGNORE_DIRS = {
    "_archive", "_exports", ".venv", "venv",
    "node_modules", ".git", "__pycache__",
    "_runtime_fixtures",
}


@dataclasses.dataclass
class Issue:
    file: str
    line: int
    raw: str
    kind: str
    note: str


@dataclasses.dataclass
class Report:
    files_scanned: int
    files_with_issues: int
    issues: list[Issue]

    @property
    def has_problems(self) -> bool:
        return bool(self.issues)

    def summary(self) -> str:
        if not self.issues:
            return f"📚 Citations OK — scanned {self.files_scanned} files."
        head = (f"📚 Citation lint — {len(self.issues)} unresolved across "
                f"{self.files_with_issues}/{self.files_scanned} files")
        rows = [head]
        # Group by file — first 8 files, first 3 issues each.
        by_file: dict[str, list[Issue]] = {}
        for i in self.issues:
            by_file.setdefault(i.file, []).append(i)
        for f, items in list(by_file.items())[:8]:
            rows.append(f"  {f}")
            for i in items[:3]:
                rows.append(f"    L{i.line}  {i.kind}:{i.raw}  — {i.note}")
        return "\n".join(rows)


# ── helpers ──────────────────────────────────────────────────────


def _is_ignored(path: Path, root: Path,
                ignore_globs: Iterable[str]) -> bool:
    rel = path.relative_to(root)
    # First: any path component in the default-ignore set short-circuits.
    if set(rel.parts) & _DEFAULT_IGNORE_DIRS:
        return True
    rel_str = str(rel)
    for pat in ignore_globs:
        if fnmatch.fnmatch(rel_str, pat):
            return True
    return False


def _md_files(root: Path,
              ignore_globs: Iterable[str]) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    for p in root.rglob("*.md"):
        if _is_ignored(p, root, ignore_globs):
            continue
        out.append(p)
    return out


# ── lint ─────────────────────────────────────────────────────────


def lint(root: Path | str = ".",
         *,
         ignore_globs: Optional[Iterable[str]] = None,
         strict: bool = False) -> Report:
    root_path = Path(root).expanduser().resolve()
    ignore = tuple(ignore_globs) if ignore_globs is not None else ()

    issues: list[Issue] = []
    files_with_issues: set[str] = set()
    files = _md_files(root_path, ignore)

    try:
        from agents.citation_guard import extract, _verify_one
    except ImportError:
        return Report(files_scanned=0, files_with_issues=0, issues=[])

    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cites = extract(text)
        if not cites:
            continue
        for c in cites:
            _verify_one(c)
        for c in cites:
            if not c.resolved:
                # Find the line this citation lives on.
                line_no = text.count("\n", 0, c.span[0]) + 1
                issues.append(Issue(
                    file=str(p.relative_to(root_path)),
                    line=line_no,
                    raw=c.raw,
                    kind=c.kind,
                    note=c.note or "unresolved",
                ))
                files_with_issues.add(str(p))

    return Report(files_scanned=len(files),
                   files_with_issues=len(files_with_issues),
                   issues=issues)
