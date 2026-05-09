"""queen_app.py — FastAPI wrapper around AI/ai/hive_queen.

Exposes the queen-side primitives over HTTPS for worker bees.

Endpoints:
    GET  /healthz                 — health check (no auth)
    POST /v1/hive/contribute      — worker submits anonymized signal
    GET  /v1/hive/updates         — worker pulls eval-gated updates
    POST /v1/hive/distill         — admin trigger: scan + publish (auth)
    GET  /v1/hive/status          — queen state summary (auth)

Auth model: bearer token. Workers authenticate with their existing
AIM_USER_TOKEN (validated via agents.auth, same flow as hub_client).
Admin endpoints require AIM_HIVE_ADMIN_TOKEN env var.

Deploy:
    pip install fastapi uvicorn
    AIM_HIVE_QUEEN_DB=/home/jaba/hive_queen/hive_queen.db \
    AIM_HIVE_ADMIN_TOKEN=<random> \
    uvicorn queen_app:app --host 127.0.0.1 --port 8080

Or via systemd unit (config/aim-hive-queen.service).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Make sibling AI.ai.* importable when running from queen_deploy/.
# queen_deploy is at AIM/AI/queen_deploy → up 2 levels gets us to AIM/.
_HERE = Path(__file__).resolve().parent
_AIM_ROOT = _HERE.parent.parent            # → AIM/
if str(_AIM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AIM_ROOT))

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from AI.ai.hive_queen import (
    accept_contribution,
    distill_candidates,
    list_contributions,
    list_updates,
    publish_update,
)

log = logging.getLogger("queen_app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


app = FastAPI(
    title="AIM Hive Queen",
    description="Federated AIM bee-and-queen aggregator",
    version="1.0",
)


# ── auth helpers ────────────────────────────────────────────────


def _validate_worker_token(token: Optional[str]) -> str:
    """Validate worker token via agents.auth. Returns username (worker
    identity) or raises HTTPException(401). If AIM_HIVE_REQUIRE_AUTH=0
    (transition mode), accept any (or no) token as anonymous."""
    if os.environ.get('AIM_HIVE_REQUIRE_AUTH') == '0':
        return 'anonymous'
    if not token:
        raise HTTPException(status_code=401,
                             detail="missing bearer token")
    if not token.startswith("Bearer "):
        raise HTTPException(status_code=401,
                             detail="invalid Authorization header format")
    raw = token[len("Bearer "):].strip()
    try:
        from agents.auth import validate_token
        info = validate_token(raw)
    except Exception as e:
        log.warning("auth backend unavailable: %s", e)
        # Fail open in framework mode? No — fail closed for safety.
        raise HTTPException(status_code=503,
                             detail="auth backend unavailable")
    if not info or not info.get("valid"):
        raise HTTPException(status_code=401, detail="invalid token")
    return info.get("username", "unknown")


def _validate_admin_token(token: Optional[str]) -> None:
    expected = os.environ.get("AIM_HIVE_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503,
                             detail="admin token not configured")
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401,
                             detail="missing admin token")
    if token[len("Bearer "):].strip() != expected:
        raise HTTPException(status_code=403,
                             detail="bad admin token")


# ── public endpoints ────────────────────────────────────────────


@app.get("/healthz")
def healthz():
    return {"status": "ok", "ts": dt.datetime.now().isoformat(timespec="seconds")}


@app.post("/v1/hive/contribute")
async def contribute(request: Request,
                      authorization: Optional[str] = Header(None)):
    user = _validate_worker_token(authorization)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be JSON object")
    contrib_id = accept_contribution(payload)
    if contrib_id is None:
        raise HTTPException(status_code=400, detail="payload rejected")
    log.info("accepted contribution %s from worker user=%s wid=%s",
             contrib_id, user, payload.get("worker_id"))
    return {"contribution_id": contrib_id}


@app.get("/v1/hive/updates")
def get_updates(since: Optional[str] = None,
                 authorization: Optional[str] = Header(None)):
    _validate_worker_token(authorization)
    rows = list_updates(since=since)
    return {
        "updates": [
            {
                "id": u.id, "ts": u.ts, "kind": u.kind,
                "body": u.body, "source_n": u.source_n,
                "eval_delta": u.eval_delta, "signature": u.signature,
            }
            for u in rows
        ]
    }


# ── admin endpoints ─────────────────────────────────────────────


@app.post("/v1/hive/distill")
def admin_distill(authorization: Optional[str] = Header(None)):
    _validate_admin_token(authorization)
    cands = distill_candidates()
    published = []
    for c in cands:
        # Conservative auto-publish policy: only publish if we have ≥3
        # workers' supporting evidence. Lower bar = manual review.
        if c.source_n >= 3:
            upd = publish_update(c, eval_pass=True, eval_delta=None)
            if upd:
                published.append({
                    "id": upd.id, "kind": upd.kind, "source_n": upd.source_n,
                })
    return {
        "candidates_found": len(cands),
        "auto_published": len(published),
        "details": published,
    }


@app.get("/v1/hive/status")
def admin_status(authorization: Optional[str] = Header(None)):
    """Status endpoint — shape matches Rust `aim-hive-queen::summary()`
    (P1.6 audit 2026-05-07: queen_summary was a markdown string, Rust
    returns an object. Aligned to Rust shape; old string form
    deprecated)."""
    _validate_admin_token(authorization)
    contribs = list_contributions(limit=100000)
    updates = list_updates()
    cands = distill_candidates()
    queen_summary_obj = {
        "n_contributions": len(contribs),
        "n_updates": len(updates),
        "candidates_pending": len(cands),
        "candidate_kinds": [c.kind for c in cands],
    }
    return {
        "queen_summary": queen_summary_obj,
        "n_contributions": len(contribs),
        "n_updates": len(updates),
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
    }


# ── error handler ───────────────────────────────────────────────
# All errors emit {"error": "...", "status": N} for parity with the
# Rust queen. P1.6 (2026-05-07 audit): added validation + generic
# handlers so request-body parse failures (default {"detail":...}) and
# uncaught exceptions also follow the canonical shape.


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": exc.status_code},
    )


try:
    from fastapi.exceptions import RequestValidationError
except ImportError:  # pragma: no cover — old FastAPI fallback
    RequestValidationError = None  # type: ignore[assignment]


if RequestValidationError is not None:

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        # Take the first error's message; full detail kept under "errors".
        first = ""
        try:
            errs = exc.errors()
            if errs:
                first = errs[0].get("msg", "validation error")
        except Exception:
            first = "validation error"
        return JSONResponse(
            status_code=422,
            content={
                "error": first or "validation error",
                "status": 422,
                "errors": exc.errors() if hasattr(exc, "errors") else [],
            },
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    log.exception("unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"error": f"{type(exc).__name__}: {exc}", "status": 500},
    )


# ── static landing page (/, /style.css, /favicon.ico) ──────────


_WEB_DIR = _HERE / "web"
if _WEB_DIR.exists():
    # Serve everything else under web/ as static. Mounted LAST so
    # API routes win.
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True),
               name="landing")
