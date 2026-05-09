"""tests/test_worktree.py — W1 git-worktree isolation (2026-05-03).

Each test sets up a throwaway git repo in tmp_path, then drives
`agents.worktree` against it. We never touch the user's real repos.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agents import worktree as wt


def _run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          check=False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Initialise a tiny git repo with one commit on `main`."""
    r = tmp_path / "repo"
    r.mkdir()
    _run(["git", "init", "-q", "--initial-branch=main", "."], cwd=r)
    _run(["git", "config", "user.email", "test@local"], cwd=r)
    _run(["git", "config", "user.name", "test"], cwd=r)
    (r / "README.md").write_text("hi")
    _run(["git", "add", "."], cwd=r)
    _run(["git", "commit", "-q", "-m", "initial"], cwd=r)
    monkeypatch.setenv("AIM_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    return r


# ── basic happy path ─────────────────────────────────────────────


def test_isolate_creates_branch_and_worktree(repo):
    with wt.isolate(repo, branch="aim/exp-x") as w:
        assert w.path.exists()
        assert w.branch == "aim/exp-x"
        assert (w.path / "README.md").exists()
        # Branch reachable in the parent repo too.
        out = _run(["git", "branch", "--list", "aim/exp-x"], cwd=repo).stdout
        assert "aim/exp-x" in out
    # keep_on_success default = True → branch survives after exit.
    out = _run(["git", "branch", "--list", "aim/exp-x"], cwd=repo).stdout
    assert "aim/exp-x" in out


def test_isolate_keep_false_discards(repo):
    with wt.isolate(repo, branch="aim/exp-disposable",
                     keep_on_success=False) as w:
        path = w.path
        assert path.exists()
    # After exit: gone.
    assert not path.exists()
    out = _run(["git", "branch", "--list", "aim/exp-disposable"], cwd=repo).stdout
    assert "aim/exp-disposable" not in out


def test_isolate_discards_on_exception(repo):
    path: Path = None  # type: ignore
    branch = "aim/exp-boom"
    with pytest.raises(RuntimeError):
        with wt.isolate(repo, branch=branch) as w:
            path = w.path
            raise RuntimeError("boom")
    assert path is not None
    assert not path.exists()
    out = _run(["git", "branch", "--list", branch], cwd=repo).stdout
    assert branch not in out


def test_isolate_auto_branch_when_none(repo):
    with wt.isolate(repo) as w:
        assert w.branch.startswith("aim/exp-")
        assert w.path.exists()


# ── file ops ─────────────────────────────────────────────────────


def test_write_and_read_inside_worktree(repo):
    with wt.isolate(repo) as w:
        w.write_file("nested/file.txt", "hello")
        assert w.read_file("nested/file.txt") == "hello"


def test_write_rejects_path_escape(repo):
    with wt.isolate(repo) as w:
        with pytest.raises(ValueError):
            w.write_file("../escape.txt", "evil")


def test_read_rejects_path_escape(repo):
    with wt.isolate(repo) as w:
        with pytest.raises(ValueError):
            w.read_file("../README.md")


# ── commit ────────────────────────────────────────────────────────


def test_commit_returns_sha(repo):
    with wt.isolate(repo) as w:
        w.write_file("new.txt", "hi")
        sha = w.commit("add new")
        assert len(sha) == 40
        # Commit landed on the worktree branch.
        log = _run(["git", "log", "--format=%s", "-1", w.branch],
                   cwd=repo).stdout
        assert "add new" in log


def test_commit_is_idempotent_when_nothing_to_commit(repo):
    with wt.isolate(repo) as w:
        sha = w.commit("noop")  # no file changes vs HEAD
        assert len(sha) == 40   # still returns a sha (the prior HEAD)


# ── merge ────────────────────────────────────────────────────────


def test_merge_to_main_fast_forward(repo):
    with wt.isolate(repo, branch="aim/ff") as w:
        w.write_file("ff.txt", "x")
        w.commit("ff change")
        ok = w.merge_to("main")
        assert ok is True
    assert (repo / "ff.txt").read_text() == "x"


# ── run_tests ────────────────────────────────────────────────────


def test_run_tests_via_validator(repo):
    with wt.isolate(repo) as w:
        r = w.run_tests("ls -la")
        assert r.ok
        assert r.rc == 0


def test_run_tests_blocks_dangerous_command(repo):
    with wt.isolate(repo) as w:
        r = w.run_tests("python -c \"import os\"")
        assert not r.ok
        assert "PERMISSION" in r.stderr


# ── orphan cleanup ───────────────────────────────────────────────


def test_cleanup_orphans_targets_aim_branches(repo):
    # Create one AIM-worktree, one user worktree.
    with wt.isolate(repo, branch="aim/exp-old") as _w1:
        pass
    _run(["git", "branch", "user-feature"], cwd=repo)
    # Force AIM dir mtime backwards.
    aim_dir = wt.worktrees_root() / "aim_exp-old"
    if aim_dir.exists():
        old = 1700_000_000  # 2023-11-15
        os.utime(aim_dir, (old, old))
    removed = wt.cleanup_orphans(repo, older_than_hours=1.0)
    assert any("aim/exp-old" in b for b in removed)
    # User-feature branch untouched.
    out = _run(["git", "branch", "--list", "user-feature"], cwd=repo).stdout
    assert "user-feature" in out


def test_cleanup_orphans_dry_run_keeps_them(repo):
    with wt.isolate(repo, branch="aim/exp-dry") as _w:
        pass
    aim_dir = wt.worktrees_root() / "aim_exp-dry"
    if aim_dir.exists():
        old = 1700_000_000
        os.utime(aim_dir, (old, old))
    removed = wt.cleanup_orphans(repo, older_than_hours=1.0, dry_run=True)
    assert "aim/exp-dry" in removed
    out = _run(["git", "branch", "--list", "aim/exp-dry"], cwd=repo).stdout
    assert "aim/exp-dry" in out


# ── input validation ────────────────────────────────────────────


def test_isolate_rejects_non_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_WORKTREE_ROOT", str(tmp_path / "wt"))
    with pytest.raises(FileNotFoundError):
        with wt.isolate(tmp_path / "not-a-repo"):
            pass
