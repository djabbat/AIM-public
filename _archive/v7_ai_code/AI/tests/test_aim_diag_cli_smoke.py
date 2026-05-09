"""AI/tests/test_aim_diag_cli_smoke.py — INT2 (2026-05-04).

End-to-end smoke test of every `aim diag --*` flag. Each invocation
should exit cleanly (rc 0 or 1, no traceback) on a freshly-isolated
state. If a future refactor renames a module/CLI flag and forgets to
update the wiring, this single test trips.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Maximal env isolation: every persistence path lives in tmp_path."""
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("AIM_EVAL_ARCHIVE_DIR", str(tmp_path / "arch"))
    fake_prompt = tmp_path / "PROMPT.md"
    fake_prompt.write_text("# v1 stub\n", encoding="utf-8")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake_prompt))
    (tmp_path / "cases").mkdir()
    (tmp_path / "AI" / "artifacts").mkdir(parents=True)
    import aim_cli, importlib, sys
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    for m in (
        "AI.ai.diagnostic_ledger",
        "AI.ai.regression_detector",
        "AI.ai.distillation_tracker",
        "AI.ai.gap_detector",
        "AI.ai.reflexion_cluster",
        "AI.ai.fix_planner",
        "AI.ai.findings_to_evals",
        "AI.ai.case_validator",
        "AI.ai.case_archiver",
        "AI.ai.dashboard",
        "AI.ai.run_self_diagnostic",
        "AI.ai.prompt_versions",
        "AI.ai.prompt_impact",
        "AI.ai.morning_brief",
        "AI.ai.health_score",
        "AI.ai.auto_sweep",
        "AI.ai.doctor",
        "AI.ai.safety_gate",
        "AI.ai.regression_alert",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# Each entry: (argv, expected-rc-set, expected-substring-in-stdout)
_FLAGS = [
    (["--trend"],            {0},     "no diagnostic runs"),
    (["--regress"],          {0},     "no baseline"),
    (["--history", "5"],     {0},     "no diagnostic runs"),
    (["--dashboard"],        {0},     "AIM/AI Dashboard"),
    (["--dashboard", "--json"], {0},  '"sections"'),
    (["--doctor"],           {0, 1},  "doctor"),
    (["--validate-cases"],   {0},     "no eval cases"),
    (["--archive-cases", "--dry-run"], {0}, "no archive candidates"),
    (["--morning"],          {0},     "Wiring"),
    (["--sweep", "--dry-run"], {0},   "Auto-sweep"),
    (["--score"],            {0, 1},  "AIM/AI health"),
    (["--info"],             {0, 1},  "AIM/AI:"),
    (["--prune-phantom", "--dry-run"], {0}, "phantom"),
    (["--list-suppressions"], {0},        "no finding suppressions"),
]


# `--backup PATH` and `--restore PATH` need explicit tmp paths to avoid
# polluting the real AI/artifacts/ directory. Tested separately:


def test_smoke_backup_explicit_path(isolated, capsys, tmp_path):
    from aim_cli import main
    out_path = tmp_path / "snap.json"
    rc = main(["diag", "--backup", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "backup written" in out
    assert out_path.exists()


def test_smoke_restore_dry_run(isolated, capsys, tmp_path):
    """Take a snapshot with one row, then restore --dry-run."""
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1)
    from aim_cli import main
    out_path = tmp_path / "snap.json"
    main(["diag", "--backup", str(out_path)])
    capsys.readouterr()  # discard
    rc = main(["diag", "--restore", str(out_path), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would insert" in out


def test_smoke_suppress_then_unsuppress(isolated, capsys):
    """End-to-end: suppress a ref, list shows it, unsuppress, list empty."""
    from aim_cli import main
    rc = main(["diag", "--suppress", "agents/x.py:42"])
    assert rc == 0
    capsys.readouterr()
    main(["diag", "--list-suppressions"])
    listing = capsys.readouterr().out
    assert "agents/x.py:42" in listing
    rc = main(["diag", "--unsuppress", "agents/x.py:42"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unsuppressed" in out


@pytest.mark.parametrize("argv,expected_rc,needle", _FLAGS,
                          ids=[" ".join(a) for a, _, _ in _FLAGS])
def test_diag_flag_smoke(isolated, capsys, argv, expected_rc, needle):
    from aim_cli import main
    rc = main(["diag"] + argv)
    out = capsys.readouterr().out
    assert rc in expected_rc, f"argv={argv} rc={rc} out={out[:200]!r}"
    assert needle in out, (
        f"argv={argv} expected {needle!r} in output, got: {out[:300]!r}"
    )


def test_no_argv_combination_crashes(isolated, capsys):
    """Sanity: running every flag in sequence shouldn't cause hidden
    state leak (e.g. one command corrupting state another reads)."""
    from aim_cli import main
    seen_rcs: list[int] = []
    for argv, _, _ in _FLAGS:
        rc = main(["diag"] + argv)
        seen_rcs.append(rc)
        capsys.readouterr()  # discard
    assert all(r in (0, 1) for r in seen_rcs)
