"""AI/tests/test_self_diagnostic.py — SD1 prompt builder (2026-05-03)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── inventory helpers (no fixture — touch real repo) ────────────


def test_inventory_returns_modules():
    from AI.ai.self_diagnostic import inventory
    inv = inventory()
    assert "modules" in inv
    assert inv["n_modules"] >= 4   # S8/S9/S10/S11 + future
    names = {Path(m["path"]).stem for m in inv["modules"]}
    expected = {"eval_synthesiser", "distillation_tracker",
                "reflexion_cluster", "gap_detector"}
    assert expected.issubset(names)


def test_inventory_records_public_api():
    from AI.ai.self_diagnostic import inventory
    inv = inventory()
    by_name = {Path(m["path"]).stem: m for m in inv["modules"]}
    assert "synthesise" in by_name["eval_synthesiser"]["public_functions"]
    assert "Cluster" in by_name["reflexion_cluster"]["public_classes"]


def test_inventory_lists_agent_imports_only_under_agents():
    from AI.ai.self_diagnostic import inventory
    inv = inventory()
    for imp in inv["agents_imports"]:
        assert imp.startswith("agents") or imp == "agents"


def test_direction_rule_clean_on_real_repo():
    """`agents/` must not import from `AI/` — fundamental contract."""
    from AI.ai.self_diagnostic import _direction_rule_status
    out = _direction_rule_status()
    assert out["clean"], (
        "Direction rule violated: agents/ imports from AI/. "
        f"Offenders: {out['violations']}"
    )


# ── build_prompt ────────────────────────────────────────────────


def test_build_prompt_has_inventory_block():
    from AI.ai.self_diagnostic import build_prompt
    text = build_prompt()
    assert "Run-time Snapshot" in text
    assert "Inventory" in text
    # Inventory is JSON-serialised — round-trip a key field.
    start = text.index("```json")
    end = text.index("\n```\n", start)
    payload = text[start + len("```json") : end].strip()
    parsed = json.loads(payload)
    assert "modules" in parsed
    assert parsed["n_modules"] >= 4


def test_build_prompt_has_all_9_phases():
    from AI.ai.self_diagnostic import build_prompt
    text = build_prompt()
    for phase in ("Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4",
                   "Phase 5", "Phase 6", "Phase 7", "Phase 8", "Phase 9"):
        assert phase in text, f"missing {phase}"


def test_build_prompt_contains_instructions():
    from AI.ai.self_diagnostic import build_prompt
    text = build_prompt()
    assert "adversarial mode" in text.lower()
    assert "L_VERIFIABILITY" in text


def test_build_prompt_missing_template_raises(monkeypatch, tmp_path):
    import AI.ai.self_diagnostic as sd
    monkeypatch.setattr(sd, "prompt_path",
                        lambda: tmp_path / "nope.md")
    with pytest.raises(FileNotFoundError):
        sd.build_prompt()


# ── write_prompt ────────────────────────────────────────────────


def test_write_prompt_default_target(tmp_path, monkeypatch):
    """Don't dirty the real artifacts/ folder during tests."""
    import AI.ai.self_diagnostic as sd
    monkeypatch.setattr(sd, "ai_root", lambda: tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "SELF_DIAGNOSTIC_PROMPT.md").write_text(
        "# Prompt body\nPhase 0\nPhase 1\nPhase 2\nPhase 3\n"
        "Phase 4\nPhase 5\nPhase 6\nPhase 7\nPhase 8\nPhase 9\n"
    )
    p = sd.write_prompt()
    assert p.exists()
    assert "self_diag_request_" in p.name
    text = p.read_text()
    assert "Phase 0" in text


def test_write_prompt_custom_dest(tmp_path, monkeypatch):
    import AI.ai.self_diagnostic as sd
    monkeypatch.setattr(sd, "ai_root", lambda: tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "SELF_DIAGNOSTIC_PROMPT.md").write_text(
        "Phase 0\nPhase 1\nPhase 2\nPhase 3\nPhase 4\n"
        "Phase 5\nPhase 6\nPhase 7\nPhase 8\nPhase 9\n"
    )
    dest = tmp_path / "out" / "diag.md"
    p = sd.write_prompt(dest)
    assert p == dest
    assert dest.exists()


# ── module inventory edge cases ─────────────────────────────────


def test_module_inventory_handles_syntax_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def: not valid\n")
    from AI.ai.self_diagnostic import _module_inventory
    info = _module_inventory(bad)
    assert "error" in info
    assert "SyntaxError" in info["error"]


def test_module_inventory_skips_private_names(tmp_path):
    p = tmp_path / "x.py"
    p.write_text(
        "def public(): pass\n"
        "def _private(): pass\n"
        "class Public: pass\n"
        "class _Private: pass\n"
    )
    from AI.ai.self_diagnostic import _module_inventory
    info = _module_inventory(p)
    assert info["public_functions"] == ["public"]
    assert info["public_classes"] == ["Public"]


# ── direction-rule violation simulation ────────────────────────


def test_direction_rule_flags_violation(tmp_path, monkeypatch):
    """Plant a fake `agents/leaky.py` that imports from AI/, confirm we catch it."""
    import AI.ai.self_diagnostic as sd
    fake_root = tmp_path / "fake_repo"
    (fake_root / "agents").mkdir(parents=True)
    (fake_root / "AI" / "ai").mkdir(parents=True)
    (fake_root / "agents" / "leaky.py").write_text(
        "from AI.ai.eval_synthesiser import synthesise\n"
        "def go(): return synthesise()\n"
    )
    monkeypatch.setattr(sd, "project_root", lambda: fake_root)
    out = sd._direction_rule_status()
    assert not out["clean"]
    assert any("leaky.py" in v for v in out["violations"])


def test_direction_rule_ignores_comments(tmp_path, monkeypatch):
    import AI.ai.self_diagnostic as sd
    fake_root = tmp_path / "fake_repo"
    (fake_root / "agents").mkdir(parents=True)
    (fake_root / "agents" / "ok.py").write_text(
        "# from AI.ai import synthesise — this is just documentation\n"
        "def go(): return 1\n"
    )
    monkeypatch.setattr(sd, "project_root", lambda: fake_root)
    out = sd._direction_rule_status()
    assert out["clean"]


# ── CLI entry point ─────────────────────────────────────────────


def test_main_prints_and_writes(tmp_path, monkeypatch, capsys):
    import AI.ai.self_diagnostic as sd
    monkeypatch.setattr(sd, "ai_root", lambda: tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "SELF_DIAGNOSTIC_PROMPT.md").write_text(
        "Phase 0\nPhase 1\nPhase 2\nPhase 3\nPhase 4\n"
        "Phase 5\nPhase 6\nPhase 7\nPhase 8\nPhase 9\n"
    )
    rc = sd._main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "prompt →" in out
