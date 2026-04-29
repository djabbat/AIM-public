"""agents/context_compressor.py — LLM-based context compression.

Reduces large memory blobs (10K+ chars) to a target budget while preserving:
    • named entities (people, projects, dates, IDs, ORCIDs, PMIDs, DOIs)
    • numbers, deadlines, file paths
    • critical decisions

Strategy:
    1. Map-reduce over chunks if very large (>30K chars)
    2. Single-pass LLM compression at target budget
    3. Cheap fallback to truncation if all calls fail

Used opportunistically by `graph._load_aim_memory()` for very long contexts.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from llm import ask

log = logging.getLogger("aim.compressor")


SYSTEM = (
    "Ты сжимаешь контекст для следующего LLM-вызова. Отвечай на русском. "
    "Сохрани все имена, даты, числа, идентификаторы (ORCID, PMID, DOI), пути, "
    "deadlines, ключевые решения. Удали повторы и риторику."
)


def _approx_tokens(s: str) -> int:
    """Rough heuristic — ~4 chars per token (Cyrillic-mixed)."""
    return max(1, len(s) // 4)


def _split_chunks(text: str, max_chars: int = 8000, overlap: int = 200) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _compress_one(chunk: str, target_tokens: int) -> str:
    target_chars = target_tokens * 4
    prompt = (
        f"СЖИМАЙ ДО ~{target_tokens} токенов (~{target_chars} символов).\n"
        f"СОХРАНИ: имена, даты, числа, ID (ORCID, PMID, DOI), deadlines, решения.\n"
        f"УДАЛИ: повторы, риторику, преамбулы.\n\n"
        f"━━━ КОНТЕКСТ ━━━\n{chunk}\n\n"
        f"━━━ СЖАТЫЙ ВАРИАНТ ━━━"
    )
    try:
        return ask(prompt, system=SYSTEM, max_tokens=max(target_tokens, 256))
    except Exception as e:
        log.warning(f"compress call failed: {e}; falling back to truncation")
        return chunk[:target_chars]


# ── Public ──────────────────────────────────────────────────────────────────


def compress(
    context: str,
    target_tokens: int = 2000,
    map_reduce_threshold_chars: int = 30000,
) -> str:
    """Return a compressed version of `context` aimed at ~target_tokens.

    No-op if input is already under target.
    """
    if not context:
        return context
    est = _approx_tokens(context)
    if est <= target_tokens:
        return context

    log.info(f"compressing {est} → {target_tokens} tokens")

    if len(context) <= map_reduce_threshold_chars:
        return _compress_one(context, target_tokens)

    # Map: per-chunk compression to ~target_tokens / N
    chunks = _split_chunks(context, max_chars=8000)
    per_chunk_budget = max(target_tokens // len(chunks), 200)
    log.info(f"map-reduce: {len(chunks)} chunks, {per_chunk_budget} tok each")

    summaries: list[str] = []
    for i, ch in enumerate(chunks, 1):
        summaries.append(_compress_one(ch, per_chunk_budget))
        log.debug(f"chunk {i}/{len(chunks)} done")

    merged = "\n\n".join(summaries)
    if _approx_tokens(merged) <= target_tokens:
        return merged
    # Reduce
    return _compress_one(merged, target_tokens)


# ── Fast lossless dedup (regex) ─────────────────────────────────────────────


def quick_dedup(text: str) -> str:
    """Drop duplicated paragraphs (exact match) before LLM compression — saves tokens."""
    seen: set[str] = set()
    out_paragraphs: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        key = para.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out_paragraphs.append(para)
    return "\n\n".join(out_paragraphs)


def _main():
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument("--target-tokens", type=int, default=2000)
    p.add_argument("--input", help="path to text file (default: stdin)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    text = open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read()
    text = quick_dedup(text)
    print(compress(text, target_tokens=args.target_tokens))


if __name__ == "__main__":
    _main()
