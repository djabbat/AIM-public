"""tests/test_aim_cli.py — G8 dispatcher (2026-05-03)."""
from __future__ import annotations

import sys
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_CONTACTS_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("AIM_TG_DRYRUN", "1")
    (tmp_path / "projects").mkdir()
    import importlib
    if "aim_cli" in sys.modules:
        importlib.reload(sys.modules["aim_cli"])
    return tmp_path


# ── version ──────────────────────────────────────────────────────


def test_version_prints(capsys):
    from aim_cli import main
    rc = main(["version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIM" in out


# ── brief ────────────────────────────────────────────────────────


def test_brief_no_args(isolated, capsys, monkeypatch):
    (isolated / "projects" / "P.yaml").write_text("name: P\nphase: DRAFT\n")
    from agents import deadline_scanner as ds
    monkeypatch.setattr(ds, "scan_memory", lambda today: [])
    from aim_cli import main
    rc = main(["brief"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "P" in out


def test_brief_specific_project(isolated, capsys):
    (isolated / "projects" / "FCLC.yaml").write_text(
        "name: FCLC\nphase: SUBMITTED\n")
    from aim_cli import main
    rc = main(["brief", "--project", "FCLC"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "FCLC" in out


# ── recall ───────────────────────────────────────────────────────


def test_recall_calls_into_index(isolated, capsys, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000:
                          [{"file": "x.md", "text": "hit", "_distance": 0.1}])
    from aim_cli import main
    rc = main(["recall", "FCLC"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Recall" in out
    assert "x.md" in out


def test_recall_json_mode(isolated, capsys, monkeypatch):
    import agents.memory_index as mi
    monkeypatch.setattr(mi, "retrieve",
                        lambda q, k=12, max_chars_per_file=4000: [])
    from aim_cli import main
    main(["recall", "anything", "--json"])
    import json
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["query"] == "anything"


# ── project subcommands ──────────────────────────────────────────


def test_project_list(isolated, capsys):
    (isolated / "projects" / "FCLC.yaml").write_text("name: FCLC\n")
    (isolated / "projects" / "MCOA.yaml").write_text("name: MCOA\n")
    from aim_cli import main
    rc = main(["project", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "FCLC" in out and "MCOA" in out


def test_project_archive_then_unarchive(isolated, capsys):
    (isolated / "projects" / "P.yaml").write_text("name: P\nphase: DRAFT\n")
    from aim_cli import main
    main(["project", "archive", "P"])
    assert not (isolated / "projects" / "P.yaml").exists()
    main(["project", "unarchive", "P"])
    assert (isolated / "projects" / "P.yaml").exists()


def test_project_sweep_dry_run(isolated, capsys):
    (isolated / "projects" / "Old.yaml").write_text(
        "name: Old\nphase: PUBLISHED\n")
    import os, time
    p = isolated / "projects" / "Old.yaml"
    old = time.time() - 365 * 24 * 3600
    os.utime(p, (old, old))
    from aim_cli import main
    main(["project", "sweep"])
    out = capsys.readouterr().out
    assert "Old" in out
    # dry-run by default → file still there.
    assert p.exists()


def test_project_transition(isolated, capsys):
    (isolated / "projects" / "P.yaml").write_text("name: P\nphase: DRAFT\n")
    from aim_cli import main
    rc = main(["project", "transition", "P", "REVIEW"])
    assert rc == 0
    body = (isolated / "projects" / "P.yaml").read_text()
    assert "phase: REVIEW" in body


# ── eval list ────────────────────────────────────────────────────


def test_eval_list(isolated, capsys, monkeypatch):
    cases = isolated / "cases"
    cases.mkdir()
    (cases / "smoke.yaml").write_text(
        "id: smoke\ntask: x\ntags: [a]\nrubrics: {min_length: 0}\n")
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    import importlib, agents.evals as ev
    importlib.reload(ev)
    from aim_cli import main
    rc = main(["eval", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "smoke" in out


# ── memory / cost / escalate ─────────────────────────────────────


def test_memory(capsys, isolated, monkeypatch):
    monkeypatch.setenv("AIM_MEMORY_DIR", str(isolated))
    import importlib, agents.memory_monitor as mm
    importlib.reload(mm)
    from aim_cli import main
    main(["memory"])
    out = capsys.readouterr().out
    assert "Memory" in out or "no issues" in out


def test_cost(capsys, isolated):
    from aim_cli import main
    main(["cost"])
    out = capsys.readouterr().out
    assert out  # any output (incl. fallback) is fine


def test_escalate_no_rules(capsys, isolated):
    (isolated / "projects" / "P.yaml").write_text("name: P\n")
    from aim_cli import main
    main(["escalate"])
    out = capsys.readouterr().out
    assert "no rules" in out


# ── unknown command ──────────────────────────────────────────────


def test_unknown_command_errors(capsys):
    from aim_cli import main
    with pytest.raises(SystemExit):
        main(["definitely-not-a-command"])


# ── diag (fix-plan from latest self-diag) ────────────────────────


def test_diag_emits_fix_plan(isolated, capsys, monkeypatch, tmp_path):
    """`aim diag` should pick the latest self_diag report (skipping the
    `_request_` prompt copies) and emit a heuristic fix plan."""
    artifacts = tmp_path / "AI" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "self_diag_request_2026-05-02.md").write_text(
        "Old prompt — should be ignored", encoding="utf-8")
    (artifacts / "self_diag_2026-05-03.md").write_text(
        "Grade: B\nIssue at `AI/ai/distillation_tracker.py:42`.\n",
        encoding="utf-8")

    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    rc = aim_cli.main(["diag"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "self_diag_2026-05-03.md" in out
    assert "WAL" in out  # path-hint matched distillation_tracker


def test_diag_explicit_report_path(isolated, capsys, tmp_path):
    rep = tmp_path / "custom.md"
    rep.write_text("`AI/ai/eval_synthesiser.py:120` issue.",
                    encoding="utf-8")
    from aim_cli import main
    rc = main(["diag", "--report", str(rep)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "L_VERIFIABILITY" in out or "citation_guard" in out


def test_diag_save_writes_markdown(isolated, capsys, tmp_path, monkeypatch):
    artifacts = tmp_path / "AI" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "self_diag_2026-05-03.md").write_text(
        "`AI/ai/gap_detector.py:50` here.", encoding="utf-8")
    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    rc = aim_cli.main(["diag", "--save"])
    assert rc == 0
    plan_files = list(artifacts.glob("fix_plan_*.md"))
    assert len(plan_files) == 1
    assert "Fix Plan" in plan_files[0].read_text()


def test_diag_no_reports_errors(isolated, capsys, tmp_path, monkeypatch):
    (tmp_path / "AI" / "artifacts").mkdir(parents=True)
    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    rc = aim_cli.main(["diag"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "no self_diag" in out


def test_diag_warns_low_compliance(isolated, capsys, tmp_path, monkeypatch):
    artifacts = tmp_path / "AI" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "self_diag_2026-05-03.md").write_text(
        "Issue at `agents/x.py` (no line)", encoding="utf-8")
    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    aim_cli.main(["diag"])
    out = capsys.readouterr().out
    assert "low compliance" in out


def test_diag_trend_empty(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    from aim_cli import main
    rc = main(["diag", "--trend"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no diagnostic runs" in out


def test_diag_trend_renders_after_record(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    from AI.ai.diagnostic_ledger import record
    record(model="ds-r", grade="B", n_refs=10, n_with_line=8, crit=1)
    from aim_cli import main
    rc = main(["diag", "--trend"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 runs" in out
    assert "80%" in out


def test_diag_history_empty(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    from aim_cli import main
    rc = main(["diag", "--history", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no diagnostic runs" in out


def test_diag_history_lists_records(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    if "AI.ai.diagnostic_ledger" in sys.modules:
        importlib.reload(sys.modules["AI.ai.diagnostic_ledger"])
    from AI.ai.diagnostic_ledger import record
    record(model="ds-r", grade="B", n_refs=10, n_with_line=10,
           ts="2026-05-03T10:00:00")
    record(model="ds-c", grade="D", n_refs=5, n_with_line=2,
           retry_used=True, ts="2026-05-03T11:00:00")
    from aim_cli import main
    rc = main(["diag", "--history", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ds-r" in out
    assert "ds-c" in out
    assert "retry=Y" in out
    assert "100%" in out
    assert "40%" in out


def test_diag_regress_no_baseline(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--regress"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no baseline" in out


def test_diag_regress_flags_new_findings(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    p1 = tmp_path / "r1.md"
    p1.write_text("`agents/x.py:1`")
    p2 = tmp_path / "r2.md"
    p2.write_text("`agents/x.py:1` and `agents/new.py:42`")
    from AI.ai.diagnostic_ledger import record
    record(model="m", grade="B", n_refs=1, n_with_line=1, crit=0,
           report_path=str(p1), ts="2026-05-03T10:00:00")
    record(model="m", grade="C", n_refs=2, n_with_line=2, crit=1,
           report_path=str(p2), ts="2026-05-04T10:00:00")
    from aim_cli import main
    rc = main(["diag", "--regress"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "REGRESSED" in out
    assert "agents/new.py:42" in out


def test_diag_gen_cases_writes_yamls(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "out"))
    import importlib, sys
    if "AI.ai.findings_to_evals" in sys.modules:
        importlib.reload(sys.modules["AI.ai.findings_to_evals"])
    artifacts = tmp_path / "AI" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "self_diag_2026-05-04.md").write_text(
        "Issue at `agents/x.py:1` and `AI/ai/y.py:42`.",
        encoding="utf-8")
    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    rc = aim_cli.main(["diag", "--gen-cases"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "written: 2 new eval cases" in out
    yamls = list((tmp_path / "out").glob("regr-*.yaml"))
    assert len(yamls) == 2


def test_diag_gen_cases_no_report_errors(isolated, capsys, tmp_path, monkeypatch):
    (tmp_path / "AI" / "artifacts").mkdir(parents=True)
    import aim_cli
    monkeypatch.setattr(aim_cli, "__file__",
                         str(tmp_path / "aim_cli.py"))
    rc = aim_cli.main(["diag", "--gen-cases"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "no self_diag" in out


def test_diag_dashboard_renders(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
              "AI.ai.distillation_tracker", "AI.ai.gap_detector",
              "AI.ai.reflexion_cluster", "AI.ai.dashboard"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--dashboard"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIM/AI Dashboard" in out
    assert "Diagnostic ledger trend" in out


def test_diag_doctor_runs(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.doctor"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--doctor"])
    out = capsys.readouterr().out
    # rc == 0 (clean) OR rc == 1 (some crit) — either is a valid CLI result.
    assert rc in (0, 1)
    assert "doctor" in out
    assert "modules" in out


def test_diag_validate_cases_empty(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    import importlib, sys
    if "AI.ai.case_validator" in sys.modules:
        importlib.reload(sys.modules["AI.ai.case_validator"])
    from aim_cli import main
    rc = main(["diag", "--validate-cases"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no eval cases" in out


def test_diag_validate_cases_flags_broken(isolated, capsys, tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "broken.yaml").write_text("id: x\ntask: y\n")
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(cases))
    import importlib, sys
    if "AI.ai.case_validator" in sys.modules:
        importlib.reload(sys.modules["AI.ai.case_validator"])
    from aim_cli import main
    rc = main(["diag", "--validate-cases"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "broken.yaml" in out


def test_diag_dashboard_json(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AI_DISTILL_DB", str(tmp_path / "distill.db"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIM_SESSIONS_DIR", str(tmp_path / "sessions"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
              "AI.ai.distillation_tracker", "AI.ai.gap_detector",
              "AI.ai.reflexion_cluster", "AI.ai.dashboard"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    import json
    from aim_cli import main
    rc = main(["diag", "--dashboard", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "sections" in payload


def test_diag_archive_cases_empty(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("AIM_EVAL_ARCHIVE_DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.case_archiver"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--archive-cases", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no archive candidates" in out


def test_diag_morning_renders(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
              "AI.ai.case_archiver", "AI.ai.doctor",
              "AI.ai.morning_brief"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--morning"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Wiring" in out
    assert "Regression check" in out
    assert "Diagnostic trend" in out


def test_diag_sweep_dry_run(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("AIM_EVAL_ARCHIVE_DIR", str(tmp_path / "arch"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1\n")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.prompt_versions",
              "AI.ai.case_validator", "AI.ai.case_archiver",
              "AI.ai.auto_sweep"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--sweep", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Auto-sweep" in out
    assert "dry-run" in out


def test_diag_score(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1\n")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
              "AI.ai.prompt_versions", "AI.ai.case_validator",
              "AI.ai.doctor", "AI.ai.health_score"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--score"])
    out = capsys.readouterr().out
    # rc 0 (>=60) or 1 (<60) — both valid CLI outcomes
    assert rc in (0, 1)
    assert "AIM/AI health" in out
    assert "/100" in out


def test_diag_info_one_line(isolated, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DIAGNOSTIC_DB", str(tmp_path / "dl.db"))
    monkeypatch.setenv("AIM_EVAL_CASES_DIR", str(tmp_path / "cases"))
    fake = tmp_path / "PROMPT.md"
    fake.write_text("v1\n")
    monkeypatch.setenv("AI_DIAGNOSTIC_PROMPT", str(fake))
    (tmp_path / "cases").mkdir()
    import importlib, sys
    for m in ("AI.ai.diagnostic_ledger", "AI.ai.regression_detector",
              "AI.ai.prompt_versions", "AI.ai.case_validator",
              "AI.ai.doctor", "AI.ai.health_score"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from aim_cli import main
    rc = main(["diag", "--info"])
    out = capsys.readouterr().out.rstrip()
    assert rc in (0, 1)
    assert "AIM/AI:" in out
    assert "\n" not in out   # exactly one line


# ── help text ────────────────────────────────────────────────────


def test_help_text_lists_subcommands(capsys):
    from aim_cli import main
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for cmd in ("brief", "recall", "digest", "eval", "project",
                "memory", "cost", "diag"):
        assert cmd in out
