"""agents/reflexion.py — thin Python shim over the `aim-reflexion`
Rust binary (Phase 8 Week 2, 2026-05-07).

Reflexion (Shinn et al., 2023; refined 2025) — when a run fails or the
self-critique finds material flaws, generate a brief verbal reflection
("what went wrong, what to try differently") and persist it. On the
NEXT run with a similar task class, retrieve recent reflections and
inject them as a hint.

Storage logic (classify, save_reflection, recent_reflections,
store_dir resolution) lives in `rust-core/crates/aim-reflexion`. This
module remains in Python only because `on_failure` calls the Python
LLM router (`llm.ask_fast`) — until `llm.py` itself is Rust (Phase 5
of MIGRATION_RUST_PHOENIX), the LLM-using flow stays here.

Public API (preserved):
    classify(task)                     → str
    save_reflection(task, summary)
    recent_reflections(task, n=3)      → list[str]
    on_failure(task, error_excerpt)    → None
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("aim.reflexion")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-reflexion"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-reflexion binary not built at {bin_path}; "
            "run `cargo build -p aim-reflexion --release` in rust-core/"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aim-reflexion {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def classify(task: str) -> str:
    """Return one of: code_edit / research / writing / diagnosis / ops /
    email / general."""
    return _run(["classify", task]).strip() or "general"


def save_reflection(task: str, summary: str, *, bucket: str | None = None) -> None:
    args = ["save"]
    if bucket:
        args += ["--bucket", bucket]
    args += [task, summary]
    try:
        _run(args)
    except Exception as e:
        log.warning(f"reflexion save failed: {e}")


def recent_reflections(task: str, n: int = 3, *,
                       bucket: str | None = None,
                       max_age_days: int = 60) -> list[str]:
    args = ["recent", "--n", str(n), "--max-age-days", str(max_age_days)]
    if bucket:
        args += ["--bucket", bucket]
    args.append(task)
    try:
        out = _run(args)
    except Exception:
        return []
    return [line for line in out.splitlines() if line.strip()]


def on_failure(task: str, error_excerpt: str) -> None:
    """Generate a brief Reflexion summary via cheap LLM and persist it.

    Stays in Python (calls `llm.ask_fast`). Will become a shim once
    Phase 5 ports `llm.py` → `aim-llm`.
    """
    try:
        from llm import ask_fast
        prompt = (
            "You are writing a one-paragraph (≤80 words) Reflexion entry.\n"
            "An AI agent just FAILED at the task below. Identify the proximate "
            "cause and ONE concrete change of strategy to try next time. Be "
            "concrete, not generic.\n\n"
            f"=== TASK ===\n{task[:600]}\n\n"
            f"=== FAILURE EVIDENCE ===\n{error_excerpt[:1500]}\n"
            "=== Your reflection: ==="
        )
        summary = ask_fast(prompt) or ""
        if summary.strip():
            save_reflection(task, summary)
    except Exception as e:
        log.debug(f"reflexion on_failure skipped: {e}")
