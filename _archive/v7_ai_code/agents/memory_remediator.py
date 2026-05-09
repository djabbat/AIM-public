"""agents/memory_remediator.py — suggest fixes for broken paths (RM1, 2026-05-03).

`memory_monitor` reports broken `path: missing` references in memory
files. Most of those paths weren't deleted — they were *renamed* (e.g.
`~/Desktop/E0/...` moved to `~/Desktop/PhD/E0/...` per the project
relocation memory). This module:

  1. Pulls every `broken_path` finding.
  2. For each, searches `~/Desktop/` for files / dirs whose basename
     matches and whose path contains some of the original components.
  3. Returns a Suggestion with confidence — high when the basename is
     unique, lower when several candidates exist.

We never auto-edit memory. The output is a punch list: open the memory
file, replace the old path with the suggested one yourself.

Public API:
    suggestions(scope=None) -> list[Suggestion]
    summary() -> str
"""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.memory_remediator")


@dataclasses.dataclass
class Suggestion:
    memory_file: str
    broken_path: str
    candidates: list[str]
    confidence: str   # "high" | "medium" | "low"

    @property
    def best(self) -> Optional[str]:
        return self.candidates[0] if self.candidates else None


# ── helpers ──────────────────────────────────────────────────────


_DESKTOP_ROOTS_ENV = "AIM_DESKTOP_ROOTS"


def _desktop_roots() -> list[Path]:
    env = os.environ.get(_DESKTOP_ROOTS_ENV)
    if env:
        return [Path(p).expanduser() for p in env.split(":") if p]
    return [Path.home() / "Desktop"]


def _basename(path: str) -> str:
    return Path(path).name


def _path_components(path: str) -> set[str]:
    """All non-trivial path components used as soft match signal."""
    parts = Path(path).expanduser().parts
    return {p for p in parts if len(p) > 2 and p not in ("Desktop", "home", "/")}


def _confidence(n_candidates: int, basename: str) -> str:
    if n_candidates == 0:
        return "low"
    if n_candidates == 1:
        return "high"
    if len(basename) > 8 and n_candidates <= 3:
        return "medium"
    return "low"


# ── search ───────────────────────────────────────────────────────


def _find_candidates(broken_path: str,
                     roots: Iterable[Path],
                     max_results: int = 5,
                     max_walk: int = 50_000) -> list[str]:
    """Walk every root looking for files / dirs whose basename matches."""
    target = _basename(broken_path)
    if not target:
        return []
    components = _path_components(broken_path) - {target}
    matches: list[tuple[int, str]] = []
    walked = 0
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob(target):
            walked += 1
            if walked > max_walk:
                break
            score = 0
            ps = set(p.parts)
            for c in components:
                if c in ps:
                    score += 1
            matches.append((score, str(p)))
        if walked > max_walk:
            break
    matches.sort(key=lambda kv: -kv[0])
    return [path for _score, path in matches[:max_results]]


# ── orchestrate ──────────────────────────────────────────────────


def suggestions(scope: Optional[str] = None,
                 *,
                 max_per_path: int = 5) -> list[Suggestion]:
    """Pull broken_path findings from memory_monitor and propose fixes."""
    try:
        from agents.memory_monitor import scan
    except ImportError:
        return []
    rep = scan()
    roots = _desktop_roots()
    out: list[Suggestion] = []
    seen: set[tuple[str, str]] = set()

    for finding in rep.findings:
        if finding.kind != "broken_path":
            continue
        # Detail format: "references missing path: <PATH>"
        marker = "missing path:"
        if marker in finding.detail:
            broken = finding.detail.split(marker, 1)[1].strip()
        else:
            broken = finding.detail
        key = (finding.file, broken)
        if key in seen:
            continue
        seen.add(key)
        cands = _find_candidates(broken, roots, max_results=max_per_path)
        out.append(Suggestion(
            memory_file=finding.file,
            broken_path=broken,
            candidates=cands,
            confidence=_confidence(len(cands), _basename(broken)),
        ))
    return out


def summary() -> str:
    items = suggestions()
    if not items:
        return "(no broken-path findings to remediate)"
    parts = [f"🔧 Memory remediator — {len(items)} broken refs"]
    high = [s for s in items if s.confidence == "high"]
    med = [s for s in items if s.confidence == "medium"]
    low = [s for s in items if s.confidence == "low"]
    parts.append(f"  high: {len(high)} · medium: {len(med)} · "
                 f"low: {len(low)}")
    for s in high[:6]:
        parts.append(f"  • {s.memory_file}  →  replace `{s.broken_path}` "
                     f"with `{s.best}`")
    for s in med[:4]:
        parts.append(f"  • {s.memory_file}  ({len(s.candidates)} candidates)  "
                     f"`{s.broken_path}` ≈ `{s.candidates[0]}` ?")
    return "\n".join(parts)
