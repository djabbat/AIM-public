"""agents/project_graph.py — project dependency graph (RT1, 2026-05-03).

Builds a directed graph of inter-project dependencies from:

  1. Explicit `depends_on:` field in each project's YAML.
  2. Discovered references in milestone blockers, goals, and stakeholder
     notes — when text mentions another known project name, we record a
     soft edge (rendered as dashed in DOT).

Output formats:
    * dot()      — Graphviz DOT, pipe through `dot -Tsvg`.
    * mermaid()  — Mermaid graph TD, drops into markdown.
    * adjacency()— dict[project, list[(target, kind)]] for programmatic use.

Public API:
    build() -> Graph
    dot(graph=None) -> str
    mermaid(graph=None) -> str
    adjacency(graph=None) -> dict
    cycles(graph=None) -> list[list[str]]
"""
from __future__ import annotations

import dataclasses
import logging
import re
from typing import Iterable, Optional

log = logging.getLogger("aim.project_graph")


@dataclasses.dataclass
class Edge:
    src: str
    dst: str
    kind: str   # "explicit" | "blocker" | "goal" | "note"


@dataclasses.dataclass
class Graph:
    projects: list[str]
    edges: list[Edge]


# ── build ────────────────────────────────────────────────────────


def _yaml_load(project: str):
    from agents import project_owner as po
    return po.load(project)


def _yaml_raw(project: str) -> dict:
    """Re-parse YAML to access fields project_owner doesn't expose."""
    import yaml
    from agents import project_owner as po
    p = po.projects_dir() / f"{project}.yaml"
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.debug("YAML parse failed for %s: %s", project, e)
        return {}


_WORD_RE = re.compile(r"\b([A-Z][A-Za-z0-9_-]{1,30})\b")


def _detect_refs(text: str, known: set[str]) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for m in _WORD_RE.finditer(text):
        tok = m.group(1)
        if tok in known and tok not in seen:
            seen.append(tok)
    return seen


def build() -> Graph:
    from agents import project_owner as po
    projects = po.list_projects()
    known = set(projects)
    edges: list[Edge] = []

    for p in projects:
        raw = _yaml_raw(p)
        if not isinstance(raw, dict):
            continue
        # Explicit depends_on (list of project names).
        for dep in raw.get("depends_on") or []:
            if isinstance(dep, str) and dep in known and dep != p:
                edges.append(Edge(src=p, dst=dep, kind="explicit"))

        # Soft refs in milestones / goals / stakeholder notes.
        for g in raw.get("goals") or []:
            for ref in _detect_refs(str(g), known):
                if ref != p:
                    edges.append(Edge(src=p, dst=ref, kind="goal"))
        for m in raw.get("milestones") or []:
            for b in (m.get("blockers") or []):
                for ref in _detect_refs(str(b), known):
                    if ref != p:
                        edges.append(Edge(src=p, dst=ref, kind="blocker"))
        for s in raw.get("stakeholders") or []:
            note = (s.get("notes") or "")
            for ref in _detect_refs(str(note), known):
                if ref != p:
                    edges.append(Edge(src=p, dst=ref, kind="note"))

    # De-dup: keep highest-priority kind per (src, dst).
    priority = {"explicit": 0, "blocker": 1, "goal": 2, "note": 3}
    best: dict[tuple[str, str], Edge] = {}
    for e in edges:
        cur = best.get((e.src, e.dst))
        if cur is None or priority[e.kind] < priority[cur.kind]:
            best[(e.src, e.dst)] = e
    return Graph(projects=projects, edges=list(best.values()))


# ── renderers ────────────────────────────────────────────────────


_DOT_STYLE = {
    "explicit": "solid",
    "blocker":  "bold",
    "goal":     "dashed",
    "note":     "dotted",
}


def dot(graph: Optional[Graph] = None) -> str:
    g = graph or build()
    lines = ["digraph aim_projects {",
             "  rankdir=LR;",
             "  node [shape=box, style=rounded];"]
    for p in g.projects:
        lines.append(f'  "{p}";')
    for e in g.edges:
        style = _DOT_STYLE.get(e.kind, "solid")
        lines.append(f'  "{e.src}" -> "{e.dst}" '
                     f'[style={style}, label="{e.kind}"];')
    lines.append("}")
    return "\n".join(lines)


def mermaid(graph: Optional[Graph] = None) -> str:
    g = graph or build()
    lines = ["```mermaid", "graph TD"]
    for p in g.projects:
        lines.append(f"  {p}")
    for e in g.edges:
        arrow = {"explicit": "-->", "blocker": "==>", "goal": "-.->", "note": "-..->"}.get(e.kind, "-->")
        lines.append(f"  {e.src} {arrow}|{e.kind}| {e.dst}")
    lines.append("```")
    return "\n".join(lines)


def adjacency(graph: Optional[Graph] = None) -> dict:
    g = graph or build()
    out: dict[str, list[tuple[str, str]]] = {p: [] for p in g.projects}
    for e in g.edges:
        out.setdefault(e.src, []).append((e.dst, e.kind))
    return out


# ── cycle detection ──────────────────────────────────────────────


def cycles(graph: Optional[Graph] = None) -> list[list[str]]:
    """Return every simple cycle in the graph (DFS, small-N tolerant)."""
    g = graph or build()
    adj: dict[str, list[str]] = {p: [] for p in g.projects}
    for e in g.edges:
        adj.setdefault(e.src, []).append(e.dst)

    found: list[list[str]] = []
    seen_cycle: set[tuple[str, ...]] = set()

    def visit(node: str, path: list[str], stack: set[str]) -> None:
        for nxt in adj.get(node, []):
            if nxt in stack:
                # Cycle: extract the loop slice.
                idx = path.index(nxt)
                loop = path[idx:]
                key = tuple(loop)
                # Canonicalise: rotate to start at lex-min element.
                rot = min(range(len(key)),
                           key=lambda i: tuple(key[i:] + key[:i]))
                canonical = tuple(key[rot:] + key[:rot])
                if canonical not in seen_cycle:
                    seen_cycle.add(canonical)
                    found.append(list(canonical))
                continue
            visit(nxt, path + [nxt], stack | {nxt})

    for p in g.projects:
        visit(p, [p], {p})
    return found
