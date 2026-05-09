//! aim-worktree — git worktree isolation for self-modifying flows.
//!
//! Lets self-modifying agents (S2 tool synthesis, S6 code patches)
//! run generated code in a throwaway branch instead of corrupting the
//! main checkout.
//!
//! ```no_run
//! use aim_worktree::isolate;
//! let mut wt = isolate(".", None).unwrap();
//! wt.write_file("foo.txt", "hello").unwrap();
//! wt.commit("first try", None).unwrap();
//! // wt drops → branch + dir survive (default keep_on_success=true)
//! ```
//!
//! Rust port of `agents/worktree.py`. Same design rules:
//! - Each isolation creates a NEW branch off `HEAD` (no writing to
//!   existing branches).
//! - Cleanup is best-effort. `cleanup_orphans` reaps `aim/*` branches
//!   older than `older_than_hours`.
//! - `merge_to` defaults to `--ff-only`; pass `Strategy::ThreeWay` for
//!   `--no-ff` (caller must satisfy L_CONSENT).

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum WorktreeError {
    #[error("not a git repo: {0}")]
    NotARepo(PathBuf),
    #[error("git command failed: {0}")]
    Git(String),
    #[error("path escapes worktree: {0}")]
    PathEscapes(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid input: {0}")]
    Invalid(String),
}

/// Run `git ...` and capture (rc, stdout, stderr).
fn run(argv: &[&str], cwd: &Path) -> std::io::Result<(i32, String, String)> {
    let out = Command::new(argv[0]).args(&argv[1..]).current_dir(cwd).output()?;
    Ok((
        out.status.code().unwrap_or(-1),
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    ))
}

fn is_repo(path: &Path) -> bool {
    path.join(".git").exists() || path.join("HEAD").exists()
}

pub fn worktrees_root() -> PathBuf {
    if let Ok(s) = std::env::var("AIM_WORKTREE_ROOT") {
        return PathBuf::from(s);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".aim").join("worktrees")
}

fn branch_safe(name: &str) -> String {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-zA-Z0-9._/\-]+").unwrap());
    let cleaned = RE.replace_all(name, "-");
    let trimmed: String = cleaned
        .trim_matches('-')
        .chars()
        .take(60)
        .collect();
    if trimmed.is_empty() {
        use rand::Rng;
        let mut rng = rand::thread_rng();
        let bytes: [u8; 4] = rng.gen();
        return hex::encode(bytes);
    }
    trimmed
}

mod hex {
    pub fn encode(bytes: impl AsRef<[u8]>) -> String {
        bytes
            .as_ref()
            .iter()
            .map(|b| format!("{:02x}", b))
            .collect()
    }
}

#[derive(Debug, Clone, Copy)]
pub enum Strategy {
    FfOnly,
    ThreeWay,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestResult {
    pub ok: bool,
    pub rc: i32,
    pub stdout: String,
    pub stderr: String,
}

pub struct Worktree {
    pub repo: PathBuf,
    pub branch: String,
    pub path: PathBuf,
    /// When true, `discard` skips removing on drop.
    keep_on_success: bool,
    closed: bool,
}

impl Worktree {
    pub fn write_file(&self, rel: &str, content: &str) -> Result<PathBuf, WorktreeError> {
        let p = self.path.join(rel);
        let resolved = p
            .canonicalize()
            .or_else(|_| {
                if let Some(parent) = p.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::write(&p, content)?;
                p.canonicalize()
            })?;
        let root = self.path.canonicalize()?;
        if !resolved.starts_with(&root) {
            return Err(WorktreeError::PathEscapes(rel.to_string()));
        }
        // Re-write in case canonicalize ran on a non-existent path
        if let Some(parent) = resolved.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&resolved, content)?;
        Ok(resolved)
    }

    pub fn read_file(&self, rel: &str) -> Result<String, WorktreeError> {
        let p = self.path.join(rel);
        let resolved = p
            .canonicalize()
            .map_err(|_| WorktreeError::Invalid(format!("not found: {rel}")))?;
        let root = self.path.canonicalize()?;
        if !resolved.starts_with(&root) {
            return Err(WorktreeError::PathEscapes(rel.to_string()));
        }
        Ok(std::fs::read_to_string(&resolved)?)
    }

    /// Stage all + commit. Returns the resulting commit SHA.
    pub fn commit(&self, message: &str, author: Option<&str>) -> Result<String, WorktreeError> {
        let (rc, _, err) = run(&["git", "add", "-A"], &self.path)?;
        if rc != 0 {
            return Err(WorktreeError::Git(format!("git add: {}", err.trim())));
        }
        let author = author.unwrap_or("AIM <aim@local>");
        let args = vec![
            "git",
            "-c",
            "user.name=AIM",
            "-c",
            "user.email=aim@local",
            "commit",
            "-m",
            message,
            "--no-verify",
            "--author",
            author,
        ];
        let (rc, out, err) = run(&args, &self.path)?;
        if rc != 0 && !(out.to_lowercase() + &err.to_lowercase()).contains("nothing to commit") {
            return Err(WorktreeError::Git(format!("git commit: {}", err.trim())));
        }
        let (rc, sha, err) = run(&["git", "rev-parse", "HEAD"], &self.path)?;
        if rc != 0 {
            return Err(WorktreeError::Git(format!("rev-parse: {}", err.trim())));
        }
        Ok(sha.trim().to_string())
    }

    /// Merge this branch into the main repo. Refuses non-fast-forward
    /// unless `Strategy::ThreeWay`.
    pub fn merge_to(&mut self, _target: &str, strategy: Strategy) -> Result<bool, WorktreeError> {
        if !self.closed {
            // best-effort commit any pending work
            let _ = self.commit("auto-commit before merge", None);
        }
        let flag = match strategy {
            Strategy::FfOnly => "--ff-only",
            Strategy::ThreeWay => "--no-ff",
        };
        let (rc, _, err) = run(&["git", "merge", flag, &self.branch], &self.repo)?;
        Ok(rc == 0 && {
            let _ = err;
            true
        })
    }

    /// Drop the worktree (and its branch) without merging.
    pub fn discard(&mut self) -> Result<(), WorktreeError> {
        if self.closed {
            return Ok(());
        }
        self.closed = true;
        let path_str = self.path.to_string_lossy().to_string();
        let _ = run(
            &["git", "worktree", "remove", "--force", &path_str],
            &self.repo,
        );
        let _ = run(&["git", "branch", "-D", &self.branch], &self.repo);
        if self.path.exists() {
            let _ = std::fs::remove_dir_all(&self.path);
        }
        Ok(())
    }

    pub fn keep_on_drop(&mut self, keep: bool) {
        self.keep_on_success = keep;
    }
}

impl Drop for Worktree {
    fn drop(&mut self) {
        if !self.closed && !self.keep_on_success {
            let _ = self.discard();
        }
    }
}

/// Create a new branch off `base_ref` (default `HEAD`) in a fresh
/// worktree. The caller is responsible for `discard()` or letting the
/// `Drop` impl clean up (depending on `keep_on_success`).
pub fn isolate(
    repo: impl AsRef<Path>,
    branch: Option<&str>,
) -> Result<Worktree, WorktreeError> {
    isolate_with(repo, branch, "HEAD", true, None)
}

#[allow(clippy::too_many_arguments)]
pub fn isolate_with(
    repo: impl AsRef<Path>,
    branch: Option<&str>,
    base_ref: &str,
    keep_on_success: bool,
    root_override: Option<&Path>,
) -> Result<Worktree, WorktreeError> {
    let repo = repo.as_ref().canonicalize().map_err(|_| {
        WorktreeError::NotARepo(repo.as_ref().to_path_buf())
    })?;
    if !is_repo(&repo) {
        return Err(WorktreeError::NotARepo(repo));
    }
    let branch_name = match branch {
        Some(b) if !b.is_empty() => {
            let safe = branch_safe(b);
            if !safe.contains('/') {
                format!("aim/{safe}")
            } else {
                safe
            }
        }
        _ => {
            use rand::Rng;
            let mut rng = rand::thread_rng();
            let bytes: [u8; 3] = rng.gen();
            let token = hex::encode(bytes);
            let date = chrono::Utc::now().format("%Y%m%d");
            format!("aim/exp-{date}-{token}")
        }
    };
    let root = root_override
        .map(|p| p.to_path_buf())
        .unwrap_or_else(worktrees_root);
    std::fs::create_dir_all(&root)?;
    let path = root.join(branch_name.replace('/', "_"));
    let path_str = path.to_string_lossy().to_string();
    let (rc, _, err) = run(
        &["git", "worktree", "add", "-b", &branch_name, &path_str, base_ref],
        &repo,
    )?;
    if rc != 0 {
        return Err(WorktreeError::Git(format!(
            "worktree add: {}",
            err.trim()
        )));
    }
    Ok(Worktree {
        repo,
        branch: branch_name,
        path,
        keep_on_success,
        closed: false,
    })
}

/// Parse `git worktree list --porcelain`.
pub fn list_worktrees(
    repo: &Path,
) -> Result<Vec<std::collections::BTreeMap<String, String>>, WorktreeError> {
    let (rc, out, _) = run(&["git", "worktree", "list", "--porcelain"], repo)?;
    if rc != 0 {
        return Ok(Vec::new());
    }
    let mut items: Vec<std::collections::BTreeMap<String, String>> = Vec::new();
    let mut cur: std::collections::BTreeMap<String, String> = Default::default();
    for line in out.lines() {
        if line.trim().is_empty() {
            if !cur.is_empty() {
                items.push(std::mem::take(&mut cur));
            }
            continue;
        }
        let (k, v) = match line.split_once(' ') {
            Some((k, v)) => (k.to_string(), v.trim().to_string()),
            None => (line.to_string(), String::new()),
        };
        cur.insert(k, v);
    }
    if !cur.is_empty() {
        items.push(cur);
    }
    Ok(items)
}

/// Remove AIM-created worktrees older than `older_than_hours`. Only
/// matches branches starting with `aim/`.
pub fn cleanup_orphans(
    repo: &Path,
    older_than_hours: f64,
    dry_run: bool,
) -> Result<Vec<String>, WorktreeError> {
    let cutoff = std::time::SystemTime::now()
        - std::time::Duration::from_secs((older_than_hours * 3600.0) as u64);
    let mut removed: Vec<String> = Vec::new();
    for wt in list_worktrees(repo)? {
        let branch = wt
            .get("branch")
            .map(|s| s.trim_start_matches("refs/heads/").to_string())
            .unwrap_or_default();
        let path = wt.get("worktree").cloned().unwrap_or_default();
        if !branch.starts_with("aim/") || path.is_empty() {
            continue;
        }
        let mtime = std::fs::metadata(&path)
            .and_then(|m| m.modified())
            .ok();
        if let Some(t) = mtime {
            if t > cutoff {
                continue;
            }
        }
        if !dry_run {
            let _ = run(&["git", "worktree", "remove", "--force", &path], repo);
            let _ = run(&["git", "branch", "-D", &branch], repo);
        }
        removed.push(branch);
    }
    Ok(removed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn init_repo(d: &Path) {
        let _ = run(&["git", "init", "--initial-branch=main"], d).unwrap();
        let _ = run(&["git", "config", "user.email", "t@t"], d).unwrap();
        let _ = run(&["git", "config", "user.name", "t"], d).unwrap();
        std::fs::write(d.join("README"), "init").unwrap();
        let _ = run(&["git", "add", "-A"], d).unwrap();
        let _ = run(&["git", "commit", "-m", "init"], d).unwrap();
    }

    #[test]
    fn not_a_repo_errors() {
        let d = tempdir().unwrap();
        let r = isolate(d.path(), Some("test"));
        assert!(matches!(r, Err(WorktreeError::NotARepo(_))));
    }

    #[test]
    fn branch_safe_strips_unsafe_chars() {
        assert_eq!(branch_safe("hello world!!"), "hello-world");
        assert_eq!(branch_safe("path/with-dots.v2"), "path/with-dots.v2");
        assert!(branch_safe("!!!").chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn branch_safe_truncates_to_60_chars() {
        let b = branch_safe(&"x".repeat(120));
        assert_eq!(b.len(), 60);
    }

    fn iso(repo: &Path, root: &Path, name: &str) -> Worktree {
        isolate_with(repo, Some(name), "HEAD", true, Some(root)).unwrap()
    }

    #[test]
    fn isolate_creates_branch_and_dir() {
        let d = tempdir().unwrap();
        let root = d.path().join(".wt");
        init_repo(d.path());
        let mut wt = iso(d.path(), &root, "test-branch");
        assert!(wt.branch.starts_with("aim/"));
        assert!(wt.path.exists());
        wt.discard().unwrap();
    }

    #[test]
    fn write_file_within_worktree_works() {
        let d = tempdir().unwrap();
        let root = d.path().join(".wt");
        init_repo(d.path());
        let mut wt = iso(d.path(), &root, "write-test");
        let p = wt.write_file("foo.txt", "hello").unwrap();
        assert!(p.exists());
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "hello");
        wt.discard().unwrap();
    }

    #[test]
    fn read_file_round_trip() {
        let d = tempdir().unwrap();
        let root = d.path().join(".wt");
        init_repo(d.path());
        let mut wt = iso(d.path(), &root, "read-test");
        wt.write_file("a.txt", "abc").unwrap();
        let body = wt.read_file("a.txt").unwrap();
        assert_eq!(body, "abc");
        wt.discard().unwrap();
    }

    #[test]
    fn commit_returns_sha() {
        let d = tempdir().unwrap();
        let root = d.path().join(".wt");
        init_repo(d.path());
        let mut wt = iso(d.path(), &root, "commit-test");
        wt.write_file("x.txt", "y").unwrap();
        let sha = wt.commit("test commit", None).unwrap();
        assert_eq!(sha.len(), 40);
        assert!(sha.chars().all(|c| c.is_ascii_hexdigit()));
        wt.discard().unwrap();
    }

    #[test]
    fn list_worktrees_includes_main() {
        let d = tempdir().unwrap();
        init_repo(d.path());
        let items = list_worktrees(d.path()).unwrap();
        assert!(!items.is_empty());
    }

    #[test]
    fn cleanup_orphans_dry_run_no_remove() {
        let d = tempdir().unwrap();
        let root = d.path().join(".wt");
        init_repo(d.path());
        let _wt = iso(d.path(), &root, "cleanup");
        let removed = cleanup_orphans(d.path(), 1000.0, true).unwrap();
        assert_eq!(removed.len(), 0);
    }
}
