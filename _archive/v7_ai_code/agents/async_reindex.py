"""agents/async_reindex.py — concurrent batched memory reindex.

Re-encodes chunks across N worker threads, each batching to the embed daemon.
On a typical 119-file corpus (~350 KB) this brings cold reindex from ~12s
down to ~3s. Falls back gracefully to in-process model if daemon is dead.

CLI:
    aim-reindex full              # parallel full rebuild
    aim-reindex incremental       # delta (mtime+size) — uses memory_index.reindex_incremental
    aim-reindex stats
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

log = logging.getLogger("aim.async_reindex")


def _enumerate():
    from agents.memory_index import _enumerate_records
    return list(_enumerate_records())


def _encode_batch(batch: list[dict]) -> list[dict]:
    """Encode a single batch via daemon; on failure fall back to model."""
    texts = [r["text"] for r in batch]
    try:
        from agents.embed_daemon import encode_via_daemon
        vecs = encode_via_daemon(texts, timeout_s=60)
        if vecs:
            for r, v in zip(batch, vecs):
                r["vector"] = v
            return batch
    except Exception as e:
        log.warning(f"daemon encode failed: {e}")
    # in-process fallback
    from agents.memory_index import _model
    arr = _model().encode(texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True)
    for r, v in zip(batch, arr):
        r["vector"] = v.tolist()
    return batch


def reindex_async(workers: int = 4, batch_size: int = 32,
                  progress: bool = True) -> dict:
    """Parallel full reindex. Returns counters."""
    t0 = time.time()
    records = _enumerate()
    if not records:
        log.warning("no memory files found")
        return {"files": 0, "chunks": 0, "elapsed_s": 0.0}

    log.info(f"async reindex: {len(records)} chunks, {workers} workers, batch={batch_size}")

    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    encoded: list[dict] = []

    bar = None
    if progress:
        try:
            from tqdm import tqdm
            bar = tqdm(total=len(records), desc="🔄 async reindex", unit="chunk")
        except ImportError:
            bar = None

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="aim-reindex") as pool:
        futures = [pool.submit(_encode_batch, b) for b in batches]
        for fut in as_completed(futures):
            encoded.extend(fut.result())
            if bar:
                bar.update(len(fut.result()))
    if bar:
        bar.close()

    # Open table and replace contents
    from agents.memory_index import _open_db, TABLE_NAME, _save_state, _file_state
    db = _open_db()
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, data=encoded)
    table.create_index(metric="cosine")
    _save_state(_file_state())

    elapsed = time.time() - t0
    log.info(f"done: {len(encoded)} chunks in {elapsed:.1f}s")
    return {
        "files":     len({r["file"] for r in encoded}),
        "chunks":    len(encoded),
        "workers":   workers,
        "batches":   len(batches),
        "elapsed_s": round(elapsed, 2),
    }


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-reindex")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("full")
    f.add_argument("--workers", type=int, default=4)
    f.add_argument("--batch-size", type=int, default=32)
    f.add_argument("--no-progress", action="store_true")

    sub.add_parser("incremental")
    sub.add_parser("stats")

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "full":
        info = reindex_async(workers=args.workers, batch_size=args.batch_size,
                             progress=not args.no_progress)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.cmd == "incremental":
        from agents.memory_index import reindex_incremental
        print(json.dumps(reindex_incremental(progress=True), ensure_ascii=False, indent=2))
    elif args.cmd == "stats":
        from agents.memory_index import status
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
