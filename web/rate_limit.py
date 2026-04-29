"""web/rate_limit.py — per-IP rate limit middleware for FastAPI.

Sliding-window token bucket per client IP. Two tiers:
    • global (default 60 req/min)        — applied to every route
    • webhook (default 10 req/min)       — applied to /webhook/*

Configurable via env:
    AIM_API_RATE_LIMIT=60              # global
    AIM_API_RATE_WEBHOOK=10            # webhooks
    AIM_API_RATE_BURST=20              # burst tolerance (per IP)
    AIM_API_RATE_TRUST_PROXY=0         # 1 → use X-Forwarded-For

Whitelist via env (comma-separated CIDR or exact IPs):
    AIM_API_RATE_WHITELIST=127.0.0.1,::1
"""

from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Callable

log = logging.getLogger("aim.rate_limit")

GLOBAL_RPM   = int(os.getenv("AIM_API_RATE_LIMIT",   "60"))
WEBHOOK_RPM  = int(os.getenv("AIM_API_RATE_WEBHOOK", "10"))
BURST        = int(os.getenv("AIM_API_RATE_BURST",   "20"))
TRUST_PROXY  = os.getenv("AIM_API_RATE_TRUST_PROXY", "0").lower() in ("1", "true", "yes")
WHITELIST    = {x.strip() for x in os.getenv("AIM_API_RATE_WHITELIST", "127.0.0.1,::1").split(",") if x.strip()}


# ── per-IP buckets ─────────────────────────────────────────────────────────


_buckets:    dict[str, deque[float]]  = defaultdict(lambda: deque(maxlen=BURST * 4))
_lock:       threading.Lock           = threading.Lock()
_blocked_total = 0


def _client_ip(request) -> str:
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _is_whitelisted(ip: str) -> bool:
    if ip in WHITELIST:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in WHITELIST:
        try:
            if "/" in entry and addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _check(ip: str, rpm: int) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    if rpm <= 0 or _is_whitelisted(ip):
        return True, 0
    now = time.time()
    cutoff = now - 60.0
    with _lock:
        bucket = _buckets[ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= rpm:
            global _blocked_total
            _blocked_total += 1
            retry = max(1, int(bucket[0] + 60 - now))
            return False, retry
        bucket.append(now)
    return True, 0


# ── FastAPI middleware ──────────────────────────────────────────────────────


async def rate_limit_middleware(request, call_next: Callable):
    """Plug into FastAPI: app.middleware("http")(rate_limit_middleware)"""
    from fastapi.responses import JSONResponse

    path = request.url.path
    ip   = _client_ip(request)

    # tighter quota for webhooks
    rpm = WEBHOOK_RPM if path.startswith("/webhook/") else GLOBAL_RPM

    ok, retry = _check(ip, rpm)
    if not ok:
        return JSONResponse(
            {"error": "rate limit exceeded", "retry_after_s": retry,
             "limit_rpm": rpm, "endpoint": path},
            status_code=429,
            headers={"Retry-After": str(retry),
                     "X-RateLimit-Limit": str(rpm)},
        )

    response = await call_next(request)
    # surface remaining quota
    remaining = max(0, rpm - len(_buckets.get(ip, [])))
    response.headers["X-RateLimit-Limit"] = str(rpm)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


def stats() -> dict:
    with _lock:
        return {
            "global_rpm":   GLOBAL_RPM,
            "webhook_rpm":  WEBHOOK_RPM,
            "burst":        BURST,
            "trust_proxy":  TRUST_PROXY,
            "whitelist":    sorted(WHITELIST),
            "tracked_ips":  len(_buckets),
            "total_blocked": _blocked_total,
        }
