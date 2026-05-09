"""tests/test_mcp_loader.py — G4 MCP-style extensibility (2026-05-02).

We don't actually spawn real subprocesses in unit tests — we feed a
fake McpServer that mimics the JSON-RPC interface. The end-to-end happy
path with a real subprocess is covered by `test_mcp_loader_e2e` (which
uses a tiny inline echo server).
"""
from __future__ import annotations

import json
import sys
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_MCP_DIR", str(tmp_path / "mcp"))
    (tmp_path / "mcp").mkdir()
    import importlib
    import agents.mcp_loader as mc
    importlib.reload(mc)
    mc.reset_for_tests()
    return mc


# ── parse_spec ────────────────────────────────────────────────────


def test_parse_spec_minimum(isolated):
    spec = isolated.parse_spec("weather", {"command": ["python3", "x.py"]})
    assert spec.name == "weather"
    assert spec.command == ["python3", "x.py"]
    assert spec.autostart is True
    assert spec.timeout_ms == 10000


def test_parse_spec_string_command_split(isolated):
    spec = isolated.parse_spec("a", {"command": "python3 -u -m m"})
    assert spec.command == ["python3", "-u", "-m", "m"]


def test_parse_spec_rejects_empty(isolated):
    with pytest.raises(ValueError):
        isolated.parse_spec("a", {"command": []})


def test_parse_spec_rejects_missing(isolated):
    with pytest.raises(ValueError):
        isolated.parse_spec("a", {})


# ── discover ──────────────────────────────────────────────────────


def test_discover_skips_invalid(tmp_path, isolated):
    (tmp_path / "mcp" / "good.toml").write_text(textwrap.dedent("""
        command = ["python3", "x.py"]
    """).strip())
    (tmp_path / "mcp" / "bad.toml").write_text("not toml [[[")
    specs = isolated.discover()
    names = {s.name for s in specs}
    assert names == {"good"}


def test_discover_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_MCP_DIR", str(tmp_path / "nonexistent"))
    import importlib
    import agents.mcp_loader as mc
    importlib.reload(mc)
    assert mc.discover() == []


# ── registry helpers (using fake servers) ─────────────────────────


class _FakeServer:
    def __init__(self, name, tools, call_results=None):
        self.spec = type("S", (), {"name": name})()
        self.tools = tools
        self._results = call_results or {}
        self.calls = []
        self.stopped = False

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool in self._results:
            r = self._results[tool]
            if isinstance(r, Exception):
                raise r
            return r
        return f"OK_{tool}"

    def stop(self):
        self.stopped = True


def test_list_tools_aggregates(isolated):
    isolated.register(_FakeServer("weather", [{"name": "forecast"}]))
    isolated.register(_FakeServer("github",  [{"name": "open_pr"},
                                                 {"name": "list_issues"}]))
    names = sorted(t["name"] for t in isolated.list_tools())
    assert names == ["forecast", "list_issues", "open_pr"]
    # Each entry tagged with origin server.
    by_server = {t["name"]: t["server"] for t in isolated.list_tools()}
    assert by_server["forecast"] == "weather"


def test_find_server_returns_owner(isolated):
    isolated.register(_FakeServer("weather", [{"name": "forecast"}]))
    srv = isolated.find_server("forecast")
    assert srv is not None
    assert isolated.find_server("nope") is None


def test_call_routes_to_server(isolated):
    s = _FakeServer("weather", [{"name": "forecast"}])
    isolated.register(s)
    out = isolated.call("forecast", {"city": "Tbilisi"})
    assert out == "OK_forecast"
    assert s.calls == [("forecast", {"city": "Tbilisi"})]


def test_call_unknown_tool(isolated):
    out = isolated.call("ghost", {})
    assert out.startswith("ERROR:NOT_FOUND")


def test_call_propagates_failure_as_error(isolated):
    s = _FakeServer("x", [{"name": "boom"}],
                    call_results={"boom": RuntimeError("no")})
    isolated.register(s)
    out = isolated.call("boom", {})
    assert out.startswith("ERROR:INTERNAL")
    assert "RuntimeError" in out


def test_unregister(isolated):
    s = _FakeServer("x", [{"name": "t"}])
    isolated.register(s)
    assert isolated.unregister("x") is True
    assert s.stopped is True
    assert isolated.unregister("x") is False


def test_shutdown_stops_all(isolated):
    s1 = _FakeServer("a", [])
    s2 = _FakeServer("b", [])
    isolated.register(s1); isolated.register(s2)
    isolated.shutdown()
    assert s1.stopped and s2.stopped
    assert isolated.list_tools() == []


# ── end-to-end with a real subprocess ────────────────────────────


_INLINE_SERVER = textwrap.dedent("""\
    import json, sys
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        rid = req.get("id")
        method = req.get("method")
        if method == "list_tools":
            res = [{"name": "echo", "description": "echo",
                    "schema": {"type": "object"}}]
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": rid, "result": res}) + "\\n")
        elif method == "call":
            args = (req.get("params") or {}).get("args", {})
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": rid,
                "result": "echo:" + str(args.get("text", ""))}) + "\\n")
        else:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": "unknown"}}) + "\\n")
        sys.stdout.flush()
""")


def test_e2e_real_subprocess(isolated, tmp_path):
    server_py = tmp_path / "echo_server.py"
    server_py.write_text(_INLINE_SERVER)

    spec = isolated.ServerSpec(
        name="echo",
        command=[sys.executable, "-u", str(server_py)],
        autostart=True, timeout_ms=5000,
    )
    srv = isolated.McpServer(spec)
    try:
        srv.start()
        assert srv.tools and srv.tools[0]["name"] == "echo"
        out = srv.call("echo", {"text": "hello-mcp"})
        assert out == "echo:hello-mcp"
    finally:
        srv.stop()
