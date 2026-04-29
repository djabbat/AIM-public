"""agents/resilient_llm.py — network-resilient LLM call wrapper.

Retries on transient errors (ConnectionError, TimeoutError, httpx.TimeoutException,
HTTP 5xx) with exponential backoff. Persists in-progress task state under
/tmp/aim_llm_ckpt_<task_id>.json so a crashed call can be resumed by the same
task_id (idempotent — if a checkpoint with completed=True exists, return it).

This is layered ON TOP of the rate-limiter + circuit-breaker already in llm.py;
those guard against quota / outage. Resilience here protects against flaky
networks, partial connectivity, and process-restart scenarios.

Usage:
    from agents.resilient_llm import resilient_ask
    response = resilient_ask("проведи peer review", task_id="peerrev-2026-04-29")
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from llm import ask as _ask, ask_deep as _ask_deep

log = logging.getLogger("aim.resilient")

CKPT_DIR = Path("/tmp")
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.HTTPStatusError,
)


def _ckpt_path(task_id: str) -> Path:
    safe = "".join(c for c in task_id if c.isalnum() or c in "-_") or "noid"
    return CKPT_DIR / f"aim_llm_ckpt_{safe}.json"


def _load_ckpt(task_id: str) -> Optional[dict]:
    p = _ckpt_path(task_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_ckpt(task_id: str, data: dict) -> None:
    p = _ckpt_path(task_id)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _drop_ckpt(task_id: str) -> None:
    p = _ckpt_path(task_id)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


# ── Tenacity-wrapped callers ────────────────────────────────────────────────


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _retry_ask(prompt: str, **kw) -> str:
    return _ask(prompt, **kw)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _retry_ask_deep(prompt: str, **kw) -> str:
    return _ask_deep(prompt, **kw)


# ── Public API ──────────────────────────────────────────────────────────────


def resilient_ask(prompt: str, task_id: Optional[str] = None,
                  deep: bool = False, **kwargs) -> str:
    """Drop-in replacement for `llm.ask` / `llm.ask_deep` with retry + checkpoint.

    If `task_id` is provided and a completed checkpoint exists for it, returns
    that result without calling the model. After a successful call the
    checkpoint is removed.
    """
    if task_id:
        ckpt = _load_ckpt(task_id)
        if ckpt and ckpt.get("completed"):
            log.info(f"resume from checkpoint {task_id}")
            return ckpt.get("response", "")

    fn = _retry_ask_deep if deep else _retry_ask
    try:
        if task_id:
            _save_ckpt(task_id, {
                "task_id":   task_id,
                "started":   datetime.now().isoformat(timespec="seconds"),
                "completed": False,
            })
        response = fn(prompt, **kwargs)
        if task_id:
            _save_ckpt(task_id, {
                "task_id":   task_id,
                "completed": True,
                "finished":  datetime.now().isoformat(timespec="seconds"),
                "response":  response,
            })
            _drop_ckpt(task_id)   # success → don't keep
        return response
    except Exception as e:
        if task_id:
            _save_ckpt(task_id, {
                "task_id":   task_id,
                "error":     f"{type(e).__name__}: {e}",
                "failed_at": datetime.now().isoformat(timespec="seconds"),
                "completed": False,
            })
        raise


def list_pending_checkpoints() -> list[dict]:
    """Find leftover checkpoints from crashed runs."""
    out = []
    for p in CKPT_DIR.glob("aim_llm_ckpt_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not data.get("completed"):
                out.append({"file": str(p), **data})
        except Exception:
            continue
    return out


def _main():
    import argparse, sys
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending", help="list incomplete checkpoints")
    cl = sub.add_parser("clear", help="remove all aim_llm_ckpt_* files")
    cl.add_argument("--all", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "pending":
        for c in list_pending_checkpoints():
            print(c)
    elif args.cmd == "clear":
        n = 0
        for p in CKPT_DIR.glob("aim_llm_ckpt_*.json"):
            p.unlink()
            n += 1
        print(f"removed {n}")


if __name__ == "__main__":
    _main()
