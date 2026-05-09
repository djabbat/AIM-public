"""tests/test_weekly_digest.py — T1 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import json

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Isolate every backing store the digest reads from."""
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("AIM_PROMPTS_DIR", str(tmp_path / "prompts"))
    monkeypatch.setenv("AIM_SYNTH_TOOLS_DIR", str(tmp_path / "synth"))
    monkeypatch.setenv("AIM_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AIM_AB_ROUTER_DB", str(tmp_path / "ab.db"))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "evals.db"))
    monkeypatch.setenv("AIM_TG_DRYRUN", "1")
    (tmp_path / "sessions").mkdir()
    import importlib
    for mod in [
        "agents.pattern_miner",
        "agents.ab_router",
        "agents.prompt_evolver",
        "agents.tool_synthesis",
        "agents.skill_synthesis",
        "agents.evals",
        "scripts.weekly_digest",
    ]:
        if mod in __import__("sys").modules:
            importlib.reload(__import__("sys").modules[mod])
    return tmp_path


def test_digest_handles_empty_state(isolated):
    from scripts import weekly_digest
    text = weekly_digest.render_digest(today=dt.date(2026, 5, 3))
    # Header line.
    assert "AIM weekly self-improvement digest" in text
    # Every section present, even if empty.
    for header in ("🔎 Pattern findings", "⚖️ A/B router",
                    "🧬 Prompt evolution", "🛠 Tool synthesis",
                    "🎯 Skill synthesis", "📈 Evals"):
        assert header in text


def test_digest_lists_recent_ab_router_decisions(isolated):
    from agents import ab_router as ar
    rid = ar.start_round("v2", baseline="v1")
    for s in [0.5, 0.51, 0.49, 0.5] * 2:
        ar.record_run(rid, "v1", score=s)
    for s in [0.8, 0.81, 0.79, 0.8] * 2:
        ar.record_run(rid, "v2", score=s)
    ar.decide(rid)
    from scripts import weekly_digest
    text = weekly_digest.render_digest(today=dt.date.today())
    assert "promote_challenger" in text or "keep_baseline" in text


def test_digest_lists_synth_events(isolated):
    from agents import tool_synthesis as ts
    cand = ts.SynthesisCandidate(
        name="r_then_e", tool_a="read_file", tool_b="edit_file", support=3,
    )
    ts.register(ts.propose(cand, repeats=2))
    from scripts import weekly_digest
    text = weekly_digest.render_digest(today=dt.date.today())
    assert "register" in text
    assert "r_then_e" in text


def test_digest_pulls_eval_versions(isolated):
    from agents import evals as ev
    ev.run_all(lambda t: "hello", version="v0", persist_results=True)
    ev.run_all(lambda t: "anything", version="v1", persist_results=True)
    from scripts import weekly_digest
    text = weekly_digest.render_digest(today=dt.date.today())
    assert "v0" in text or "v1" in text
    assert "version=" in text


def test_digest_main_dryrun_prints(isolated, capsys):
    from scripts import weekly_digest
    rc = weekly_digest.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "AIM weekly self-improvement digest" in out


def test_digest_filters_by_window(isolated):
    """Events older than `window_days` must NOT appear."""
    from agents import tool_synthesis as ts
    # Manually write an old audit row.
    audit = ts._audit_path()
    audit.parent.mkdir(parents=True, exist_ok=True)
    old_ts = "2024-01-01T00:00:00"
    audit.write_text(json.dumps({
        "ts": old_ts, "event": "register", "name": "ancient",
        "support": 3, "tool_a": "x", "tool_b": "y", "path": "/tmp/x",
    }) + "\n")
    from scripts import weekly_digest
    text = weekly_digest.render_digest(today=dt.date(2026, 5, 3),
                                        window_days=7)
    # The ancient row falls outside the window.
    assert "ancient" not in text
