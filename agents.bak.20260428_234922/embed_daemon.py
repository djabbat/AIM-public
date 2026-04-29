"""
agents/embed_daemon.py — Unix-socket embedding service.

Loads sentence-transformers/all-MiniLM-L6-v2 ONCE at startup; clients connect
to a UDS at ~/.claude/embed.sock and exchange JSON messages:

    request:  {"texts": ["...", "..."]}
    response: {"vectors": [[...], [...]]}    # 384-dim each

Saves ~3-4 seconds per CLI invocation by avoiding model reload.

Run as foreground service:
    aim-embed-daemon start          # foregrounds, prints to stdout
    aim-embed-daemon start --bg     # backgrounds via setsid+nohup
    aim-embed-daemon stop
    aim-embed-daemon status
    aim-embed-daemon ping           # health check
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("aim.embed_daemon")

SOCK_PATH = Path.home() / ".claude" / "embed.sock"
PID_PATH = Path.home() / ".claude" / "embed.pid"
LOG_PATH = Path.home() / ".claude" / "embed.log"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _setup_rotating_logging():
    """Attach a 10MB-rotated handler to the daemon logger (5 backups)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("aim.embed_daemon")
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    handler = RotatingFileHandler(
        str(LOG_PATH), maxBytes=10 * 1024 * 1024, backupCount=5
    )
    handler.setFormatter(
        logging.Formatter("[%(name)s %(asctime)s] %(levelname)s %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


import hashlib
from collections import OrderedDict


class _State:
    model = None
    last_used = time.time()
    cache: "OrderedDict[str, list]" = OrderedDict()
    cache_max = int(os.getenv("AIM_EMBED_CACHE_MAX", "512"))
    cache_hits = 0
    cache_misses = 0


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _cache_get(text: str):
    key = _cache_key(text)
    if key in _State.cache:
        _State.cache.move_to_end(key)
        _State.cache_hits += 1
        return _State.cache[key]
    _State.cache_misses += 1
    return None


def _cache_put(text: str, vec):
    key = _cache_key(text)
    _State.cache[key] = vec
    _State.cache.move_to_end(key)
    if len(_State.cache) > _State.cache_max:
        _State.cache.popitem(last=False)


def _load_model_once():
    if _State.model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"loading {EMBED_MODEL}…")
        t0 = time.time()
        _State.model = SentenceTransformer(EMBED_MODEL)
        log.info(f"model ready in {time.time() - t0:.1f}s")
    _State.last_used = time.time()
    return _State.model


def _handle_request(payload: dict) -> dict:
    if "ping" in payload:
        total = _State.cache_hits + _State.cache_misses
        ratio = (_State.cache_hits / total * 100) if total else 0.0
        return {
            "ok": True, "pong": True, "model": EMBED_MODEL,
            "uptime_s": time.time() - _State.last_used,
            "cache_size": len(_State.cache),
            "cache_hits": _State.cache_hits,
            "cache_misses": _State.cache_misses,
            "cache_ratio": round(ratio, 1),
        }
    if "stats" in payload:
        total = _State.cache_hits + _State.cache_misses
        ratio = (_State.cache_hits / total * 100) if total else 0.0
        return {
            "ok": True, "cache_size": len(_State.cache),
            "cache_hits": _State.cache_hits,
            "cache_misses": _State.cache_misses,
            "cache_ratio": round(ratio, 1),
        }
    texts = payload.get("texts")
    if not texts or not isinstance(texts, list):
        return {"ok": False, "error": "missing 'texts' (list of strings)"}

    # Check cache first; only encode the misses
    out = [None] * len(texts)
    miss_idx, miss_texts = [], []
    for i, t in enumerate(texts):
        v = _cache_get(t)
        if v is not None:
            out[i] = v
        else:
            miss_idx.append(i)
            miss_texts.append(t)
    if miss_texts:
        model = _load_model_once()
        vecs = model.encode(miss_texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True)
        for i, t, v in zip(miss_idx, miss_texts, vecs):
            vec_list = v.tolist()
            _cache_put(t, vec_list)
            out[i] = vec_list
    _State.last_used = time.time()
    return {"ok": True, "vectors": out}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        # Wire format: 4-byte big-endian length prefix + JSON body
        try:
            head = self.rfile.read(4)
            if len(head) < 4:
                return
            n = int.from_bytes(head, "big")
            body = b""
            while len(body) < n:
                chunk = self.rfile.read(n - len(body))
                if not chunk:
                    break
                body += chunk
            payload = json.loads(body.decode("utf-8"))
            response = _handle_request(payload)
        except Exception as e:
            log.exception("handler error")
            response = {"ok": False, "error": str(e)}
        out = json.dumps(response).encode("utf-8")
        self.wfile.write(len(out).to_bytes(4, "big"))
        self.wfile.write(out)


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _run_server():
    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    server = _UnixServer(str(SOCK_PATH), _Handler)
    os.chmod(SOCK_PATH, 0o600)

    PID_PATH.write_text(str(os.getpid()))

    def _graceful(*_):
        log.info("shutdown signal received")
        try:
            server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)

    # Pre-warm the model so the first request is fast
    threading.Thread(target=_load_model_once, daemon=True).start()

    log.info(f"listening on {SOCK_PATH}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()
        if PID_PATH.exists():
            PID_PATH.unlink()
        log.info("stopped cleanly")


# ─── Client helper (used by memory_index.py) ──────────────────────────────


def encode_via_daemon(texts: list[str], timeout_s: float = 10.0) -> list[list[float]] | None:
    """Try to encode via daemon. Returns None if daemon is unavailable."""
    if not SOCK_PATH.exists():
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout_s)
        s.connect(str(SOCK_PATH))
        body = json.dumps({"texts": texts}).encode("utf-8")
        s.sendall(len(body).to_bytes(4, "big"))
        s.sendall(body)
        head = s.recv(4)
        if len(head) < 4:
            return None
        n = int.from_bytes(head, "big")
        chunks = []
        while sum(len(c) for c in chunks) < n:
            chunk = s.recv(min(65536, n - sum(len(c) for c in chunks)))
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
        resp = json.loads(b"".join(chunks).decode("utf-8"))
        if resp.get("ok") and "vectors" in resp:
            return resp["vectors"]
    except Exception as e:
        log.debug(f"daemon call failed: {e}")
    return None


def daemon_status() -> dict:
    if not SOCK_PATH.exists():
        return {"running": False, "reason": "socket missing"}
    pid = None
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
        except Exception:
            pass
    if pid is None:
        return {"running": False, "reason": "pid file missing"}
    try:
        os.kill(pid, 0)
    except Exception:
        return {"running": False, "reason": f"pid {pid} not alive"}
    # ping it
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(str(SOCK_PATH))
        body = json.dumps({"ping": True}).encode("utf-8")
        s.sendall(len(body).to_bytes(4, "big"))
        s.sendall(body)
        head = s.recv(4)
        n = int.from_bytes(head, "big")
        resp = json.loads(s.recv(n).decode("utf-8"))
        s.close()
        return {"running": True, "pid": pid, "model": resp.get("model"), "responded": True}
    except Exception as e:
        return {"running": False, "pid": pid, "reason": f"socket exists but ping failed: {e}"}


def stop_daemon() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        # wait briefly
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except Exception:
                break
        return True
    except Exception:
        return False


def _main():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--bg", action="store_true", help="Detach and run in background")
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("ping")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s %(asctime)s] %(message)s", datefmt="%H:%M:%S")
    _setup_rotating_logging()

    if args.cmd == "start":
        if daemon_status().get("running"):
            print("[start] already running; use 'stop' first")
            return
        if args.bg:
            # double-fork
            if os.fork() != 0:
                print(f"[start] backgrounded; pid file at {PID_PATH}")
                return
            os.setsid()
            if os.fork() != 0:
                os._exit(0)
            sys.stdout = open("/dev/null", "w")
            sys.stderr = open(str(Path.home() / ".claude" / "embed.log"), "a", buffering=1)
            sys.stdin = open("/dev/null", "r")
        _run_server()
    elif args.cmd == "stop":
        if stop_daemon():
            print("[stop] daemon stopped")
        else:
            print("[stop] no running daemon")
    elif args.cmd == "status":
        for k, v in daemon_status().items():
            print(f"  {k}: {v}")
    elif args.cmd == "ping":
        info = daemon_status()
        if info.get("running"):
            print(f"OK pid={info['pid']} model={info.get('model','?')}")
        else:
            print(f"NO ({info.get('reason')})")
            sys.exit(1)


if __name__ == "__main__":
    _main()
