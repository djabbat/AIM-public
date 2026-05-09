"""AI/tests/test_fix_planner.py — S14 (2026-05-03)."""
from __future__ import annotations

import pytest


# ── _parse_ref ──────────────────────────────────────────────────


def test_parse_ref_with_line():
    from AI.ai.fix_planner import _parse_ref
    assert _parse_ref("agents/foo.py:42") == ("agents/foo.py", 42)


def test_parse_ref_path_only():
    from AI.ai.fix_planner import _parse_ref
    assert _parse_ref("AI/ai/x.py") == ("AI/ai/x.py", None)


def test_parse_ref_with_backticks():
    from AI.ai.fix_planner import _parse_ref
    assert _parse_ref("`agents/foo.py:5`") == ("agents/foo.py", 5)


def test_parse_ref_strips_leading_dot_slash():
    from AI.ai.fix_planner import _parse_ref
    assert _parse_ref("./scripts/x.sh") == ("scripts/x.sh", None)


def test_parse_ref_invalid():
    from AI.ai.fix_planner import _parse_ref
    assert _parse_ref("this is not a path") is None


# ── _suggestion_for heuristics ─────────────────────────────────


def test_suggestion_pmid_triggers_verifiability():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("foo.py", {1: "    return PMID: 99999"})
    assert "citation_guard" in s


def test_suggestion_subprocess_triggers_sandbox():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("foo.py",
                        {1: "subprocess.run(['rm', '-rf', '/'])"})
    assert "bash sandbox" in s.lower() or "validate_bash" in s.lower()


def test_suggestion_sqlite_triggers_db_hardening():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("foo.py", {1: "conn = sqlite3.connect(p)"})
    assert "WAL" in s or "INSERT OR REPLACE" in s


def test_suggestion_silent_except():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("foo.py",
                        {1: "    except Exception:",
                         2: "        pass"})
    assert "silent" in s.lower()


def test_suggestion_for_test_file():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("tests/test_x.py",
                        {1: "def test_thing(): pass"})
    assert "test" in s.lower()


def test_suggestion_for_md_file():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("README.md", {1: "# hello"})
    assert "documentation" in s.lower()


def test_suggestion_default():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("agents/foo.py", {1: "x = y + 1"})
    assert "Read the file" in s


def test_suggestion_patient_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("Patients/x.md", {1: "name: x"})
    assert "Privacy" in s or "L_PRIVACY" in s


# ── path-pattern hints (CRIT/HIGH-aware) ────────────────────────


def test_suggestion_distillation_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("AI/ai/distillation_tracker.py", {})
    assert "WAL" in s and "CRIT-2" in s


def test_suggestion_eval_synthesiser_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("AI/ai/eval_synthesiser.py", {})
    assert "L_VERIFIABILITY" in s or "citation_guard" in s


def test_suggestion_gap_detector_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("AI/ai/gap_detector.py", {})
    assert "CRIT-3" in s or "materialise" in s


def test_suggestion_worktree_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("agents/worktree.py", {})
    assert "isolate" in s.lower()


def test_suggestion_self_modify_path():
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("AI/ai/self_modify.py", {})
    assert "Eval-gate" in s or "S1 evals" in s


def test_path_hints_take_precedence_over_default():
    """Without snippets, path hint still fires (was: default fallback)."""
    from AI.ai.fix_planner import _suggestion_for
    s = _suggestion_for("AI/ai/distillation_tracker.py", {})
    assert "Read the file at the cited line" not in s


# ── plan() ──────────────────────────────────────────────────────


def test_plan_groups_by_file(tmp_path):
    """Multiple findings for same file → one FileFix entry."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "foo.py").write_text(
        "line 1\nline 2\nline 3\nline 4\nline 5\n")
    from AI.ai.fix_planner import plan
    p = plan(["agents/foo.py:2", "agents/foo.py:4"], root=repo)
    assert p.n_files == 1
    assert p.files[0].line_refs == [2, 4]
    assert p.files[0].snippets[2] == "line 2"
    assert p.files[0].snippets[4] == "line 4"


def test_plan_handles_missing_file(tmp_path):
    """Ref to a non-existent file → entry without snippets."""
    from AI.ai.fix_planner import plan
    p = plan(["agents/ghost.py:5"], root=tmp_path)
    assert p.n_files == 1
    assert p.files[0].snippets == {}


def test_plan_handles_path_only_ref(tmp_path):
    from AI.ai.fix_planner import plan
    p = plan(["agents/foo.py"], root=tmp_path)
    assert p.n_files == 1
    assert p.files[0].line_refs == []


def test_plan_empty_input():
    from AI.ai.fix_planner import plan
    p = plan([])
    assert p.n_files == 0
    assert p.n_lines == 0


def test_plan_invalid_refs_skipped(tmp_path):
    from AI.ai.fix_planner import plan
    p = plan(["not a path", ""], root=tmp_path)
    assert p.n_files == 0


def test_plan_context_lines(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    from AI.ai.fix_planner import plan
    p = plan(["x.py:5"], root=repo, context_lines=2)
    snippets = p.files[0].snippets
    # Should include lines 3, 4, 5, 6, 7
    assert set(snippets.keys()) == {3, 4, 5, 6, 7}


# ── summary / render_markdown ──────────────────────────────────


def test_summary_no_files():
    from AI.ai.fix_planner import FixPlan, summary
    assert "no shared findings" in summary(FixPlan(0, 0, []))


def test_summary_lists_files(tmp_path):
    repo = tmp_path / "r"; repo.mkdir()
    (repo / "x.py").write_text("a\nb\nc\n")
    from AI.ai.fix_planner import plan, summary
    s = summary(plan(["x.py:2"], root=repo))
    assert "x.py" in s
    assert "L 2" in s


def test_render_markdown_includes_snippets(tmp_path):
    repo = tmp_path / "r"; repo.mkdir()
    (repo / "agents").mkdir()
    (repo / "agents" / "foo.py").write_text(
        "import x\ndef f(): return PMID: 99999\n")
    from AI.ai.fix_planner import plan, render_markdown
    text = render_markdown(plan(["agents/foo.py:2"], root=repo))
    assert "agents/foo.py" in text
    assert "PMID: 99999" in text
    assert "Suggestion" in text


def test_render_markdown_empty():
    from AI.ai.fix_planner import FixPlan, render_markdown
    text = render_markdown(FixPlan(0, 0, []))
    assert "nothing to plan" in text


# ── write_plan ──────────────────────────────────────────────────


def test_write_plan_default(tmp_path, monkeypatch):
    import AI.ai.fix_planner as fp
    monkeypatch.setattr(fp, "ai_root", lambda: tmp_path)
    out = fp.write_plan(fp.FixPlan(0, 0, []))
    assert out.exists()
    assert "fix_plan_" in out.name


def test_write_plan_custom_dest(tmp_path):
    import AI.ai.fix_planner as fp
    dest = tmp_path / "custom" / "plan.md"
    out = fp.write_plan(fp.FixPlan(0, 0, []), dest=dest)
    assert out == dest
    assert dest.exists()


# ── integration: parse → plan ───────────────────────────────────


def test_integration_with_meta_evaluator(tmp_path):
    """End-to-end: run meta_evaluator.shared_only on synthetic reports,
    feed result into plan(), get one entry per repeated file ref."""
    repo = tmp_path / "r"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "shared.py").write_text(
        "x = 1\ny = 2\n")
    from AI.ai.meta_evaluator import shared_only
    reports = [
        "Grade: B\n`agents/shared.py:2` `agents/extra.py:5`",
        "Grade: B\n`agents/shared.py:2` `agents/other.py:9`",
    ]
    shared = shared_only(reports)
    assert "agents/shared.py:2" in shared
    from AI.ai.fix_planner import plan
    p = plan(shared, root=repo)
    assert p.n_files == 1
    assert "agents/shared.py" in p.files[0].path
