"""agents/tracing.py — OpenTelemetry distributed tracing for AIM.

Opt-in via AIM_TRACING=1. Default endpoint http://localhost:4317 (Jaeger or
Tempo via OTLP/gRPC). Falls back to a no-op tracer if the OpenTelemetry SDK
is not installed.

Wire-in:
    from agents.tracing import init_tracing, span, traced
    init_tracing()                    # idempotent, safe to call many times

    @traced("graph_invoke")           # decorator
    def run_agent(task): ...

    with span("planner", task=task):  # context manager
        ...

Quick start (Jaeger):
    docker run -d --name jaeger \\
      -p 16686:16686 -p 4317:4317 \\
      jaegertracing/all-in-one:latest
    export AIM_TRACING=1
    aim-graph "задача"
    # Jaeger UI: http://localhost:16686
"""

from __future__ import annotations

import contextlib
import logging
import os
from functools import wraps
from typing import Any, Callable, Optional

log = logging.getLogger("aim.tracing")

ENABLED = os.getenv("AIM_TRACING", "").lower() in ("1", "true", "yes")
ENDPOINT = os.getenv("AIM_TRACING_ENDPOINT", "http://localhost:4317")
SERVICE  = os.getenv("AIM_TRACING_SERVICE", "aim")

_tracer: Any = None
_initialized: bool = False


def _otel_available() -> bool:
    try:
        import opentelemetry  # noqa: F401
        return True
    except ImportError:
        return False


def init_tracing(service_name: str = SERVICE, endpoint: str = ENDPOINT) -> Any:
    """Initialise the global tracer once. Returns the tracer (or None)."""
    global _tracer, _initialized
    if _initialized:
        return _tracer
    _initialized = True

    if not ENABLED:
        log.debug("tracing disabled (set AIM_TRACING=1 to enable)")
        return None
    if not _otel_available():
        log.warning("AIM_TRACING=1 but opentelemetry-sdk not installed; "
                    "pip install opentelemetry-sdk opentelemetry-exporter-otlp "
                    "opentelemetry-instrumentation-httpx opentelemetry-instrumentation-sqlite3")
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument optional libraries
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass
        try:
            from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
            SQLite3Instrumentor().instrument()
        except Exception:
            pass
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            from web.api import app as _web_app
            FastAPIInstrumentor.instrument_app(_web_app)
        except Exception:
            pass

        _tracer = trace.get_tracer(service_name)
        log.info(f"OTel tracing initialised → {endpoint} (service={service_name})")
        return _tracer
    except Exception as e:
        log.warning(f"tracing init failed: {e}")
        return None


def get_tracer():
    if not _initialized:
        init_tracing()
    return _tracer


@contextlib.contextmanager
def span(name: str, **attributes):
    """Context manager — no-op if tracing disabled."""
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as sp:
        try:
            for k, v in attributes.items():
                if v is None:
                    continue
                if isinstance(v, (str, int, float, bool)):
                    sp.set_attribute(k, v)
                else:
                    sp.set_attribute(k, str(v)[:200])
        except Exception:
            pass
        try:
            yield sp
        except Exception as e:
            try:
                sp.record_exception(e)
                from opentelemetry.trace import StatusCode, Status
                sp.set_status(Status(StatusCode.ERROR, str(e)[:200]))
            except Exception:
                pass
            raise


def traced(name: Optional[str] = None) -> Callable:
    """Decorator: wrap function in a span. Span name defaults to fn.__qualname__."""
    def decorator(fn: Callable) -> Callable:
        sname = name or fn.__qualname__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with span(sname):
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def _main():
    """`python -m agents.tracing test` — emit a test span."""
    import argparse, time
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("test")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    init_tracing()

    if args.cmd == "status":
        print(f"enabled:  {ENABLED}")
        print(f"endpoint: {ENDPOINT}")
        print(f"service:  {SERVICE}")
        print(f"otel sdk: {'yes' if _otel_available() else 'no'}")
        print(f"tracer:   {'active' if _tracer else 'no-op'}")
    elif args.cmd == "test":
        with span("test_span", note="hello"):
            time.sleep(0.05)
            with span("nested"):
                time.sleep(0.05)
        print("emitted; flush in ~5s; check Jaeger UI")
        time.sleep(6)


if __name__ == "__main__":
    _main()
