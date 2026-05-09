"""tests/test_diff_analyser.py — DA1 (2026-05-03)."""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture
def repo(tmp_path):
    """Throwaway git repo with one initial commit."""
    r = tmp_path / "repo"
    r.mkdir()
    def run(*a):
        return subprocess.run(["git", *a], cwd=r, capture_output=True,
                              text=True, check=False)
    run("init", "-q", "--initial-branch=main", ".")
    run("config", "user.email", "t@local")
    run("config", "user.name", "t")
    (r / "README.md").write_text("hello")
    run("add", ".")
    run("commit", "-q", "-m", "initial")
    return r


# ── path → bucket ────────────────────────────────────────────────


@pytest.mark.parametrize("path,bucket", [
    ("tests/test_x.py", "test"),
    ("README.md", "docs"),
    ("docs/intro.rst", "docs"),
    (".github/workflows/ci.yml", "ci"),
    ("Dockerfile", "build"),
    ("Cargo.toml", "build"),
    ("requirements.txt", "build"),
    ("style.css", "style"),
    (".gitignore", "chore"),
    ("agents/foo.py", "code"),
])
def test_bucket_for_path(path, bucket):
    from agents.diff_analyser import _bucket_for_path
    assert _bucket_for_path(path) == bucket


# ── analyse ──────────────────────────────────────────────────────


def test_analyse_empty_repo(repo):
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert a.is_empty()


def test_analyse_added_files(repo):
    (repo / "agents").mkdir()
    (repo / "agents" / "new.py").write_text("def f(): pass\n")
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert "agents/new.py" in a.files_added
    assert a.is_empty() is False


def test_analyse_modified_file_with_dominant_test(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    (repo / "tests" / "test_b.py").write_text("def test_b(): pass\n")
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert a.primary_bucket == "test"


def test_analyse_modified_docs_dominates(repo):
    (repo / "agents").mkdir()
    (repo / "agents" / "x.py").write_text("x = 1\n")
    (repo / "docs.md").write_text("hi")
    (repo / "more.md").write_text("hi")
    (repo / "another.md").write_text("hi")
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert a.primary_bucket == "docs"


def test_analyse_code_split_into_feat(repo, monkeypatch):
    (repo / "feat.py").write_text("def new(): pass\n" * 20)
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert a.primary_bucket in ("feat", "refactor")


def test_analyse_code_with_fix_keyword(repo, monkeypatch):
    """If diff text contains 'fix:' / 'bugfix' / 'regression', bucket is fix."""
    (repo / "src.py").write_text(
        "# fix: handle empty input\n"
        "def f(): return 0\n"
    )
    from agents.diff_analyser import analyse
    a = analyse(repo)
    assert a.primary_bucket == "fix"


# ── suggest_message ──────────────────────────────────────────────


def test_suggest_no_changes(repo):
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo)
    assert "no changes" in msg


def test_suggest_test_change(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo)
    first = msg.splitlines()[0]
    assert first.startswith("test")
    assert ":" in first


def test_suggest_docs_change(repo):
    (repo / "GUIDE.md").write_text("docs body\n")
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo)
    assert msg.splitlines()[0].startswith("docs")


def test_suggest_includes_bucket_summary(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("x")
    (repo / "doc.md").write_text("docs")
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo)
    assert "Buckets:" in msg


def test_suggest_polish_failure_does_not_crash(repo, monkeypatch):
    (repo / "x.py").write_text("y = 1\n")
    import llm

    def boom(_p):
        raise RuntimeError("nope")

    monkeypatch.setattr(llm, "ask_fast", boom, raising=False)
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo, polish=True)
    # Falls back to the un-polished body.
    assert "(" in msg and ")" in msg


def test_suggest_polish_replaces_text(repo, monkeypatch):
    (repo / "x.py").write_text("y = 1\n")
    import llm
    monkeypatch.setattr(llm, "ask_fast", lambda _p: "polished output",
                         raising=False)
    from agents.diff_analyser import suggest_message
    msg = suggest_message(repo, polish=True)
    assert msg == "polished output"


# ── scope inference ─────────────────────────────────────────────


def test_scope_hint_picks_dominant_dir():
    from agents.diff_analyser import _scope_hint
    out = _scope_hint(["agents/a.py", "agents/b.py", "scripts/c.py"])
    assert out == "agents"


def test_scope_hint_empty():
    from agents.diff_analyser import _scope_hint
    assert _scope_hint([]) == ""
