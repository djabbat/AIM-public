"""tests/test_citation_linter.py — PR2 (2026-05-03)."""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Stub the literature verifier so tests don't hit the network."""
    import tools.literature as lit
    # Default: anything is unresolved unless monkeypatched in the test.
    monkeypatch.setattr(lit, "verify_pmid", lambda p: None)
    monkeypatch.setattr(lit, "verify_doi", lambda d: None)
    import importlib, sys
    for m in ["agents.citation_guard", "agents.citation_linter"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ── empty / no citations ─────────────────────────────────────────


def test_no_citations_no_issues(isolated):
    (isolated / "doc.md").write_text("Plain markdown, no refs.\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.files_scanned == 1
    assert rep.has_problems is False


def test_no_md_files(isolated):
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.files_scanned == 0


# ── unresolved citations ─────────────────────────────────────────


def test_unresolved_pmid_flagged(isolated):
    (isolated / "draft.md").write_text("Cite PMID: 99999 here.\n"
                                         "And another PMID: 88888.\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.has_problems
    assert len(rep.issues) == 2
    assert all(i.kind == "pmid" for i in rep.issues)


def test_unresolved_doi_flagged(isolated):
    (isolated / "draft.md").write_text("See doi 10.1234/fake.x for refs.\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.has_problems
    assert rep.issues[0].kind == "doi"


def test_resolved_citation_not_flagged(isolated, monkeypatch):
    import tools.literature as lit
    monkeypatch.setattr(lit, "verify_pmid",
                        lambda p: {"title": "Real", "year": 2024})
    import importlib, agents.citation_guard as cg
    importlib.reload(cg)
    (isolated / "draft.md").write_text("Cite PMID: 12345 — real.\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.has_problems is False


# ── line numbers ─────────────────────────────────────────────────


def test_issue_records_line_number(isolated):
    md = "intro line\n\nMethods refer to PMID: 99999\nDiscussion."
    (isolated / "x.md").write_text(md)
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.issues[0].line == 3


# ── ignore globs ─────────────────────────────────────────────────


def test_default_ignore_skips_archive(isolated):
    (isolated / "_archive").mkdir()
    (isolated / "_archive" / "old.md").write_text("PMID: 99999\n")
    (isolated / "live.md").write_text("PMID: 88888\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    files = {i.file for i in rep.issues}
    assert "live.md" in files
    assert not any(f.startswith("_archive") for f in files)


def test_custom_ignore_globs(isolated):
    (isolated / "skip-me.md").write_text("PMID: 99999\n")
    (isolated / "keep.md").write_text("PMID: 99999\n")
    from agents.citation_linter import lint
    rep = lint(isolated, ignore_globs=["skip-me.md"])
    files = {i.file for i in rep.issues}
    assert files == {"keep.md"}


# ── summary string ──────────────────────────────────────────────


def test_summary_clean(isolated):
    (isolated / "x.md").write_text("clean")
    from agents.citation_linter import lint
    s = lint(isolated).summary()
    assert "Citations OK" in s


def test_summary_lists_issues(isolated):
    (isolated / "draft.md").write_text("PMID: 99999\nPMID: 88888\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    s = rep.summary()
    assert "unresolved" in s
    assert "draft.md" in s


# ── multiple files ──────────────────────────────────────────────


def test_multiple_files_aggregated(isolated):
    (isolated / "a.md").write_text("PMID: 11111\n")
    (isolated / "b.md").write_text("PMID: 22222\nPMID: 33333\n")
    (isolated / "clean.md").write_text("nothing here\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.files_scanned == 3
    assert rep.files_with_issues == 2
    assert len(rep.issues) == 3


# ── recursive walk ──────────────────────────────────────────────


def test_recursive_walk(isolated):
    nested = isolated / "subdir" / "nested"
    nested.mkdir(parents=True)
    (nested / "deep.md").write_text("PMID: 99999\n")
    from agents.citation_linter import lint
    rep = lint(isolated)
    assert rep.files_scanned == 1
    assert "deep.md" in rep.issues[0].file


# ── missing root ────────────────────────────────────────────────


def test_missing_root_returns_empty(isolated, tmp_path):
    from agents.citation_linter import lint
    rep = lint(tmp_path / "no-such-dir")
    assert rep.files_scanned == 0
    assert rep.has_problems is False
