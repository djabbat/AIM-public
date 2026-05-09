"""tests/test_skill_synthesis.py — S7 (2026-05-02)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    (tmp_path / "sessions").mkdir()
    import importlib
    import agents.skill_synthesis as ss
    importlib.reload(ss)
    return ss


def write_session(setup_root, name, events):
    p = setup_root / "sessions" / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ── candidate mining ─────────────────────────────────────────────


def test_candidates_finds_ngrams(isolated, tmp_path):
    sessions = tmp_path / "sessions"
    for sid in range(4):
        write_session(tmp_path, f"s{sid}", [
            {"type": "tool_call", "tool": "read_file", "session_id": sid,
             "args": {}},
            {"type": "tool_call", "tool": "edit_file", "session_id": sid,
             "args": {}},
            {"type": "tool_call", "tool": "bash", "session_id": sid,
             "args": {}},
        ])
    cands = isolated.candidates(min_length=3, min_support=3)
    assert any(c.steps == ["read_file", "edit_file", "bash"] for c in cands)


def test_candidates_skips_short_sessions(isolated, tmp_path):
    write_session(tmp_path, "s", [
        {"type": "tool_call", "tool": "x", "session_id": 1, "args": {}}
    ])
    assert isolated.candidates(min_length=3) == []


def test_candidates_min_support(isolated, tmp_path):
    # Only 2 sessions exhibit the trio → below min_support=3.
    for sid in range(2):
        write_session(tmp_path, f"s{sid}", [
            {"type": "tool_call", "tool": "a", "session_id": sid, "args": {}},
            {"type": "tool_call", "tool": "b", "session_id": sid, "args": {}},
            {"type": "tool_call", "tool": "c", "session_id": sid, "args": {}},
        ])
    assert isolated.candidates(min_support=3) == []


# ── propose / register / load ────────────────────────────────────


def test_propose_accepts_step_shapes(isolated):
    skill = isolated.propose(
        "publish",
        steps=[
            "md_to_docx",
            {"tool": "write_cover_letter", "args": {"to": "Editor"}},
            ("email_journal", {"subject": "Submission"}),
        ],
        description="ship a paper",
    )
    assert skill.name == "publish"
    assert [s.tool for s in skill.steps] == [
        "md_to_docx", "write_cover_letter", "email_journal"]


def test_propose_rejects_invalid_name(isolated):
    with pytest.raises(ValueError):
        isolated.propose("Bad-Name", steps=["x"])


def test_propose_requires_steps(isolated):
    with pytest.raises(ValueError):
        isolated.propose("ok", steps=[])


def test_register_and_load_roundtrip(isolated):
    skill = isolated.propose("sync_repo",
                              steps=["bash", "bash", "bash"],
                              description="git push flow")
    isolated.register(skill)
    assert "sync_repo" in isolated.list_registered()
    loaded = isolated.load("sync_repo")
    assert loaded.name == "sync_repo"
    assert loaded.description == "git push flow"
    assert len(loaded.steps) == 3


def test_load_unknown_raises(isolated):
    with pytest.raises(FileNotFoundError):
        isolated.load("ghost-skill")


def test_remove_returns_bool(isolated):
    skill = isolated.propose("temp", steps=["bash"])
    isolated.register(skill)
    assert isolated.remove("temp") is True
    assert isolated.remove("temp") is False


# ── invoke ───────────────────────────────────────────────────────


def test_invoke_runs_all_steps(isolated):
    skill = isolated.propose(
        "echo_chain",
        steps=[("read_file", {"path": "/tmp/{file}"}),
               ("bash", {"command": "ls"})],
    )
    isolated.register(skill)

    calls = []

    class Stub:
        def call(self, name, args):
            calls.append((name, args))
            return f"OK_{name}"

    out = isolated.invoke("echo_chain", params={"file": "hello.txt"},
                           registry=Stub())
    assert out["ok"] is True
    assert calls[0] == ("read_file", {"path": "/tmp/hello.txt"})
    assert calls[1] == ("bash", {"command": "ls"})


def test_invoke_stops_on_first_error(isolated):
    skill = isolated.propose("fail_chain",
                              steps=["a", "b", "c"])
    isolated.register(skill)

    class Stub:
        def call(self, name, args):
            return "ERROR:X:nope" if name == "b" else "OK"

    out = isolated.invoke("fail_chain", registry=Stub())
    assert out["ok"] is False
    assert out["failed_at"] == 1
    assert out["tool"] == "b"


def test_invoke_unknown_skill_raises(isolated):
    with pytest.raises(FileNotFoundError):
        isolated.invoke("ghost")


# ── audit ────────────────────────────────────────────────────────


def test_audit_logs_register_invoke(isolated):
    skill = isolated.propose("logged", steps=["bash"])
    isolated.register(skill)

    class Stub:
        def call(self, n, a): return "OK"

    isolated.invoke("logged", registry=Stub())
    h = isolated.history()
    events = [r["event"] for r in h]
    assert "register" in events
    assert "invoke_ok" in events
