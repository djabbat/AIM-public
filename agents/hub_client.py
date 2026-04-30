"""agents/hub_client.py — node-side glue to the AIM Hub.

A "node" is a per-user local AIM install (Linux/macOS/Windows). It runs the
full stack locally — own SQLite, own DeepSeek/Groq keys, own Patients/.
The only thing it asks the hub:

    1. "Is this AIM_USER_TOKEN valid?  Whose is it?"  (on startup, then 24h cache)
    2. "Heartbeat: I am node <id> for user <X> at <host>"  (best-effort, optional)

LLM calls NEVER go through the hub. Patients NEVER go to the hub.

Env vars (from ~/.aim_env, cross-platform):
    AIM_HUB_URL        e.g. https://hub.longevity.ge   (omit → local-only mode)
    AIM_USER_TOKEN     long-lived opaque token issued by hub admin
    AIM_NODE_ID        optional stable id; default: hostname-username
    AIM_OFFLINE_GRACE  hours the cached identity stays valid offline (default 168 = 7d)

Public API:
    current_user()                 → dict | None       (cached, fast)
    validate(force=False)          → dict | None       (round-trip if needed)
    require_user()                 → dict              (raises SystemExit if missing)
    heartbeat()                    → bool              (best-effort)
    is_local_only()                → bool              (no hub configured)
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.hub_client")

NODE_VERSION = "7.0"

# ── Cross-platform cache dir ────────────────────────────────────────────────


def _cache_dir() -> Path:
    """User cache dir: ~/.cache/aim (Linux), ~/Library/Caches/aim (mac),
    %LOCALAPPDATA%\\aim\\Cache (Windows). No external dep."""
    sysname = platform.system()
    if sysname == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA",
                                   Path.home() / "AppData" / "Local"))
        d = base / "aim" / "Cache"
    elif sysname == "Darwin":
        d = Path.home() / "Library" / "Caches" / "aim"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME",
                                str(Path.home() / ".cache"))) / "aim"
    d.mkdir(parents=True, exist_ok=True)
    return d


_CACHE_FILE = _cache_dir() / "hub_identity.json"


# ── Env ─────────────────────────────────────────────────────────────────────


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def is_local_only() -> bool:
    return not _env("AIM_HUB_URL")


def _node_id() -> str:
    nid = _env("AIM_NODE_ID")
    if nid:
        return nid
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "anon"
    return f"{host}-{user}"


# ── Cache ───────────────────────────────────────────────────────────────────


def _read_cache() -> dict | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(payload: dict) -> None:
    payload = dict(payload)
    payload["cached_at"] = int(time.time())
    try:
        _CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(_CACHE_FILE, 0o600)
        except OSError:
            pass  # Windows
    except Exception as e:
        log.warning(f"could not write hub cache: {e}")


def _cache_fresh(cache: dict, max_age_h: float) -> bool:
    age = time.time() - cache.get("cached_at", 0)
    return age < max_age_h * 3600


def clear_cache() -> None:
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()


# ── HTTP (no extra deps; urllib only) ───────────────────────────────────────


def _hub_post(path: str, body: dict, timeout: float = 5.0) -> dict | None:
    import urllib.request
    import urllib.error
    url = _env("AIM_HUB_URL").rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": f"aim-node/{NODE_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 300:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning(f"hub unreachable ({path}): {e}")
        return None
    except Exception as e:
        log.warning(f"hub call failed ({path}): {e}")
        return None


# ── Public ──────────────────────────────────────────────────────────────────


def validate(force: bool = False) -> dict | None:
    """Round-trip to the hub if cache is missing or `force=True`.

    Returns user dict on success, None if hub configured but token invalid,
    None if no token. In offline scenarios with a recent cache, returns the
    cached user dict.
    """
    if is_local_only():
        return None

    token = _env("AIM_USER_TOKEN")
    if not token:
        log.error("AIM_USER_TOKEN not set in ~/.aim_env")
        return None

    grace_h = float(_env("AIM_OFFLINE_GRACE") or "168")

    cache = _read_cache()
    if cache and not force and _cache_fresh(cache, max_age_h=24) and cache.get("token") == token:
        return cache.get("user")

    resp = _hub_post("/api/auth/validate-token", {"token": token,
                                                   "node_id": _node_id(),
                                                   "host": socket.gethostname(),
                                                   "version": NODE_VERSION})
    if resp and resp.get("ok") and resp.get("user"):
        _write_cache({"token": token, "user": resp["user"]})
        return resp["user"]

    # Hub said NO → wipe cache, refuse.
    if resp is not None and resp.get("ok") is False:
        log.error("hub rejected AIM_USER_TOKEN")
        clear_cache()
        return None

    # Hub unreachable → fall back to cache within grace window.
    if cache and cache.get("token") == token and _cache_fresh(cache, max_age_h=grace_h):
        log.warning("hub unreachable; using cached identity (offline mode)")
        return cache.get("user")

    return None


def current_user() -> dict | None:
    """Cheap path: returns cached user if fresh, otherwise validates."""
    if is_local_only():
        return None
    cache = _read_cache()
    if cache and _cache_fresh(cache, max_age_h=24):
        return cache.get("user")
    return validate()


def require_user() -> dict:
    """For CLI/GUI/Telegram entry points. Exits on failure."""
    if is_local_only():
        # local-only is allowed — return synthetic local user
        return {"id": 0, "username": "local", "role": "user", "local_only": True}
    u = validate()
    if u is None:
        import sys
        sys.exit(
            "AIM: cannot authenticate this node.\n"
            "  Set AIM_HUB_URL and AIM_USER_TOKEN in ~/.aim_env\n"
            "  (on Windows: %USERPROFILE%\\.aim_env)\n"
            "  Get a token from your hub admin via:\n"
            "    python -m scripts.user_admin token <username>\n"
        )
    return u


def heartbeat() -> bool:
    """Best-effort heartbeat to the hub. Never blocks AIM operation."""
    if is_local_only():
        return False
    token = _env("AIM_USER_TOKEN")
    if not token:
        return False
    resp = _hub_post("/api/nodes/heartbeat",
                     {"token": token, "node_id": _node_id(),
                      "host": socket.gethostname(),
                      "version": NODE_VERSION},
                     timeout=3.0)
    return bool(resp and resp.get("ok"))
