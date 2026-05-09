use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::Value;

pub struct Bash;

/// Tightly scoped: each entry is (program, allowed-args-prefixes).
/// We require ALL args to start with one of the prefixes, OR be one of the
/// fixed allowed flags. This blocks `python -c <code>`, `cargo run`,
/// `find -delete`, etc.
const ALLOW: &[(&str, &[&str])] = &[
    ("ls",       &["-l", "-a", "-la", "-1", "-h", "/", "."]),
    ("cat",      &["/", "."]),
    ("head",     &["-n", "/", "."]),
    ("tail",     &["-n", "-f", "/", "."]),
    ("wc",       &["-l", "-c", "-w", "/", "."]),
    ("file",     &["/", "."]),
    ("stat",     &["/", "."]),
    ("pwd",      &[]),
    ("which",    &[]),     // arg is a bare name — no prefix needed
    ("echo",     &[]),
    // git: read-only subcommands only. `remote` removed 2026-05-02 — it
    // can create network-bound side effects (e.g. `git remote add origin
    // http://evil`). Network ops (clone/fetch/pull/push) and config
    // mutators (config/credential) remain absent from this list.
    ("git",      &["status", "log", "diff", "show", "branch", "rev-parse", "ls-files"]),
    ("rg",       &["-n", "-i", "-l", "-c", "/", ".", "--"]),
    ("grep",     &["-n", "-i", "-r", "-l", "-c", "/", ".", "--"]),
    ("sqlite3",  &["/", ".", "--"]),  // sqlite3 file query — assume read-only intent
    ("tree",     &["-L", "-d", "/", "."]),
];

// Flags that enable arbitrary code execution, FS mutation, or
// configuration tampering on commands that are otherwise read-only.
// Matched as PREFIX (so `--exec-path=…` is caught alongside `--exec`).
const BLOCKED_FLAG_PREFIXES: &[&str] = &[
    "-c",          // python/elixir/bash -c <code>
    "-e",          // elixir -e
    "--exec",      // git --exec-path, find --exec
    "--config",    // git --config-env, --config
    "-delete",     // find -delete
    "-execdir",
    "-fprint",     // covers -fprint, -fprint0, -fprintf, -fls
    "-fls",
    "-ok",         // covers -ok, -okdir
];

#[async_trait]
impl Tool for Bash {
    fn name(&self) -> &'static str { "bash" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let cmd = args.get("command").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: command".to_string())?;
        let timeout_ms = args.get("timeout_ms").and_then(|v| v.as_u64()).unwrap_or(30_000).min(60_000);

        for ch in &['|', ';', '&', '`', '$', '>', '<', '\n', '\\'] {
            if cmd.contains(*ch) {
                return Err(format!("forbidden shell metachar: {ch:?}"));
            }
        }

        let mut parts = cmd.split_whitespace();
        let head = parts.next().unwrap_or("");
        let rest: Vec<&str> = parts.collect();

        let allowed_args = ALLOW.iter().find(|(p, _)| *p == head)
            .map(|(_, a)| *a)
            .ok_or_else(|| format!("command '{head}' not in allow-list"))?;

        for arg in &rest {
            if BLOCKED_FLAG_PREFIXES.iter().any(|p| arg.starts_with(p)) {
                return Err(format!("blocked flag: {arg}"));
            }
        }

        // Per-arg validation: must start with one of allowed prefixes OR be a
        // dotted relative path / a bare token (for tools like `which`).
        if !allowed_args.is_empty() {
            for arg in &rest {
                let ok = allowed_args.iter().any(|p| arg.starts_with(p))
                    || arg.starts_with("./")
                    || (!arg.starts_with('-') && !arg.contains('/'));
                if !ok {
                    return Err(format!(
                        "arg '{arg}' not allowed for '{head}'; allowed prefixes: {:?}", allowed_args
                    ));
                }
            }
        }

        let fut = tokio::process::Command::new(head)
            .args(&rest)
            .output();

        let out = tokio::time::timeout(std::time::Duration::from_millis(timeout_ms), fut).await
            .map_err(|_| format!("timeout after {timeout_ms} ms"))?
            .map_err(|e| format!("spawn: {e}"))?;

        let stdout = String::from_utf8_lossy(&out.stdout);
        let stderr = String::from_utf8_lossy(&out.stderr);

        // Truncate output to keep context manageable.
        let head_text = head_truncate(&stdout, 16_000);
        let err_text = head_truncate(&stderr, 4_000);
        Ok(format!("[exit {}]\nSTDOUT:\n{}\nSTDERR:\n{}",
            out.status.code().unwrap_or(-1), head_text, err_text))
    }
}

fn head_truncate(s: &str, max: usize) -> String {
    if s.len() <= max { return s.to_string(); }
    let mut i = max;
    while !s.is_char_boundary(i) && i > 0 { i -= 1; }
    format!("{}…[truncated; total {} bytes]", &s[..i], s.len())
}
