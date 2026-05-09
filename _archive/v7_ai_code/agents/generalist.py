"""agents/generalist.py — tool-using executor (Claude-style agency).

Replaces the rigid Planner→Executor→Reviewer LangGraph 3-node loop with a
free-form ReAct-style cycle:

    while not done:
        next_action = LLM(history)
        if next_action is "final":
            return answer
        result = run_tool(next_action)
        history.append(result)

The LLM is DeepSeek-V4 (cloud, default per user 2026-04-30). Tools wrap
the existing AIM stack: read/edit/bash, memory_recall/save, doctor delegate,
writer delegate, researcher delegate, kernel_check, citation_verify.

Public API:
    run(task, *, max_iters=10, kernel=True, model_hint=None) → dict
        returns {"answer": str, "trace": [...], "tools_used": [...]}
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import platform
import re
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from llm import ask, ask_deep, ask_long, ask_critical

log = logging.getLogger("aim.generalist")


# ── Tool registry ──────────────────────────────────────────────────────────


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    schema: dict = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)   # [{call, result_preview}]


_TOOLS: dict[str, Tool] = {}
_TOOLS_LOCK = threading.RLock()


def register_tool(name: str, description: str, schema: dict,
                  examples: Optional[list[dict]] = None):
    def deco(fn):
        with _TOOLS_LOCK:
            _TOOLS[name] = Tool(name=name, description=description, fn=fn,
                                 schema=schema, examples=examples or [])
        return fn
    return deco


# ── Built-in tools (file I/O, bash, memory, agents, kernel) ────────────────


@register_tool(
    "todo_write",
    "Publish a visible TODO checklist to the user terminal. Use for any task "
    "with ≥3 distinct steps so the user sees progress. Pass the FULL list "
    "every time — items are replaced wholesale, not merged. Each item: "
    "{id: stable string key, content: 1-line description, status: "
    "'pending' | 'in_progress' | 'completed'}. Mark exactly one as "
    "'in_progress' while you work on it; flip to 'completed' as soon as the "
    "step is done. The list renders in a top panel of the AIM AI REPL with "
    "▢ ▣ ☑ markers.",
    {"items": "list of {id, content, status} dicts"},
)
def _t_todo_write(items: list[dict]) -> str:
    """Update the visible TODO checklist.

    Anchor preservation: if an existing item with the same `id` is on
    disk and its content is LONGER than the new content (typical
    accidental shortening — e.g. dropping absolute paths), keep the
    longer pre-existing content. Status updates always go through.
    Adding new items / removing old ones is allowed.
    """
    import json as _j
    import pathlib as _pl
    import time as _time
    p = _pl.Path.home() / ".cache" / "aim" / "repl_todos.json"
    p.parent.mkdir(parents=True, exist_ok=True)

    # Load previous state (id → previous content) so we can refuse silent
    # shortening of items the user (or an earlier turn) anchored.
    prev_by_id: dict[str, str] = {}
    try:
        prev = _j.loads(p.read_text(encoding="utf-8"))
        for it in prev.get("items") or []:
            if isinstance(it, dict):
                prev_by_id[str(it.get("id", ""))] = str(it.get("content", ""))
    except (OSError, ValueError):
        pass

    valid: list[dict] = []
    preserved = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("id") or it.get("ID") or "").strip() or str(len(valid) + 1)
        content = str(it.get("content") or it.get("desc") or "").strip()
        status = str(it.get("status") or "pending").strip().lower()
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        if not content:
            continue
        # Anchor preservation: if previous content exists and was longer,
        # keep it. Treat shortening as accidental (LLM dropping path info).
        prev_content = prev_by_id.get(sid, "")
        if prev_content and len(prev_content) > len(content) + 10:
            content = prev_content
            preserved += 1
        valid.append({"id": sid, "content": content[:500], "status": status})
    try:
        p.write_text(
            _j.dumps({"items": valid, "ts": _time.time()},
                     ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        return f"ERROR:IO:{e}"
    done = sum(1 for x in valid if x["status"] == "completed")
    note = f", {preserved} content anchors preserved" if preserved else ""
    return f"OK: todo list updated ({done}/{len(valid)} done{note})"


@register_tool(
    "read_file",
    "Read a UTF-8 text file. Returns first 6000 chars; pass offset/limit to page.",
    {"path": "absolute path", "offset": "int line start (default 0)",
     "limit": "int line count (default 200)"},
)
def _t_read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    blocked = _gate_path(path, write=False)
    if blocked:
        return blocked
    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR:NOT_FOUND:{p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sl = lines[offset:offset + limit]
    return "\n".join(sl)[:6000]
# gate functions extracted to agents/generalist_pkg/gates.py (2026-05-07).
# Re-imported so legacy callers can keep using these names.
from agents.generalist_pkg.gates import (  # noqa: E402
    _post_write_verify,
    _gate_external,
    _gate_path,
    _gate_write,
    _SECRET_PATH_RE,
)

@register_tool(
    "view_file",
    "Read a file with LINE-NUMBERED viewport and total-line metadata. Use when planning a precise edit, especially with apply_patch. SWE-agent-style viewport.",
    {"path": "absolute path",
     "start_line": "int default 1 (1-indexed)",
     "end_line": "int default 200; -1 = end-of-file",
     "context_around": "if set, return ±N lines around a search regex"},
    examples=[{
        "call": {"tool": "view_file",
                 "args": {"path": "/path/to/file.py",
                          "start_line": 100, "end_line": 150}},
    }],
)
def _t_view_file(path: str, start_line: int = 1, end_line: int = 200,
                 context_around: str = "") -> str:
    blocked = _gate_path(path, write=False)
    if blocked:
        return blocked
    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR:NOT_FOUND:{p}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR:INTERNAL:{e}"
    lines = text.splitlines()
    total = len(lines)
    if context_around:
        try:
            import re as _re
            rgx = _re.compile(context_around)
        except _re.error as e:
            return f"ERROR:INVALID_INPUT:bad regex — {e}"
        hits = []
        for i, ln in enumerate(lines, 1):
            if rgx.search(ln):
                lo = max(1, i - 8)
                hi = min(total, i + 8)
                hits.append((lo, hi, i))
        if not hits:
            return f"(no matches for /{context_around}/ in {total} lines)"
        out = [f"FILE: {p}  ({total} lines, {len(hits)} matches)"]
        for lo, hi, mid in hits[:5]:
            out.append(f"\n— ±8 around line {mid} —")
            for j in range(lo, hi + 1):
                marker = "→" if j == mid else " "
                out.append(f"{marker}{j:>5}: {lines[j-1]}")
        return "\n".join(out)[:6000]
    if end_line == -1:
        end_line = total
    start_line = max(1, start_line)
    end_line = min(total, end_line)
    chunk = lines[start_line - 1:end_line]
    out = [f"FILE: {p}  ({total} total lines, viewing {start_line}-{end_line})"]
    for j, ln in enumerate(chunk, start_line):
        out.append(f"{j:>5}: {ln}")
    return "\n".join(out)[:8000]


@register_tool(
    "write_file",
    "Write text to a file (overwrites). Returns 'OK <bytes>' on success. Blocked by L_PRIVACY if path is under Patients/ or content contains PII unless AIM_ALLOW_PATIENT_WRITE=1.",
    {"path": "absolute path", "content": "text to write"},
)
def _t_write_file(path: str, content: str) -> str:
    blocked = _gate_path(path, write=True) or _gate_write(path, content)
    if blocked:
        return blocked
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _post_write_verify(p)
    return f"OK {len(content)} bytes → {p}"


@register_tool(
    "edit_file",
    "Replace ONE occurrence of old_text with new_text in the file. old_text must be unique. On match-not-unique returns context lines so you can refine.",
    {"path": "abs path", "old_text": "exact match", "new_text": "replacement"},
)
def _t_edit_file(path: str, old_text: str, new_text: str) -> str:
    blocked = _gate_path(path, write=True)
    if blocked:
        return blocked
    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR:NOT_FOUND:{p}"
    content = p.read_text(encoding="utf-8")
    occ = content.count(old_text)
    if occ == 0:
        return "ERROR:NOT_FOUND:old_text not found in file"
    if occ > 1:
        # Surface a few lines of context for each occurrence so the LLM can
        # add more uniqueness instead of blindly retrying.
        snippets = []
        idx = 0
        for i in range(occ):
            j = content.find(old_text, idx)
            line = content.count("\n", 0, j) + 1
            snippets.append(f"  line {line}")
            idx = j + len(old_text)
        return (f"ERROR:INVALID_INPUT:old_text occurs {occ}× — at "
                f"{', '.join(snippets)}. Add surrounding context to make it unique.")
    blocked = _gate_write(path, new_text)
    if blocked:
        return blocked
    p.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    _post_write_verify(p)
    return "OK 1 replacement"


@register_tool(
    "apply_patch",
    "Apply a unified diff to one or more files atomically (uses `patch -p0` or git apply). Format: standard `--- a/file` / `+++ b/file` headers. Either all hunks apply or none do.",
    {"diff": "unified-diff text including file headers and @@ hunks",
     "strip": "int (default 0; pass 1 if diff has a/ and b/ prefixes)"},
    examples=[{
        "call": {"tool": "apply_patch",
                 "args": {"diff": "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
                          "strip": 1}}
    }],
)
def _t_apply_patch(diff: str, strip: int = 0) -> str:
    if not diff.strip():
        return "ERROR:INVALID_INPUT:empty diff"
    if "@@" not in diff:
        return "ERROR:INVALID_INPUT:not a unified diff (no @@ hunk markers)"
    # G2 path sandbox: validate every target path in the diff before
    # touching the filesystem. The `+++ b/<path>` line names the file
    # that will receive writes.
    for line in diff.splitlines():
        if not line.startswith("+++ "):
            continue
        rhs = line[4:].strip()
        if rhs == "/dev/null":  # delete-file diff has +++ /dev/null
            continue
        # Strip the `b/` prefix when strip>0
        parts = rhs.split("/", strip) if strip > 0 else [rhs]
        target = parts[-1]
        # Skip timestamp suffix (some diffs have "path<TAB>2026-…")
        target = target.split("\t", 1)[0]
        blocked_path = _gate_path(target, write=True)
        if blocked_path:
            return blocked_path
    # L_PRIVACY: scan diff for Patients/ paths or PII patterns
    blocked = _gate_write("(patch)", diff)
    if blocked:
        return blocked
    # Try `git apply` first if available — better error messages, preserves
    # mode bits, supports binary diffs.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
        tmp = f.name
    try:
        # Try git apply --check first (no side-effects) to validate
        check = subprocess.run(["git", "apply", "--check",
                                f"-p{strip}", tmp],
                                capture_output=True, text=True)
        if check.returncode == 0:
            do = subprocess.run(["git", "apply", f"-p{strip}", tmp],
                                capture_output=True, text=True)
            if do.returncode == 0:
                return f"OK applied via git apply (-p{strip})"
            return f"ERROR:INTERNAL:git apply: {do.stderr.strip()}"
        # Fall back to standard `patch`
        do = subprocess.run(["patch", f"-p{strip}", "-N", "-i", tmp],
                            capture_output=True, text=True)
        if do.returncode == 0:
            return f"OK applied via patch -p{strip}\n{do.stdout.strip()[:1000]}"
        return (f"ERROR:INTERNAL:patch failed (rc={do.returncode}): "
                f"{do.stdout.strip()}\n{do.stderr.strip()}")[:2000]
    finally:
        Path(tmp).unlink(missing_ok=True)


@register_tool(
    "glob",
    "Glob for files matching a shell pattern (e.g. 'agents/*.py' or '**/*.md'). Returns up to 200 paths.",
    {"pattern": "glob pattern", "root": "optional root directory (default cwd)"},
)
def _t_glob(pattern: str, root: str = ".") -> str:
    from pathlib import Path as _P
    base = _P(root).expanduser().resolve()
    if not base.is_dir():
        return f"ERROR:NOT_FOUND:{base}"
    matches = sorted(str(p) for p in base.glob(pattern) if p.exists())[:200]
    return "\n".join(matches) or "(no matches)"


@register_tool(
    "grep",
    "Search for a regex pattern across files. Uses ripgrep if available, else Python re. Returns matches with file:line:text.",
    {"pattern": "regex (Python or POSIX-extended)", "path": "directory or file (default '.')",
     "max_results": "int default 100"},
)
def _t_grep(pattern: str, path: str = ".", max_results: int = 100) -> str:
    rg = subprocess.run(["which", "rg"], capture_output=True, text=True)
    if rg.returncode == 0 and rg.stdout.strip():
        out = subprocess.run(["rg", "--no-heading", "--line-number",
                               "-m", str(max_results), pattern, path],
                             capture_output=True, text=True, timeout=15)
        return (out.stdout.strip() or "(no matches)")[:6000]
    # Pure-Python fallback
    import re as _re
    try:
        rgx = _re.compile(pattern)
    except _re.error as e:
        return f"ERROR:INVALID_INPUT:bad regex — {e}"
    base = Path(path).expanduser()
    files = [base] if base.is_file() else \
            [p for p in base.rglob("*") if p.is_file() and p.stat().st_size < 5_000_000]
    out: list[str] = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8",
                                                  errors="replace").splitlines(), 1):
                if rgx.search(line):
                    out.append(f"{f}:{i}:{line[:200]}")
                    if len(out) >= max_results:
                        return "\n".join(out)[:6000]
        except Exception:
            continue
    return "\n".join(out)[:6000] or "(no matches)"


def _bwrap_available() -> bool:
    """Check if bubblewrap is installed (Linux only). Sandbox is opt-in via
    AIM_SANDBOX=1 — most users don't have bwrap installed by default."""
    if platform.system() != "Linux":
        return False
    try:
        return subprocess.run(["which", "bwrap"], capture_output=True,
                              text=True).returncode == 0
    except Exception:
        return False


def _maybe_sandbox(command: str) -> list[str]:
    """If AIM_SANDBOX=1 and bwrap is installed, wrap the command. Otherwise
    return a direct argv list (no shell parsing).

    We always shlex.split into argv so subprocess.Popen runs the binary
    directly without /bin/sh — this means even if our metachar regex
    missed something exotic, no shell will interpret it.
    """
    try:
        argv = shlex.split(command)
    except ValueError:
        # Fallback: validation should have rejected this earlier; if we
        # got here with unparseable input, force-fail by returning a no-op.
        argv = ["false"]
    if os.environ.get("AIM_SANDBOX") == "1" and _bwrap_available():
        return ["bwrap",
                "--ro-bind", "/", "/",
                "--tmpfs", "/tmp",
                "--proc", "/proc",
                "--dev", "/dev",
                "--unshare-all", "--share-net",
                "--die-with-parent",
                "--bind", str(Path.cwd()), str(Path.cwd()),  # writable cwd
                "--"] + argv
    return argv


_BASH_ALLOW = ("ls", "cat", "head", "tail", "wc", "grep", "find",
               "git", "python", "python3", "pytest", "pip", "echo",
               "diff", "stat", "file", "which")
# Async bash uses a wider allowlist for build/test workflows. Shells
# (bash/sh/zsh) and `make` are NOT allowed — they break the gate model.
_BASH_ASYNC_ALLOW = ("ls", "cat", "head", "tail", "wc", "grep", "find",
                     "git", "python", "python3", "pytest", "pip", "npm", "yarn",
                     "ollama", "echo", "diff", "uvicorn", "node", "rsync",
                     "cargo", "go", "mvn", "gradle")
# Shell metacharacters that enable command chaining / IO redirection /
# subshell execution. If any of these appears in the command, the
# whitelist on "first token" is meaningless.
_BASH_META_RE = re.compile(r"[;&|<>`\n\r]|\$\(")
# Token blacklist that's checked AFTER shlex.split, in case a chained
# command sneaks past _BASH_META_RE via a quoting trick.
_BASH_DANGEROUS_TOKENS = {
    "rm", "mv", "cp", "chmod", "chown", "dd", "mkfs",
    "sudo", "su", "doas", "kill", "killall",
    "curl", "wget", "ncat", "nc", "socat", "ssh", "scp", "sftp",
    # Shell / arbitrary exec wrappers — never allowed as args.
    "bash", "sh", "zsh", "fish", "ksh", "csh", "tcsh", "dash",
    "eval", "exec", "source",
    # File-mutating helpers that bypass per-command policy.
    "xargs", "tee", "truncate", "shred",
    # In-place editors.
    "ex", "vim", "nvim", "emacs",
}

# Per-command flag policy. Maps allowlisted first-token → set of forbidden
# argv tokens (case-sensitive, exact match). This is the second line of
# defence after metachar / dangerous-token checks: a whitelisted command
# may still be coerced into arbitrary execution via a single dangerous
# flag (`python -c`, `find -delete`, `pip install <pypi-pkg>`).
_BASH_FORBIDDEN_FLAGS = {
    # python -c / -m run arbitrary code; also disallow privileged stdin tricks
    # (-i interactive, -P isolated-but-still-arbitrary)
    "python":  {"-c", "-m", "-i"},
    "python3": {"-c", "-m", "-i"},
    # find: actions that mutate FS or execute external commands
    "find":    {"-delete", "-exec", "-execdir", "-ok", "-okdir",
                "-fprintf", "-fprint", "-fprint0", "-fls"},
    # git: subcommands that touch network, config, or remote state
    "git":     {"config", "remote", "clone", "fetch", "pull", "push",
                "submodule", "credential"},
    # pip: install/uninstall execute arbitrary setup.py from PyPI
    "pip":     {"install", "uninstall", "wheel", "download"},
    # pytest: --collect-only is fine; -p plugins can load arbitrary code
    "pytest":  {"-p", "--rootdir", "--import-mode"},
    # npm / yarn / cargo / go / mvn / gradle (used in async): block install/run
    "npm":     {"install", "i", "publish", "exec", "run-script"},
    "yarn":    {"add", "install", "publish", "exec", "run"},
    "cargo":   {"install", "publish", "run"},
    "go":      {"install", "get", "run"},
    "mvn":     {"deploy", "install"},
    "gradle":  {"publish"},
}


def _validate_bash(command: str, allow: tuple[str, ...]) -> Optional[str]:
    """Return None if command is safe to execute under the given allowlist,
    or an "ERROR:..." string explaining why it was rejected.

    Centralises the security gate so sync and async bash share the same
    policy. Order of checks (most cheap → most specific):

      1. metacharacters that enable chaining / redirection / subshells
      2. shlex parse (rejects unbalanced quotes etc.)
      3. first-token allowlist
      4. per-command forbidden-flag policy (python -c, find -delete, …)
      5. dangerous-token deny-list scan over remaining argv
    """
    if not isinstance(command, str):
        return "ERROR:INVALID_INPUT:command must be a string"
    if _BASH_META_RE.search(command):
        return ("ERROR:PERMISSION:shell metacharacters disallowed (; & | < > "
                "` $( newline). Run separate bash calls instead of chaining.")
    try:
        toks = shlex.split(command)
    except ValueError as e:
        return f"ERROR:INVALID_INPUT:cannot parse command: {e}"
    if not toks:
        return "ERROR:INVALID_INPUT:empty command"
    first = toks[0].split("/")[-1]
    if first not in allow:
        return (f"ERROR:PERMISSION:command '{first}' not whitelisted; "
                f"allowed: {allow}")
    forbidden = _BASH_FORBIDDEN_FLAGS.get(first, set())
    for t in toks[1:]:
        if t in forbidden:
            return (f"ERROR:PERMISSION:flag/subcommand '{t}' forbidden for "
                    f"'{first}' (deny-list).")
        bare = t.split("/")[-1]
        if bare in _BASH_DANGEROUS_TOKENS:
            return (f"ERROR:PERMISSION:dangerous token '{bare}' not allowed "
                    "as argument (deny-list)")
    return None


@register_tool(
    "bash",
    "Run a shell command. Whitelist on first token: ls, cat, head, tail, "
    "wc, grep, find, git, python/python3 (one-liners only via -c), pytest, "
    "pip, echo, diff, stat, file, which. REJECTS commands containing shell "
    "metacharacters (; & | < > ` $( newline) or dangerous tokens "
    "(rm/mv/cp/chmod/sudo/curl/wget/ssh/scp/nc/kill). 60s timeout. Optional "
    "bubblewrap sandbox via AIM_SANDBOX=1.",
    {"command": "shell command string"},
)
def _t_bash(command: str) -> str:
    err = _validate_bash(command, _BASH_ALLOW)
    if err is not None:
        return err
    cmd_list = _maybe_sandbox(command)
    try:
        proc = subprocess.run(cmd_list, capture_output=True,
                              text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "ERROR:TIMEOUT:bash exceeded 60s"
    out = (proc.stdout + proc.stderr).strip()
    return out[:4000] + ("\n[…truncated]" if len(out) > 4000 else "")


_SCRATCHPADS: dict[str, dict[str, str]] = {}   # run_id → {key: value}
_INTERRUPTED: dict[str, bool] = {}             # run_id → True if SIGINT
_STATE_LOCK = threading.RLock()                # protects all per-run dicts

# contextvars-based run id — every spawned thread/task inherits parent's
# context unless explicitly overridden by run() at start. This means
# delegate_parallel sub-agents see THEIR OWN run_id, not the parent's.
_RUN_ID_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_aim_run_id", default=None,
)


def _current_run_id() -> Optional[str]:
    return _RUN_ID_VAR.get()


def request_interrupt(run_id: Optional[str] = None) -> None:
    """Signal a running generalist to stop at the next safe point.
    `run_id=None` interrupts the run associated with the calling context."""
    if run_id is None:
        run_id = _current_run_id()
    if run_id:
        with _STATE_LOCK:
            _INTERRUPTED[run_id] = True


@register_tool(
    "note",
    "Save a value to the per-run scratchpad. Use for working memory: intermediate counts, plans, partial findings the user does NOT need to see in the final answer. Survives within one run() invocation.",
    {"key": "string identifier (no spaces preferred)",
     "value": "string content (≤4000 chars)"},
)
def _t_note(key: str, value: str) -> str:
    rid = _current_run_id()
    if rid is None:
        return "ERROR:UNAVAILABLE:no active run scratchpad"
    with _STATE_LOCK:
        pad = _SCRATCHPADS.setdefault(rid, {})
        pad[key] = str(value)[:4000]
        n = len(pad)
    return f"OK noted '{key}' ({n} entries)"


@register_tool(
    "recall",
    "Retrieve a previously noted value. With no key, returns the list of all keys in the scratchpad.",
    {"key": "string identifier (omit to list all keys)"},
)
def _t_recall(key: str = "") -> str:
    rid = _current_run_id()
    if rid is None:
        return "ERROR:UNAVAILABLE:no active run scratchpad"
    with _STATE_LOCK:
        pad = dict(_SCRATCHPADS.get(rid, {}))
    if not key:
        return "keys: " + ", ".join(sorted(pad)) if pad else "(scratchpad empty)"
    if key not in pad:
        return f"ERROR:NOT_FOUND:no entry '{key}'. Keys: {sorted(pad)}"
    return pad[key]


# ── Async bash jobs (long-running commands) ──────────────────────────────


_BG_JOBS: dict[str, dict] = {}   # job_id → {proc, stdout_path, started, cmd}
_BG_JOBS_LOCK = threading.RLock()


@register_tool(
    "bash_async",
    "Start a shell command in the background. Returns a job_id you can poll with bash_status / bash_output. Use for long-running things (test suites, builds, downloads). Whitelisted prefix as bash.",
    {"command": "shell command",
     "cwd": "optional working directory (default cwd)"},
)
def _t_bash_async(command: str, cwd: Optional[str] = None) -> str:
    import secrets as _sec, tempfile
    err = _validate_bash(command, _BASH_ASYNC_ALLOW)
    if err is not None:
        return err
    # cwd hardening — must be an existing directory, no traversal tricks.
    if cwd is not None:
        try:
            cwd_p = Path(cwd).expanduser().resolve(strict=True)
        except (FileNotFoundError, RuntimeError, OSError) as e:
            return f"ERROR:INVALID_INPUT:cwd not accessible: {e}"
        if not cwd_p.is_dir():
            return f"ERROR:INVALID_INPUT:cwd is not a directory: {cwd_p}"
        cwd = str(cwd_p)
    job_id = "j" + _sec.token_hex(4)
    out_path = Path(tempfile.gettempdir()) / f"aim_{job_id}.log"
    f = out_path.open("w", encoding="utf-8")
    # shell=False — Popen receives an argv list; no shell parsing means
    # metacharacters in args are literal even if our regex missed them.
    cmd_list = _maybe_sandbox(command)
    proc = subprocess.Popen(cmd_list, stdout=f, stderr=subprocess.STDOUT,
                            cwd=cwd, text=True)
    _BG_JOBS[job_id] = {"proc": proc, "log": out_path,
                        "started": __import__("time").time(),
                        "cmd": command, "fh": f}
    return f"OK job_id={job_id}  (poll with bash_status / bash_output)"


@register_tool(
    "bash_status",
    "Check status of a background bash job started with bash_async.",
    {"job_id": "string returned by bash_async"},
)
def _t_bash_status(job_id: str) -> str:
    j = _BG_JOBS.get(job_id)
    if not j:
        return f"ERROR:NOT_FOUND:unknown job_id '{job_id}'"
    proc = j["proc"]
    rc = proc.poll()
    elapsed = __import__("time").time() - j["started"]
    if rc is None:
        return f"running  pid={proc.pid}  elapsed={elapsed:.1f}s  cmd={j['cmd']!r}"
    return f"exited  rc={rc}  elapsed={elapsed:.1f}s  cmd={j['cmd']!r}"


@register_tool(
    "bash_output",
    "Get the latest accumulated stdout/stderr of a background bash job (last 4000 chars).",
    {"job_id": "string returned by bash_async",
     "tail": "int chars from end (default 4000)"},
)
def _t_bash_output(job_id: str, tail: int = 4000) -> str:
    j = _BG_JOBS.get(job_id)
    if not j:
        return f"ERROR:NOT_FOUND:unknown job_id '{job_id}'"
    try:
        text = j["log"].read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR:INTERNAL:read log: {e}"
    if len(text) > tail:
        text = "[…earlier truncated]\n" + text[-tail:]
    rc = j["proc"].poll()
    state = "running" if rc is None else f"exited rc={rc}"
    return f"[{state}]\n{text}"


@register_tool(
    "bash_kill",
    "Kill a background bash job started with bash_async.",
    {"job_id": "string returned by bash_async"},
)
def _t_bash_kill(job_id: str) -> str:
    j = _BG_JOBS.get(job_id)
    if not j:
        return f"ERROR:NOT_FOUND:unknown job_id '{job_id}'"
    proc = j["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    try: j["fh"].close()
    except Exception: pass
    return f"OK killed {job_id} (rc={proc.poll()})"


def _with_timeout(fn, args, timeout: float = 5.0):
    """Run a callable with a timeout. Uses ThreadPoolExecutor for portability
    (works on Windows; signal-based timeouts don't)."""
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, **args) if isinstance(args, dict) else pool.submit(fn, args)
        try:
            return fut.result(timeout=timeout)
        except _cf.TimeoutError:
            return f"ERROR:TIMEOUT:operation exceeded {timeout}s"


@register_tool(
    "memory_recall",
    "Semantic search over Claude memory + cross-project Desktop memory. Returns top-k passages.",
    {"query": "string", "k": "int default 6", "timeout_s": "float default 5"},
)
def _t_memory_recall(query: str, k: int = 6, timeout_s: float = 10.0) -> str:
    def _do():
        from agents.memory_index import retrieve
        return retrieve(query, k=k)
    try:
        hits = _with_timeout(_do, {}, timeout=timeout_s)
    except Exception as e:
        return f"ERROR:UNAVAILABLE:memory_index: {e}"
    if isinstance(hits, str) and hits.startswith("ERROR:"):
        return hits
    if not hits:
        return "(no hits)"
    out = []
    for h in hits[:k]:
        out.append(f"— {h.get('file','?')}\n  {h.get('text','')[:300]}")
    return "\n".join(out)


@register_tool(
    "memory_save",
    "Save a short atomic fact to user's auto-memory. Use for explicit user instructions to remember.",
    {"text": "fact to remember", "category": "str default 'general'"},
)
def _t_memory_save(text: str, category: str = "general") -> str:
    try:
        from agents.memory_store import remember
        path = remember(text, category=category, quiet=True)
        return f"OK saved → {Path(str(path)).name}"
    except Exception as e:
        return f"ERROR:INTERNAL:{e}"


@register_tool(
    "web_search",
    "Search the web (DuckDuckGo, no API key). Returns list of {title, url, snippet}. Use for grants, news, anything outside PubMed.",
    {"query": "search query string", "n": "int default 8"},
)
def _t_web_search(query: str, n: int = 8) -> str:
    from tools.web import web_search
    hits = web_search(query, n=n)
    return json.dumps(hits, ensure_ascii=False)[:6000]


_WEB_FETCH_DEFAULT_ALLOW = (
    "pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "doi.org", "dx.doi.org", "api.crossref.org", "search.crossref.org",
    "scholar.google.com", "europepmc.org", "www.europepmc.org",
    "elifesciences.org", "www.biorxiv.org", "www.medrxiv.org",
    "longevity.ge", "www.longevity.ge", "drjaba.com", "www.drjaba.com",
    "github.com", "raw.githubusercontent.com", "gist.github.com",
    "arxiv.org", "www.arxiv.org",
    "huggingface.co",
    "ec.europa.eu",  # EIC Pathfinder
)


def _web_fetch_host_allowed(url: str) -> tuple[bool, str]:
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False, "unparseable URL"
    if not host:
        return False, "no hostname in URL"
    extra = os.environ.get("AIM_WEB_FETCH_ALLOW", "")
    extra_set = {h.strip().lower() for h in extra.split(",") if h.strip()}
    allow = set(_WEB_FETCH_DEFAULT_ALLOW) | extra_set
    if host in allow:
        return True, host
    # Allow exact-suffix subdomain match (e.g. eu-west-1.foo.bar matches
    # "foo.bar"). Only when the suffix has at least one dot, to avoid
    # accidentally allowing "*.com".
    for d in allow:
        if "." in d and host.endswith("." + d):
            return True, host
    return False, host


@register_tool(
    "web_fetch",
    "Fetch a URL, strip HTML to plain text. ALLOWLIST-gated: only "
    "scientific/repo domains are accepted by default (pubmed/doi/crossref/"
    "europepmc/elife/biorxiv/medrxiv/arxiv/scholar/longevity.ge/drjaba.com/"
    "github/huggingface/ec.europa.eu). Extend via AIM_WEB_FETCH_ALLOW env "
    "(comma-separated hostnames). Returns up to ~8000 chars of readable text.",
    {"url": "absolute URL", "max_chars": "int default 8000"},
)
def _t_web_fetch(url: str, max_chars: int = 8000) -> str:
    ok, host = _web_fetch_host_allowed(url)
    if not ok:
        return (f"ERROR:PERMISSION:web_fetch host {host!r} not in allowlist. "
                "Add to AIM_WEB_FETCH_ALLOW env (csv) or use one of the "
                "default science/repo hosts.")
    from tools.web import web_fetch
    return web_fetch(url, max_chars=max_chars)


@register_tool(
    "view_image",
    "Look at a PNG/JPG/PDF page and answer a question about it. Native vision via Claude or DS-V4 (OCR as last-resort fallback).",
    {"path": "absolute path to image or PDF",
     "prompt": "what to look for / question",
     "page": "PDF page number (0-indexed, default 0)"},
)
def _t_view_image(path: str, prompt: str, page: int = 0) -> str:
    from tools.vision import see
    return see(path, prompt, page=page)


@register_tool(
    "verify_pmid",
    "Look up a PMID at PubMed (8s timeout). Returns metadata or ERROR.",
    {"pmid": "string of digits"},
)
def _t_verify_pmid(pmid: str) -> str:
    from tools.literature import verify_pmid
    rec = _with_timeout(verify_pmid, {"pmid": pmid}, timeout=8.0)
    if isinstance(rec, str) and rec.startswith("ERROR:"):
        return rec
    return json.dumps(rec, ensure_ascii=False) if rec else f"ERROR:NOT_FOUND:PMID {pmid} not found at PubMed"


@register_tool(
    "verify_doi",
    "Look up a DOI at Crossref (8s timeout). Returns metadata or ERROR.",
    {"doi": "DOI string (e.g. 10.1126/sciadv.adh2560)"},
)
def _t_verify_doi(doi: str) -> str:
    from tools.literature import verify_doi
    rec = _with_timeout(verify_doi, {"doi": doi}, timeout=8.0)
    if isinstance(rec, str) and rec.startswith("ERROR:"):
        return rec
    return json.dumps(rec, ensure_ascii=False) if rec else f"ERROR:NOT_FOUND:DOI {doi} not found at Crossref"


@register_tool(
    "search_pubmed",
    "Search PubMed and return up to n verified records. Each record is real.",
    {"query": "string", "n": "int default 8"},
)
def _t_search_pubmed(query: str, n: int = 8) -> str:
    from tools.literature import pubmed_search
    rows = pubmed_search(query, n=n)
    return json.dumps(rows, ensure_ascii=False)[:6000]


@register_tool(
    "delegate_doctor",
    "Delegate a clinical task to DoctorAgent (diagnose/treatment/labs). Returns the doctor's response.",
    {"action": "diagnose|treatment|labs|chat", "input": "free text"},
)
def _t_delegate_doctor(action: str, input: str) -> str:
    from agents.doctor import DoctorAgent
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision

    fn_map = {"diagnose":  ("dx",        lambda: DoctorAgent().diagnose(input)),
              "treatment": ("treatment", lambda: DoctorAgent().treatment(input)),
              "labs":      ("test",      lambda: DoctorAgent().interpret_labs(input)),
              "chat":      ("chat",      lambda: DoctorAgent().chat(input))}
    if action not in fn_map:
        return f"ERROR:INVALID_INPUT:unknown doctor action '{action}'"
    action_type, service_fn = fn_map[action]

    decision = Decision(
        id=f"doctor.{action}",
        description=f"clinical {action}",
        action_type=action_type,
        payload={"input": str(input)[:2000]},
    )
    # `chat` is conversational, not a clinical decision — skip Ze scoring.
    return orchestrate(decision, service_fn, skip_ze=(action == "chat"))


@register_tool(
    "delegate_writer",
    "Delegate a writing task. Actions:\n"
    "  • tbpr_review — Triple-Blind Peer Review (3 reviewers + verdict) of a "
    "scientific article. Use this for any TBPR cycle. Args: manuscript "
    "(path to .md OR raw text), template (optional path; default = "
    "~/Desktop/AIM-service/templates/TBPR_article.md), output (REQUIRED for "
    "long content — path where the review will be written directly; the "
    "tool returns a short OK summary, not the full text), lang (default 'en').\n"
    "  • apply_fixes — Apply a TBPR review's recommendations to produce a "
    "revised article. Args: manuscript (path or text), review (path or "
    "text), output (REQUIRED — path for the revised article), lang.\n"
    "  IMPORTANT: for tbpr_review and apply_fixes always pass `output` so the "
    "tool writes to disk itself. Tool history is truncated at 4000 chars, so "
    "without `output` the long result is unrecoverable for a follow-up "
    "write_file call.\n"
    "  • review — generic single-reviewer peer review (use tbpr_review "
    "instead for proper TBPR).\n"
    "  • edit — copy-edit / tighten / academic-rewrite / abstract / polish.\n"
    "  • cover_letter, response, md_to_docx — see writer.py.\n"
    "Path args (`manuscript`, `template`, `review`) are auto-loaded.",
    {"action": "tbpr_review|apply_fixes|review|edit|cover_letter|response|md_to_docx",
     "args": "dict of parameters (see tool description)"},
    examples=[{
        "call": {"tool": "delegate_writer",
                 "args": {"action": "tbpr_review",
                          "args": {"manuscript":
                                       "/home/oem/Desktop/Overpopulation_drafts/06_Unified_v1.md",
                                   "output":
                                       "/home/oem/Desktop/Overpopulation_drafts/07_TBPR_Cycle1.md",
                                   "lang": "en"}}},
    }, {
        "call": {"tool": "delegate_writer",
                 "args": {"action": "apply_fixes",
                          "args": {"manuscript":
                                       "/home/oem/Desktop/Overpopulation_drafts/06_Unified_v1.md",
                                   "review":
                                       "/home/oem/Desktop/Overpopulation_drafts/07_TBPR_Cycle1.md",
                                   "output":
                                       "/home/oem/Desktop/Overpopulation_drafts/06_Unified_v2.md",
                                   "lang": "en"}}},
    }, {
        "call": {"tool": "delegate_writer",
                 "args": {"action": "md_to_docx",
                          "args": {"md": "/home/oem/Desktop/article.md",
                                   "docx": "/home/oem/Desktop/article.docx"}}},
    }],
)
def _t_delegate_writer(action: str, args: dict) -> str:
    from agents import writer as W
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    args = args or {}

    # md_to_docx is a format conversion — no kernel pipeline.
    if action == "md_to_docx":
        try:
            return f"OK → {W.md_to_docx(args['md'], args['docx'])}"
        except Exception as e:
            return f"ERROR:INTERNAL:writer.md_to_docx failed: {e}"

    # Resolver: review/edit/tbpr_review/apply_fixes need text content. Accept:
    #   • `text`        — content directly
    #   • `manuscript`  — path to .md (auto-loaded)
    #   • `path`        — path to .md (auto-loaded, alias of manuscript)
    def _resolve_arg_to_text(args_dict: dict, *keys: str
                              ) -> tuple[str | None, str | None]:
        """Try `keys` in order; if a value is a string starting with '/' or '~'
        OR ends with .md/.txt, treat as path and read it. Otherwise treat as
        literal content. First non-empty hit wins."""
        for k in keys:
            v = args_dict.get(k)
            if not isinstance(v, str) or not v:
                continue
            looks_like_path = (v.startswith("/") or v.startswith("~")
                                or v.endswith((".md", ".txt", ".rst")))
            if looks_like_path:
                from pathlib import Path as _P
                p = _P(v).expanduser()
                if not p.exists():
                    return None, f"ERROR:NOT_FOUND:{p}"
                try:
                    return p.read_text(encoding="utf-8", errors="replace"), None
                except Exception as e:
                    return None, f"ERROR:INTERNAL:read {p}: {e}"
            return v, None
        return None, None

    if action in ("review", "edit"):
        _txt, _err = _resolve_arg_to_text(args, "text", "manuscript", "path", "file")
        if _err:
            return _err
        if _txt is None:
            return ("ERROR:INVALID_INPUT:review/edit requires 'text' (content) "
                    "OR 'manuscript'/'path' (file path)")
        args = {**args, "text": _txt}

    if action == "tbpr_review":
        _txt, _err = _resolve_arg_to_text(args, "manuscript", "text", "path", "file")
        if _err:
            return _err
        if _txt is None:
            return ("ERROR:INVALID_INPUT:tbpr_review requires 'manuscript' "
                    "(path to .md or content)")
        # Template — default to AIM-service TBPR_article.md if not specified.
        _tmpl_path = args.get("template") or str(
            Path.home() / "Desktop" / "AIM-service" / "templates" / "TBPR_article.md")
        _tmpl, _terr = _resolve_arg_to_text({"template": _tmpl_path}, "template")
        if _terr:
            return _terr
        args = {**args, "manuscript_text": _txt, "template_text": _tmpl or ""}

    if action == "apply_fixes":
        _txt, _err = _resolve_arg_to_text(args, "manuscript", "article", "text", "path")
        if _err:
            return _err
        _rev, _rerr = _resolve_arg_to_text(args, "review", "review_path", "review_text")
        if _rerr:
            return _rerr
        if _txt is None or _rev is None:
            return ("ERROR:INVALID_INPUT:apply_fixes requires 'manuscript' "
                    "(article path or text) AND 'review' (review path or text)")
        args = {**args, "manuscript_text": _txt, "review_text": _rev}

    # When `output` is set on a long-text action, write the result to disk
    # ourselves and return a short status — the LLM history truncates tool
    # results at 4K, so a 14K TBPR review would otherwise be unrecoverable
    # for a follow-up write_file. Long-text actions are tbpr_review and
    # apply_fixes.
    _output_path = args.get("output") or args.get("output_path")

    def _write_to_disk_and_summarize(text: str, kind: str) -> str:
        if not _output_path:
            return text
        p = Path(_output_path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        except Exception as e:
            return f"ERROR:INTERNAL:write {p}: {e}"
        verdict_line = ""
        for line in text.splitlines():
            if "verdict" in line.lower() and any(
                k in line.upper()
                for k in ("REJECT", "REVISE_MAJOR", "REVISE_MINOR",
                          "ACCEPT", "MAJOR", "MINOR")
            ):
                verdict_line = f"\nverdict: {line.strip()[:120]}"
                break
        return f"OK [{kind}] wrote {len(text)} chars → {p}{verdict_line}"

    fn_map = {
        "review":       ("peer_review_emit",
                         lambda: W.review(args["text"],
                                          focus=args.get("focus", "peer-review"),
                                          lang=args.get("lang", "en"))),
        "tbpr_review":  ("peer_review_emit",
                         lambda: _write_to_disk_and_summarize(
                             W.tbpr_review(args["manuscript_text"],
                                           args.get("template_text", ""),
                                           lang=args.get("lang", "en")),
                             "tbpr_review")),
        "apply_fixes":  ("emit_text",
                         lambda: _write_to_disk_and_summarize(
                             W.apply_review_fixes(args["manuscript_text"],
                                                   args["review_text"],
                                                   lang=args.get("lang", "en")),
                             "apply_fixes")),
        "edit":         ("emit_text",
                         lambda: W.edit(args["text"],
                                        mode=args.get("mode", "tighten"),
                                        lang=args.get("lang", "en"))),
        "cover_letter": ("send_letter",
                         lambda: W.cover_letter(
                             args["manuscript"], args["journal"],
                             author=args.get("author", "Jaba Tkemaladze"),
                             lang=args.get("lang", "en"))),
        "response":     ("peer_review_emit",
                         lambda: W.response_to_reviewers(
                             args["manuscript"], args["reviews"],
                             lang=args.get("lang", "en"))),
    }
    if action not in fn_map:
        return f"ERROR:INVALID_INPUT:unknown writer action '{action}'"
    action_type, service_fn = fn_map[action]

    decision = Decision(
        id=f"writer.{action}",
        description=f"writer.{action}",
        action_type=action_type,
        payload={"args": {k: str(v)[:200] for k, v in args.items()}},
    )
    return orchestrate(decision, service_fn)


@register_tool(
    "delegate_email",
    "Gmail operations: list/search threads, read thread, draft, or send. send requires explicit user_confirmed=True.",
    {"action": "list|search|get|draft|send|labels",
     "args": "dict — see agents.email_agent docstring"},
)
def _t_delegate_email(action: str, args: dict | None = None) -> str:
    from agents import email_agent as E
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    args = args or {}

    # Read-only ops: no kernel pipeline.
    try:
        if action == "list":
            return json.dumps(E.list_threads(q=args.get("q", "newer_than:7d"),
                                              n=args.get("n", 20)),
                              ensure_ascii=False)[:6000]
        if action == "search":
            return json.dumps(E.search(args["query"], n=args.get("n", 20)),
                              ensure_ascii=False)[:6000]
        if action == "get":
            t = E.get_thread(args["thread_id"])
            return json.dumps({"id": t.get("id"),
                               "n": len(t.get("messages", [])),
                               "snippet": t.get("snippet", "")},
                              ensure_ascii=False)
        if action == "labels":
            return json.dumps(E.list_labels(), ensure_ascii=False)[:4000]
    except Exception as e:
        return f"ERROR:INTERNAL:email.{action} failed: {e}"

    # Side-effect ops go through orchestrator (L0-L3 + L_PRIVACY + L_CONSENT
    # for send; defense-in-depth — email_agent also keeps inner checks).
    if action == "draft":
        decision = Decision(
            id="email.draft",
            description="draft email",
            action_type="external_api_call_with_data",
            payload={"to": args.get("to"), "subject": args.get("subject"),
                     "body": (args.get("body") or "")[:8000]},
        )
        try:
            return orchestrate(
                decision,
                lambda: f"DRAFT created: id={E.draft(args['to'], args['subject'], args['body'], thread_id=args.get('thread_id'), cc=args.get('cc'), bcc=args.get('bcc')).get('id')}",
                
            )
        except PermissionError as e:
            return f"BLOCKED by kernel: {e}"

    if action == "send":
        decision = Decision(
            id="email.send",
            description="send email",
            action_type="email_send",
            payload={"to": args.get("to"), "subject": args.get("subject"),
                     "body": (args.get("body") or "")[:8000]},
        )
        ctx = {"user_confirmed": bool(args.get("user_confirmed"))}
        try:
            return orchestrate(
                decision,
                lambda: (lambda r: f"SENT id={r.get('id')} threadId={r.get('threadId')}")(
                    E.send(args["to"], args["subject"], args["body"],
                           thread_id=args.get("thread_id"),
                           cc=args.get("cc"), bcc=args.get("bcc"),
                           user_confirmed=bool(args.get("user_confirmed")))),
                context=ctx, 
            )
        except PermissionError as e:
            return f"BLOCKED by kernel: {e}"

    return f"ERROR:INVALID_INPUT:unknown email action '{action}'"


@register_tool(
    "run_tests",
    "Run a test command (e.g. 'pytest tests/test_x.py -q -x'). Returns stdout/stderr + exit code. Use after edit_file/apply_patch to verify implicitly. Whitelisted prefix as bash.",
    {"command": "test command",
     "cwd": "optional working directory",
     "timeout_s": "int default 120"},
    examples=[{
        "call": {"tool": "run_tests",
                 "args": {"command": "pytest tests/test_auth.py -q -x",
                          "cwd": "/home/oem/Desktop/AIM"}},
    }],
)
def _t_run_tests(command: str, cwd: Optional[str] = None,
                 timeout_s: int = 120) -> str:
    allow = ("pytest", "python", "python3", "npm", "yarn",
             "make", "cargo", "go", "mvn", "gradle", "bash", "sh")
    first = (shlex.split(command) or [""])[0].split("/")[-1]
    if first not in allow:
        return f"ERROR:PERMISSION:command '{first}' not whitelisted for run_tests"
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              text=True, cwd=cwd, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return f"ERROR:TIMEOUT:tests exceeded {timeout_s}s"
    out = (proc.stdout + proc.stderr).strip()
    head = f"[exit={proc.returncode}]\n"
    if proc.returncode == 0:
        return head + "TESTS PASSED\n" + out[-2500:]
    return head + "TESTS FAILED\n" + out[-3500:]


@register_tool(
    "delegate_coder",
    "Delegate code-edits to CoderAgent (Aider wrap + edit-then-test loop). For one-shot edits OR iterate-until-tests-pass.",
    {"files": "list of file paths to edit",
     "instruction": "natural-language edit task",
     "test_cmd": "optional shell test command (e.g. 'pytest tests/test_x.py -q'); when given, runs edit→test→fix loop",
     "max_iters": "int default 3 (only used when test_cmd is set)"},
)
def _t_delegate_coder(files: list[str], instruction: str,
                      test_cmd: Optional[str] = None,
                      max_iters: int = 3) -> str:
    from agents.coder import CoderAgent
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision

    # Pre-flight L_PRIVACY: code edits in Patients/ require explicit override.
    for p in (files or []):
        if "Patients/" in str(p) or "/Patients/" in str(p):
            if os.environ.get("AIM_ALLOW_PATIENT_WRITE") != "1":
                return ("ERROR:PERMISSION:coder blocked under L_PRIVACY — "
                        f"path '{p}' is inside Patients/. Set "
                        "AIM_ALLOW_PATIENT_WRITE=1 to override.")

    decision = Decision(
        id="coder.edit",
        description=f"code edit: {(instruction or '')[:80]}",
        action_type="code_edit",
        payload={"files": list(files or []),
                 "instruction": str(instruction)[:1000],
                 "test_cmd": test_cmd or ""},
    )

    def _service():
        agent = CoderAgent(files)
        if test_cmd:
            res = agent.edit_and_test(instruction, test_cmd, max_iters=max_iters)
            tail = res.last_test[-1500:]
            return (f"ok={res.ok} iters={res.iters}\n"
                    f"--- last test output ---\n{tail}")
        return agent.edit(instruction)[:6000]

    return orchestrate(decision, _service)


@register_tool(
    "delegate_researcher",
    "Literature search & summarisation with hard PMID/DOI verification.",
    {"action": "find|summarise|verify_text|formulate_queries", "args": "dict"},
)
def _t_delegate_researcher(action: str, args: dict) -> str:
    from agents import researcher as R
    from agents.orchestrator import orchestrate
    from agents.kernel import Decision
    args = args or {}

    # `find` returns search rows (not emitted prose) and `verify_text` /
    # `formulate_queries` are pure utilities — none need the orchestrator.
    if action == "find":
        try:
            rows = R.find(args["query"], n=args.get("n", 10),
                          source=args.get("source", "pubmed"))
            return json.dumps(rows, ensure_ascii=False)[:6000]
        except Exception as e:
            return f"ERROR:INTERNAL:researcher.find failed: {e}"
    if action == "verify_text":
        try:
            rep = R.verify_text(args["text"], mode=args.get("mode", "annotate"))
            return rep.summary() + "\n\n" + rep.text[:4000]
        except Exception as e:
            return f"ERROR:INTERNAL:researcher.verify_text failed: {e}"
    if action == "formulate_queries":
        try:
            return json.dumps(R.formulate_queries(args["topic"],
                              n=args.get("n", 5)), ensure_ascii=False)
        except Exception as e:
            return f"ERROR:INTERNAL:researcher.formulate_queries failed: {e}"

    if action == "summarise":
        decision = Decision(
            id="researcher.summarise", description="summarise",
            action_type="emit_text",
            payload={"records_n": len(args.get("records", []) or [])},
        )
        service_fn = lambda: R.summarise(  # noqa: E731
            args["records"], args.get("focus", ""), lang=args.get("lang", "en"))
        return orchestrate(decision, service_fn)

    return f"ERROR:INVALID_INPUT:unknown researcher action '{action}'"


@register_tool(
    "delegate_parallel",
    "Spawn N independent generalist sub-runs and synthesize their answers. Use for fan-out (e.g. peer-review each section in parallel).",
    {"tasks": "list of task strings (each will run in its own generalist)",
     "max_iters": "int per sub-run (default 6)",
     "synthesise": "if True, ask LLM to merge results into one answer (default True)"},
)
def _t_delegate_parallel(tasks: list[str], max_iters: int = 6,
                         synthesise: bool = True) -> str:
    if not isinstance(tasks, list) or not tasks:
        return "ERROR:INVALID_INPUT:tasks must be a non-empty list of strings"

    from agents.orchestrator import orchestrate
    from agents.kernel import Decision

    decision = Decision(
        id="parallel.dispatch",
        description=f"parallel run of {len(tasks)} sub-tasks",
        action_type="parallel_dispatch",
        payload={"n_tasks": len(tasks),
                 "first_task": str(tasks[0])[:200]},
    )

    def _service():
        results: list[str] = [""] * len(tasks)
        with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
            futs = {pool.submit(run, t, max_iters=max_iters,
                                speculative=False): i
                    for i, t in enumerate(tasks)}
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    results[i] = fut.result().get("answer", "")
                except Exception as e:
                    results[i] = f"[sub-task failed: {e}]"
        if not synthesise:
            return json.dumps([{"task": t, "answer": r}
                               for t, r in zip(tasks, results)],
                              ensure_ascii=False)[:6000]
        blocks = "\n\n".join(
            f"=== Sub-task {i+1}: {tasks[i]} ===\n{results[i]}"
            for i in range(len(tasks)))
        syn_prompt = (
            "You are synthesising parallel sub-task results into one coherent "
            "answer. Quote only the substance; remove redundancy; preserve every "
            "factual claim that appeared in any sub-result.\n\n" + blocks
        )
        try:
            from llm import ask_critical as _ask
        except Exception:
            from llm import ask_deep as _ask
        return _ask(syn_prompt)

    return orchestrate(decision, _service)


@register_tool(
    "critique",
    "Adversarial review of a plan or draft by a DIFFERENT model than the main one. Catches single-model blind spots. Returns critique text or 'OK' if no flaws found.",
    {"text": "the plan or draft to critique",
     "context": "optional task context for the critic",
     "focus": "optional focus area (e.g. 'fact-check', 'security', 'logic')"},
    examples=[{
        "call": {"tool": "critique",
                 "args": {"text": "Plan: send email to Klien with patient lab results.",
                          "focus": "privacy + correctness"}},
    }],
)
def _t_critique(text: str, context: str = "", focus: str = "fact-check + logic") -> str:
    """Cross-model critique. If main is Claude/Gemini, calls DS-reasoner.
    Otherwise prefers Claude → Gemini → DS-reasoner."""
    try:
        from llm import (anthropic_available, gemini_available,
                          DEEPSEEK_API_KEY, _claude_chat, _gemini_chat,
                          ask_deep)
        from config import Models
    except Exception as e:
        return f"ERROR:UNAVAILABLE:{e}"

    sys = ("You are an adversarial reviewer. Find MATERIAL flaws in the "
            "plan/draft below. Material = wrong fact, unsupported claim, "
            "fabricated PMID/DOI, harmful or unsafe action, missing user "
            "constraint, security issue, logical contradiction. Style nits "
            "are NOT material. If acceptable, reply EXACTLY 'OK'. Otherwise "
            "list flaws as numbered bullets, 1-2 lines each.\n"
            f"Focus area: {focus}")
    prompt = (f"=== CONTEXT ===\n{context[:1500]}\n=== END ===\n\n"
              f"=== PLAN/DRAFT TO REVIEW ===\n{text[:6000]}\n=== END ===")

    # Pick the BEST cross-model critic available
    if DEEPSEEK_API_KEY:
        # DS-reasoner is the best critic for cross-model dissent (different
        # post-training family from Claude/Gemini)
        out = ask_deep(prompt, system=sys)
        if out: return f"[critic=ds-pro]\n{out.strip()}"
    if anthropic_available():
        out = _claude_chat(prompt, system=sys, model=Models.CLAUDE_OPUS,
                           temperature=0)
        if out: return f"[critic=claude-opus]\n{out.strip()}"
    if gemini_available():
        out = _gemini_chat(prompt, system=sys, model=Models.GEMINI_PRO,
                           temperature=0)
        if out: return f"[critic=gemini-2.5-pro]\n{out.strip()}"
    return "ERROR:UNAVAILABLE:no critique provider configured"


@register_tool(
    "kernel_check",
    "Pre-action check: pass a Decision payload, get L_PRIVACY/L_CONSENT/L_VERIFIABILITY verdict.",
    {"action_type": "string (e.g. email_send, git_push_public, emit_text)",
     "payload": "dict",
     "context": "dict (e.g. {'user_confirmed': true})"},
)
def _t_kernel_check(action_type: str, payload: dict, context: dict | None = None) -> str:
    from agents.kernel import Decision, evaluate_extended
    d = Decision(id="adhoc", description=str(payload)[:80],
                 action_type=action_type, payload=payload or {})
    res = evaluate_extended(d, patient={}, context=context or {})
    return json.dumps({
        "passed": res.passed,
        "privacy": res.privacy, "consent": res.consent,
        "verifiability": res.verifiability,
        "reasons": res.reasons,
    }, ensure_ascii=False)


@register_tool(
    "ze_verify",
    "Calibrate a factual claim BEFORE asserting it. Pass a hypothesis (what "
    "you predict the code/file says) and an observation (verbatim grep or "
    "view_file output you actually got). Returns match_score ∈ [0,1], a diff "
    "of missing/extra tokens, and a verdict (MATCH/PARTIAL/MISMATCH). "
    "MANDATORY before stating any specific file:line, function name, count, "
    "schema column, or quoted code line in a final answer. Records to "
    "ze_events with action_type='ze_verify_claim' for trend analysis.",
    {"hypothesis": "what you predict (e.g. 'phi formula on orchestrator.py:121 returns 1.0 default')",
     "observation": "verbatim grep / view_file output you got"},
    examples=[{
        "call": {"tool": "ze_verify",
                 "args": {"hypothesis": "evaluate_l_privacy has 4 callers outside kernel.py",
                          "observation": "agents/orchestrator.py:160: ok = evaluate_l_privacy(...)\nagents/generalist.py:148: from agents.kernel import evaluate_l_privacy\nagents/email_agent.py:193: from agents.kernel import evaluate_l_privacy"}},
    }],
)
def _t_ze_verify(hypothesis: str, observation: str) -> str:
    """Hypothesis-vs-observation calibration. Built-in Ze routine.

    Computes a Jaccard-style match score on tokens, returns the
    asymmetric diff (what was claimed but not seen, and vice-versa),
    and persists the calibration event so trend analysis can show
    whether the agent is over- or under-confident.
    """
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        return json.dumps({"match_score": 0.0, "verdict": "INVALID",
                           "diff": "empty hypothesis"}, ensure_ascii=False)
    if not isinstance(observation, str) or not observation.strip():
        return json.dumps({"match_score": 0.0, "verdict": "INVALID",
                           "diff": "empty observation"}, ensure_ascii=False)

    # English+Russian stop words + connective phrases that don't anchor a code claim.
    _STOP = {"at", "in", "on", "of", "the", "a", "an", "is", "are", "was",
             "be", "to", "for", "with", "from", "by", "as", "and", "or",
             "not", "no", "yes", "returns", "default", "value", "formula",
             "exists", "has", "have", "do", "does", "if", "else", "function",
             "method", "class", "true", "false",
             "и", "на", "в", "с", "по", "из", "для", "это", "что", "есть"}

    def _toks(s: str) -> set[str]:
        # Tokens: alphanumerics + underscore + slash + dot + colon (keeps
        # file.py:line refs intact), length ≥ 2, lowercased, stop-words removed.
        raw = {t.lower() for t in re.findall(r"[A-Za-z0-9_./:]{2,}", s)}
        return {t for t in raw if t not in _STOP}

    h_tok = _toks(hypothesis)
    o_tok = _toks(observation)
    if not h_tok:
        return json.dumps({"match_score": 0.0, "verdict": "INVALID",
                           "diff": "no anchoring tokens in hypothesis after "
                                   "stop-word filter"}, ensure_ascii=False)

    # Substring-aware match: a hypothesis token counts as found if it's
    # equal to OR a substring of any observation token. This handles cases
    # like "orchestrator.py" (hypothesis) vs "agents/orchestrator.py:113"
    # (observation) — same file, just longer prefix in observation.
    o_blob = " ".join(o_tok) + " "
    matched = {t for t in h_tok if t in o_tok or t in o_blob}

    overlap = len(matched) / len(h_tok)
    only_in_h = sorted(h_tok - matched)[:15]
    extra_in_o = sorted(o_tok - h_tok)[:15]

    if overlap >= 0.70:
        verdict = "MATCH"
    elif overlap >= 0.40:
        verdict = "PARTIAL"
    else:
        verdict = "MISMATCH"

    # Persist calibration event so we can build a trend.
    try:
        from agents.kernel import Decision
        from agents.orchestrator import _persist_ze_event, _ZeMetrics
        d = Decision(id="ze_verify_claim",
                     description=hypothesis[:80],
                     action_type="ze_verify_claim",
                     payload={"hypothesis": hypothesis[:1000],
                              "observation": observation[:2000]})
        m = _ZeMetrics(
            impedance_before=1.0 - overlap,  # before verify: full uncertainty about claim
            impedance_after=0.0 if verdict == "MATCH" else (1.0 - overlap),
            instant_c=overlap if verdict == "MATCH" else -(1.0 - overlap),
            phi_ze=overlap,                  # calibration score
            utility=overlap,
        )
        _persist_ze_event(d, blocked_at=None, metrics=m,
                          output_chars=len(observation))
    except Exception as e:
        log.debug(f"ze_verify persist failed: {e}")

    return json.dumps({
        "match_score": round(overlap, 3),
        "verdict": verdict,
        "missing_from_observation": only_in_h,
        "extra_in_observation": extra_in_o,
        "advice": ("OK to assert" if verdict == "MATCH"
                   else "DO NOT ASSERT — fix hypothesis to match observation, "
                        "or quote observation verbatim instead"),
    }, ensure_ascii=False)


@register_tool(
    "ze_verify_symbol",
    "AST-verify that a Python symbol (function/class/constant) is actually "
    "defined at file:line. Catches the kind of hallucination where the line "
    "number is correct but the symbol on it is something else. Use BEFORE "
    "asserting 'X defined at file:N'.",
    {"symbol": "name of the function/class/constant",
     "file": "path to .py file (absolute, or repo-relative)",
     "line": "1-indexed line number where the symbol is claimed to be defined",
     "kind": "expected kind: 'def' | 'class' | 'const' | 'any' (default 'any')"},
)
def _t_ze_verify_symbol(symbol: str, file: str, line: int,
                        kind: str = "any") -> str:
    from pathlib import Path as _P
    from agents.ast_verify import def_at as _def_at
    p = _P(file).expanduser()
    if not p.is_absolute():
        # Try AIM root prefix, then a few subdirs.
        root = _P(__file__).resolve().parent.parent
        for cand in (root / file, *(root / sub / p.name
                                     for sub in ("agents", "tools", "tests",
                                                  "scripts", "web", "cli"))):
            if cand.is_file():
                p = cand
                break
    if not p.is_file():
        return json.dumps({"verdict": "FILE_NOT_FOUND",
                           "given_path": file}, ensure_ascii=False)
    sym = _def_at(p, int(line))
    if sym is None:
        return json.dumps({"verdict": "NO_SYMBOL_AT_LINE",
                           "file": str(p), "line": int(line)},
                          ensure_ascii=False)
    name_ok = sym.name == symbol
    kind_ok = (kind == "any" or sym.kind == kind
               or (kind == "def" and sym.kind == "async_def"))
    if name_ok and kind_ok:
        verdict = "MATCH"
    elif name_ok:
        verdict = "WRONG_KIND"
    else:
        verdict = "WRONG_SYMBOL"
    return json.dumps({
        "verdict": verdict,
        "expected_symbol": symbol,
        "expected_kind": kind,
        "actual_symbol": sym.name,
        "actual_kind": sym.kind,
        "actual_lineno": sym.lineno,
        "actual_end_lineno": sym.end_lineno,
    }, ensure_ascii=False)


# ── Tool-loop driver ───────────────────────────────────────────────────────


# SYSTEM_PROMPT extracted to agents/generalist_pkg/prompts.py (2026-05-07).
# Re-imported here so legacy callers can keep using:
#   from agents.generalist import SYSTEM_PROMPT
from agents.generalist_pkg.prompts import SYSTEM_PROMPT  # noqa: E402


def _format_tools_block() -> str:
    rows = []
    for t in _TOOLS.values():
        schema_str = ", ".join(f"{k}: {v}" for k, v in t.schema.items())
        rows.append(f"  {t.name}({schema_str})  — {t.description}")
        # F1: render up to 1 example per tool inline (terse) for the
        # high-mistake tools that expose examples.
        for ex in t.examples[:1]:
            call = json.dumps(ex.get("call") or {}, ensure_ascii=False)
            rows.append(f"      example: {call}")
    return "AVAILABLE TOOLS:\n" + "\n".join(rows)


_SEMANTIC_DEDUP_TOOLS = {"memory_recall", "grep", "glob", "web_search",
                         "search_pubmed", "verify_pmid", "verify_doi",
                         "read_file", "view_file"}
_VOLATILE_KEYS = {"k", "limit", "max_results", "timeout_s", "timeout",
                  "offset", "start_line", "end_line", "context_around"}
# Read-class tools (paging through one file with different offset/limit) are
# legitimately repeatable — a long file read in 3 chunks is normal. Use a
# higher window-hits threshold for them than for search-class tools.
_READ_CLASS_TOOLS = {"read_file", "view_file"}


def _stuck_signature(action: dict) -> str:
    """Normalize an action so semantically-equivalent calls share a signature.

    For search-type tools, drops volatile params (k/limit/timeout) and
    lowercases string args. So `memory_recall(query="TBPR Cycle 1", k=5)`
    and `memory_recall(query="tbpr cycle 1", k=10)` collapse to one
    signature — letting the loop guard catch repeats that differ only in
    cosmetic args.
    """
    if not isinstance(action, dict):
        return str(action)[:300]
    if "parallel" in action:
        try:
            inner = sorted(_stuck_signature(p) for p in action.get("parallel") or [])
            return "PAR|" + "|".join(inner)
        except Exception:
            return str(action)[:300]
    tool = action.get("tool", "")
    args = action.get("args") or {}
    if tool in _SEMANTIC_DEDUP_TOOLS and isinstance(args, dict):
        keep = {}
        for k, v in args.items():
            if k in _VOLATILE_KEYS:
                continue
            if isinstance(v, str):
                keep[k] = v.lower().strip()
            else:
                keep[k] = v
        try:
            return tool + "|" + json.dumps(keep, sort_keys=True,
                                            default=str, ensure_ascii=False)
        except Exception:
            return tool + "|" + str(keep)[:300]
    try:
        return json.dumps(action, sort_keys=True, default=str)[:300]
    except Exception:
        return str(action)[:300]


def run(task: str, *, max_iters: int = 10, kernel: bool = True,
        model_hint: Optional[str] = None,
        speculative: bool = True,
        critique: bool = True,
        ensemble: bool = True,
        session_id: Optional[int] = None,
        on_event: Optional[Callable[[dict], None]] = None) -> dict:
    """Tool-agency cycle. Returns dict with answer + trace.

    Args:
        speculative: background prefetch of likely tools while LLM thinks.
        critique:    on critical tasks, run a self-critique pass on `final`
                     and regenerate once if material flaws are found.
        ensemble:    on critical tasks, route the FIRST plan via ensemble
                     (3 models in parallel + adjudication) for grounding.
    """
    import secrets as _sec, signal as _signal
    run_id = _sec.token_hex(6)
    _run_id_token = _RUN_ID_VAR.set(run_id)

    # SIGINT handler — only install if main thread. Sub-agents spawned via
    # delegate_parallel run in worker threads with their own run_id (via
    # contextvars), so they don't trample this handler.
    _prev_sigint = None
    try:
        if threading.current_thread() is threading.main_thread():
            def _sigint_handler(_sig, _frame):
                with _STATE_LOCK:
                    _INTERRUPTED[run_id] = True
            _prev_sigint = _signal.signal(_signal.SIGINT, _sigint_handler)
    except Exception:
        pass

    history: list[dict] = [{"role": "user", "content": task}]
    trace: list[dict] = []
    tools_used: list[str] = []
    recent_actions: list[str] = []   # for stuck-loop detection
    recent_tool_names: list[str] = []  # for search-spam frequency cap
    stuck_warned = False
    critical = False

    # Reflexion: inject recent reflections as a hint at start
    try:
        from agents.reflexion import recent_reflections, classify as _rclass
        bucket = _rclass(task)
        refs = recent_reflections(task, n=3)
        if refs:
            history.append({
                "role": "tool", "name": "_reflexion",
                "result": (f"REFLEXION HINTS (bucket={bucket}, "
                           f"{len(refs)} past reflections):\n"
                           + "\n".join(f"  • {r}" for r in refs)
                           + "\nUse these to avoid prior pitfalls.")
            })
    except Exception as e:
        log.debug(f"reflexion inject skipped: {e}")
    try:
        from agents.ensemble import is_critical as _is_crit
        critical = _is_crit(task)
    except Exception:
        pass

    # F2: JSONL session log under platform-portable cache dir.
    def _log_dir() -> Path:
        import platform as _pl
        sysname = _pl.system()
        if sysname == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA",
                                       Path.home() / "AppData" / "Local"))
            d = base / "aim" / "sessions"
        elif sysname == "Darwin":
            d = Path.home() / "Library" / "Caches" / "aim" / "sessions"
        else:
            d = Path(os.environ.get("XDG_CACHE_HOME",
                                    str(Path.home() / ".cache"))) / "aim" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    log_path = _log_dir() / f"{run_id}.jsonl"
    try:
        log_path.write_text(json.dumps({"type": "run_start", "task": task,
                                        "session_id": session_id,
                                        "ts": __import__("datetime")
                                              .datetime.now().isoformat()}) + "\n",
                             encoding="utf-8")
    except Exception:
        pass

    def _jsonl(ev: dict) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def _persist(role: str, name: str, content: str) -> None:
        if session_id is None:
            return
        try:
            from db import save_message
            save_message(session_id, role, content,
                         model="generalist", provider=name)
        except Exception as e:
            log.debug(f"persist failed: {e}")

    def emit(ev: dict) -> None:
        # F2: append every event to JSONL session log
        _jsonl(ev)
        # D1: persist tool calls + tool results to messages table
        et = ev.get("type")
        if et == "tool_call":
            _persist("tool_call", ev.get("tool", "?"),
                     json.dumps(ev.get("args") or {}, ensure_ascii=False)[:1000])
        elif et == "tool_result":
            _persist("tool_result", ev.get("tool", "?"),
                     str(ev.get("result_preview", ""))[:1000])
        elif et == "final":
            _persist("assistant", "final", str(ev.get("answer", ""))[:4000])
        if on_event:
            try:
                on_event(ev)
            except Exception as _e:
                log.debug(f"on_event callback raised: {_e}")

    emit({"type": "start", "task": task, "critical": critical})

    pf = None
    if speculative:
        try:
            from agents.speculative_prefetch import Prefetcher
            pf = Prefetcher()
        except Exception as e:
            log.debug(f"prefetcher disabled: {e}")

    from pathlib import Path as _Path
    _AIM_ROOT = _Path(__file__).resolve().parent.parent
    _self_locator = (
        "RUNTIME LOCATION:\n"
        f"  AIM root  = {_AIM_ROOT}\n"
        f"  agents/   = {_AIM_ROOT}/agents\n"
        f"  cli/      = {_AIM_ROOT}/cli\n"
        f"  scripts/  = {_AIM_ROOT}/scripts\n"
        f"  web/      = {_AIM_ROOT}/web\n"
        f"  tools/    = {_AIM_ROOT}/tools\n"
        "When the user asks introspection questions about AIM itself, read\n"
        "files relative to AIM root above. Do NOT guess paths like\n"
        "/home/<user>/Desktop/AIM — that path does not exist.\n"
    )
    # In-flight task list snapshot — auto-injected so the LLM resolves
    # "continue / продолжи / оборвался / where did we leave off" against
    # the active todo list FIRST, before reading SESSION_STATE.md or TODO.md.
    _todo_snap = ""
    try:
        import json as _j
        _todo_path = Path.home() / ".cache" / "aim" / "repl_todos.json"
        if _todo_path.exists():
            _td = _j.loads(_todo_path.read_text(encoding="utf-8"))
            _items = _td.get("items") or []
            if _items:
                _MARK = {"completed": "☑", "in_progress": "▣", "pending": "▢"}
                _lines = ["CURRENT TASK LIST (visible to user in REPL):"]
                for it in _items:
                    _lines.append(
                        f"  {_MARK.get(it.get('status'), '▢')} "
                        f"{it.get('content','')}"
                    )
                _lines.append(
                    "When the user says 'continue / продолжи / на чём "
                    "остановились / where did we leave off', resume the "
                    "▣ in-progress item ABOVE — do NOT read SESSION_STATE.md "
                    "or TODO.md unless the list above is empty.")
                _todo_snap = "\n".join(_lines) + "\n\n"
    except Exception:
        _todo_snap = ""

    sys_prompt = (SYSTEM_PROMPT + "\n\n" + _self_locator + "\n"
                   + _todo_snap + _format_tools_block())

    # On critical tasks, use ensemble to ground the first plan across providers.
    if critical and ensemble:
        try:
            from agents.ensemble import ensemble_ask
            res = ensemble_ask(
                "Outline (5-10 numbered bullets) the strongest plan to "
                "accomplish this task. Be concrete; mention which AIM tools "
                f"are needed. Task: {task}",
                system="You are a planning advisor for a tool-using agent.")
            history.append({"role": "tool", "name": "_ensemble_plan",
                            "result": ("ENSEMBLE PLAN "
                                f"(consensus={res.get('consensus')}, "
                                f"agreement={res.get('agreement')}):\n"
                                + (res.get("answer") or "")[:3000])})
            tools_used.append("ensemble_plan")
            trace.append({"iter": -1, "ensemble": {
                "consensus": res.get("consensus"),
                "agreement": res.get("agreement"),
                "adjudicator": res.get("adjudicator"),
            }})
        except Exception as e:
            log.warning(f"ensemble plan skipped: {e}")

    for it in range(max_iters):
        if _INTERRUPTED.get(run_id):
            log.info(f"generalist {run_id}: interrupted by user")
            emit({"type": "interrupted"})
            if pf is not None:
                pf.shutdown()
            with _STATE_LOCK:
                _SCRATCHPADS.pop(run_id, None)
                _INTERRUPTED.pop(run_id, None)
            try: _RUN_ID_VAR.reset(_run_id_token)
            except Exception: pass
            if _prev_sigint is not None:
                try: _signal.signal(_signal.SIGINT, _prev_sigint)
                except Exception: pass
            return {"answer": "[interrupted by user]",
                    "trace": trace, "tools_used": tools_used,
                    "iters": it, "interrupted": True}
        if pf is not None:
            pf.observe(history)
        history = _maybe_compact(history)
        # A1: native messages[] with strict JSON mode (DS/Gemini/Groq) —
        # better prefix-cache hit, fewer parse failures. Synthetic prompt
        # is used only for the deep-reasoning path or as a fallback.
        if it == 0 or "research" in task.lower() or "review" in task.lower():
            # Deep path: use synthetic prompt because DS-reasoner doesn't
            # always honour response_format on the first reasoning turn.
            prompt = _render_for_llm(history)
            raw = ask_deep(prompt, system=sys_prompt)
        else:
            msgs = _render_messages(history, sys_prompt)
            raw = _llm_call_msgs(msgs)
            if not raw:
                # Cloud unreachable → fall back to synthetic prompt + ask()
                prompt = _render_for_llm(history)
                raw = ask(prompt, system=sys_prompt)
        action = _parse_action(raw)
        trace.append({"iter": it, "raw": raw[:500], "action": action})

        # Parse failure → feed error back, retry
        if not action:
            log.warning("generalist: invalid JSON from LLM; retrying")
            history.append({"role": "tool", "name": "_parser",
                            "result": "ERROR:INVALID_INPUT:previous reply was not valid JSON. "
                                      "Reply with EXACTLY one JSON object: "
                                      '{"tool": "...", "args": {...}} '
                                      'OR {"parallel": [...]} OR {"final": "..."}'})
            continue

        # Stuck-loop detection — three triggers:
        #   (a) 3 consecutive identical signatures
        #   (b) same signature ≥3 times within last 6 actions
        #       (covers "interleaved with one decoy call" pattern)
        #   (c) same SEARCH-class tool called ≥4 times within last 6 actions
        #       (LLM varying query strings cosmetically without converging)
        # Multi-action pipelines (`{"actions": [...]}`) and parallel blocks
        # (`{"parallel": [...]}`) are FLATTENED — each inner step is tracked
        # separately so a single LLM round emitting 3 read_files of the same
        # file still triggers the guard.
        _inner_steps: list[dict] = []
        if isinstance(action.get("actions"), list) and action["actions"]:
            for step in action["actions"]:
                if not isinstance(step, dict):
                    continue
                if isinstance(step.get("parallel"), list) and step["parallel"]:
                    for c in step["parallel"]:
                        if isinstance(c, dict):
                            _inner_steps.append(c)
                else:
                    _inner_steps.append(step)
        elif isinstance(action.get("parallel"), list) and action["parallel"]:
            for c in action["parallel"]:
                if isinstance(c, dict):
                    _inner_steps.append(c)
        else:
            _inner_steps = [action]

        for sub in _inner_steps:
            recent_actions.append(_stuck_signature(sub))
            sub_tool = sub.get("tool") or ""
            recent_tool_names.append(sub_tool)
        if len(recent_actions) > 8:
            recent_actions = recent_actions[-8:]
        if len(recent_tool_names) > 8:
            recent_tool_names = recent_tool_names[-8:]

        sig = recent_actions[-1] if recent_actions else _stuck_signature(action)
        tool_name = recent_tool_names[-1] if recent_tool_names else (
            action.get("tool") or ("__parallel__" if "parallel" in action else ""))
        consecutive3 = (len(recent_actions) >= 3 and
                         recent_actions[-1] == recent_actions[-2] == recent_actions[-3])
        # Read-class tools (read_file/view_file) need ≥4 hits to fire — paging
        # through one long file with different offsets is legitimate. Search-
        # class tools (memory_recall/grep/glob/etc.) keep the stricter ≥3.
        window_threshold = 4 if tool_name in _READ_CLASS_TOOLS else 3
        window_hits = recent_actions[-6:].count(sig)
        search_spam = (tool_name in _SEMANTIC_DEDUP_TOOLS and
                        tool_name not in _READ_CLASS_TOOLS and
                        recent_tool_names[-6:].count(tool_name) >= 4)
        if consecutive3 or window_hits >= window_threshold or search_spam:
            log.warning(
                f"generalist: stuck-loop detected "
                f"(consecutive3={consecutive3}, window_hits={window_hits}, "
                f"search_spam={search_spam}, tool={tool_name})")
            if not stuck_warned:
                if search_spam:
                    msg = (f"WARNING:STUCK:You called '{tool_name}' "
                           f"{recent_tool_names[-6:].count(tool_name)} times in "
                           f"the last 6 steps with varying queries but no "
                           f"convergence. STOP searching. Either: (a) work with "
                           f"the results you already have, (b) finalise with "
                           f"what's known, (c) ask the user. Another search "
                           f"call will abort the run.")
                else:
                    msg = ("WARNING:STUCK:You repeated the same action. "
                           "Either change strategy, use a different tool, or "
                           "finalise. Another repeat will abort the run.")
                history.append({"role": "tool", "name": "_loop_guard",
                                "result": msg})
                stuck_warned = True
                continue
            # Second strike — abort
            emit({"type": "stuck_aborted", "action": sig[:100]})
            if pf is not None:
                pf.shutdown()
            with _STATE_LOCK:
                _SCRATCHPADS.pop(run_id, None)
                _INTERRUPTED.pop(run_id, None)
            try: _RUN_ID_VAR.reset(_run_id_token)
            except Exception: pass
            if _prev_sigint is not None:
                try: _signal.signal(_signal.SIGINT, _prev_sigint)
                except Exception: pass
            return {"answer": "[stuck-loop aborted: same action repeated]",
                    "trace": trace, "tools_used": tools_used,
                    "iters": it, "stuck": True}

        if "final" in action:
            final_text = action["final"]
            if critical and critique and final_text and not action.get("_critiqued"):
                emit({"type": "self_critique_start"})
                fix = _self_critique(task, final_text)
                if fix:
                    log.info("generalist: self-critique surfaced flaws; regenerating")
                    emit({"type": "self_critique_failed",
                          "preview": fix[:200]})
                    try:
                        from agents.reflexion import save_reflection
                        save_reflection(task,
                                         f"first draft was rejected by self-critique: {fix[:400]}")
                    except Exception:
                        pass
                    history.append({"role": "tool", "name": "_self_critique",
                                    "result": "CRITIQUE OF YOUR DRAFT FINAL:\n"
                                              + fix[:2000]
                                              + "\nPlease emit a corrected final."})
                    tools_used.append("self_critique")
                    continue
                emit({"type": "self_critique_passed"})
            if pf is not None:
                pf.shutdown()
            with _STATE_LOCK:
                _SCRATCHPADS.pop(run_id, None)
                _INTERRUPTED.pop(run_id, None)
            try: _RUN_ID_VAR.reset(_run_id_token)
            except Exception: pass
            if _prev_sigint is not None:
                try: _signal.signal(_signal.SIGINT, _prev_sigint)
                except Exception: pass
            # Auto Ze-verify on final answer: scan every <file>:<line> ref
            # against the file system. Broken refs are surfaced as a header
            # so the user (or downstream agent) sees them. Best-effort —
            # never block on Ze-verify failure here; the answer still goes out.
            broken_refs: list[str] = []
            ast_wrong: list[str] = []
            try:
                from agents.orchestrator import _ze_verify_output
                _vr = _ze_verify_output(final_text)
                if _vr.bad:
                    broken_refs = list(_vr.bad)
                    head = "; ".join(broken_refs[:5])
                    extra = "" if len(broken_refs) <= 5 else f"; +{len(broken_refs)-5} more"
                    final_text = (
                        f"[Ze-verify] {_vr.ok}/{_vr.total} refs OK; "
                        f"BROKEN ({len(broken_refs)}): {head}{extra}\n\n"
                        + final_text
                    )
            except Exception as _e:
                log.debug(f"final-stage Ze-verify failed: {_e}")
            try:
                from agents.ast_verify import verify_claims as _ast_verify_claims
                from pathlib import Path as _Path
                _aim_root = _Path(__file__).resolve().parent.parent
                _ar = _ast_verify_claims(final_text, search_root=_aim_root)
                if _ar.bad:
                    ast_wrong = list(_ar.bad)
                    head = "; ".join(ast_wrong[:5])
                    extra = "" if len(ast_wrong) <= 5 else f"; +{len(ast_wrong)-5} more"
                    final_text = (
                        f"[Ze-AST] {_ar.ok}/{_ar.total} claims OK; "
                        f"WRONG ({len(ast_wrong)}): {head}{extra}\n\n"
                        + final_text
                    )
            except Exception as _e:
                log.debug(f"final-stage AST verify failed: {_e}")

            emit({"type": "final", "answer": final_text,
                  "tools_used": tools_used, "iters": it + 1,
                  "broken_refs": broken_refs,
                  "ast_wrong": ast_wrong})
            return {"answer": final_text, "trace": trace,
                    "tools_used": tools_used, "iters": it + 1,
                    "broken_refs": broken_refs,
                    "ast_wrong": ast_wrong}

        # Multi-action pipeline (A3) — mixed sequential + parallel groups
        if isinstance(action.get("actions"), list) and action["actions"]:
            for step in action["actions"]:
                if not isinstance(step, dict):
                    continue
                if isinstance(step.get("parallel"), list) and step["parallel"]:
                    calls = step["parallel"]
                    for c in calls:
                        emit({"type": "tool_call", "tool": c.get("tool"),
                              "args": c.get("args"), "parallel": True})
                    results = _run_tools_parallel(calls)
                    for call, result in zip(calls, results):
                        tname = call.get("tool", "?")
                        tools_used.append(f"{tname}*")
                        history.append({"role": "tool", "name": tname,
                                        "result": str(result)[:4000]})
                        emit({"type": "tool_result", "tool": tname,
                              "ok": not str(result).startswith("ERROR"),
                              "result_preview": str(result)[:200]})
                else:
                    tname = step.get("tool")
                    args = step.get("args") or {}
                    if tname not in _TOOLS:
                        history.append({"role": "tool", "name": tname or "?",
                                        "result": f"ERROR:NOT_FOUND:unknown tool '{tname}'"})
                        continue
                    tools_used.append(tname)
                    emit({"type": "tool_call", "tool": tname, "args": args,
                          "parallel": False})
                    result = _run_one_tool(tname, args)
                    history.append({"role": "tool", "name": tname,
                                    "result": str(result)[:4000]})
                    emit({"type": "tool_result", "tool": tname,
                          "ok": not str(result).startswith("ERROR"),
                          "result_preview": str(result)[:200]})
            continue

        # Parallel tool calls — fan-out concurrently
        if isinstance(action.get("parallel"), list) and action["parallel"]:
            calls = action["parallel"]
            for c in calls:
                emit({"type": "tool_call", "tool": c.get("tool"),
                      "args": c.get("args"), "parallel": True})
            results = _run_tools_parallel(calls)
            for call, result in zip(calls, results):
                tname = call.get("tool", "?")
                tools_used.append(f"{tname}*")
                history.append({"role": "tool", "name": tname,
                                "result": str(result)[:4000]})
                emit({"type": "tool_result", "tool": tname,
                      "ok": not str(result).startswith("ERROR"),
                      "result_preview": str(result)[:200]})
            continue

        # Single tool call
        tool = action.get("tool")
        args = action.get("args") or {}
        if tool not in _TOOLS:
            history.append({"role": "tool", "name": tool or "?",
                            "result": f"ERROR:NOT_FOUND:unknown tool '{tool}'. "
                                      f"Available: {list(_TOOLS)}"})
            emit({"type": "tool_error", "tool": tool, "reason": "unknown"})
            continue
        tools_used.append(tool)
        emit({"type": "tool_call", "tool": tool, "args": args, "parallel": False})
        cached = pf.consume(tool, args) if pf is not None else None
        if cached is not None:
            tools_used[-1] = f"{tool}+spec"
            result = cached
            emit({"type": "tool_result", "tool": tool, "cached": True,
                  "ok": not str(result).startswith("ERROR"),
                  "result_preview": str(result)[:200]})
        else:
            result = _run_one_tool(tool, args)
            emit({"type": "tool_result", "tool": tool, "cached": False,
                  "ok": not str(result).startswith("ERROR"),
                  "result_preview": str(result)[:200]})
        history.append({"role": "tool", "name": tool, "result": str(result)[:4000]})

    if pf is not None:
        pf.shutdown()
    with _STATE_LOCK:
        _SCRATCHPADS.pop(run_id, None)
        _INTERRUPTED.pop(run_id, None)
    try: _RUN_ID_VAR.reset(_run_id_token)
    except Exception: pass
    if _prev_sigint is not None:
        try: _signal.signal(_signal.SIGINT, _prev_sigint)
        except Exception: pass
    return {"answer": "[max iterations reached without final answer]",
            "trace": trace, "tools_used": tools_used, "iters": max_iters}


def run_streaming(task: str, **kwargs):
    """Generator wrapper that yields events as the generalist works.

    Usage:
        for ev in run_streaming("задача"):
            if ev["type"] == "tool_call":  print(f"  → {ev['tool']}")
            elif ev["type"] == "final":    print(ev["answer"])
    """
    import threading
    import queue as _queue
    q: _queue.Queue = _queue.Queue()
    DONE = object()

    def _emit(ev: dict) -> None:
        q.put(ev)

    def _worker():
        try:
            run(task, on_event=_emit, **kwargs)
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(DONE)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    while True:
        ev = q.get()
        if ev is DONE:
            return
        yield ev


def _run_one_tool(tool: str, args: Any) -> str:
    if tool not in _TOOLS:
        return f"ERROR:NOT_FOUND:unknown tool '{tool}'"
    try:
        if isinstance(args, dict):
            return str(_TOOLS[tool].fn(**args))
        return str(_TOOLS[tool].fn(args))
    except TypeError as e:
        return f"ERROR:INVALID_INPUT:bad arguments to {tool} — {e}"
    except Exception as e:
        return f"ERROR:INTERNAL:{tool} raised: {e}"


def _run_tools_parallel(calls: list[dict], max_workers: int = 6) -> list[str]:
    """Run multiple independent tool calls concurrently. Order preserved."""
    out = [""] * len(calls)
    if not calls:
        return out
    with ThreadPoolExecutor(max_workers=min(max_workers, len(calls))) as pool:
        futs = {pool.submit(_run_one_tool, c.get("tool", ""), c.get("args") or {}): i
                for i, c in enumerate(calls)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    return out


_CRITIQUED_TASKS: set[str] = set()


def _self_critique(task: str, draft: str) -> str:
    """Adversarial review of a draft final. Returns critique text only when
    the reviewer flags MATERIAL flaws (≥1 of: missing fact, unsupported
    claim, fabricated citation, factually wrong, harmful advice). One-shot
    only per task — `_CRITIQUED_TASKS` ensures we don't loop."""
    key = task[:200]
    if key in _CRITIQUED_TASKS:
        return ""
    _CRITIQUED_TASKS.add(key)
    crit_sys = (
        "You are an adversarial reviewer. Your job is to find MATERIAL flaws "
        "in the draft answer below. Material flaw = wrong fact, unsupported "
        "claim, fabricated PMID/DOI, harmful or unsafe advice, missing key "
        "constraint from the user request. Do NOT nitpick style.\n"
        "Output: if the draft is acceptable, reply EXACTLY with the literal "
        "string OK and nothing else. Otherwise list flaws as numbered bullets, "
        "each flaw 1-2 lines.")
    crit_prompt = (f"USER TASK: {task}\n\n=== DRAFT FINAL ANSWER ===\n{draft}\n=== END ===")
    try:
        verdict = ask_critical(crit_prompt, system=crit_sys).strip()
    except Exception as e:
        log.warning(f"self_critique LLM error: {e}")
        return ""
    if verdict.upper().startswith("OK") and len(verdict) <= 6:
        return ""
    return verdict


_TIKTOKEN_ENC = None


def _get_encoder():
    global _TIKTOKEN_ENC
    if _TIKTOKEN_ENC is not None:
        return _TIKTOKEN_ENC
    try:
        import tiktoken
        _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _TIKTOKEN_ENC = False    # sentinel: don't try again
    return _TIKTOKEN_ENC


def _count_text_tokens(text: str) -> int:
    """Best-effort token count. Uses tiktoken when available; otherwise
    a non-ASCII-aware estimate (~3.3 chars/tok for Latin, ~1.5 for CJK)."""
    if not text:
        return 0
    enc = _get_encoder()
    if enc:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Heuristic: count Latin and non-Latin separately
    latin = sum(1 for c in text if ord(c) < 0x80)
    other = len(text) - latin
    return max(1, latin // 4 + other // 2)


def _approx_tokens(history: list[dict]) -> int:
    return sum(_count_text_tokens(str(m.get("content", "") or m.get("result", "")))
               for m in history)


def _maybe_compact(history: list[dict], *, threshold_tokens: int = 30_000,
                   keep_last: int = 4) -> list[dict]:
    """If history grows too large, summarise everything but the last N turns.

    Returns the (possibly-compacted) history list. The summary is inserted
    as a synthetic role='tool' entry named '_compacted'.
    """
    if _approx_tokens(history) < threshold_tokens or len(history) < keep_last + 4:
        return history
    head = history[:-keep_last]
    tail = history[-keep_last:]
    blob = "\n\n".join(
        (f"[{m.get('role')}]" + (f"[{m.get('name')}]" if m.get("name") else "")
         + " " + (m.get("content") or m.get("result") or "")[:1500])
        for m in head
    )
    try:
        from llm import ask_long
        summary = ask_long(
            "Compact the following AIM agent transcript. Preserve every "
            "decision, every tool result that contains a fact the agent will "
            "still need, and every blocked/failed action. Drop verbosity. "
            "Output a numbered list under 1500 tokens.\n\n=== TRANSCRIPT ===\n"
            + blob,
            system="You are a transcript compactor. Be terse and lossless.",
            max_tokens=4096,
        )
    except Exception as e:
        log.warning(f"compaction failed: {e}; truncating instead")
        summary = ("(compaction failed; only most recent turns retained)")
    log.info(f"generalist: compacted {len(head)} earlier turns "
             f"(~{_approx_tokens(head)} tok → {len(summary)//4} tok)")
    return [
        history[0],     # original user task
        {"role": "tool", "name": "_compacted",
         "result": "EARLIER TURNS COMPACTED:\n" + summary},
        *tail,
    ]


def _render_for_llm(history: list[dict]) -> str:
    """Synthetic-prompt fallback (used when provider can't take messages[])."""
    parts = []
    for msg in history:
        role = msg.get("role")
        if role == "user":
            parts.append(f"USER: {msg['content']}")
        elif role == "tool":
            parts.append(f"TOOL[{msg['name']}] →\n{msg['result']}")
        elif role == "assistant":
            parts.append(f"ASSISTANT (you previously): {msg['content'][:1000]}")
    parts.append("\nReply with ONE JSON object: a tool call, parallel batch, OR a final answer.")
    return "\n\n".join(parts)


def _render_messages(history: list[dict], system: str) -> list[dict]:
    """Native OpenAI-compatible messages[] for DeepSeek/Gemini/Groq.
    Tool results become assistant + user pairs (since OpenAI-compat /v1
    surfaces don't always allow standalone role='tool' without prior
    tool_calls). This formulation works on all three providers reliably.
    """
    msgs: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        role = m.get("role")
        if role == "user":
            msgs.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            msgs.append({"role": "assistant", "content": m["content"]})
        elif role == "tool":
            msgs.append({"role": "user",
                         "content": f"[tool_result:{m.get('name','?')}]\n"
                                    f"{m.get('result','')}"})
    msgs.append({"role": "user",
                 "content": "Reply with ONE JSON object: "
                            '{"tool":...,"args":...} OR '
                            '{"parallel":[...]} OR {"final":"..."}'})
    return msgs


def _llm_call_msgs(messages: list[dict]) -> str:
    """Call DeepSeek-V4-flash with structured messages — better cache hit
    rate and tool-use accuracy than synthetic prompt rendering. Falls back
    to ask() if DS unreachable."""
    from llm import (DEEPSEEK_API_KEY, _deepseek, _breaker_for, _limiter_for,
                      _record_llm_error)
    from config import Models, LLM_TEMPERATURE, LLM_MAX_TOKENS
    if not DEEPSEEK_API_KEY:
        return ""
    _breaker_for("deepseek").before_call()
    _limiter_for("deepseek").acquire()
    try:
        resp = _deepseek().chat.completions.create(
            model=Models.DS_CHAT, messages=messages,
            temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        _breaker_for("deepseek").on_success()
        return resp.choices[0].message.content.strip()
    except Exception as e:
        _breaker_for("deepseek").on_failure()
        _record_llm_error("deepseek", e)
        log.warning(f"DS structured call failed, fallback to ask(): {e}")
        return ""


def _parse_action(raw: str) -> dict:
    """Extract a valid JSON action from the model output. Returns {} on
    parse failure (caller will feed the failure back to the LLM and retry
    instead of treating raw text as a final answer)."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    import re as _re
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # First balanced {...} block
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    start = -1
    return {}   # parse failure — treated explicitly by run()
