"""web/api.py — FastAPI HTTP + WebSocket front-end for AIM.

Endpoints:
    GET  /                   — minimal HTML chat (web/static/index.html)
    POST /api/chat           — submit task; returns task_id + initial state
    GET  /api/health         — proxies agents.metrics health snapshot
    GET  /api/memory         — top-k semantic retrieve
    WS   /ws/{task_id}       — token stream from streaming reviewer

Run:
    pip install fastapi uvicorn websockets
    aim-web --port 8080         (or:  python -m web.api --port 8080)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

# Allow running as `python -m web.api` from AIM root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger("aim.web")

app = FastAPI(title="AIM Web", version="7.0")

_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Per-IP rate limit (global + tighter for /webhook/*)
try:
    from web.rate_limit import rate_limit_middleware
    app.middleware("http")(rate_limit_middleware)
except Exception as e:
    log.info(f"rate-limit middleware not attached: {e}")

# Webhook surface (auth via X-AIM-Webhook-Token header; AIM_WEBHOOK_TOKEN env)
try:
    from web.webhooks import router as _webhook_router
    app.include_router(_webhook_router)
except Exception as e:
    log.info(f"webhook router not mounted: {e}")

_executor = ThreadPoolExecutor(max_workers=4)
_tasks: dict[str, dict[str, Any]] = {}   # task_id → {state, result, queue}


# ── Models ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    query: str
    use_memory: bool = True
    full_memory: bool = False
    parallel: bool = False
    debate: bool = False


class ChatResponse(BaseModel):
    task_id: str
    status: str
    websocket: str


# ── Routes ──────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    """Minimal browser UI — single-file HTML."""
    fp = _static_dir / "index.html"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"))
    return HTMLResponse(_DEFAULT_HTML)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "state": "queued",
        "request": req.dict(),
        "queue": asyncio.Queue(),
    }
    asyncio.get_event_loop().run_in_executor(_executor, _run_task, task_id)
    return ChatResponse(task_id=task_id, status="queued", websocket=f"/ws/{task_id}")


@app.get("/api/health")
async def health():
    try:
        from agents.metrics import _build_health
        return JSONResponse(_build_health())
    except Exception as e:
        return JSONResponse({"status": "unknown", "error": str(e)}, status_code=503)


@app.get("/api/health/full")
async def health_full():
    """Full self-diagnostic report — every subsystem probed."""
    try:
        from agents.self_health import SelfHealthChecker
        info = SelfHealthChecker(quick=False).check_all()
        status = 200 if info["overall_status"] == "healthy" else 503
        return JSONResponse(info, status_code=status)
    except Exception as e:
        return JSONResponse({"status": "unknown", "error": str(e)}, status_code=503)


@app.get("/api/memory")
async def memory_query(q: str, k: int = 8):
    try:
        from agents.memory_index import retrieve
        hits = retrieve(q, k=k)
        return {"hits": hits, "count": len(hits)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Memory editor endpoints ────────────────────────────────────────────────


@app.get("/memory")
async def memory_editor():
    p = _static_dir / "memory_editor.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists()
                        else "memory_editor.html missing")


@app.get("/api/memory/search")
async def memory_search(q: str = "", mode: str = "flat", k: int = 20):
    if mode == "graph":
        from agents.graphrag import query as graphrag_query
        hits = graphrag_query(q or " ", k=k, hops=1) if q else []
    else:
        from agents.memory_index import retrieve
        hits = retrieve(q or " ", k=k) if q else []
    # Try to enrich with priority/tags from frontmatter
    try:
        from agents.memory_priority import _read_frontmatter, _locate
        for h in hits:
            p = _locate(h["file"])
            if p:
                fm = _read_frontmatter(p)
                h["priority"] = fm.get("priority", "NORMAL")
                if "tags" in fm:
                    h["tags"] = [t for t in str(fm["tags"]).split(",") if t]
    except Exception:
        pass
    return hits


class MemoryAdd(BaseModel):
    text: str
    category: str = "general"
    tags: str = ""


@app.post("/api/memory/add")
async def memory_add(body: MemoryAdd):
    from agents.memory_store import remember
    md = {"tags": [t.strip() for t in body.tags.split(",") if t.strip()]} if body.tags else None
    path = remember(body.text, category=body.category, metadata=md, quiet=True)
    return {"ok": True, "file": Path(str(path)).name}


@app.get("/api/memory/get")
async def memory_get(file: str):
    from agents.memory_priority import _locate
    p = _locate(file)
    if not p or not p.exists():
        raise HTTPException(404, f"not found: {file}")
    return {"file": file, "text": p.read_text(encoding="utf-8")}


class MemoryUpdate(BaseModel):
    file: str
    text: str


@app.post("/api/memory/update")
async def memory_update(body: MemoryUpdate):
    from agents.memory_priority import _locate
    p = _locate(body.file)
    if not p or not p.exists():
        raise HTTPException(404, f"not found: {body.file}")
    p.write_text(body.text, encoding="utf-8")
    return {"ok": True}


class MemoryDelete(BaseModel):
    file: str


@app.post("/api/memory/delete")
async def memory_delete(body: MemoryDelete):
    from agents.memory_priority import _locate
    p = _locate(body.file)
    if not p or not p.exists():
        raise HTTPException(404, f"not found: {body.file}")
    p.unlink()
    return {"ok": True}


@app.websocket("/ws/{task_id}")
async def stream(websocket: WebSocket, task_id: str):
    if task_id not in _tasks:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue: asyncio.Queue = _tasks[task_id]["queue"]
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))
            if event.get("type") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass


# ── Worker ──────────────────────────────────────────────────────────────────


def _run_task(task_id: str) -> None:
    """Run agent in thread pool; push state events to the task's async queue."""
    rec = _tasks[task_id]
    rec["state"] = "running"
    loop = asyncio.new_event_loop()

    def emit(payload: dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(rec["queue"].put(payload), loop)

    threading_loop_done = asyncio.Event()

    async def _drain():
        await threading_loop_done.wait()
    try:
        from agents.graph import run_agent
        req = rec["request"]

        emit({"type": "status", "msg": "загрузка памяти…"})
        result = run_agent(
            req["query"],
            use_memory=req.get("use_memory", True),
            full_memory=req.get("full_memory", False),
            parallel=req.get("parallel", False),
            debate=req.get("debate", False),
        )
        rec["result"] = result
        emit({"type": "plan", "plan": result.get("plan", [])})
        for chunk in result.get("step_results", []):
            emit({"type": "step", "text": chunk})
        emit({"type": "review", "text": result.get("review", "")})
        emit({"type": "done", "iteration": result.get("iteration", 0)})
    except Exception as e:
        log.exception("task failed")
        emit({"type": "error", "error": str(e)})
    finally:
        rec["state"] = "done"
        threading_loop_done.set()
        loop.close()


# ── Default HTML (used if static/index.html missing) ────────────────────────


_DEFAULT_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>AIM Web</title>
<style>
body{font-family:system-ui,sans-serif;max-width:780px;margin:2rem auto;padding:0 1rem;}
textarea{width:100%;height:120px;font-family:monospace;}
pre{background:#f4f4f5;padding:1rem;border-radius:6px;white-space:pre-wrap;}
button{padding:.6rem 1.2rem;background:#205493;color:white;border:0;border-radius:4px;cursor:pointer;}
.tag{display:inline-block;padding:.2rem .6rem;border-radius:3px;background:#eef;margin-right:.5rem;}
</style></head><body>
<h1>AIM · LangGraph</h1>
<textarea id="q" placeholder="Введи задачу…"></textarea>
<p>
  <label><input type="checkbox" id="mem" checked> память</label>
  <label><input type="checkbox" id="par"> parallel</label>
  <label><input type="checkbox" id="deb"> debate</label>
  <button onclick="run()">▶ Запустить</button>
</p>
<div id="out"></div>
<script>
async function run(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  const out=document.getElementById('out'); out.innerHTML='<p>⏳ запуск…</p>';
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:q,
      use_memory:document.getElementById('mem').checked,
      parallel:document.getElementById('par').checked,
      debate:document.getElementById('deb').checked})});
  const {task_id,websocket}=await r.json();
  const ws=new WebSocket(`ws://${location.host}${websocket}`);
  ws.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='plan'){out.innerHTML+='<h3>📋 план</h3><ol>'+msg.plan.map(s=>'<li>'+s+'</li>').join('')+'</ol>';}
    else if(msg.type==='step'){out.innerHTML+='<pre>'+msg.text+'</pre>';}
    else if(msg.type==='review'){out.innerHTML+='<h3>✅ review</h3><pre>'+msg.text+'</pre>';}
    else if(msg.type==='done'){out.innerHTML+='<p><span class=tag>iteration '+msg.iteration+'</span></p>';}
    else if(msg.type==='error'){out.innerHTML+='<p style=color:red>❌ '+msg.error+'</p>';}
  };
}
</script></body></html>
"""


# ── CLI entrypoint ──────────────────────────────────────────────────────────


def _main():
    import argparse
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.getenv("AIM_WEB_PORT", "8080")))
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.metrics:
        try:
            from agents.metrics import start_metrics_server
            start_metrics_server()
        except ImportError:
            pass
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    _main()
