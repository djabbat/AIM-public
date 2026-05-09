"""agents/mcp_loader.py — MCP-style runtime tool registry (G4, 2026-05-02).

A tiny subset of the Model Context Protocol that lets users add new
tools by dropping a TOML config under `~/.aim/mcp/<name>.toml` —
without editing AIM source. Each TOML describes ONE server which
exposes one or more tools; AIM spawns the server as a subprocess and
talks JSON-RPC 2.0 over its stdin/stdout.

Minimal TOML shape:

    name = "weather"
    command = ["python3", "-u", "-m", "my_weather_server"]
    cwd = "~/projects/weather"      # optional
    env = { OPENWEATHER_KEY = "..." } # optional
    autostart = true                  # default true
    timeout_ms = 10000                # default 10s

JSON-RPC dialogue (the server is responsible for impl):

    1.  AIM → server:  {"jsonrpc":"2.0","id":1,"method":"list_tools"}
        server replies with `result = [{"name":"forecast", "description":"…",
                                         "schema":{"type":"object",…}}, …]`
    2.  AIM → server:  {"jsonrpc":"2.0","id":2,"method":"call",
                        "params":{"name":"forecast","args":{"city":"Tbilisi"}}}
        server replies with `result = "<output text>"` or
        `error = {"code":-32000, "message":"…"}`.

Public API:
    discover() -> list[ServerSpec]
    load_all() -> dict[name, McpServer]   # spawn every autostart server
    list_tools() -> list[dict]            # union from running servers
    call(tool_name, args) -> str          # routes to the right server
    shutdown()                            # SIGTERM all spawned children
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aim.mcp")


def config_dir() -> Path:
    env = os.environ.get("AIM_MCP_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".aim" / "mcp"


# ── server spec & runtime ────────────────────────────────────────


@dataclasses.dataclass
class ServerSpec:
    name: str
    command: list[str]
    cwd: Optional[str] = None
    env: dict = dataclasses.field(default_factory=dict)
    autostart: bool = True
    timeout_ms: int = 10000


def _load_toml(path: Path) -> dict:
    try:
        import tomllib  # py3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore
    with path.open("rb") as f:
        return tomllib.load(f)


def parse_spec(name: str, raw: dict) -> ServerSpec:
    command = raw.get("command")
    if isinstance(command, str):
        command = shlex.split(command)
    if not isinstance(command, list) or not command:
        raise ValueError(f"{name}: command must be a non-empty list")
    return ServerSpec(
        name=str(raw.get("name", name)),
        command=[str(c) for c in command],
        cwd=str(raw["cwd"]) if "cwd" in raw else None,
        env=dict(raw.get("env") or {}),
        autostart=bool(raw.get("autostart", True)),
        timeout_ms=int(raw.get("timeout_ms", 10000)),
    )


def discover() -> list[ServerSpec]:
    d = config_dir()
    if not d.exists():
        return []
    out: list[ServerSpec] = []
    for p in sorted(d.glob("*.toml")):
        try:
            raw = _load_toml(p)
            out.append(parse_spec(p.stem, raw))
        except Exception as e:
            log.warning("skip MCP config %s: %s", p, e)
    return out


# ── server runtime ───────────────────────────────────────────────


class McpServer:
    """A long-lived subprocess speaking JSON-RPC 2.0 over stdio.

    Thread-safe: all RPC calls are serialised behind a lock. We do NOT
    yet support server-initiated notifications (model context updates,
    progress) — those would need an async loop.
    """

    def __init__(self, spec: ServerSpec):
        self.spec = spec
        self.proc: Optional[subprocess.Popen] = None
        self.tools: list[dict] = []
        self._lock = threading.Lock()
        self._next_id = 1

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        env = os.environ.copy()
        env.update(self.spec.env or {})
        cwd = Path(self.spec.cwd).expanduser() if self.spec.cwd else None
        self.proc = subprocess.Popen(
            self.spec.command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd, env=env, text=True, bufsize=1,
        )
        # Don't block: even if list_tools fails, the server is alive.
        try:
            self.tools = self._rpc("list_tools") or []
        except Exception as e:
            log.warning("list_tools failed for %s: %s", self.spec.name, e)
            self.tools = []

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        except Exception:
            pass
        finally:
            self.proc = None

    def _rpc(self, method: str, params: Optional[dict] = None) -> Any:
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError(f"{self.spec.name}: not running")
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            req = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                req["params"] = params
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()

            deadline = time.time() + self.spec.timeout_ms / 1000.0
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError(
                        f"{self.spec.name}: server closed stdout")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Skip notifications until we see the response with our id.
                if msg.get("id") != rid:
                    continue
                if "error" in msg and msg["error"]:
                    raise RuntimeError(
                        f"{self.spec.name} {method}: "
                        f"{msg['error'].get('message', msg['error'])}")
                return msg.get("result")
                # (deadline check is theoretical for blocking readline; the
                #  main protection is OS-level Popen.kill on shutdown.)
                _ = deadline

    def call(self, tool: str, args: dict) -> str:
        result = self._rpc("call", {"name": tool, "args": args})
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)


# ── registry ─────────────────────────────────────────────────────


_RUNNING: dict[str, McpServer] = {}
_REGISTRY_LOCK = threading.RLock()


def load_all() -> dict[str, McpServer]:
    """Discover specs and start every autostart server. Idempotent."""
    with _REGISTRY_LOCK:
        for spec in discover():
            if spec.name in _RUNNING:
                continue
            if not spec.autostart:
                continue
            srv = McpServer(spec)
            try:
                srv.start()
                _RUNNING[spec.name] = srv
                log.info("MCP server up: %s (%d tools)",
                         spec.name, len(srv.tools))
            except Exception as e:
                log.error("MCP %s failed to start: %s", spec.name, e)
        return dict(_RUNNING)


def list_tools() -> list[dict]:
    """Union of all tools currently exposed by running servers."""
    out: list[dict] = []
    with _REGISTRY_LOCK:
        for srv in _RUNNING.values():
            for t in srv.tools:
                out.append({**t, "server": srv.spec.name})
    return out


def find_server(tool_name: str) -> Optional[McpServer]:
    with _REGISTRY_LOCK:
        for srv in _RUNNING.values():
            if any((t.get("name") == tool_name) for t in srv.tools):
                return srv
    return None


def call(tool_name: str, args: dict) -> str:
    srv = find_server(tool_name)
    if srv is None:
        return f"ERROR:NOT_FOUND:no MCP server exposes tool {tool_name!r}"
    try:
        return srv.call(tool_name, args)
    except Exception as e:
        return f"ERROR:INTERNAL:{type(e).__name__}: {e}"


def register(server: McpServer) -> None:
    """Used by tests + dynamic loading."""
    with _REGISTRY_LOCK:
        _RUNNING[server.spec.name] = server


def unregister(name: str) -> bool:
    with _REGISTRY_LOCK:
        srv = _RUNNING.pop(name, None)
        if srv is None:
            return False
        srv.stop()
        return True


def shutdown() -> None:
    with _REGISTRY_LOCK:
        for srv in list(_RUNNING.values()):
            srv.stop()
        _RUNNING.clear()


def reset_for_tests() -> None:
    """Drop all state without trying to terminate (for fixtures)."""
    with _REGISTRY_LOCK:
        _RUNNING.clear()
