"""
agents/memory_index.py — semantic memory retrieval over Claude memory files.

Uses sentence-transformers (all-MiniLM-L6-v2, 384-dim, ~80MB) for embeddings
and LanceDB (file-based, embedded) for vector storage. Both are fully local;
no network calls after the first model download.

Build the index once:
    python3 -m agents.memory_index reindex

Query at runtime (used by graph.py):
    from agents.memory_index import retrieve
    chunks = retrieve("какой у Tkemaladze ORCID", k=12)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

log = logging.getLogger("aim.memory_index")

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
INDEX_DIR = Path.home() / ".claude" / "memory_index"
TABLE_NAME = "memory_v1"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # 384-dim, ~80MB, fast on CPU
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200


def _split_chunks(text: str) -> list[str]:
    """Window the text into overlapping chunks. Crude but adequate for short memory files."""
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _encode(texts: list[str]):
    """Encode texts to vectors. Tries the embed daemon first (fast); falls back
    to in-process model load if daemon is not running."""
    try:
        from agents.embed_daemon import encode_via_daemon
        vecs = encode_via_daemon(texts)
        if vecs is not None:
            log.info(f"[encode] used embed daemon ({len(texts)} texts)")
            return vecs
    except Exception as e:
        log.debug(f"daemon path failed: {e}")
    # Fallback: in-process model load (~3-4s on first call)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBED_MODEL)
    arr = model.encode(texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True)
    return [v.tolist() for v in arr]


def _model():
    """Legacy entrypoint kept for indexing pipeline. Always loads in-process."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL)


def _open_db():
    import lancedb
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(INDEX_DIR))


def _enumerate_records() -> Iterable[dict]:
    """Yield {file, chunk_id, text, mtime} for every chunk of every memory file."""
    if not MEMORY_DIR.exists():
        return
    for f in sorted(MEMORY_DIR.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"skip {f}: {e}")
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        for i, chunk in enumerate(_split_chunks(content)):
            yield {
                "file": f.name,
                "chunk_id": i,
                "text": chunk,
                "mtime": mtime,
            }


def reindex() -> dict[str, int]:
    """Rebuild the embedding index from scratch. Returns counters."""
    model = _model()
    records = list(_enumerate_records())
    if not records:
        log.warning("no memory files found")
        return {"files": 0, "chunks": 0}

    log.info(f"embedding {len(records)} chunks across {len({r['file'] for r in records})} files…")
    texts = [r["text"] for r in records]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True)

    for r, e in zip(records, embeddings):
        r["vector"] = e.tolist()

    db = _open_db()
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, data=records)
    table.create_index(metric="cosine")

    return {
        "files": len({r["file"] for r in records}),
        "chunks": len(records),
        "dim": len(records[0]["vector"]),
    }


def retrieve(query: str, k: int = 12, max_chars_per_file: int = 4000) -> list[dict]:
    """Top-k chunks by semantic similarity. Returns [{file, text, _distance}, ...].

    Behaviour:
    - Connects to LanceDB; if index doesn't exist, returns []
    - Deduplicates per file: at most max_chars_per_file from each file
    - Sorted by distance (lower = closer)
    """
    try:
        db = _open_db()
        if TABLE_NAME not in db.table_names():
            log.warning(f"no index at {INDEX_DIR}/{TABLE_NAME}; run `aim-memory-index reindex`")
            return []
        table = db.open_table(TABLE_NAME)
    except Exception as e:
        log.warning(f"LanceDB open failed: {e}")
        return []

    try:
        qvec = _encode([query])[0]
    except Exception as e:
        log.warning(f"embedding query failed: {e}")
        return []

    # Pull more than k, then dedupe to k unique files
    raw = table.search(qvec).metric("cosine").limit(k * 4).to_list()

    seen: dict[str, int] = {}
    result: list[dict] = []
    for hit in raw:
        f = hit["file"]
        if seen.get(f, 0) >= max_chars_per_file:
            continue
        seen[f] = seen.get(f, 0) + len(hit["text"])
        result.append({
            "file": f,
            "text": hit["text"],
            "_distance": hit.get("_distance", 0.0),
        })
        if len({r["file"] for r in result}) >= k:
            break
    return result


def status() -> dict:
    """Quick status of the index."""
    info = {
        "index_dir": str(INDEX_DIR),
        "memory_dir": str(MEMORY_DIR),
        "memory_files": len(list(MEMORY_DIR.glob("*.md"))) if MEMORY_DIR.exists() else 0,
    }
    try:
        db = _open_db()
        if TABLE_NAME not in db.table_names():
            info["index_status"] = "missing"
        else:
            t = db.open_table(TABLE_NAME)
            info["index_status"] = "ready"
            info["index_chunks"] = t.count_rows()
    except Exception as e:
        info["index_status"] = f"error: {e}"
    return info


def _main():
    import argparse
    p = argparse.ArgumentParser(description="Semantic memory index (sentence-transformers + LanceDB)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reindex", help="Rebuild the embedding index from scratch")
    sub.add_parser("status", help="Show index status")
    q = sub.add_parser("query", help="Run a test query against the index")
    q.add_argument("text", help="Query text")
    q.add_argument("-k", type=int, default=8)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "reindex":
        print(f"[reindex] memory dir: {MEMORY_DIR}")
        print(f"[reindex] index dir:  {INDEX_DIR}")
        print(f"[reindex] embedding model: {EMBED_MODEL}")
        info = reindex()
        print(f"[reindex] DONE: {info['files']} files → {info['chunks']} chunks, dim={info.get('dim','?')}")
    elif args.cmd == "status":
        for k, v in status().items():
            print(f"  {k}: {v}")
    elif args.cmd == "query":
        hits = retrieve(args.text, k=args.k)
        if not hits:
            print("  (no hits — index empty or out of memory range)")
            return
        print(f"\n  top-{len(hits)} for: {args.text!r}")
        print("  " + "─" * 80)
        for h in hits:
            print(f"  {h['_distance']:.3f}  {h['file']}")
            preview = h['text'].replace('\n', ' ')[:160]
            print(f"         {preview}…")
            print()


if __name__ == "__main__":
    _main()
