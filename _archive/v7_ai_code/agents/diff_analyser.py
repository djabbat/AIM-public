"""agents/diff_analyser.py — git-diff classifier + commit suggester (DA1, 2026-05-03).

Reads `git status --porcelain` + `git diff` + `git diff --staged` for
the current repo, then:

  1. Classifies the change set into Conventional-Commit-style buckets:
     test, feat, fix, refactor, docs, build, chore, perf, style, ci.
  2. Counts files per bucket; produces a one-line subject + a short body
     summarising the dominant change. No LLM unless `polish=True`.
  3. Optionally polishes the suggestion via `llm.ask_fast`.

This is a "would-be" commit suggester — it never auto-commits. The
output goes to `aim git suggest`, which the user can paste directly
into `git commit -m`.

Public API:
    analyse(repo) -> Analysis
    suggest_message(repo, *, polish=False) -> str
"""
from __future__ import annotations

import dataclasses
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.diff_analyser")


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Analysis:
    files_changed: list[str]
    files_added: list[str]
    files_deleted: list[str]
    insertions: int
    deletions: int
    bucket_counts: dict[str, int]   # {bucket_name: file_count}
    primary_bucket: str
    short_summary: str

    def is_empty(self) -> bool:
        return not (self.files_changed or self.files_added
                     or self.files_deleted)


# ── git wrappers ─────────────────────────────────────────────────


def _git(repo: Path, *args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=repo,
                             capture_output=True, text=True, check=False)
        return out.stdout
    except FileNotFoundError:
        return ""


def _porcelain(repo: Path) -> list[tuple[str, str]]:
    """Status rows including individual untracked files (not just dirs).

    `git status --porcelain` reports only the dir for untracked content.
    `--untracked-files=all` (or `-uall`) walks every file inside.
    """
    out = _git(repo, "status", "--porcelain=v1", "-uall")
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        # `XY path` (XY is two-char status) — handle " M ", "??", "A ", etc.
        status = line[:2]
        path = line[3:].strip()
        rows.append((status, path))
    return rows


def _diff_text(repo: Path) -> str:
    """Combined HEAD diff including untracked files (intent-to-add).

    Used for keyword matching (fix/regression/etc.) — we don't want to
    miss content in newly-added files.
    """
    _git(repo, "add", "--intent-to-add", "--", ".")
    return _git(repo, "diff", "HEAD")


def _diff_stat(repo: Path) -> tuple[int, int]:
    """(insertions, deletions) across staged + unstaged diff."""
    out = _git(repo, "diff", "--shortstat", "HEAD")
    ins = del_ = 0
    m = re.search(r"(\d+)\s+insertion", out)
    if m:
        ins = int(m.group(1))
    m = re.search(r"(\d+)\s+deletion", out)
    if m:
        del_ = int(m.group(1))
    return ins, del_


# ── classification ───────────────────────────────────────────────


_RULES: list[tuple[str, "re.Pattern[str]"]] = [
    ("test",    re.compile(r"(?:^|/)tests?(?:/|$)|_test\.|\.test\.|test_[\w-]+\.py")),
    ("docs",    re.compile(r"\.md$|\.rst$|^docs/|^README", re.I)),
    ("ci",      re.compile(r"^\.github/|^\.gitlab-ci\.yml$|/ci\.yml$|circleci")),
    ("build",   re.compile(r"^Cargo\.toml$|^pyproject\.toml$|^package\.json$|"
                            r"^Dockerfile|^Makefile$|requirements.*\.txt$")),
    ("style",   re.compile(r"\.css$|\.scss$|\.sass$|\.less$")),
    ("chore",   re.compile(r"^\.gitignore$|^LICENSE$|^\.editorconfig$")),
    ("perf",    re.compile(r"perf|bench|optimi[sz]e", re.I)),
]


def _bucket_for_path(path: str) -> str:
    for name, pat in _RULES:
        if pat.search(path):
            return name
    return "code"  # general code change; resolved to feat/fix/refactor below


def _heuristic_code_subtype(repo: Path, files: list[str],
                             insertions: int, deletions: int) -> str:
    """For 'code' bucket files, decide feat/fix/refactor based on signals."""
    text = _diff_text(repo) + _git(repo, "diff", "--staged")
    low = text.lower()
    if any(kw in low for kw in ("fix(", "fix:", "fixed ", "bugfix",
                                  "regression", "крэш", "ошибк")):
        return "fix"
    if insertions > 5 * max(deletions, 1):
        return "feat"
    if deletions > 2 * max(insertions, 1):
        return "refactor"
    return "feat"


# ── analyse ──────────────────────────────────────────────────────


def analyse(repo: Path | str) -> Analysis:
    repo = Path(repo).expanduser().resolve()
    rows = _porcelain(repo)
    files_added: list[str] = []
    files_deleted: list[str] = []
    files_changed: list[str] = []
    for status, path in rows:
        if "?" in status or "A" in status:
            files_added.append(path)
        elif "D" in status:
            files_deleted.append(path)
        else:
            files_changed.append(path)

    all_files = files_added + files_deleted + files_changed
    counts: dict[str, int] = {}
    for p in all_files:
        b = _bucket_for_path(p)
        counts[b] = counts.get(b, 0) + 1

    insertions, deletions = _diff_stat(repo)
    primary = "chore"
    if counts:
        primary = max(counts, key=lambda k: counts[k])
    if primary == "code":
        primary = _heuristic_code_subtype(repo, all_files, insertions, deletions)

    summary_parts: list[str] = []
    if files_added:
        summary_parts.append(f"+{len(files_added)}")
    if files_changed:
        summary_parts.append(f"~{len(files_changed)}")
    if files_deleted:
        summary_parts.append(f"-{len(files_deleted)}")
    short = (" ".join(summary_parts) +
              f"  ({insertions}+/{deletions}- lines)")

    return Analysis(
        files_changed=files_changed,
        files_added=files_added,
        files_deleted=files_deleted,
        insertions=insertions,
        deletions=deletions,
        bucket_counts=counts,
        primary_bucket=primary,
        short_summary=short.strip(),
    )


# ── commit message suggestion ────────────────────────────────────


def _scope_hint(files: list[str]) -> str:
    """Pick a scope from the most common top-level dir."""
    if not files:
        return ""
    tops: dict[str, int] = {}
    for f in files:
        head, _, _ = f.partition("/")
        tops[head] = tops.get(head, 0) + 1
    return max(tops, key=tops.get) if tops else ""


def suggest_message(repo: Path | str, *, polish: bool = False) -> str:
    a = analyse(repo)
    if a.is_empty():
        return "(no changes to commit)"
    scope = _scope_hint(a.files_added + a.files_changed + a.files_deleted)
    type_ = a.primary_bucket
    # Conventional commits: type(scope): subject
    subject_bits = [type_]
    if scope and scope != type_:
        subject_bits[-1] += f"({scope})"
    subject_bits.append(": ")

    # Short description: dominant kind of change.
    if type_ == "test":
        descr = f"add/update tests across {len(a.files_added + a.files_changed)} files"
    elif type_ == "docs":
        descr = "update documentation"
    elif type_ == "ci":
        descr = "tweak CI configuration"
    elif type_ == "build":
        descr = "update build / dependencies"
    elif type_ == "fix":
        descr = "fix bug"
    elif type_ == "feat":
        descr = "add new functionality"
    elif type_ == "refactor":
        descr = "refactor"
    elif type_ == "perf":
        descr = "performance improvement"
    elif type_ == "style":
        descr = "style updates"
    else:
        descr = "chores"

    body = [
        f"{''.join(subject_bits)}{descr}",
        "",
        a.short_summary,
    ]
    if a.bucket_counts:
        body.append("Buckets: " + ", ".join(
            f"{k}={v}" for k, v in sorted(a.bucket_counts.items(),
                                            key=lambda kv: -kv[1])))

    text = "\n".join(body)
    if polish:
        try:
            from llm import ask_fast
            polished = ask_fast(
                "Polish this commit message; preserve facts, ≤ 72 chars subject:\n\n"
                + text)
            if polished and polished.strip():
                text = polished.strip()
        except Exception as e:
            log.debug("polish failed: %s", e)
    return text
