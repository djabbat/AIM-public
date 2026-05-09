"""agents/metrics.py — Prometheus metrics + health endpoint.

Exposes Prometheus counters/histograms/gauges over HTTP at $AIM_METRICS_PORT
(default 9090) and a `/healthz` JSON endpoint with live system state.

Start the server once at process startup:

    from agents.metrics import start_metrics_server, track_latency
    start_metrics_server()        # background thread, non-blocking

    @track_latency("graph_invoke")
    def run_agent(task): ...

Scrape with Prometheus:

    scrape_configs:
      - job_name: aim
        static_configs: [{ targets: ["localhost:9090"] }]
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

log = logging.getLogger("aim.metrics")

DEFAULT_PORT = int(os.getenv("AIM_METRICS_PORT", "9090"))
HEALTH_PORT = int(os.getenv("AIM_HEALTH_PORT", str(DEFAULT_PORT + 1)))

# ── Core counters/histograms ────────────────────────────────────────────────

REQUESTS = Counter(
    "aim_requests_total",
    "Total requests handled by AIM components",
    ["endpoint", "status"],
)
LATENCY = Histogram(
    "aim_latency_seconds",
    "Wall-clock latency",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# Memory / embedding-daemon
MEMORY_HITS    = Counter("aim_memory_hits_total",   "Semantic memory cache hits")
MEMORY_MISSES  = Counter("aim_memory_misses_total", "Semantic memory cache misses")
EMBED_LATENCY  = Histogram("aim_embed_latency_seconds", "Embedding daemon latency",
                           buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0))

# LLM provider metrics
LLM_TOKENS_IN   = Counter("aim_llm_tokens_in_total",  "LLM input tokens",  ["provider", "model"])
LLM_TOKENS_OUT  = Counter("aim_llm_tokens_out_total", "LLM output tokens", ["provider", "model"])
LLM_CACHE_RATIO = Gauge("aim_llm_cache_ratio", "DeepSeek prompt-cache hit ratio (%)", ["model"])
LLM_ERRORS      = Counter("aim_llm_errors_total", "LLM errors by provider/cause", ["provider", "cause"])

# Daemon health
DAEMON_HEALTH       = Gauge("aim_embed_daemon_health",       "Embed daemon: 1=ok 0=down")
DAEMON_CACHE_SIZE   = Gauge("aim_embed_cache_size",          "Embed daemon LRU cache size")
DAEMON_CACHE_RATIO  = Gauge("aim_embed_cache_ratio",         "Embed daemon LRU cache hit ratio (%)")

# Graph state
GRAPH_ITERATIONS    = Histogram("aim_graph_iterations", "Iterations per agent run",
                                buckets=(1, 2, 3, 4, 5, 10))
GRAPH_PLAN_SIZE     = Histogram("aim_graph_plan_size", "Planner step count",
                                buckets=(1, 2, 3, 4, 5, 7, 10))


# ── Health endpoint ─────────────────────────────────────────────────────────


def _build_health() -> dict[str, Any]:
    """Snapshot of live system state. Cheap to call; no LLM."""
    health: dict[str, Any] = {
        "status": "ok",
        "timestamp": time.time(),
        "components": {},
    }
    # Embed daemon
    try:
        from agents.embed_daemon import daemon_status
        st = daemon_status()
        health["components"]["embed_daemon"] = st
        DAEMON_HEALTH.set(1 if st.get("running") else 0)
    except Exception as e:
        health["components"]["embed_daemon"] = {"running": False, "reason": str(e)}
        DAEMON_HEALTH.set(0)

    # Memory index
    try:
        from agents.memory_index import status as mem_status
        health["components"]["memory_index"] = mem_status()
    except Exception as e:
        health["components"]["memory_index"] = {"error": str(e)}

    # Decide overall
    if not health["components"].get("embed_daemon", {}).get("running"):
        health["status"] = "degraded"
    return health


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # silence
        return

    def do_GET(self):
        if self.path in ("/healthz", "/health"):
            body = json.dumps(_build_health(), default=str, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/metrics",):
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


_started = False


def start_metrics_server(port: int = DEFAULT_PORT, health_port: int = HEALTH_PORT) -> None:
    """Start Prometheus + health endpoint on background threads (idempotent)."""
    global _started
    if _started:
        return
    try:
        start_http_server(port)
        log.info(f"prometheus metrics on :{port}/metrics")
    except OSError as e:
        log.warning(f"metrics server failed to bind :{port}: {e}")
        return

    def _serve_health():
        srv = HTTPServer(("127.0.0.1", health_port), _HealthHandler)
        log.info(f"health endpoint on :{health_port}/healthz")
        try:
            srv.serve_forever()
        except Exception:
            pass

    threading.Thread(target=_serve_health, daemon=True).start()
    _started = True


# ── Decorator ───────────────────────────────────────────────────────────────


def track_latency(endpoint: str) -> Callable:
    """Wrap a function to record REQUESTS + LATENCY under `endpoint`."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                result = func(*args, **kwargs)
                REQUESTS.labels(endpoint=endpoint, status="success").inc()
                return result
            except Exception:
                REQUESTS.labels(endpoint=endpoint, status="error").inc()
                raise
            finally:
                LATENCY.labels(endpoint=endpoint).observe(time.time() - t0)

        return wrapper

    return decorator


# ── CLI helper ──────────────────────────────────────────────────────────────


def _main():
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--health-port", type=int, default=HEALTH_PORT)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    start_metrics_server(args.port, args.health_port)
    print(f"metrics: http://localhost:{args.port}/metrics")
    print(f"health:  http://localhost:{args.health_port}/healthz")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    _main()
