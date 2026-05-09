"""tests/test_llm_client.py — unit tests for the Phase 5b HTTP shim
(`agents/llm_client.py`).

These tests use mock HTTP servers (urllib mock via monkeypatch) so they
do NOT need a running aim-llm service.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_is_enabled_false_when_url_unset(monkeypatch):
    monkeypatch.delenv("AIM_LLM_HTTP_URL", raising=False)
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client
    assert not llm_client.is_enabled()


def test_is_enabled_true_when_url_set(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:8770")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client
    assert llm_client.is_enabled()


def test_ask_returns_reply(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:8770")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client

    class _Resp:
        def __init__(self, body):
            self._body = body.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._body

    body = json.dumps({"reply": "Hello!", "provider": "ollama",
                       "model": "llama3.2", "attempts": []})
    with mock.patch.object(llm_client.urllib.request, "urlopen",
                           return_value=_Resp(body)):
        out = llm_client.ask("hi")
    assert out == "Hello!"


def test_each_tier_function_passes_correct_tier(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:8770")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client

    seen_tiers: list[str] = []

    def fake_urlopen(req, timeout=None):
        seen_tiers.append(json.loads(req.data.decode("utf-8"))["tier"])
        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"reply": "ok"}).encode()
        return _R()

    with mock.patch.object(llm_client.urllib.request, "urlopen",
                           side_effect=fake_urlopen):
        llm_client.ask("x")
        llm_client.ask_fast("x")
        llm_client.ask_deep("x")
        llm_client.ask_long("x")
        llm_client.ask_critical("x")

    assert seen_tiers == ["default", "fast", "deep", "long", "critical"]


def test_system_message_prepended(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:8770")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["msgs"] = json.loads(req.data.decode("utf-8"))["messages"]
        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"reply": "ok"}).encode()
        return _R()

    with mock.patch.object(llm_client.urllib.request, "urlopen",
                           side_effect=fake_urlopen):
        llm_client.ask("user input", system="be terse")

    assert len(captured["msgs"]) == 2
    assert captured["msgs"][0] == {"role": "system", "content": "be terse"}
    assert captured["msgs"][1] == {"role": "user", "content": "user input"}


def test_ask_raises_on_unreachable_service(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:9999")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    with mock.patch.object(llm_client.urllib.request, "urlopen",
                           side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="unreachable"):
            llm_client.ask("hi")


def test_ask_raises_on_5xx(monkeypatch):
    monkeypatch.setenv("AIM_LLM_HTTP_URL", "http://127.0.0.1:8770")
    sys.modules.pop("agents.llm_client", None)
    from agents import llm_client
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 503, "Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"upstream"}'),
        )

    with mock.patch.object(llm_client.urllib.request, "urlopen",
                           side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            llm_client.ask("hi")
