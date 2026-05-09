//! aim-memory-health — healthcheck framework for the AIM memory layer.
//!
//! Port of `agents/memory_health.py`. The Python module bundled checks
//! against LanceDB / GraphRAG pickle / memory_versioning snapshots —
//! all Python-tied storage concerns. The Rust port keeps the **check
//! orchestration shape** and exposes pluggable [`Inspector`] traits so
//! the host wires real LanceDB / pickle / FS inspectors.
//!
//! ## Issue codes (match Python)
//! - `INDEX_DIR_MISSING`
//! - `LANCEDB_TABLE_MISSING`
//! - `LANCEDB_EMPTY`
//! - `LANCEDB_CORRUPTED`
//! - `GRAPHRAG_CORRUPTED`
//! - `STATE_STALE`
//! - `STATE_CORRUPTED`
//! - `MEMORY_DIR_MISSING`
//! - `MEMORY_DIR_EMPTY`

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HealthError {
    #[error("inspector: {0}")]
    Inspector(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Status {
    Ok,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Issue {
    /// `INDEX_DIR_MISSING` / `LANCEDB_TABLE_MISSING` / etc.
    pub code: String,
    /// Optional context (`"diff: 12 files in state not on disk"`).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub detail: String,
}

impl Issue {
    pub fn new(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            detail: String::new(),
        }
    }

    pub fn with_detail(code: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            detail: detail.into(),
        }
    }

    /// `CODE: detail` if there's a detail, else just `CODE` — matches
    /// the Python issue-string format.
    pub fn render(&self) -> String {
        if self.detail.is_empty() {
            self.code.clone()
        } else {
            format!("{}: {}", self.code, self.detail)
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthReport {
    pub status: Status,
    pub issues: Vec<Issue>,
    pub checked_at: String,
    pub index_dir: String,
    pub memory_dir: String,
}

impl HealthReport {
    pub fn is_ok(&self) -> bool {
        self.status == Status::Ok
    }
}

#[derive(Debug, Clone)]
pub struct HealthPaths {
    pub index_dir: PathBuf,
    pub memory_dir: PathBuf,
    pub graphrag: PathBuf,
    pub state: PathBuf,
}

impl HealthPaths {
    /// Default paths matching `agents/memory_health.py`:
    /// - `~/.claude/memory_index/`
    /// - `~/.claude/projects/-home-oem/memory/`
    /// - `~/.claude/memory_index/graphrag.gpickle`
    /// - `~/.claude/memory_index/_index_state.pkl`
    pub fn default_layout() -> Self {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        let index_dir = home.join(".claude").join("memory_index");
        let memory_dir = home
            .join(".claude")
            .join("projects")
            .join("-home-oem")
            .join("memory");
        Self {
            graphrag: index_dir.join("graphrag.gpickle"),
            state: index_dir.join("_index_state.pkl"),
            index_dir,
            memory_dir,
        }
    }
}

/// Pluggable inspector — each implementation runs ONE check and returns
/// zero or one issues. The host wires real LanceDB / pickle / FS
/// implementations; tests inject `StubInspector`.
pub trait Inspector: Send + Sync {
    fn name(&self) -> &str;
    fn inspect(&self, paths: &HealthPaths) -> Result<Option<Issue>, HealthError>;
}

// ── Built-in inspectors that need no Python deps ────────────────────────

pub struct IndexDirInspector;
impl Inspector for IndexDirInspector {
    fn name(&self) -> &str {
        "index_dir"
    }
    fn inspect(&self, paths: &HealthPaths) -> Result<Option<Issue>, HealthError> {
        if !paths.index_dir.exists() {
            return Ok(Some(Issue::new("INDEX_DIR_MISSING")));
        }
        Ok(None)
    }
}

pub struct MemoryDirInspector;
impl Inspector for MemoryDirInspector {
    fn name(&self) -> &str {
        "memory_dir"
    }
    fn inspect(&self, paths: &HealthPaths) -> Result<Option<Issue>, HealthError> {
        if !paths.memory_dir.exists() {
            return Ok(Some(Issue::new("MEMORY_DIR_MISSING")));
        }
        let count = match std::fs::read_dir(&paths.memory_dir) {
            Ok(rd) => rd
                .filter_map(|e| e.ok())
                .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md"))
                .count(),
            Err(e) => {
                return Err(HealthError::Inspector(format!(
                    "memory_dir read failed: {e}"
                )))
            }
        };
        if count == 0 {
            return Ok(Some(Issue::new("MEMORY_DIR_EMPTY")));
        }
        Ok(None)
    }
}

/// Test stub — returns a pre-baked issue or none.
pub struct StubInspector {
    name: String,
    pub result: Result<Option<Issue>, HealthError>,
}

impl StubInspector {
    pub fn ok(name: &str) -> Self {
        Self {
            name: name.into(),
            result: Ok(None),
        }
    }
    pub fn flag(name: &str, code: &str) -> Self {
        Self {
            name: name.into(),
            result: Ok(Some(Issue::new(code))),
        }
    }
    pub fn flag_with_detail(name: &str, code: &str, detail: &str) -> Self {
        Self {
            name: name.into(),
            result: Ok(Some(Issue::with_detail(code, detail))),
        }
    }
    pub fn err(name: &str, e: &str) -> Self {
        Self {
            name: name.into(),
            result: Err(HealthError::Inspector(e.into())),
        }
    }
}

impl Inspector for StubInspector {
    fn name(&self) -> &str {
        &self.name
    }
    fn inspect(&self, _paths: &HealthPaths) -> Result<Option<Issue>, HealthError> {
        // Clone the result — Result<Option<Issue>, HealthError> isn't Clone, so re-build manually.
        match &self.result {
            Ok(None) => Ok(None),
            Ok(Some(i)) => Ok(Some(i.clone())),
            Err(e) => Err(HealthError::Inspector(e.to_string())),
        }
    }
}

/// Drive a chain of inspectors against `paths`. Inspector errors become
/// `INSPECTOR_ERROR: <name>: <msg>` issues — the check still runs all
/// remaining inspectors instead of bailing out. Status = OK iff zero
/// issues; FAILED otherwise.
pub fn check(
    paths: &HealthPaths,
    inspectors: &[&dyn Inspector],
) -> HealthReport {
    let mut issues: Vec<Issue> = Vec::new();
    for ins in inspectors {
        match ins.inspect(paths) {
            Ok(None) => {}
            Ok(Some(i)) => issues.push(i),
            Err(e) => issues.push(Issue::with_detail(
                "INSPECTOR_ERROR",
                format!("{}: {}", ins.name(), e),
            )),
        }
    }
    let status = if issues.is_empty() {
        Status::Ok
    } else {
        Status::Failed
    };
    HealthReport {
        status,
        issues,
        checked_at: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        index_dir: paths.index_dir.to_string_lossy().to_string(),
        memory_dir: paths.memory_dir.to_string_lossy().to_string(),
    }
}

/// Convenience: run the built-in FS-only inspectors plus any extras the
/// host wired (LanceDB / GraphRAG / state). Built-ins always run first
/// so the most basic invariants surface even when fancier checks crash.
pub fn check_with_defaults<'a>(
    paths: &HealthPaths,
    extras: &[&'a dyn Inspector],
) -> HealthReport {
    let index_dir = IndexDirInspector;
    let memory_dir = MemoryDirInspector;
    let defaults: Vec<&dyn Inspector> = vec![&index_dir, &memory_dir];
    let mut all = defaults.clone();
    for e in extras {
        all.push(*e);
    }
    check(paths, &all)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn paths_in(dir: &TempDir) -> HealthPaths {
        let index = dir.path().join("memory_index");
        let memory = dir.path().join("memory");
        HealthPaths {
            graphrag: index.join("graphrag.gpickle"),
            state: index.join("_index_state.pkl"),
            index_dir: index,
            memory_dir: memory,
        }
    }

    #[test]
    fn issue_render_with_and_without_detail() {
        assert_eq!(Issue::new("X").render(), "X");
        assert_eq!(Issue::with_detail("X", "y").render(), "X: y");
    }

    #[test]
    fn ok_report_when_no_issues() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let s_ok = StubInspector::ok("noop");
        let report = check(&p, &[&s_ok]);
        assert!(report.is_ok());
        assert!(report.issues.is_empty());
        assert_eq!(report.status, Status::Ok);
    }

    #[test]
    fn failed_report_when_any_issue() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let s = StubInspector::flag("lancedb", "LANCEDB_EMPTY");
        let report = check(&p, &[&s]);
        assert!(!report.is_ok());
        assert_eq!(report.status, Status::Failed);
        assert_eq!(report.issues.len(), 1);
        assert_eq!(report.issues[0].code, "LANCEDB_EMPTY");
    }

    #[test]
    fn inspector_error_becomes_inspector_error_issue() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let s = StubInspector::err("graphrag", "pickle corrupt");
        let report = check(&p, &[&s]);
        assert!(!report.is_ok());
        assert_eq!(report.issues[0].code, "INSPECTOR_ERROR");
        assert!(report.issues[0].detail.contains("graphrag"));
        assert!(report.issues[0].detail.contains("pickle corrupt"));
    }

    #[test]
    fn one_inspector_failure_doesnt_block_others() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let crashing = StubInspector::err("crashing", "boom");
        let surviving = StubInspector::flag("survive", "LANCEDB_TABLE_MISSING");
        let report = check(&p, &[&crashing, &surviving]);
        assert_eq!(report.issues.len(), 2);
        assert_eq!(report.issues[0].code, "INSPECTOR_ERROR");
        assert_eq!(report.issues[1].code, "LANCEDB_TABLE_MISSING");
    }

    #[test]
    fn detail_round_trips_through_serde() {
        let issue = Issue::with_detail("STATE_STALE", "diff: 12 files");
        let raw = serde_json::to_string(&issue).unwrap();
        let back: Issue = serde_json::from_str(&raw).unwrap();
        assert_eq!(back, issue);
        let report = HealthReport {
            status: Status::Failed,
            issues: vec![issue],
            checked_at: "2026-05-04T20:00:00".into(),
            index_dir: "/x".into(),
            memory_dir: "/y".into(),
        };
        let raw = serde_json::to_string(&report).unwrap();
        assert!(raw.contains("FAILED"));
        assert!(raw.contains("STATE_STALE"));
    }

    #[test]
    fn index_dir_inspector_flags_missing_dir() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let i = IndexDirInspector;
        let r = i.inspect(&p).unwrap();
        assert_eq!(r.unwrap().code, "INDEX_DIR_MISSING");
    }

    #[test]
    fn index_dir_inspector_silent_when_present() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        std::fs::create_dir_all(&p.index_dir).unwrap();
        let i = IndexDirInspector;
        assert!(i.inspect(&p).unwrap().is_none());
    }

    #[test]
    fn memory_dir_inspector_flags_missing() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let i = MemoryDirInspector;
        let r = i.inspect(&p).unwrap();
        assert_eq!(r.unwrap().code, "MEMORY_DIR_MISSING");
    }

    #[test]
    fn memory_dir_inspector_flags_empty() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        std::fs::create_dir_all(&p.memory_dir).unwrap();
        // No .md files
        let i = MemoryDirInspector;
        let r = i.inspect(&p).unwrap();
        assert_eq!(r.unwrap().code, "MEMORY_DIR_EMPTY");
    }

    #[test]
    fn memory_dir_inspector_silent_with_md_files() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        std::fs::create_dir_all(&p.memory_dir).unwrap();
        std::fs::write(p.memory_dir.join("MEMORY.md"), "# index").unwrap();
        let i = MemoryDirInspector;
        assert!(i.inspect(&p).unwrap().is_none());
    }

    #[test]
    fn check_with_defaults_runs_built_ins_then_extras() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let extra = StubInspector::flag("custom", "CUSTOM_FAULT");
        let report = check_with_defaults(&p, &[&extra]);
        // Two defaults flag missing dirs + one extra fault = 3 issues
        assert_eq!(report.issues.len(), 3);
        let codes: Vec<&str> = report.issues.iter().map(|i| i.code.as_str()).collect();
        assert!(codes.contains(&"INDEX_DIR_MISSING"));
        assert!(codes.contains(&"MEMORY_DIR_MISSING"));
        assert!(codes.contains(&"CUSTOM_FAULT"));
    }

    #[test]
    fn check_with_defaults_clean_when_all_good() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        std::fs::create_dir_all(&p.index_dir).unwrap();
        std::fs::create_dir_all(&p.memory_dir).unwrap();
        std::fs::write(p.memory_dir.join("MEMORY.md"), "# index").unwrap();
        let report = check_with_defaults(&p, &[]);
        assert!(report.is_ok(), "report: {:?}", report);
    }

    #[test]
    fn report_includes_paths() {
        let dir = TempDir::new().unwrap();
        let p = paths_in(&dir);
        let report = check(&p, &[]);
        assert!(report.index_dir.contains("memory_index"));
        assert!(report.memory_dir.contains("memory"));
        assert!(!report.checked_at.is_empty());
    }

    #[test]
    fn default_layout_uses_home_subpaths() {
        let p = HealthPaths::default_layout();
        assert!(p.index_dir.to_string_lossy().contains("memory_index"));
        assert!(p.memory_dir.to_string_lossy().contains("memory"));
        assert!(p.graphrag.to_string_lossy().ends_with("graphrag.gpickle"));
        assert!(p.state.to_string_lossy().ends_with("_index_state.pkl"));
    }
}
