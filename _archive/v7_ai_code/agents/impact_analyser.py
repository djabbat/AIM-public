"""agents/impact_analyser.py — code change-impact analyser (SC1, 2026-05-03).

Static reverse-import map for the AIM codebase. When you change
`agents/X.py`, run `aim impact agents/X.py` (or programmatic call) to
see:

  * which test files import the module (or any symbol from it)
  * which other agents/scripts modules transitively depend on it
  * a one-line "consider running these tests" recommendation

Implementation:
  * Walks `agents/`, `scripts/`, `tests/` and parses each .py via `ast`.
  * Records every `import X` / `from X import …` reference.
  * For a target like `agents/foo.py` we resolve to module name
    `agents.foo` and walk the reverse map.

Public API:
    build_index(roots=("agents","scripts","tests")) -> Index
    impact_for(target, *, index=None) -> Impact
"""
from __future__ import annotations

import ast
import dataclasses
import logging
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("aim.impact_analyser")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclasses.dataclass
class Index:
    # forward[module] = set of modules it imports
    forward: dict[str, set[str]]
    # reverse[module] = set of modules that import it
    reverse: dict[str, set[str]]
    # path[module] = filesystem path
    path: dict[str, Path]


@dataclasses.dataclass
class Impact:
    target_module: str
    target_path: str
    direct_dependents: list[str]
    transitive_dependents: list[str]
    test_files: list[str]


# ── module name resolution ──────────────────────────────────────


def _path_to_module(path: Path, root: Path) -> Optional[str]:
    """`agents/foo.py` → `agents.foo`; `agents/__init__.py` → `agents`."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return None
    return ".".join(parts)


def _imports_in_file(path: Path) -> set[str]:
    """Module names referenced by `import` / `from … import …`."""
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import — we ignore (rare in AIM).
                continue
            if node.module:
                out.add(node.module)
    return out


# ── index ────────────────────────────────────────────────────────


def _walk_py_files(root: Path,
                    sub_roots: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for sub in sub_roots:
        d = root / sub
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts or ".pytest_cache" in p.parts:
                continue
            out.append(p)
    return out


def build_index(sub_roots: Iterable[str] = ("agents", "scripts", "tests"),
                root: Optional[Path] = None) -> Index:
    root = root or repo_root()
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    paths: dict[str, Path] = {}

    files = _walk_py_files(root, sub_roots)
    for f in files:
        mod = _path_to_module(f, root)
        if mod is None:
            continue
        paths[mod] = f
        deps = _imports_in_file(f)
        forward[mod] = deps
        for d in deps:
            reverse.setdefault(d, set()).add(mod)
            # Also register every prefix so `agents.X` looking up `agents.X.foo`
            # still resolves at module-level.
            head = d
            while "." in head:
                head = head.rsplit(".", 1)[0]
                reverse.setdefault(head, set()).add(mod)
    return Index(forward=forward, reverse=reverse, path=paths)


# ── impact ───────────────────────────────────────────────────────


def _resolve_target(target: str | Path,
                    index: Index, root: Path) -> Optional[str]:
    """Take a path or module name and return the canonical module."""
    target_str = str(target)
    if target_str in index.path:
        return target_str
    p = Path(target_str)
    if p.is_absolute():
        mod = _path_to_module(p, root)
    else:
        mod = _path_to_module((root / p).resolve(), root)
    if mod and mod in index.path:
        return mod
    if target_str in index.forward:
        return target_str
    return None


def impact_for(target: str | Path,
                *, index: Optional[Index] = None,
                root: Optional[Path] = None) -> Impact:
    root = root or repo_root()
    idx = index or build_index(root=root)
    mod = _resolve_target(target, idx, root)
    if mod is None:
        raise FileNotFoundError(f"unknown target: {target}")

    direct = sorted(idx.reverse.get(mod, set()))
    # Transitive — BFS across reverse map (but exclude tests so we have
    # a clean "library impact" view).
    seen: set[str] = set()
    queue = [m for m in direct if not m.startswith("tests.")]
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for parent in idx.reverse.get(cur, ()):
            if parent.startswith("tests."):
                continue
            if parent not in seen:
                queue.append(parent)
    transitive = sorted(seen - {mod})
    test_files = [m for m in direct if m.startswith("tests.")]
    return Impact(
        target_module=mod,
        target_path=str(idx.path.get(mod, Path(""))),
        direct_dependents=direct,
        transitive_dependents=transitive,
        test_files=test_files,
    )


def summary(target: str | Path) -> str:
    try:
        i = impact_for(target)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    parts = [
        f"📡 Impact for {i.target_module} ({i.target_path})",
        f"  direct dependents:    {len(i.direct_dependents)}",
        f"  transitive (no tests): {len(i.transitive_dependents)}",
        f"  test files importing: {len(i.test_files)}",
    ]
    if i.test_files:
        parts.append("  recommended test runs:")
        for t in i.test_files[:8]:
            parts.append(f"    - {t}")
    return "\n".join(parts)
