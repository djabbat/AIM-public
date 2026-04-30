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
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from tqdm import tqdm  # type: ignore
    _TQDM = True
except ImportError:
    _TQDM = False

log = logging.getLogger("aim.memory_index")

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-home-oem" / "memory"
INDEX_DIR = Path.home() / ".claude" / "memory_index"
INDEX_STATE_FILE = INDEX_DIR / "_index_state.pkl"
TABLE_NAME = "memory_v1"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # 384-dim, ~80MB, fast on CPU
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200

# Cross-project ingestion (added 2026-04-30): index core .md files from
# user's Desktop project tree. Toggle via env to keep indexer fast in tests.
DESKTOP_DIR = Path.home() / "Desktop"
CORE_MD_NAMES = (
    "CONCEPT.md", "STATE.md", "THEORY.md", "DESIGN.md",
    "EVIDENCE.md", "PARAMETERS.md", "OPEN_PROBLEMS.md",
    "MEMORY.md", "README.md",
)
DESKTOP_PROJECT_GLOB = (
    "LongevityCommon/**/", "FCLC/**/", "MCOA/**/", "Ze/**/",
    "BioSense/**/", "CDATA/**/", "AIM/**/", "Annals/**/",
    "PhD/**/", "Books/**/", "GLA/**/",
)
INDEX_DESKTOP = os.getenv("AIM_INDEX_DESKTOP_PROJECTS", "1") == "1"


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
    """Yield {file, chunk_id, text, mtime} for every chunk of every memory file.

    Sources:
      1. ~/.claude/projects/-home-oem/memory/*.md   (auto-memory)
      2. ~/Desktop/<project>/{CONCEPT,STATE,THEORY,…}.md  (cross-project core)
         — only when AIM_INDEX_DESKTOP_PROJECTS=1 (default).
    """
    seen: set[Path] = set()

    def _emit(f: Path, label: str):
        if f in seen or not f.exists():
            return
        seen.add(f)
        try:
            content = f.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"skip {f}: {e}")
            return
        if not content.strip():
            return
        mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        for i, chunk in enumerate(_split_chunks(content)):
            yield {
                "file":     label,
                "chunk_id": i,
                "text":     chunk,
                "mtime":    mtime,
            }

    if MEMORY_DIR.exists():
        for f in sorted(MEMORY_DIR.glob("*.md")):
            yield from _emit(f, f.name)

    if INDEX_DESKTOP and DESKTOP_DIR.exists():
        for project in sorted(p for p in DESKTOP_DIR.iterdir()
                              if p.is_dir() and not p.name.startswith(".")):
            for name in CORE_MD_NAMES:
                f = project / name
                yield from _emit(f, f"{project.name}/{name}")


def _file_state() -> dict[str, tuple]:
    """(mtime, size) for every indexed file — used for incremental reindex."""
    state: dict[str, tuple] = {}
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*.md"):
            st = f.stat()
            state[f.name] = (st.st_mtime, st.st_size)
    if INDEX_DESKTOP and DESKTOP_DIR.exists():
        for project in (p for p in DESKTOP_DIR.iterdir()
                        if p.is_dir() and not p.name.startswith(".")):
            for name in CORE_MD_NAMES:
                f = project / name
                if f.exists():
                    st = f.stat()
                    state[f"{project.name}/{name}"] = (st.st_mtime, st.st_size)
    return state


def _load_state() -> dict[str, tuple]:
    if INDEX_STATE_FILE.exists():
        try:
            with open(INDEX_STATE_FILE, "rb") as fh:
                return pickle.load(fh)
        except Exception as e:
            log.warning(f"failed to load index state: {e}")
    return {}


def _save_state(state: dict[str, tuple]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_STATE_FILE, "wb") as fh:
        pickle.dump(state, fh)


def reindex(progress: bool = True, parallel: bool = False) -> dict[str, int]:
    """Rebuild the embedding index from scratch. Returns counters.

    progress: show tqdm bar if installed.
    parallel: encode in batches via the daemon (already cached) — currently a no-op
              hint because the daemon batches internally; flag kept for future use.
    """
    records = list(_enumerate_records())
    if not records:
        log.warning("no memory files found")
        return {"files": 0, "chunks": 0}

    log.info(f"embedding {len(records)} chunks across {len({r['file'] for r in records})} files…")
    texts = [r["text"] for r in records]

    # Prefer the running daemon (LRU-cached); fall back to in-process model.
    iterator_label = "🔄 Индексация памяти"
    if _TQDM and progress:
        bar = tqdm(total=len(texts), desc=iterator_label, unit="chunk", ncols=80)
    else:
        bar = None

    embeddings: list[list[float]] = []
    BATCH = 64
    used_daemon = False
    try:
        from agents.embed_daemon import encode_via_daemon
        for i in range(0, len(texts), BATCH):
            chunk = texts[i:i + BATCH]
            vecs = encode_via_daemon(chunk, timeout_s=60.0)
            if vecs is None:
                raise RuntimeError("daemon unavailable")
            embeddings.extend(vecs)
            if bar:
                bar.update(len(chunk))
        used_daemon = True
    except Exception as e:
        log.info(f"daemon encode failed ({e}); falling back to in-process model")
        if bar:
            bar.reset()
        model = _model()
        embeddings = []
        for i in range(0, len(texts), BATCH):
            chunk = texts[i:i + BATCH]
            arr = model.encode(chunk, batch_size=BATCH, show_progress_bar=False, convert_to_numpy=True)
            embeddings.extend(v.tolist() for v in arr)
            if bar:
                bar.update(len(chunk))
    if bar:
        bar.close()

    for r, e in zip(records, embeddings):
        r["vector"] = e

    db = _open_db()
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, data=records)
    table.create_index(metric="cosine")

    _save_state(_file_state())
    log.info(f"reindex done; daemon_used={used_daemon}")

    return {
        "files": len({r["file"] for r in records}),
        "chunks": len(records),
        "dim": len(records[0]["vector"]),
    }


def reindex_incremental(progress: bool = True) -> dict[str, int]:
    """Reindex only files whose (mtime, size) changed since last run.

    Falls back to full reindex when LanceDB table is missing or no state file.
    """
    new_state = _file_state()
    old_state = _load_state()

    if not old_state:
        log.info("no prior state — running full reindex")
        return reindex(progress=progress)

    db = _open_db()
    if TABLE_NAME not in db.table_names():
        log.info("index missing — running full reindex")
        return reindex(progress=progress)

    changed = [n for n, st in new_state.items() if old_state.get(n) != st]
    deleted = [n for n in old_state if n not in new_state]

    if not changed and not deleted:
        log.info("no changes detected; skip reindex")
        return {"files": 0, "chunks": 0, "changed": 0, "deleted": 0}

    table = db.open_table(TABLE_NAME)

    # Delete rows for changed/deleted files
    affected = set(changed) | set(deleted)
    quoted = ",".join(f"'{n}'" for n in affected)
    try:
        table.delete(f"file IN ({quoted})")
    except Exception as e:
        log.warning(f"partial delete failed ({e}); falling back to full reindex")
        return reindex(progress=progress)

    # Re-embed changed files
    new_records: list[dict] = []
    for r in _enumerate_records():
        if r["file"] in changed:
            new_records.append(r)

    if new_records:
        texts = [r["text"] for r in new_records]
        if _TQDM and progress:
            bar = tqdm(total=len(texts), desc="🔄 Инкрементальный reindex", unit="chunk", ncols=80)
        else:
            bar = None
        from agents.embed_daemon import encode_via_daemon
        BATCH = 64
        embeddings: list[list[float]] = []
        try:
            for i in range(0, len(texts), BATCH):
                ch = texts[i:i + BATCH]
                vecs = encode_via_daemon(ch, timeout_s=60.0)
                if vecs is None:
                    raise RuntimeError("daemon unavailable")
                embeddings.extend(vecs)
                if bar:
                    bar.update(len(ch))
        except Exception:
            model = _model()
            arr = model.encode(texts, batch_size=BATCH, show_progress_bar=False, convert_to_numpy=True)
            embeddings = [v.tolist() for v in arr]
            if bar:
                bar.update(len(texts))
        if bar:
            bar.close()
        for r, e in zip(new_records, embeddings):
            r["vector"] = e
        table.add(new_records)

    _save_state(new_state)
    return {
        "files": len(set(r["file"] for r in new_records)),
        "chunks": len(new_records),
        "changed": len(changed),
        "deleted": len(deleted),
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
    r_full = sub.add_parser("reindex", help="Rebuild the embedding index from scratch")
    r_full.add_argument("--no-progress", action="store_true")
    r_inc = sub.add_parser("reindex-incremental", help="Re-index only changed memory files")
    r_inc.add_argument("--no-progress", action="store_true")
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
        info = reindex(progress=not args.no_progress)
        print(f"[reindex] DONE: {info['files']} files → {info['chunks']} chunks, dim={info.get('dim','?')}")
    elif args.cmd == "reindex-incremental":
        info = reindex_incremental(progress=not args.no_progress)
        print(f"[reindex-incremental] changed={info.get('changed',0)} deleted={info.get('deleted',0)} "
              f"reembedded={info.get('chunks',0)} chunks across {info.get('files',0)} files")
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
