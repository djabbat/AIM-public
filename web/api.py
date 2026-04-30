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

from fastapi import (FastAPI, WebSocket, WebSocketDisconnect, HTTPException,
                     Depends, Request, Response, Cookie, Header)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger("aim.web")

# AIM has two run modes for the web layer:
#   AIM_ROLE=hub    → multi-user auth server (issues tokens, audit, no LLM)
#   AIM_ROLE=node   → per-user local AIM (default; chat/memory/LLM, gated by token)
AIM_ROLE = os.getenv("AIM_ROLE", "node").lower()
assert AIM_ROLE in ("hub", "node"), f"AIM_ROLE must be 'hub' or 'node', got {AIM_ROLE!r}"

app = FastAPI(title=f"AIM {AIM_ROLE.capitalize()}", version="7.0")

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


# ── Auth dependencies ───────────────────────────────────────────────────────


def _bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def _hub_user_from_request(request: Request) -> Optional[dict]:
    """Extract authenticated user on the hub side. Tries JWT cookie first,
    then API token (Bearer / X-AIM-Token), then None."""
    from agents import auth as _auth
    # JWT cookie (browser sessions)
    jwt = request.cookies.get("aim_jwt")
    if jwt:
        u = _auth.verify_jwt(jwt)
        if u:
            return u
    # API token (nodes / CLI / GUI)
    tok = (_bearer(request.headers.get("authorization"))
           or request.headers.get("x-aim-token"))
    if tok:
        u = _auth.get_user_by_token(tok)
        if u:
            return u
    return None


def _node_user_from_request(request: Request) -> Optional[dict]:
    """On node side, authentication is "did the *local* user start AIM with a
    valid AIM_USER_TOKEN" — verified once at process start by hub_client.
    The web UI is bound to 127.0.0.1 by default; if exposed on LAN, we still
    accept only the local node identity (no per-request token check)."""
    from agents import hub_client
    return hub_client.current_user()


def require_user(request: Request) -> dict:
    if AIM_ROLE == "hub":
        u = _hub_user_from_request(request)
    else:
        u = _node_user_from_request(request)
    if not u:
        raise HTTPException(401, "authentication required")
    return u


def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "admin role required")
    return user


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


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    email: Optional[str] = None


class TokenValidateRequest(BaseModel):
    token: str
    node_id: Optional[str] = None
    host: Optional[str] = None
    version: Optional[str] = None


class HeartbeatRequest(BaseModel):
    token: str
    node_id: str
    host: Optional[str] = None
    version: Optional[str] = None


# ── Hub-side routes (auth, users, audit, nodes) ─────────────────────────────


if AIM_ROLE == "hub":

    @app.get("/", response_class=HTMLResponse)
    async def hub_index(request: Request):
        u = _hub_user_from_request(request)
        if u is None:
            return HTMLResponse(_LOGIN_HTML)
        return HTMLResponse(_HUB_DASHBOARD_HTML.replace("{{USER}}", u["username"])
                                              .replace("{{ROLE}}", u["role"]))

    @app.post("/api/auth/login")
    async def auth_login(body: LoginRequest, request: Request):
        from agents import auth as _auth
        u = _auth.verify_password(body.username, body.password)
        if u is None:
            _auth.audit(None, "auth.login_failed", target=body.username,
                        ip=(request.client.host if request.client else None))
            raise HTTPException(401, "invalid credentials")
        token = _auth.issue_jwt(u["id"], ttl_days=7)
        _auth.audit(u["id"], "auth.login",
                    ip=(request.client.host if request.client else None),
                    ua=request.headers.get("user-agent"))
        resp = JSONResponse({"ok": True, "user": u})
        resp.set_cookie("aim_jwt", token, max_age=7 * 86400,
                        httponly=True, samesite="lax",
                        secure=os.getenv("AIM_HUB_HTTPS", "0") == "1")
        return resp

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        from agents import auth as _auth
        jwt = request.cookies.get("aim_jwt")
        if jwt:
            _auth.revoke_jwt(jwt)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("aim_jwt")
        return resp

    @app.get("/api/auth/me")
    async def auth_me(user: dict = Depends(require_user)):
        return {"user": user}

    @app.post("/api/auth/validate-token")
    async def validate_token(body: TokenValidateRequest, request: Request):
        """Called by node hub_client on startup. Returns the user the token
        is bound to, plus records a heartbeat. NOT public — token is the secret."""
        from agents import auth as _auth
        u = _auth.get_user_by_token(body.token)
        if u is None:
            return {"ok": False}
        if body.node_id:
            _auth.record_node_heartbeat(u["id"], body.node_id,
                                        host=body.host or "",
                                        version=body.version or "")
        _auth.audit(u["id"], "node.validate", target=body.node_id,
                    ip=(request.client.host if request.client else None))
        return {"ok": True, "user": u}

    @app.post("/api/nodes/heartbeat")
    async def nodes_heartbeat(body: HeartbeatRequest):
        from agents import auth as _auth
        u = _auth.get_user_by_token(body.token)
        if u is None:
            raise HTTPException(401, "invalid token")
        _auth.record_node_heartbeat(u["id"], body.node_id,
                                    host=body.host or "",
                                    version=body.version or "")
        return {"ok": True}

    @app.get("/api/nodes")
    async def nodes_list(user: dict = Depends(require_user)):
        from agents import auth as _auth
        if user["role"] == "admin":
            return {"nodes": _auth.list_nodes()}
        return {"nodes": _auth.list_nodes(user_id=user["id"])}

    @app.get("/api/users")
    async def users_list(_: dict = Depends(require_admin)):
        from agents import auth as _auth
        return {"users": _auth.list_users()}

    @app.post("/api/users")
    async def users_create(body: CreateUserRequest, admin: dict = Depends(require_admin)):
        from agents import auth as _auth
        u = _auth.create_user(body.username, body.password, role=body.role,
                              email=body.email)
        _auth.audit(admin["id"], "user.create", target=body.username)
        return {"ok": True, "user": u}

    @app.post("/api/users/{user_id}/disable")
    async def users_disable(user_id: int, admin: dict = Depends(require_admin)):
        from agents import auth as _auth
        _auth.disable_user(user_id)
        _auth.audit(admin["id"], "user.disable", target=str(user_id))
        return {"ok": True}

    @app.post("/api/users/{user_id}/token")
    async def users_token(user_id: int, admin: dict = Depends(require_admin)):
        from agents import auth as _auth
        tok = _auth.issue_api_token(user_id)
        _auth.audit(admin["id"], "token.issue", target=str(user_id))
        return {"ok": True, "token": tok}

    @app.post("/api/users/{user_id}/link-code")
    async def users_link_code(user_id: int, admin: dict = Depends(require_admin)):
        from agents import auth as _auth
        # Allow self-service: a regular user can link their own Telegram.
        if admin["role"] != "admin" and admin["id"] != user_id:
            raise HTTPException(403)
        code = _auth.create_link_code(user_id, ttl_min=10)
        _auth.audit(admin["id"], "telegram.link_code", target=str(user_id))
        return {"ok": True, "code": code, "ttl_min": 10}

    class _ConsumeLinkBody(BaseModel):
        code: str
        telegram_id: int

    @app.post("/api/telegram/consume-link")
    async def telegram_consume_link(body: _ConsumeLinkBody):
        """Public endpoint — called by user's Telegram bot when they send /link.
        The 6-digit code is the secret; if it's valid we bind tg_id to its user."""
        from agents import auth as _auth
        u = _auth.consume_link_code(body.code, body.telegram_id)
        if u is None:
            raise HTTPException(400, "invalid or expired code")
        _auth.audit(u["id"], "telegram.linked", target=str(body.telegram_id))
        return {"ok": True, "user": u}

    @app.get("/api/audit")
    async def audit_view(user: dict = Depends(require_user), n: int = 100,
                         user_id: Optional[int] = None):
        from agents import auth as _auth
        # Non-admins see only their own audit
        if user["role"] != "admin":
            user_id = user["id"]
        return {"audit": _auth.list_audit(user_id=user_id, limit=n)}

# ── Node-side routes (chat, memory, LLM) — gated by hub_client ──────────────


if AIM_ROLE == "node":

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Minimal browser UI — single-file HTML."""
        fp = _static_dir / "index.html"
        if fp.exists():
            return HTMLResponse(fp.read_text(encoding="utf-8"))
        return HTMLResponse(_DEFAULT_HTML)

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, user: dict = Depends(require_user)):
        task_id = uuid.uuid4().hex[:12]
        _tasks[task_id] = {
            "state": "queued",
            "request": req.dict(),
            "user_id": user.get("id"),
            "queue": asyncio.Queue(),
        }
        asyncio.get_event_loop().run_in_executor(_executor, _run_task, task_id)
        return ChatResponse(task_id=task_id, status="queued", websocket=f"/ws/{task_id}")


@app.get("/api/health")
async def health():
    """Always public — used by node startup probes and hub liveness."""
    try:
        from agents.metrics import _build_health
        info = _build_health() if AIM_ROLE == "node" else {}
        info["role"] = AIM_ROLE
        return JSONResponse(info)
    except Exception as e:
        return JSONResponse({"status": "unknown", "error": str(e), "role": AIM_ROLE},
                            status_code=503)


if AIM_ROLE == "node":

    @app.get("/api/health/full")
    async def health_full(_: dict = Depends(require_user)):
        try:
            from agents.self_health import SelfHealthChecker
            info = SelfHealthChecker(quick=False).check_all()
            status = 200 if info["overall_status"] == "healthy" else 503
            return JSONResponse(info, status_code=status)
        except Exception as e:
            return JSONResponse({"status": "unknown", "error": str(e)}, status_code=503)

    @app.get("/api/memory")
    async def memory_query(q: str, k: int = 8, _: dict = Depends(require_user)):
        try:
            from agents.memory_index import retrieve
            hits = retrieve(q, k=k)
            return {"hits": hits, "count": len(hits)}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.get("/memory")
    async def memory_editor(_: dict = Depends(require_user)):
        p = _static_dir / "memory_editor.html"
        return HTMLResponse(p.read_text(encoding="utf-8") if p.exists()
                            else "memory_editor.html missing")


class MemoryAdd(BaseModel):
    text: str
    category: str = "general"
    tags: str = ""


class MemoryUpdate(BaseModel):
    file: str
    text: str


class MemoryDelete(BaseModel):
    file: str


if AIM_ROLE == "node":

    @app.get("/api/memory/search")
    async def memory_search(q: str = "", mode: str = "flat", k: int = 20,
                            _: dict = Depends(require_user)):
        if mode == "graph":
            from agents.graphrag import query as graphrag_query
            hits = graphrag_query(q or " ", k=k, hops=1) if q else []
        else:
            from agents.memory_index import retrieve
            hits = retrieve(q or " ", k=k) if q else []
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

    @app.post("/api/memory/add")
    async def memory_add(body: MemoryAdd, _: dict = Depends(require_user)):
        from agents.memory_store import remember
        md = {"tags": [t.strip() for t in body.tags.split(",") if t.strip()]} if body.tags else None
        path = remember(body.text, category=body.category, metadata=md, quiet=True)
        return {"ok": True, "file": Path(str(path)).name}

    @app.get("/api/memory/get")
    async def memory_get(file: str, _: dict = Depends(require_user)):
        from agents.memory_priority import _locate
        p = _locate(file)
        if not p or not p.exists():
            raise HTTPException(404, f"not found: {file}")
        return {"file": file, "text": p.read_text(encoding="utf-8")}

    @app.post("/api/memory/update")
    async def memory_update(body: MemoryUpdate, _: dict = Depends(require_user)):
        from agents.memory_priority import _locate
        p = _locate(body.file)
        if not p or not p.exists():
            raise HTTPException(404, f"not found: {body.file}")
        p.write_text(body.text, encoding="utf-8")
        return {"ok": True}

    @app.post("/api/memory/delete")
    async def memory_delete(body: MemoryDelete, _: dict = Depends(require_user)):
        from agents.memory_priority import _locate
        p = _locate(body.file)
        if not p or not p.exists():
            raise HTTPException(404, f"not found: {body.file}")
        p.unlink()
        return {"ok": True}


if AIM_ROLE == "node":

    @app.websocket("/ws/{task_id}")
    async def stream(websocket: WebSocket, task_id: str):
        # task_id is an unguessable 12-hex token; only created by authenticated
        # /api/chat, so reaching here implies the chat route already authorized.
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


# ── Hub HTML (login + dashboard) ────────────────────────────────────────────


_LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AIM Hub · Login</title>
<style>
body{font-family:system-ui,sans-serif;max-width:380px;margin:6rem auto;padding:0 1rem;}
h1{font-size:1.4rem;margin-bottom:1.5rem;}
input{display:block;width:100%;padding:.6rem;margin:.4rem 0;font-size:1rem;
      border:1px solid #ccc;border-radius:4px;}
button{padding:.7rem 1.5rem;background:#205493;color:white;border:0;
       border-radius:4px;cursor:pointer;font-size:1rem;}
.err{color:#a00;margin:1rem 0;font-size:.9rem;}
.note{color:#666;font-size:.85rem;margin-top:2rem;}
</style></head><body>
<h1>AIM Hub · Sign in</h1>
<form id="f">
  <input id="u" placeholder="username" autocomplete="username" autofocus>
  <input id="p" type="password" placeholder="password" autocomplete="current-password">
  <button type="submit">Sign in</button>
  <div id="e" class="err"></div>
</form>
<p class="note">Hub manages users, tokens, audit. Each AIM node runs locally on
its own machine with its own DeepSeek key — LLM compute stays at the user.</p>
<script>
document.getElementById('f').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const u=document.getElementById('u').value, p=document.getElementById('p').value;
  const r=await fetch('/api/auth/login',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:u,password:p})});
  if(r.ok){location.href='/';}
  else{document.getElementById('e').textContent='Invalid credentials';}
});
</script></body></html>
"""

_HUB_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AIM Hub</title>
<style>
body{font-family:system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;}
h1{font-size:1.3rem;}
table{border-collapse:collapse;width:100%;margin:1rem 0;}
th,td{border-bottom:1px solid #eee;padding:.5rem;text-align:left;font-size:.9rem;}
button{padding:.4rem .9rem;background:#205493;color:white;border:0;
       border-radius:4px;cursor:pointer;}
button.alt{background:#666;}
button.danger{background:#a33;}
.tag{display:inline-block;padding:.1rem .4rem;border-radius:3px;background:#eef;
     font-size:.8rem;}
.toolbar{margin:1rem 0;display:flex;gap:.5rem;align-items:center;}
input{padding:.4rem;border:1px solid #ccc;border-radius:3px;}
</style></head><body>
<h1>AIM Hub  <span class="tag">{{USER}} · {{ROLE}}</span>
<button class="alt" onclick="logout()" style="float:right">Sign out</button></h1>

<h2>Users</h2>
<div class="toolbar" id="adm" style="display:none">
  <input id="nu" placeholder="username">
  <input id="np" type="password" placeholder="password (≥8)">
  <select id="nr"><option>user</option><option>admin</option></select>
  <button onclick="createUser()">+ Create user</button>
</div>
<table id="users"><thead><tr>
  <th>ID</th><th>Username</th><th>Role</th><th>Telegram</th><th>State</th>
  <th>Actions</th></tr></thead><tbody></tbody></table>

<h2>Active nodes</h2>
<table id="nodes"><thead><tr>
  <th>User</th><th>Node ID</th><th>Host</th><th>Version</th><th>Last seen</th>
  </tr></thead><tbody></tbody></table>

<h2>Recent audit</h2>
<table id="audit"><thead><tr>
  <th>Time</th><th>User</th><th>Action</th><th>Target</th><th>IP</th>
  </tr></thead><tbody></tbody></table>

<script>
const me = "{{USER}}", role = "{{ROLE}}";
if (role === "admin") document.getElementById('adm').style.display = 'flex';

async function api(path, opts={}){
  const r = await fetch(path, {credentials:'same-origin', ...opts});
  if (r.status === 401) {location.href='/'; return;}
  return r.json();
}
async function logout(){await fetch('/api/auth/logout',{method:'POST'}); location.href='/';}

async function refresh(){
  const u = await api('/api/users').catch(()=>({users:[]}));
  const tb = document.querySelector('#users tbody'); tb.innerHTML='';
  (u.users || []).forEach(x => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${x.id}</td><td>${x.username}</td><td>${x.role}</td>
      <td>${x.telegram_id || '—'}</td>
      <td>${x.disabled ? 'DISABLED' : 'active'}</td>
      <td>
        <button onclick="issueToken(${x.id})">issue token</button>
        <button onclick="linkCode(${x.id})">/link code</button>
        ${role === 'admin' ? `<button class="danger" onclick="disableUser(${x.id})">disable</button>` : ''}
      </td>`;
    tb.appendChild(tr);
  });

  const n = await api('/api/nodes').catch(()=>({nodes:[]}));
  const ntb = document.querySelector('#nodes tbody'); ntb.innerHTML='';
  (n.nodes || []).forEach(x => {
    ntb.innerHTML += `<tr><td>${x.username || x.user_id}</td><td>${x.node_id}</td>
      <td>${x.host || '—'}</td><td>${x.version || '—'}</td>
      <td>${x.last_seen}</td></tr>`;
  });

  const a = await api('/api/audit?n=50').catch(()=>({audit:[]}));
  const atb = document.querySelector('#audit tbody'); atb.innerHTML='';
  (a.audit || []).forEach(x => {
    atb.innerHTML += `<tr><td>${x.ts}</td><td>${x.user_id || '—'}</td>
      <td>${x.action}</td><td>${x.target || '—'}</td><td>${x.ip || '—'}</td></tr>`;
  });
}

async function createUser(){
  const username=document.getElementById('nu').value;
  const password=document.getElementById('np').value;
  const r=document.getElementById('nr').value;
  const res=await api('/api/users',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username,password,role:r})});
  if (res && res.ok){document.getElementById('nu').value='';
    document.getElementById('np').value=''; refresh();}
  else alert('failed: '+JSON.stringify(res));
}
async function issueToken(id){
  const res=await api(`/api/users/${id}/token`,{method:'POST'});
  if (res && res.token) prompt('Copy this token (one-time view):', res.token);
}
async function linkCode(id){
  const res=await api(`/api/users/${id}/link-code`,{method:'POST'});
  if (res && res.code) alert(`Send to Telegram bot:\\n  /link ${res.code}\\n(${res.ttl_min} min)`);
}
async function disableUser(id){
  if (!confirm('Disable user '+id+'?')) return;
  await api(`/api/users/${id}/disable`,{method:'POST'}); refresh();
}
refresh();
setInterval(refresh, 15000);
</script></body></html>
"""


# ── CLI entrypoint ──────────────────────────────────────────────────────────


def _main():
    import argparse
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.getenv("AIM_WEB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("AIM_WEB_PORT", "8080")))
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    log.info(f"AIM web starting in role={AIM_ROLE} on {args.host}:{args.port}")

    if AIM_ROLE == "node":
        # Validate the node identity at startup. Hub must be reachable on first
        # run; subsequent runs use the 24h cache.
        try:
            from agents import hub_client
            if hub_client.is_local_only():
                log.info("AIM_HUB_URL not set — running in local-only mode (single user)")
            else:
                u = hub_client.validate()
                if u is None:
                    log.error("Could not authenticate node against hub. "
                              "Check AIM_HUB_URL and AIM_USER_TOKEN in ~/.aim_env.")
                    raise SystemExit(2)
                log.info(f"Node authenticated as user '{u['username']}' (role={u['role']})")
        except SystemExit:
            raise
        except Exception as e:
            log.warning(f"hub_client unavailable: {e}")

    if args.metrics:
        try:
            from agents.metrics import start_metrics_server
            start_metrics_server()
        except ImportError:
            pass
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    _main()
