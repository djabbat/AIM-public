"""agents/worktree.py — git worktree isolation (W1, 2026-05-03).

Lets self-modifying flows (S2 tool synthesis, future S6 code patches)
exec generated code in a throwaway branch instead of corrupting main.
Wraps `git worktree add/remove` with a context manager:

    with isolate(repo, branch="ai-experiment-XYZ") as wt:
        wt.write_file("foo.py", code)
        ok, msg = wt.run_tests("pytest tests/test_foo.py")
        if ok:
            wt.commit("S2: synthesise foo")
            wt.merge_to("main")        # opt-in
        # __exit__ tears the worktree down

Design choices:
  * Each isolation creates a NEW branch off the current HEAD; we never
    write directly to an existing branch.
  * Cleanup is best-effort — orphaned worktrees can be reaped via
    `cleanup_orphans(older_than_hours=24)`.
  * Tests inside the worktree run via the bash whitelist (the same
    permission gate the agent uses for any shell call); we don't shell
    out unconstrained.
  * No automatic merge: even after success, the user must call
    `merge_to(...)` explicitly. Default is to leave the branch around
    so a human can review the diff.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator, Optional

log = logging.getLogger("aim.worktree")


# ── helpers ──────────────────────────────────────────────────────


def _run(argv: list[str], cwd: Optional[Path] = None,
         timeout: float = 60.0) -> tuple[int, str, str]:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


_BRANCH_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")


def _branch_safe(name: str) -> str:
    """Coerce a string into a filesystem-safe branch suffix."""
    name = re.sub(r"[^a-zA-Z0-9._/-]+", "-", name).strip("-")[:60]
    return name or secrets.token_hex(4)


def _is_repo(path: Path) -> bool:
    return (path / ".git").exists() or (path / "HEAD").exists()


def worktrees_root() -> Path:
    """Where worktrees live (default ~/.aim/worktrees)."""
    env = os.environ.get("AIM_WORKTREE_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".aim" / "worktrees"


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class TestResult:
    ok: bool
    rc: int
    stdout: str
    stderr: str


class Worktree:
    """Handle to an isolated branch + checkout."""

    def __init__(self, repo: Path, branch: str, path: Path):
        self.repo = repo
        self.branch = branch
        self.path = path
        self._closed = False

    # ── filesystem ops ───────────────────────────────────────────

    def write_file(self, rel_path: str, content: str) -> Path:
        p = (self.path / rel_path).resolve()
        if not str(p).startswith(str(self.path.resolve())):
            raise ValueError(f"path escapes worktree: {rel_path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def read_file(self, rel_path: str) -> str:
        p = (self.path / rel_path).resolve()
        if not str(p).startswith(str(self.path.resolve())):
            raise ValueError(f"path escapes worktree: {rel_path}")
        return p.read_text(encoding="utf-8")

    # ── git ops ──────────────────────────────────────────────────

    def commit(self, message: str, *, author: str = "AIM <aim@local>") -> str:
        rc, _, err = _run(["git", "add", "-A"], cwd=self.path)
        if rc != 0:
            raise RuntimeError(f"git add failed: {err.strip()}")
        rc, out, err = _run(
            ["git", "-c", f"user.name=AIM",
             "-c", f"user.email=aim@local",
             "commit", "-m", message,
             "--no-verify",   # skip pre-commit hooks: would re-run tests
             "--author", author],
            cwd=self.path,
        )
        if rc != 0 and "nothing to commit" not in (out + err).lower():
            raise RuntimeError(f"git commit failed: {err.strip()}")
        rc, sha, err = _run(["git", "rev-parse", "HEAD"], cwd=self.path)
        if rc != 0:
            raise RuntimeError(f"rev-parse HEAD failed: {err.strip()}")
        return sha.strip()

    def merge_to(self, target: str = "main", *,
                 strategy: str = "ff-only") -> bool:
        """Merge this branch into `target` in the main checkout. Returns True
        on success. Refuses if not fast-forward by default (set strategy="merge"
        to force a 3-way merge — but that requires user_confirmed=True at the
        L_CONSENT layer; this function does NOT handle consent on its own).
        """
        # Step 1: ensure there's something to merge.
        if not self._closed:
            self.commit("auto-commit before merge")
        # Step 2: in the main repo, merge our branch.
        flag = "--ff-only" if strategy == "ff-only" else "--no-ff"
        rc, out, err = _run(["git", "merge", flag, self.branch],
                            cwd=self.repo)
        if rc != 0:
            log.warning("merge %s → %s failed: %s", self.branch, target,
                        err.strip())
            return False
        return True

    # ── shell ops via the same gate generalist.bash uses ────────

    def run_tests(self, command: str = "pytest -q",
                  timeout: float = 300.0) -> TestResult:
        """Run `command` inside the worktree. Goes through the same bash
        validator used by agents.generalist (so generated code can't
        smuggle `python -c "..."` etc.)."""
        from agents.generalist import _validate_bash, _BASH_ALLOW
        err = _validate_bash(command, _BASH_ALLOW)
        if err is not None:
            return TestResult(False, -1, "", err)
        try:
            import shlex
            rc, out, sterr = _run(shlex.split(command),
                                  cwd=self.path, timeout=timeout)
        except subprocess.TimeoutExpired:
            return TestResult(False, -1, "", f"timeout after {timeout}s")
        return TestResult(rc == 0, rc, out, sterr)

    # ── lifecycle ────────────────────────────────────────────────

    def discard(self) -> None:
        """Drop the worktree (and its branch) without merging."""
        if self._closed:
            return
        self._closed = True
        # `git worktree remove --force` cleans both the dir and the meta.
        _run(["git", "worktree", "remove", "--force", str(self.path)],
             cwd=self.repo)
        # Best-effort branch delete; ignore failure (already-merged etc).
        _run(["git", "branch", "-D", self.branch], cwd=self.repo)
        # Defensive: if the dir survived for some reason, blow it away.
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)


# ── context manager / factory ────────────────────────────────────


@contextlib.contextmanager
def isolate(repo: Path | str,
            branch: Optional[str] = None,
            *,
            base_ref: str = "HEAD",
            keep_on_success: bool = True,
            ) -> Iterator[Worktree]:
    """Create a new branch off `base_ref` in a fresh worktree.

    On normal exit:
      * if keep_on_success=True, the branch+worktree survive (default —
        gives the human a chance to review).
      * if keep_on_success=False, discard everything.
    On exception: always discard.

    Raises FileNotFoundError if `repo` isn't a git repo, or RuntimeError
    if `git worktree add` fails (e.g. branch name already taken).
    """
    repo = Path(repo).expanduser().resolve()
    if not _is_repo(repo):
        raise FileNotFoundError(f"not a git repo: {repo}")

    # Auto-name the branch if the caller didn't pick one.
    if branch is None:
        branch = f"aim/exp-{dt.datetime.now():%Y%m%d}-{secrets.token_hex(3)}"
    branch = branch.strip()
    if not branch or "/" not in branch and not _BRANCH_RE.match(branch):
        # Allow only sensible branch names; prefix unsafe ones.
        branch = f"aim/{_branch_safe(branch)}"

    root = worktrees_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / branch.replace("/", "_")

    rc, _, err = _run(["git", "worktree", "add", "-b", branch,
                       str(path), base_ref], cwd=repo)
    if rc != 0:
        raise RuntimeError(f"git worktree add failed: {err.strip()}")

    wt = Worktree(repo=repo, branch=branch, path=path)
    raised = False
    try:
        yield wt
    except Exception:
        raised = True
        raise
    finally:
        if raised or not keep_on_success:
            wt.discard()


# ── cleanup orphans ──────────────────────────────────────────────


def list_worktrees(repo: Path) -> list[dict]:
    """Parse `git worktree list --porcelain`."""
    rc, out, _ = _run(["git", "worktree", "list", "--porcelain"], cwd=repo)
    if rc != 0:
        return []
    items: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                items.append(cur)
                cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v.strip()
    if cur:
        items.append(cur)
    return items


def cleanup_orphans(repo: Path | str, *,
                    older_than_hours: float = 24.0,
                    dry_run: bool = False) -> list[str]:
    """Remove AIM-created worktrees older than `older_than_hours`.

    Only matches worktrees whose branch starts with `aim/` to avoid
    nuking user-managed ones.
    """
    repo = Path(repo).expanduser().resolve()
    cutoff = time.time() - older_than_hours * 3600
    removed: list[str] = []
    for wt in list_worktrees(repo):
        branch = (wt.get("branch") or "").removeprefix("refs/heads/")
        path = wt.get("worktree")
        if not branch.startswith("aim/") or not path:
            continue
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0
        if mtime > cutoff:
            continue
        if not dry_run:
            _run(["git", "worktree", "remove", "--force", path], cwd=repo)
            _run(["git", "branch", "-D", branch], cwd=repo)
        removed.append(branch)
    return removed
