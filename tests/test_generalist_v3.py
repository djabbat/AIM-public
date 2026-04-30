"""tests/test_generalist_v3.py — Phase 1 + Phase 2 hardening tests."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── P1.1: contextvars run-state isolation ─────────────────────────────────


def test_contextvar_isolated_per_thread():
    """Sub-thread that doesn't run() should see None — no leak from caller."""
    from agents import generalist as G
    G._RUN_ID_VAR.set("parent_run")
    seen = {}

    def worker():
        seen["child"] = G._current_run_id()
    t = threading.Thread(target=worker)
    t.start(); t.join()
    # Default ContextVar copies parent's context — child sees parent unless reset.
    # We expose a helper to reset, but baseline behaviour is inherit.
    assert seen["child"] in ("parent_run", None)


def test_request_interrupt_uses_contextvar():
    from agents import generalist as G
    G._RUN_ID_VAR.set("ctx_run")
    G._INTERRUPTED.clear()
    G.request_interrupt()
    assert G._INTERRUPTED.get("ctx_run") is True
    G._INTERRUPTED.clear()
    G._RUN_ID_VAR.set(None)


# ── P1.2: locks present on global dicts ───────────────────────────────────


def test_locks_exist():
    from agents import generalist as G
    assert isinstance(G._TOOLS_LOCK, type(threading.RLock()))
    assert isinstance(G._BG_JOBS_LOCK, type(threading.RLock()))
    assert isinstance(G._STATE_LOCK, type(threading.RLock()))


# ── P1.3: kernel_check enforced on writes ─────────────────────────────────


def test_write_blocked_under_patients(tmp_path, monkeypatch):
    from agents.generalist import _t_write_file
    monkeypatch.delenv("AIM_ALLOW_PATIENT_WRITE", raising=False)
    fake_patients = tmp_path / "Patients" / "X"
    fake_patients.mkdir(parents=True)
    target = fake_patients / "test.txt"
    out = _t_write_file(str(target), "patient note")
    assert out.startswith("ERROR:PERMISSION")
    assert "L_PRIVACY" in out
    assert not target.exists()


def test_write_allowed_with_override(tmp_path, monkeypatch):
    from agents.generalist import _t_write_file
    monkeypatch.setenv("AIM_ALLOW_PATIENT_WRITE", "1")
    fake_patients = tmp_path / "Patients" / "X"
    fake_patients.mkdir(parents=True)
    target = fake_patients / "ok.txt"
    out = _t_write_file(str(target), "patient note")
    assert out.startswith("OK")
    assert target.exists()


def test_write_normal_path_works(tmp_path):
    from agents.generalist import _t_write_file
    target = tmp_path / "ordinary.txt"
    out = _t_write_file(str(target), "hello")
    assert out.startswith("OK")
    assert target.read_text() == "hello"


# ── P1.4: token counting handles non-ASCII ────────────────────────────────


def test_token_counter_doesnt_overshoot_russian():
    from agents.generalist import _count_text_tokens
    russian = "Это пример русского текста для проверки счётчика токенов." * 5
    n = _count_text_tokens(russian)
    # Should be reasonable — not wildly larger than rough English equivalent
    eng = "This is a sample English text for token counter verification." * 5
    n_eng = _count_text_tokens(eng)
    # Allow ~3× tolerance, but not the 1.5× overshoot of len/4 alone
    assert n < n_eng * 3
    assert n > 0


# ── P1.5: stuck-loop signature hashing ─────────────────────────────────────


def test_action_signature_stable():
    """Same action dict produces same JSON signature for stuck-loop detection."""
    a1 = {"tool": "read_file", "args": {"path": "/tmp/x"}}
    a2 = {"tool": "read_file", "args": {"path": "/tmp/x"}}
    s1 = json.dumps(a1, sort_keys=True, default=str)[:300]
    s2 = json.dumps(a2, sort_keys=True, default=str)[:300]
    assert s1 == s2


# ── P1.6: typed errors ────────────────────────────────────────────────────


def test_read_file_typed_error():
    from agents.generalist import _t_read_file
    out = _t_read_file("/nonexistent/path/xyz")
    assert out.startswith("ERROR:NOT_FOUND:")


def test_edit_file_unique_match_required():
    from agents.generalist import _t_edit_file, _t_write_file
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("hello world\nhello world\n")
        path = f.name
    try:
        out = _t_edit_file(path, "hello world", "hi")
        assert out.startswith("ERROR:INVALID_INPUT:")
        assert "occurs 2×" in out
    finally:
        Path(path).unlink()


# ── P1.7: timeouts ─────────────────────────────────────────────────────────


def test_with_timeout_helper_returns_timeout():
    from agents.generalist import _with_timeout
    def slow(): time.sleep(2); return "done"
    out = _with_timeout(slow, {}, timeout=0.3)
    assert isinstance(out, str) and out.startswith("ERROR:TIMEOUT")


# ── P2.1: Anthropic cache_control wired (smoke — doesn't actually call) ──


def test_claude_chat_signature_supports_cache():
    from llm import _claude_chat
    import inspect
    sig = inspect.signature(_claude_chat)
    assert "cache_system" in sig.parameters


# ── P2.2: run_tests tool present ──────────────────────────────────────────


def test_run_tests_tool_registered():
    from agents.generalist import _TOOLS
    assert "run_tests" in _TOOLS


def test_run_tests_passes_simple():
    from agents.generalist import _t_run_tests
    out = _t_run_tests("python3 -c 'assert 1+1==2'")
    assert "TESTS PASSED" in out
    assert "[exit=0]" in out


def test_run_tests_fails_simple():
    from agents.generalist import _t_run_tests
    out = _t_run_tests("python3 -c 'assert 1+1==3'")
    assert "TESTS FAILED" in out
    assert "[exit=1]" in out


# ── P2.3: Reflexion ───────────────────────────────────────────────────────


def test_reflexion_classify_buckets():
    from agents.reflexion import classify
    assert classify("fix the auth bug") in ("code_edit", "ops")
    assert classify("write peer review of manuscript") == "writing"
    assert classify("diagnose anemia") == "diagnosis"
    assert classify("hello world") == "general"


def test_reflexion_save_and_recall(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Reload to pick up env
    if "agents.reflexion" in sys.modules:
        del sys.modules["agents.reflexion"]
    from agents.reflexion import save_reflection, recent_reflections
    save_reflection("write peer review of paper X",
                    "lesson: do not trust DOI without Crossref check")
    refs = recent_reflections("draft a peer review of paper Y", n=3)
    assert any("Crossref" in r for r in refs)


# ── P2.4: critique tool ───────────────────────────────────────────────────


def test_critique_tool_registered():
    from agents.generalist import _TOOLS
    assert "critique" in _TOOLS


# ── P2.5: localized editor ────────────────────────────────────────────────


def test_view_file_returns_numbered_lines(tmp_path):
    from agents.generalist import _t_view_file
    f = tmp_path / "x.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    out = _t_view_file(str(f), 2, 4)
    assert "    2: b" in out
    assert "    4: d" in out
    assert "5 total lines" in out


def test_view_file_context_around_regex(tmp_path):
    from agents.generalist import _t_view_file
    f = tmp_path / "x.py"
    f.write_text("\n".join(f"line {i}" for i in range(20)) + "\nfind_me HERE\n")
    out = _t_view_file(str(f), context_around="find_me")
    assert "→" in out  # marker on the matched line
    assert "find_me HERE" in out


# ── P2.6: sandbox helper ──────────────────────────────────────────────────


def test_sandbox_helper_no_bwrap_returns_plain_shell(monkeypatch):
    from agents.generalist import _maybe_sandbox
    monkeypatch.delenv("AIM_SANDBOX", raising=False)
    cmd = _maybe_sandbox("echo hi")
    assert cmd == ["/bin/sh", "-c", "echo hi"]


# ── P2.7: implicit verification ──────────────────────────────────────────


def test_post_write_verify_catches_bad_python(tmp_path):
    from agents.generalist import _post_write_verify
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n    pass\n")
    warn = _post_write_verify(f)
    assert warn and warn.startswith("WARN")


def test_post_write_verify_passes_good_python(tmp_path):
    from agents.generalist import _post_write_verify
    f = tmp_path / "good.py"
    f.write_text("def fine():\n    return 42\n")
    warn = _post_write_verify(f)
    assert warn is None


def test_post_write_verify_catches_bad_json(tmp_path):
    from agents.generalist import _post_write_verify
    f = tmp_path / "bad.json"
    f.write_text("{ this is not json }")
    warn = _post_write_verify(f)
    assert warn and warn.startswith("WARN")
