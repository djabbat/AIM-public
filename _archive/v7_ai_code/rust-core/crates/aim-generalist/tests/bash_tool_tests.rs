//! G1 hardening (2026-05-02): regression tests for the bash whitelist gate.
//!
//! Driven through Registry::dispatch so we never depend on the private
//! Bash type. The Rust gate is much stricter than the Python one (no
//! `find`, no `python` at all in the allowlist), so the attack matrix
//! here is smaller — we focus on flag-prefix matching, removing `git
//! remote`, and the existing forbidden-character set.

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;

async fn bash(cmd: &str) -> ToolResult {
    let reg = Registry::with_defaults();
    reg.dispatch(&ToolCall {
        name: "bash".into(),
        args: json!({ "command": cmd, "timeout_ms": 5000 }),
    }).await
}

fn err_msg(r: ToolResult) -> String {
    match r {
        ToolResult::Err(e) => e,
        ToolResult::Ok(o)  => panic!("expected Err, got Ok: {o}"),
    }
}

fn ok_msg(r: ToolResult) -> String {
    match r {
        ToolResult::Ok(o)  => o,
        ToolResult::Err(e) => panic!("expected Ok, got Err: {e}"),
    }
}

// ── Refusals ────────────────────────────────────────────────────────

#[tokio::test]
async fn rejects_unknown_command() {
    let e = err_msg(bash("python -V").await);
    assert!(e.contains("not in allow-list"), "got: {e}");
}

#[tokio::test]
async fn rejects_metacharacter_pipe() {
    let e = err_msg(bash("ls | wc").await);
    assert!(e.contains("forbidden shell metachar"), "got: {e}");
}

#[tokio::test]
async fn rejects_metacharacter_subshell() {
    let e = err_msg(bash("echo $(whoami)").await);
    assert!(e.contains("forbidden shell metachar"), "got: {e}");
}

#[tokio::test]
async fn rejects_git_clone() {
    // git clone is absent from the per-subcommand allowlist.
    let e = err_msg(bash("git clone https://example.com/x.git").await);
    assert!(e.contains("not allowed for 'git'"), "got: {e}");
}

#[tokio::test]
async fn rejects_git_remote_after_2026_05_02() {
    // `remote` was removed from git allowlist in the G1 hardening pass.
    let e = err_msg(bash("git remote -v").await);
    assert!(e.contains("not allowed for 'git'"), "got: {e}");
}

#[tokio::test]
async fn rejects_blocked_flag_prefix_exec_path() {
    // `--exec-path=…` previously slipped past exact-match BLOCKED_FLAGS.
    let e = err_msg(bash("git --exec-path=/tmp status").await);
    assert!(e.contains("blocked flag"), "got: {e}");
}

#[tokio::test]
async fn rejects_blocked_flag_config_env() {
    let e = err_msg(bash("git --config-env=foo=bar status").await);
    assert!(e.contains("blocked flag"), "got: {e}");
}

#[tokio::test]
async fn rejects_dash_c_anywhere_in_args() {
    // -c on any whitelisted command is dangerous (python/bash/elixir style).
    // git -c is also a thing (sets config for one invocation).
    let e = err_msg(bash("git -c core.editor=evil status").await);
    assert!(e.contains("blocked flag"), "got: {e}");
}

// ── Allowed ─────────────────────────────────────────────────────────

#[tokio::test]
async fn allows_safe_git_status() {
    let out = ok_msg(bash("git status").await);
    // We can't assert exit 0 (this may not be a git repo), but we should
    // have produced some output and not been refused.
    assert!(out.contains("[exit"), "expected exit marker, got: {out}");
}

#[tokio::test]
async fn allows_echo() {
    let out = ok_msg(bash("echo hello-aim").await);
    assert!(out.contains("hello-aim"), "got: {out}");
}

#[tokio::test]
async fn allows_pwd() {
    let out = ok_msg(bash("pwd").await);
    assert!(out.contains("[exit 0]"), "got: {out}");
}
