"""tests/test_path_sandbox.py — G2 path sandbox (2026-05-02).

Verifies that read_file / view_file / write_file / edit_file / apply_patch
refuse to touch:
  * secret-path patterns (~/.ssh/, ~/.aim_env, ~/.aws/, ~/.gnupg/, etc.)
  * any write outside AIM_GENERALIST_ROOT (default ~/Desktop)
  * traversal escapes (`~/Desktop/../etc/passwd`)
  * symlink escapes (a symlink inside the root pointing outside)

AIM_NO_PATH_SANDBOX=1 disables the gate entirely (CLI override).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agents.generalist import (
    _gate_path,
    _t_read_file,
    _t_view_file,
    _t_write_file,
    _t_edit_file,
    _t_apply_patch,
)


# ── _gate_path direct unit tests ──────────────────────────────────────


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    """Make AIM_GENERALIST_ROOT point at an empty tmp dir for the test.
    Drops AIM_NO_PATH_SANDBOX in case it leaked in from the user's env."""
    monkeypatch.setenv("AIM_GENERALIST_ROOT", str(tmp_path))
    monkeypatch.delenv("AIM_NO_PATH_SANDBOX", raising=False)
    return tmp_path


@pytest.mark.parametrize("path", [
    "~/.ssh/id_rsa",
    "~/.ssh/authorized_keys",
    "~/.aim_env",
    "~/.aws/credentials",
    "~/.kube/config",
    "~/.gnupg/private-keys-v1.d",
    "~/.netrc",
    "~/.config/sops/age/keys.txt",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/sudoers.d/whatever",
    "~/.bash_history",
    "~/.zsh_history",
    "~/.npmrc",
    "~/.pypirc",
    "~/.docker/config.json",
])
def test_gate_blocks_secret_paths_on_read(path, isolated_root):
    err = _gate_path(path, write=False)
    assert err is not None and "secret-path" in err, (
        f"Expected secret-path block for {path!r}, got {err}")


def test_gate_blocks_write_outside_root(isolated_root, tmp_path):
    # Outside the configured root → write must be rejected.
    other = tmp_path.parent / "outside.txt"
    err = _gate_path(str(other), write=True)
    assert err is not None and "outside AIM_GENERALIST_ROOT" in err


def test_gate_blocks_traversal(isolated_root, tmp_path):
    # `<root>/../etc/passwd` — resolve() flattens .. so the result is /etc/passwd.
    # That hits the secret-path deny-list, OR the outside-root check, depending
    # on which fires first. Either is a correct refusal.
    target = str(tmp_path / ".." / "etc" / "passwd")
    err = _gate_path(target, write=True)
    assert err is not None
    assert "PERMISSION" in err


def test_gate_allows_writes_inside_root(isolated_root):
    target = isolated_root / "subdir" / "file.txt"
    err = _gate_path(str(target), write=True)
    assert err is None, f"unexpected refusal: {err}"


def test_gate_allows_reads_inside_root(isolated_root):
    f = isolated_root / "readme.md"
    f.write_text("hello")
    err = _gate_path(str(f), write=False)
    assert err is None


def test_gate_bypassed_by_env_var(isolated_root, monkeypatch):
    monkeypatch.setenv("AIM_NO_PATH_SANDBOX", "1")
    err = _gate_path("/etc/shadow", write=True)
    assert err is None  # bypass active


# ── End-to-end tool refusals ──────────────────────────────────────────


def test_read_file_refuses_aim_env(isolated_root):
    out = _t_read_file("~/.aim_env")
    assert out.startswith("ERROR:PERMISSION") and "secret-path" in out


def test_view_file_refuses_ssh(isolated_root):
    out = _t_view_file("~/.ssh/id_rsa")
    assert out.startswith("ERROR:PERMISSION")


def test_write_file_refuses_outside_root(isolated_root, tmp_path):
    target = tmp_path.parent / "leaked.txt"
    out = _t_write_file(str(target), "should never land")
    assert out.startswith("ERROR:PERMISSION")
    assert not target.exists()


def test_write_file_refuses_secret_path(isolated_root):
    out = _t_write_file("~/.ssh/authorized_keys", "evil")
    assert out.startswith("ERROR:PERMISSION")


def test_write_file_allows_inside_root(isolated_root):
    target = isolated_root / "ok.md"
    out = _t_write_file(str(target), "hello-aim")
    assert out.startswith("OK")
    assert target.read_text() == "hello-aim"


def test_edit_file_refuses_secret_path(isolated_root):
    out = _t_edit_file("~/.bashrc", "old", "evil")
    assert out.startswith("ERROR:")  # either PERMISSION or NOT_FOUND


def test_edit_file_refuses_outside_root(isolated_root, tmp_path):
    target = tmp_path.parent / "outside.txt"
    target.write_text("old text")
    try:
        out = _t_edit_file(str(target), "old", "evil")
        assert out.startswith("ERROR:PERMISSION")
        assert target.read_text() == "old text"  # untouched
    finally:
        target.unlink(missing_ok=True)


def test_apply_patch_refuses_target_outside_root(isolated_root, tmp_path):
    outside = tmp_path.parent / "outside_patch.txt"
    diff = (
        f"--- a/{outside}\n"
        f"+++ b/{outside}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    out = _t_apply_patch(diff, strip=1)
    # Either PERMISSION (path sandbox) or git-apply failure if we got that far;
    # _t_apply_patch checks paths up-front so we expect the sandbox refusal.
    assert out.startswith("ERROR:PERMISSION"), f"got: {out}"


def test_apply_patch_refuses_secret_target(isolated_root):
    diff = (
        "--- a/.ssh/authorized_keys\n"
        "+++ b/.ssh/authorized_keys\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+ssh-rsa EVIL\n"
    )
    out = _t_apply_patch(diff, strip=1)
    assert out.startswith("ERROR:PERMISSION")


# ── Symlink escape ────────────────────────────────────────────────────


def test_symlink_into_secret_path_is_blocked(isolated_root):
    """Symlinks that resolve into a secret-path pattern must be refused.

    G2 design choice (2026-05-02): READS are liberal — only the secret-path
    deny-list applies, no root-prefix check. This test confirms that the
    deny-list still catches symlink-laundering: an "innocent" link inside
    the sandbox that points at ~/.ssh resolves to a deny-listed path, so
    the read must fail.

    For WRITES, the prefix check is enforced separately (test_write_file_*).
    """
    home = Path.home()
    real_target = home / ".ssh"
    if not real_target.exists():
        pytest.skip("~/.ssh missing on this host")
    link = isolated_root / "innocent.md"
    os.symlink(real_target, link)
    out = _t_read_file(str(link))
    assert out.startswith("ERROR:PERMISSION"), (
        f"symlink to ~/.ssh must be refused, got: {out!r}")
