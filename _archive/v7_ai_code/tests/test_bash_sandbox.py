"""tests/test_bash_sandbox.py — G1 bash sandbox hardening (2026-05-02).

Verifies that the validation layer in agents.generalist._validate_bash
blocks the attack classes that the prior whitelist/metachar regime missed:

  * `python -c "..."` — arbitrary Python execution
  * `find -delete`, `find -exec` — filesystem mutation / external exec
  * `pip install`, `npm install`, `cargo run` — supply-chain code exec
  * `git clone`, `git config` — network / config tampering
  * shells (`bash`, `sh`) reaching async allowlist — full shell exec
  * deny-list args (`xargs`, `tee`, `eval`) used to escape per-command policy
  * `_t_bash_async` previously used shell=True — confirm validation is now applied
"""
from __future__ import annotations

import pytest

from agents.generalist import (
    _BASH_ALLOW,
    _BASH_ASYNC_ALLOW,
    _validate_bash,
    _t_bash,
    _t_bash_async,
)


# ── Direct validator unit tests ────────────────────────────────────────


@pytest.mark.parametrize("cmd", [
    # python arbitrary code
    'python -c "import os; os.system(\'rm -rf /tmp/x\')"',
    'python3 -c "print(1)"',
    "python -m http.server 8000",
    "python3 -i",
    # find FS-mutating actions
    "find /tmp -delete",
    "find . -name '*.py' -exec rm {} +",
    "find . -execdir sh {} +",
    "find . -fprintf /etc/passwd '%p\\n'",
    "find . -fprint /tmp/leak",
    "find . -ok rm {} +",
    # pip / supply chain
    "pip install requests",
    "pip uninstall foo",
    "pip download torch",
    # git network/config
    "git clone https://example.com/x.git",
    "git config --global core.editor evil",
    "git push origin main",
    "git fetch",
    "git pull",
    # pytest plugin loading
    "pytest -p evil_plugin",
])
def test_validator_blocks_dangerous_flags(cmd):
    err = _validate_bash(cmd, _BASH_ALLOW)
    assert err is not None and err.startswith("ERROR:PERMISSION"), (
        f"Expected refusal for {cmd!r}, got: {err}")


@pytest.mark.parametrize("cmd", [
    # Async allowlist must not leak shells / make.
    "bash -c 'whoami'",
    "sh script.sh",
    "zsh -c 'echo'",
])
def test_async_allowlist_no_shell(cmd):
    err = _validate_bash(cmd, _BASH_ASYNC_ALLOW)
    assert err is not None and err.startswith("ERROR:PERMISSION")


@pytest.mark.parametrize("cmd", [
    # Even though `xargs`/`tee`/`eval` are not in the first-token allowlist,
    # they previously could appear as argv to a whitelisted command via
    # quoting tricks. Now caught by the dangerous-token scan.
    "find . -name '*.txt' xargs",       # xargs as bare arg
    "git tee somefile",                 # tee as arg
    "python eval",                      # bare 'eval' arg
    "python bash",                      # bare 'bash' arg
])
def test_dangerous_tokens_in_args_are_blocked(cmd):
    err = _validate_bash(cmd, _BASH_ALLOW)
    assert err is not None and err.startswith("ERROR:PERMISSION")


@pytest.mark.parametrize("cmd", [
    # Metacharacter check — pre-existing, regression guard.
    "ls; cat /etc/passwd",
    "ls && rm x",
    "ls | tee /tmp/x",
    "echo $(whoami)",
    "echo `id`",
    "ls > /tmp/x",
    "ls < /etc/passwd",
])
def test_metacharacters_blocked(cmd):
    err = _validate_bash(cmd, _BASH_ALLOW)
    assert err is not None and err.startswith("ERROR:PERMISSION")


@pytest.mark.parametrize("cmd", [
    # Safe baseline — must pass validation.
    "ls -la",
    "cat README.md",
    "grep -rn 'foo' agents/",
    "find . -name '*.py' -type f",
    "git status",
    "git log --oneline -10",
    "git diff HEAD~1",
    "python --version",
    "python3 -V",
    "pytest tests/test_kernel.py -x",
    "wc -l agents/generalist.py",
    "diff a.txt b.txt",
])
def test_safe_commands_pass(cmd):
    err = _validate_bash(cmd, _BASH_ALLOW)
    assert err is None, f"Unexpected refusal for {cmd!r}: {err}"


# ── End-to-end via the actual tool ────────────────────────────────────


def test_t_bash_blocks_python_dash_c():
    out = _t_bash('python -c "print(99)"')
    assert out.startswith("ERROR:PERMISSION")


def test_t_bash_blocks_find_delete():
    out = _t_bash("find /tmp -name nothere -delete")
    assert out.startswith("ERROR:PERMISSION")


def test_t_bash_allows_safe():
    out = _t_bash("echo hello")
    assert "hello" in out
    assert not out.startswith("ERROR:")


def test_t_bash_async_blocks_shell_invocation():
    out = _t_bash_async("bash -c 'date'")
    assert out.startswith("ERROR:PERMISSION")


def test_t_bash_async_blocks_pip_install():
    out = _t_bash_async("pip install evil-pkg")
    assert out.startswith("ERROR:PERMISSION")


def test_t_bash_async_rejects_bad_cwd(tmp_path):
    out = _t_bash_async("ls", cwd=str(tmp_path / "does-not-exist"))
    assert out.startswith("ERROR:INVALID_INPUT")
