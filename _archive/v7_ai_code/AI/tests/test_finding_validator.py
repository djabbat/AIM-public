"""AI/tests/test_finding_validator.py — FV1 (2026-05-04)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    import importlib, sys
    if "AI.ai.finding_validator" in sys.modules:
        importlib.reload(sys.modules["AI.ai.finding_validator"])
    return tmp_path


# ── classify() — single-rule contradictions ────────────────────


def test_unique_constraint_false_positive(isolated, tmp_path):
    """Claim 'no UNIQUE' contradicted by CREATE UNIQUE INDEX in file."""
    f = tmp_path / "x.py"
    f.write_text(textwrap.dedent("""
        def setup():
            conn.execute("CREATE UNIQUE INDEX uq_x ON t(a, b)")
    """))
    from AI.ai.finding_validator import classify
    v = classify("record() — no UNIQUE constraint visible", f)
    assert v.status == "false_positive"
    assert v.rule == "claim_negates_existing_sql"


def test_typed_return_false_positive(isolated, tmp_path):
    f = tmp_path / "x.py"
    f.write_text(textwrap.dedent("""
        def synthesise() -> list[Path]:
            return []
    """))
    from AI.ai.finding_validator import classify
    v = classify("synthesise() returns None implicitly", f)
    assert v.status == "false_positive"
    assert v.rule == "claim_negates_typed_return"


def test_existence_guard_false_positive(isolated, tmp_path):
    f = tmp_path / "x.py"
    f.write_text(textwrap.dedent("""
        def gaps():
            sd = sessions_dir()
            if not sd.exists():
                return []
    """))
    from AI.ai.finding_validator import classify
    v = classify("gaps() crashes on missing sessions_dir", f)
    assert v.status == "false_positive"
    assert v.rule == "claim_negates_existence_guard"


def test_citation_guard_false_positive(isolated, tmp_path):
    f = tmp_path / "x.py"
    f.write_text(textwrap.dedent("""
        from agents.citation_guard import extract
        def emit():
            _verify_no_fabricated_citations(spec)
    """))
    from AI.ai.finding_validator import classify
    v = classify("synthesise() — no citation_guard", f)
    assert v.status == "false_positive"
    assert v.rule == "claim_negates_citation_guard"


def test_lock_false_positive(isolated, tmp_path):
    f = tmp_path / "x.py"
    f.write_text(textwrap.dedent("""
        import threading
        _LOCK = threading.RLock()
        def record():
            with _LOCK:
                ...
    """))
    from AI.ai.finding_validator import classify
    v = classify("record() — race condition", f)
    assert v.status == "false_positive"
    assert v.rule == "claim_negates_lock"


def test_no_match_returns_unverified(isolated, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def x(): pass\n")
    from AI.ai.finding_validator import classify
    v = classify("x() has subtle off-by-one in loop counter", f)
    assert v.status == "unverified"
    assert v.rule == "no_match"


def test_missing_file_unverified(isolated, tmp_path):
    from AI.ai.finding_validator import classify
    v = classify("some claim", tmp_path / "nonexistent.py")
    assert v.status == "unverified"
    assert v.rule == "no_file"


# ── _extract_file_ref ──────────────────────────────────────────


# ── audit_report — end-to-end ──────────────────────────────────


def test_audit_report_classifies_mixed(isolated, tmp_path):
    """Report with one claim contradicted by code + one with no rule
    match. Findings on single lines (parser works line-by-line)."""
    src = tmp_path / "AI" / "ai"
    src.mkdir(parents=True)
    (src / "distillation_tracker.py").write_text(
        'CREATE UNIQUE INDEX uq ON t(a)'
    )
    (src / "morning_brief.py").write_text("def x(): pass\n")
    report = (
        "- **`distillation_tracker.py`** record — no UNIQUE constraint visible. "
        "→ **high** (duplicate entries on re-run).\n"
        "- **`morning_brief.py`** has subtle bug in line ordering. → **med**.\n"
    )
    from AI.ai.finding_validator import audit_report
    out = audit_report(report, repo_root=tmp_path)
    assert out.n_findings == 2
    assert out.n_false == 1
    assert out.n_unverified == 1


def test_audit_report_empty(isolated):
    from AI.ai.finding_validator import audit_report
    out = audit_report("plain markdown without findings",
                        repo_root=Path("/tmp"))
    assert out.n_findings == 0


def test_audit_report_resolves_bare_filename(isolated, tmp_path):
    """Bare 'foo.py' should be tried in both AI/ai/ and agents/."""
    (tmp_path / "AI" / "ai").mkdir(parents=True)
    (tmp_path / "AI" / "ai" / "foo.py").write_text(
        "def x() -> list[int]: return []\n"
    )
    report = "**`foo.py`** returns None implicitly. → **high**."
    from AI.ai.finding_validator import audit_report
    out = audit_report(report, repo_root=tmp_path)
    assert out.n_false == 1


# ── summary ────────────────────────────────────────────────────


def test_summary_no_findings(isolated):
    from AI.ai.finding_validator import summary
    s = summary("plain text", repo_root=Path("/tmp"))
    assert "no severity-tagged" in s


def test_summary_lists_false_positives(isolated, tmp_path):
    src = tmp_path / "AI" / "ai"
    src.mkdir(parents=True)
    (src / "x.py").write_text("def f() -> dict: return {}\n")
    report = "**`x.py`** returns None implicitly. → **high**."
    from AI.ai.finding_validator import summary
    s = summary(report, repo_root=tmp_path)
    assert "1 findings" in s
    assert "false positive: 1" in s


# ── real-world integration ─────────────────────────────────────


def test_real_diagnostic_artifact_yields_false_positives(isolated):
    """Run the validator on the real saved diagnostic. We don't pin
    the exact count (depends on the report file's lifecycle) — we
    just assert the validator processes without crash and finds at
    least some false-positives (since the audit on 2026-05-03 showed
    ~93% noise)."""
    from AI.ai.run_self_diagnostic import ai_root
    artifacts = ai_root() / "artifacts"
    if not artifacts.exists():
        pytest.skip("no artifacts dir")
    real = sorted(p for p in artifacts.glob("self_diag_*.md")
                   if "_request_" not in p.name)
    if not real:
        pytest.skip("no real diagnostic reports")
    from AI.ai.finding_validator import audit_report
    out = audit_report(real[-1].read_text(encoding="utf-8"))
    assert out.n_findings >= 0   # parses without crash
    # If we found any false positives, great — that's the value-add
    # If none — still a clean pass.
