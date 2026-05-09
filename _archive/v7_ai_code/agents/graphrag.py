"""agents/graphrag.py — knowledge-graph layer over the semantic memory index.

Builds a NetworkX graph of entities extracted from memory files, where edges
encode co-occurrence within the same file. At query time:

    1. Embed the query, find seed nodes via cosine similarity.
    2. Expand 1–2 hops along edges.
    3. Return distinct memory chunks attached to that subgraph.

This complements (not replaces) `agents.memory_index.retrieve`: GraphRAG is
better when the query needs *transitive* reasoning ("X relates to Y via Z")
and where co-occurrence in the same memory file is meaningful.

Graph state is persisted under `~/.claude/memory_index/graphrag.gpickle`.
"""

from __future__ import annotations

import logging
import pickle
import re
from pathlib import Path
from typing import Iterable

import networkx as nx

log = logging.getLogger("aim.graphrag")

MEMORY_DIR  = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
GRAPH_PATH  = Path.home() / ".claude" / "memory_index" / "graphrag.gpickle"

# Crude entity regex for proper nouns (Cyrillic + Latin) and acronyms (3+ caps)
_ENTITY_RE = re.compile(
    r"\b("
    r"[A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}(?:[-\s][A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}){0,3}"  # PascalCase / Capitalised phrases
    r"|[A-ZА-Я]{3,}"   # acronyms (CDATA, MCOA, FCLC, GLA, …)
    r")\b"
)
# Stopwords that pass the regex but aren't entities
_STOP = {"The", "This", "That", "Why", "How", "When", "Что", "Это", "Как", "Почему", "Если",
         "READ", "TODO", "DONE", "OPEN", "CLOSED", "TRUE", "FALSE"}


def _extract_entities(text: str) -> list[str]:
    out = []
    seen: set[str] = set()
    for m in _ENTITY_RE.finditer(text):
        e = m.group(1).strip()
        if e in _STOP or e.lower() in seen:
            continue
        seen.add(e.lower())
        out.append(e)
    return out


def build_graph() -> nx.Graph:
    """Walk memory dir, extract entities per file, build co-occurrence graph."""
    g = nx.Graph()
    if not MEMORY_DIR.exists():
        log.warning(f"memory dir not found: {MEMORY_DIR}")
        return g

    for fp in sorted(MEMORY_DIR.glob("*.md")):
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        ents = _extract_entities(text)
        if len(ents) < 2:
            continue
        for ent in ents:
            if ent not in g:
                g.add_node(ent, files=set())
            g.nodes[ent]["files"].add(fp.name)
        # Edges: co-occurrence within same file
        for i, e1 in enumerate(ents):
            for e2 in ents[i + 1:]:
                if g.has_edge(e1, e2):
                    g[e1][e2]["weight"] += 1
                else:
                    g.add_edge(e1, e2, weight=1)

    log.info(f"graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    return g


def save_graph(g: nx.Graph) -> None:
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    # NetworkX 3.x deprecates write_gpickle; use plain pickle.
    with open(GRAPH_PATH, "wb") as fh:
        pickle.dump(g, fh)
    log.info(f"saved graph → {GRAPH_PATH}")


def load_graph() -> nx.Graph:
    if not GRAPH_PATH.exists():
        return build_graph_and_save()
    with open(GRAPH_PATH, "rb") as fh:
        return pickle.load(fh)


def build_graph_and_save() -> nx.Graph:
    g = build_graph()
    save_graph(g)
    return g


def query(query_text: str, k: int = 6, hops: int = 1) -> list[dict]:
    # Cache check (#64)
    try:
        from agents.graphrag_cache import cached_query, store as _gc_store
        hit = cached_query(query_text, k, hops)
        if hit is not None:
            return hit
    except Exception:
        _gc_store = None  # type: ignore[assignment]
    result = _query_uncached(query_text, k=k, hops=hops)
    try:
        if _gc_store:
            _gc_store(query_text, k, hops, result)
    except Exception:
        pass
    return result


def _query_uncached(query_text: str, k: int = 6, hops: int = 1) -> list[dict]:
    """Return memory chunks reachable via graph expansion from seed entities.

    Strategy:
      1. extract entities from query
      2. seed nodes ← entities present in graph
      3. expand `hops` steps along weighted edges (top-k neighbours by weight)
      4. fetch distinct files from union node-set, return chunks via memory_index.retrieve
    """
    try:
        g = load_graph()
    except Exception as e:
        log.warning(f"graphrag fallback to flat retrieval ({e})")
        from agents.memory_index import retrieve
        return retrieve(query_text, k=k)

    q_ents = [e for e in _extract_entities(query_text) if e in g]
    if not q_ents:
        from agents.memory_index import retrieve
        return retrieve(query_text, k=k)

    visited: set[str] = set(q_ents)
    frontier = list(q_ents)
    for _ in range(hops):
        new_frontier: list[str] = []
        for node in frontier:
            neighbours = sorted(
                g[node].items(), key=lambda kv: -kv[1].get("weight", 1)
            )[:k]
            for nb, _data in neighbours:
                if nb not in visited:
                    visited.add(nb)
                    new_frontier.append(nb)
        frontier = new_frontier
        if not frontier:
            break

    # Files referenced by any visited node
    files: set[str] = set()
    for node in visited:
        files |= g.nodes[node].get("files", set())

    # Hand off to flat semantic retrieval, biasing on these files
    from agents.memory_index import retrieve
    flat = retrieve(query_text, k=k * 2)
    boosted = [h for h in flat if h["file"] in files][:k]
    return boosted or flat[:k]


def _main():
    import argparse, json
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="build & persist the entity graph")
    sub.add_parser("stats", help="print graph stats")
    qp = sub.add_parser("query", help="run a graph-expanded query")
    qp.add_argument("text")
    qp.add_argument("-k", type=int, default=6)
    qp.add_argument("--hops", type=int, default=1)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "build":
        g = build_graph_and_save()
        print(f"nodes={g.number_of_nodes()} edges={g.number_of_edges()}")
    elif args.cmd == "stats":
        g = load_graph()
        top = sorted(g.degree, key=lambda x: -x[1])[:20]
        print(f"nodes={g.number_of_nodes()} edges={g.number_of_edges()}")
        print("top by degree:")
        for n, d in top:
            print(f"  {d:>3}  {n}")
    elif args.cmd == "query":
        for h in query(args.text, k=args.k, hops=args.hops):
            print(f"  {h.get('_distance', 0):.3f}  {h['file']}")
            print(f"         {h['text'][:160]}…")


if __name__ == "__main__":
    _main()
