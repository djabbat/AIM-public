"""agents/module_registry.py — capability map of agents/ + scripts/ (G12, 2026-05-03).

Walks every .py file under agents/ and scripts/ via the AST, records:

  * module name
  * top-level public functions / classes (no leading underscore)
  * one-line docstring summary
  * imports (so we can build dep graphs cheaply)

Output:
  * `Capability` dataclass per module
  * `registry()` — list[Capability]
  * `summary()` — markdown overview suitable for README / healthz
  * `as_dict()` — JSON-friendly dict

Used for:
  * onboarding doc generation
  * `aim health` dependency overview
  * impact analyser cross-check
"""
from __future__ import annotations

import ast
import dataclasses
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.module_registry")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


_DEFAULT_ROOTS = ("agents", "scripts")


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Capability:
    module: str
    path: str
    description: str
    public_functions: list[str]
    public_classes: list[str]
    imports: list[str]


# ── parse ────────────────────────────────────────────────────────


def _module_for(path: Path, root: Path) -> Optional[str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _parse(path: Path) -> Optional[Capability]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None
    docstring = ast.get_docstring(tree) or ""
    summary = (docstring.splitlines() or [""])[0].strip()

    funcs: list[str] = []
    classes: list[str] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if not node.name.startswith("_"):
                funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return Capability(
        module="",   # filled in by caller
        path=str(path),
        description=summary[:200],
        public_functions=sorted(funcs),
        public_classes=sorted(classes),
        imports=sorted(set(imports)),
    )


# ── walk ─────────────────────────────────────────────────────────


def registry(roots: tuple[str, ...] = _DEFAULT_ROOTS,
             root: Optional[Path] = None) -> list[Capability]:
    root = root or repo_root()
    out: list[Capability] = []
    for sub in roots:
        d = root / sub
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in p.parts or ".pytest_cache" in p.parts:
                continue
            mod = _module_for(p, root)
            if mod is None:
                continue
            cap = _parse(p)
            if cap is None:
                continue
            cap.module = mod
            out.append(cap)
    return out


def get(module: str, *,
        index: Optional[list[Capability]] = None) -> Optional[Capability]:
    idx = index or registry()
    for c in idx:
        if c.module == module:
            return c
    return None


def by_subsystem(roots: tuple[str, ...] = _DEFAULT_ROOTS,
                 root: Optional[Path] = None
                 ) -> dict[str, list[Capability]]:
    """Group capabilities by their top-level package (agents/scripts/...)."""
    out: dict[str, list[Capability]] = {}
    for c in registry(roots, root=root):
        head = c.module.split(".", 1)[0]
        out.setdefault(head, []).append(c)
    return out


def summary(roots: tuple[str, ...] = _DEFAULT_ROOTS,
            root: Optional[Path] = None) -> str:
    groups = by_subsystem(roots, root=root)
    parts: list[str] = ["# AIM module registry", ""]
    total = sum(len(v) for v in groups.values())
    parts.append(f"_{total} modules in {len(groups)} subsystems_")
    parts.append("")
    for head, caps in sorted(groups.items()):
        parts.append(f"## {head} ({len(caps)} modules)")
        for c in caps:
            desc = c.description or "_(no docstring)_"
            parts.append(f"- **{c.module}** — {desc}")
            funcs = c.public_functions[:6]
            classes = c.public_classes[:4]
            if funcs or classes:
                api: list[str] = []
                if classes:
                    api.append("classes: " + ", ".join(classes))
                if funcs:
                    api.append("fns: " + ", ".join(funcs))
                parts.append(f"  - API: {' · '.join(api)}")
        parts.append("")
    return "\n".join(parts)


def as_dict(roots: tuple[str, ...] = _DEFAULT_ROOTS,
            root: Optional[Path] = None) -> dict:
    return {
        "modules": [dataclasses.asdict(c)
                    for c in registry(roots, root=root)]
    }
