"""AI/tests/test_skill_standard.py — HV4 (2026-05-04)."""
from __future__ import annotations

import json

import pytest


# ── single-skill conversion ────────────────────────────────────


def test_to_agentskills_basic():
    from AI.ai.skill_standard import to_agentskills
    aim = {"skill_id": "auto-x", "theme": ["pubmed", "verify"],
           "rationale": "verify PMIDs before emit"}
    ext = to_agentskills(aim)
    assert ext["name"] == "auto-x"
    assert "verify PMIDs" in ext["description"]
    assert ext["trigger_phrases"] == ["pubmed", "verify"]
    assert "AIM Hive Queen" in ext["metadata"]["author"]


def test_to_agentskills_synthesizes_instructions_when_no_body():
    from AI.ai.skill_standard import to_agentskills
    aim = {"skill_id": "auto-y", "theme": ["a", "b"]}
    ext = to_agentskills(aim)
    assert "Trigger" in ext["instructions"]
    assert "a" in ext["instructions"]


def test_to_agentskills_preserves_body():
    from AI.ai.skill_standard import to_agentskills
    aim = {"skill_id": "auto-z", "body": "step 1: do X\nstep 2: do Y"}
    ext = to_agentskills(aim)
    assert ext["instructions"] == "step 1: do X\nstep 2: do Y"


def test_to_agentskills_rejects_missing_id():
    from AI.ai.skill_standard import to_agentskills
    with pytest.raises(ValueError, match="skill_id"):
        to_agentskills({"theme": ["x"]})


def test_from_agentskills_basic():
    from AI.ai.skill_standard import from_agentskills
    ext = {"name": "import-1",
           "description": "fetch from PubMed",
           "trigger_phrases": ["pubmed"],
           "instructions": "## Steps\n1. ...\n",
           "metadata": {"tags": ["search"]}}
    aim = from_agentskills(ext)
    assert aim["skill_id"] == "import-1"
    assert aim["theme"] == ["pubmed"]
    assert "external-import" in aim["tags"]


def test_from_agentskills_rejects_missing_name():
    from AI.ai.skill_standard import from_agentskills
    with pytest.raises(ValueError):
        from_agentskills({"description": "x"})


# ── round-trip identity ────────────────────────────────────────


def test_round_trip_preserves_skill_id():
    from AI.ai.skill_standard import round_trip_aim
    aim = {"skill_id": "rt-1", "theme": ["a", "b"], "rationale": "r"}
    out = round_trip_aim(aim)
    assert out["skill_id"] == aim["skill_id"]
    assert out["theme"] == aim["theme"]


def test_round_trip_preserves_body():
    from AI.ai.skill_standard import round_trip_aim
    aim = {"skill_id": "rt-2", "body": "exact body text"}
    assert round_trip_aim(aim)["body"] == "exact body text"


# ── batch I/O ──────────────────────────────────────────────────


def test_export_dir_writes_files(tmp_path):
    src = tmp_path / "aim_skills"
    src.mkdir()
    (src / "a.json").write_text(json.dumps(
        {"skill_id": "a", "theme": ["t1"]}))
    (src / "b.json").write_text(json.dumps(
        {"skill_id": "b", "theme": ["t2"]}))
    dst = tmp_path / "external"
    from AI.ai.skill_standard import export_dir
    n = export_dir(src, dst)
    assert n == 2
    assert (dst / "a.json").exists()
    assert (dst / "b.json").exists()
    parsed = json.loads((dst / "a.json").read_text())
    assert parsed["name"] == "a"


def test_import_dir_writes_aim_format(tmp_path):
    src = tmp_path / "external"
    src.mkdir()
    (src / "x.json").write_text(json.dumps({
        "name": "x", "description": "do x",
        "trigger_phrases": ["x"], "instructions": "..."}))
    dst = tmp_path / "aim_skills"
    from AI.ai.skill_standard import import_dir
    n = import_dir(src, dst)
    assert n == 1
    parsed = json.loads((dst / "x.json").read_text())
    assert parsed["skill_id"] == "x"


def test_export_dir_skips_existing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.json").write_text(json.dumps({"skill_id": "a"}))
    dst = tmp_path / "dst"
    from AI.ai.skill_standard import export_dir
    export_dir(src, dst)
    n_again = export_dir(src, dst)
    assert n_again == 0   # already exists, no overwrite


def test_export_dir_overwrite_flag(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.json").write_text(json.dumps({"skill_id": "a"}))
    dst = tmp_path / "dst"
    from AI.ai.skill_standard import export_dir
    export_dir(src, dst)
    assert export_dir(src, dst, overwrite=True) == 1


def test_import_export_round_trip(tmp_path):
    """A skill exported then re-imported should match the original on
    key fields."""
    src = tmp_path / "aim"
    src.mkdir()
    aim = {"skill_id": "rt", "theme": ["a", "b"],
            "rationale": "do thing", "body": "step1\nstep2"}
    (src / "rt.json").write_text(json.dumps(aim))
    mid = tmp_path / "external"
    out = tmp_path / "aim_back"
    from AI.ai.skill_standard import export_dir, import_dir
    export_dir(src, mid)
    import_dir(mid, out)
    rebuilt = json.loads((out / "rt.json").read_text())
    assert rebuilt["skill_id"] == "rt"
    assert rebuilt["theme"] == ["a", "b"]
    assert rebuilt["body"] == "step1\nstep2"


def test_export_dir_handles_missing_src(tmp_path):
    from AI.ai.skill_standard import export_dir
    assert export_dir(tmp_path / "nope", tmp_path / "dst") == 0
