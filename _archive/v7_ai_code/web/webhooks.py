"""web/webhooks.py — webhook surface for external automations (n8n, Zapier, IFTTT…).

Mounted into `web/api.py` as a sub-router. All endpoints accept JSON, run the
payload via `agents.job_queue` so callers get back a `task_id` immediately
(non-blocking), and optionally POST back to a `callback_url` when done.

Auth: shared-secret header `X-AIM-Webhook-Token`. Set the secret via env:
    AIM_WEBHOOK_TOKEN=<long-random-string>
If unset, endpoints reject all requests (fail-closed).

Endpoints:
    POST /webhook/memory/add       store a fact
    POST /webhook/graph/run        run a LangGraph task (async)
    POST /webhook/memory/search    semantic search
    POST /webhook/health           returns /healthz JSON
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("aim.webhooks")
router = APIRouter(prefix="/webhook", tags=["webhooks"])

WEBHOOK_TOKEN = os.getenv("AIM_WEBHOOK_TOKEN", "")


def _check_token(token: Optional[str]) -> None:
    if not WEBHOOK_TOKEN:
        raise HTTPException(503, "AIM_WEBHOOK_TOKEN not set on server")
    if not token or token != WEBHOOK_TOKEN:
        raise HTTPException(401, "invalid webhook token")


# ── Models ──────────────────────────────────────────────────────────────────


class MemoryAddPayload(BaseModel):
    fact:        str
    category:    str = "webhook"
    tags:        Optional[list[str]] = None
    priority:    Optional[str] = None
    ttl_hours:   Optional[int] = None
    callback_url: Optional[str] = None


class GraphRunPayload(BaseModel):
    task:         str
    use_memory:   bool = True
    full_memory:  bool = False
    parallel:     bool = False
    debate:       bool = False
    tree_plan:    bool = False
    callback_url: Optional[str] = None


class MemorySearchPayload(BaseModel):
    query: str
    k:     int = 8
    graph: bool = False


# ── Helpers ─────────────────────────────────────────────────────────────────


def _post_callback(url: str, payload: dict[str, Any], timeout: float = 10.0) -> None:
    try:
        with httpx.Client(timeout=timeout) as cl:
            cl.post(url, json=payload)
        log.info(f"callback ok → {url}")
    except Exception as e:
        log.warning(f"callback {url} failed: {e}")


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/memory/add")
async def memory_add(
    body: MemoryAddPayload,
    x_aim_webhook_token: Optional[str] = Header(default=None),
):
    _check_token(x_aim_webhook_token)
    from agents.job_queue import submit
    from agents.memory_store import remember
    from agents.memory_priority import save_with_priority, Priority

    def _work() -> dict:
        if body.priority:
            try:
                prio = Priority[body.priority.upper()]
            except KeyError:
                prio = Priority.NORMAL
            path = save_with_priority(
                body.fact, category=body.category, priority=prio,
                ttl_hours=body.ttl_hours, tags=body.tags,
            )
        else:
            md = {"tags": body.tags} if body.tags else None
            if body.ttl_hours is not None:
                (md := md or {})["ttl_hours"] = body.ttl_hours
            path = remember(body.fact, category=body.category, metadata=md, quiet=True)
        result = {"ok": True, "file": str(path)}
        if body.callback_url:
            _post_callback(body.callback_url, result)
        return result

    job_id = submit("webhook.memory.add", _work, tags=["webhook", "memory"])
    return {"task_id": job_id, "status": "accepted"}


@router.post("/memory/search")
async def memory_search(
    body: MemorySearchPayload,
    x_aim_webhook_token: Optional[str] = Header(default=None),
):
    _check_token(x_aim_webhook_token)
    if body.graph:
        from agents.graphrag import query as graphrag_query
        hits = graphrag_query(body.query, k=body.k, hops=1)
    else:
        from agents.memory_index import retrieve
        hits = retrieve(body.query, k=body.k)
    return {"hits": hits, "count": len(hits)}


@router.post("/graph/run")
async def graph_run(
    body: GraphRunPayload,
    x_aim_webhook_token: Optional[str] = Header(default=None),
):
    _check_token(x_aim_webhook_token)
    from agents.job_queue import submit
    from agents.graph import run_agent

    def _work() -> dict:
        result = run_agent(
            body.task,
            use_memory=body.use_memory,
            full_memory=body.full_memory,
            parallel=body.parallel,
            debate=body.debate,
            tree_plan=body.tree_plan,
        )
        out = {
            "ok":            True,
            "plan":          result.get("plan", []),
            "step_results":  result.get("step_results", []),
            "review":        result.get("review", ""),
            "iteration":     result.get("iteration", 0),
        }
        if body.callback_url:
            _post_callback(body.callback_url, out)
        return out

    job_id = submit("webhook.graph.run", _work, tags=["webhook", "graph"])
    return {"task_id": job_id, "status": "accepted"}


@router.post("/health")
async def health(x_aim_webhook_token: Optional[str] = Header(default=None)):
    _check_token(x_aim_webhook_token)
    try:
        from agents.metrics import _build_health
        return _build_health()
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str,
    x_aim_webhook_token: Optional[str] = Header(default=None),
):
    _check_token(x_aim_webhook_token)
    from agents.job_queue import get
    info = get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    return info
