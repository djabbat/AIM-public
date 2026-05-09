"""AI/tests/test_backup.py — BK1 (2026-05-04)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_EVAL_DB", str(tmp_path / "eval.db"))
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1\n")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger",
              "AI.ai.distillation_tracker",
              "AI.ai.prompt_versions",
              "AI.ai.health_score",
              "AI.ai.finding_suppressions",
              "AI.ai.backup"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── snapshot ────────────────────────────────────────────────────


def test_snapshot_empty_dbs(isolated):
    from AI.ai.backup import snapshot
    s = snapshot()
    assert s["version"] == 1
    assert "diagnostic_db" in s
    assert "distillation_db" in s
    # No tables yet — no module has touched the DB.
    assert s["diagnostic_db"]["tables"] == {}


def test_snapshot_captures_runs(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from AI.ai.backup import snapshot
    s = snapshot()
    runs = s["diagnostic_db"]["tables"]["runs"]
    assert len(runs) == 1
    assert runs[0]["model"] == "m"


def test_snapshot_captures_prompt_versions(isolated):
    from AI.ai.prompt_versions import record_current
    record_current()
    from AI.ai.backup import snapshot
    s = snapshot()
    rows = s["diagnostic_db"]["tables"]["prompt_versions"]
    assert len(rows) == 1


def test_snapshot_captures_suppressions(isolated):
    from AI.ai.finding_suppressions import suppress
    suppress("agents/x.py:1", reason="known")
    from AI.ai.backup import snapshot
    s = snapshot()
    rows = s["diagnostic_db"]["tables"]["finding_suppressions"]
    assert len(rows) == 1


def test_snapshot_includes_health_scores(isolated):
    from AI.ai.health_score import record
    record()
    from AI.ai.backup import snapshot
    s = snapshot()
    rows = s["diagnostic_db"]["tables"]["health_scores"]
    assert len(rows) == 1


# ── write_snapshot ──────────────────────────────────────────────


def test_write_snapshot_explicit_path(isolated, tmp_path):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from AI.ai.backup import write_snapshot
    out = tmp_path / "backup.json"
    write_snapshot(out)
    payload = json.loads(out.read_text())
    assert payload["version"] == 1
    assert payload["diagnostic_db"]["tables"]["runs"]


def test_write_snapshot_default_filename(isolated, monkeypatch, tmp_path):
    """Default writes to AI/artifacts/backup_<ts>.json."""
    monkeypatch.setattr("AI.ai.run_self_diagnostic.ai_root",
                         lambda: tmp_path / "AI")
    from AI.ai.backup import write_snapshot
    out = write_snapshot()
    assert out.name.startswith("backup_")
    assert out.suffix == ".json"
    assert out.exists()


# ── restore ─────────────────────────────────────────────────────


def test_restore_round_trip(isolated, tmp_path):
    """snapshot → write → wipe → restore → snapshot equal."""
    from AI.ai.diagnostic_ledger import record, all_rows
    from AI.ai.finding_suppressions import suppress
    record(model="m", grade="B", n_refs=1, n_with_line=1,
           ts="2026-05-04T10:00:00")
    suppress("agents/x.py:1", reason="known")

    from AI.ai.backup import write_snapshot, restore
    out = tmp_path / "snap.json"
    write_snapshot(out)

    # Wipe
    (tmp_path / "dl.db").unlink()

    # Re-import to recreate empty schema
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    importlib.reload(sys.modules["AI.ai.finding_suppressions"])

    counts = restore(out)
    assert counts["dry_run"] is False
    assert counts["diagnostic_db"]["runs"] == 1
    from AI.ai.diagnostic_ledger import all_rows
    assert len(all_rows()) == 1


def test_restore_dry_run_doesnt_write(isolated, tmp_path):
    from AI.ai.diagnostic_ledger import record, all_rows
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from AI.ai.backup import write_snapshot, restore
    out = tmp_path / "snap.json"
    write_snapshot(out)

    (tmp_path / "dl.db").unlink()
    import importlib, sys
    importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])

    counts = restore(out, dry_run=True)
    assert counts["dry_run"] is True
    assert counts["diagnostic_db"]["runs"] == 1
    # but DB still empty
    from AI.ai.diagnostic_ledger import all_rows
    assert all_rows() == []


def test_restore_missing_file(isolated, tmp_path):
    from AI.ai.backup import restore
    with pytest.raises(FileNotFoundError):
        restore(tmp_path / "no-such.json")


# ── summary ─────────────────────────────────────────────────────


def test_summary_renders(isolated):
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from AI.ai.backup import summary
    s = summary()
    assert "Backup snapshot" in s
    assert "runs" in s
