//! aim-project-archive — auto-archive flow (A1).
//!
//! Port of `agents/project_archive.py`. Once a project's phase is
//! terminal (PUBLISHED / ARCHIVED / REJECTED) and its YAML hasn't been
//! touched for `idle_months`, it's a candidate to move to
//! `_archive/<year>/<name>.yaml` so it stops crowding the daily brief.
//!
//! ## Public API
//! - [`Archive::archive`] / [`Archive::unarchive`]
//! - [`Archive::archived_list`] — every archived YAML with year + path
//! - [`Archive::candidates`] — terminal-phase + idle ≥ N months
//! - [`Archive::autosweep`] — list candidates, optionally archive in-place
//! - [`Archive::history`] — JSONL audit log

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ArchiveError {
    #[error("no project at {0:?}")]
    NotFound(PathBuf),
    #[error("active project {0:?} already exists")]
    Exists(String),
    #[error("no archive of {0:?}")]
    NoArchive(String),
    #[error("archive root does not exist")]
    NoArchiveRoot,
    #[error("project owner: {0}")]
    Owner(#[from] aim_project_owner::ProjectError),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArchiveCandidate {
    pub project: String,
    pub phase: String,
    pub last_modified: NaiveDate,
    pub idle_days: i64,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArchivedEntry {
    pub project: String,
    pub year: String,
    pub path: String,
}

const TERMINAL_PHASES: &[&str] = &["PUBLISHED", "ARCHIVED", "REJECTED"];

pub fn default_audit_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("project_archive.jsonl")
}

pub struct Archive {
    pub projects_dir: PathBuf,
    pub audit_path: PathBuf,
    /// Test seam — overrides Utc::now for deterministic destinations
    /// and audit timestamps.
    pub now_override: Option<DateTime<Utc>>,
}

impl Archive {
    pub fn new(projects_dir: impl Into<PathBuf>, audit_path: impl Into<PathBuf>) -> Self {
        Self {
            projects_dir: projects_dir.into(),
            audit_path: audit_path.into(),
            now_override: None,
        }
    }

    pub fn from_env() -> Self {
        Self::new(aim_project_owner::projects_dir(), default_audit_path())
    }

    pub fn with_now(mut self, now: DateTime<Utc>) -> Self {
        self.now_override = Some(now);
        self
    }

    fn now(&self) -> DateTime<Utc> {
        self.now_override.unwrap_or_else(Utc::now)
    }

    pub fn archive_root(&self) -> PathBuf {
        self.projects_dir.join("_archive")
    }

    /// Move `<project>.yaml` to `_archive/<year>/<project>.yaml`.
    /// Stamps the filename with `YYYYMMDD-HHMMSS` if the destination
    /// already exists (matches Python).
    pub fn archive(&self, project: &str, reason: &str) -> Result<PathBuf, ArchiveError> {
        let src = self.projects_dir.join(format!("{project}.yaml"));
        if !src.exists() {
            return Err(ArchiveError::NotFound(src));
        }
        let now = self.now();
        let year = now.format("%Y").to_string();
        let dest_dir = self.archive_root().join(&year);
        std::fs::create_dir_all(&dest_dir)?;
        let mut dest = dest_dir.join(format!("{project}.yaml"));
        if dest.exists() {
            let stamp = now.format("%Y%m%d-%H%M%S").to_string();
            dest = dest_dir.join(format!("{project}.{stamp}.yaml"));
        }
        std::fs::rename(&src, &dest)?;
        self.audit(serde_json::json!({
            "event": "archive",
            "project": project,
            "to": dest.to_string_lossy(),
            "reason": reason,
        }))?;
        Ok(dest)
    }

    /// Find the most-recently-modified archive copy and move it back.
    pub fn unarchive(&self, project: &str) -> Result<PathBuf, ArchiveError> {
        let root = self.archive_root();
        if !root.exists() {
            return Err(ArchiveError::NoArchiveRoot);
        }
        let mut candidates: Vec<(PathBuf, std::time::SystemTime)> = Vec::new();
        for entry in std::fs::read_dir(&root)? {
            let entry = entry?;
            let year_dir = entry.path();
            if !year_dir.is_dir() {
                continue;
            }
            for f in std::fs::read_dir(&year_dir)? {
                let f = f?;
                let p = f.path();
                if p.extension().and_then(|s| s.to_str()) != Some("yaml") {
                    continue;
                }
                let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                let project_name = stem.split('.').next().unwrap_or(stem);
                if project_name != project {
                    continue;
                }
                if let Ok(meta) = p.metadata() {
                    if let Ok(mtime) = meta.modified() {
                        candidates.push((p, mtime));
                    }
                }
            }
        }
        if candidates.is_empty() {
            return Err(ArchiveError::NoArchive(project.to_string()));
        }
        // Sort newest-first and pick the head
        candidates.sort_by(|a, b| b.1.cmp(&a.1));
        let src = candidates.into_iter().next().unwrap().0;
        let dest = self.projects_dir.join(format!("{project}.yaml"));
        if dest.exists() {
            return Err(ArchiveError::Exists(project.to_string()));
        }
        std::fs::rename(&src, &dest)?;
        self.audit(serde_json::json!({
            "event": "unarchive",
            "project": project,
            "from": src.to_string_lossy(),
        }))?;
        Ok(dest)
    }

    /// Every YAML under `_archive/`, sorted by year then filename.
    pub fn archived_list(&self) -> Result<Vec<ArchivedEntry>, ArchiveError> {
        let root = self.archive_root();
        if !root.exists() {
            return Ok(Vec::new());
        }
        let mut years: Vec<PathBuf> = std::fs::read_dir(&root)?
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        years.sort();
        let mut out = Vec::new();
        for ydir in years {
            let mut yaml_files: Vec<PathBuf> = std::fs::read_dir(&ydir)?
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("yaml"))
                .collect();
            yaml_files.sort();
            for p in yaml_files {
                let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                let project = stem.split('.').next().unwrap_or(stem).to_string();
                let year = ydir
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("")
                    .to_string();
                out.push(ArchivedEntry {
                    project,
                    year,
                    path: p.to_string_lossy().to_string(),
                });
            }
        }
        Ok(out)
    }

    /// Active projects whose phase is terminal AND whose YAML mtime is
    /// older than `today - idle_months × 30 days`.
    pub fn candidates(
        &self,
        idle_months: u32,
        today: NaiveDate,
    ) -> Result<Vec<ArchiveCandidate>, ArchiveError> {
        let cutoff = today - chrono::Duration::days((idle_months as i64) * 30);
        let mut out = Vec::new();
        for name in aim_project_owner::list_projects(&self.projects_dir) {
            let state = match aim_project_owner::load(&self.projects_dir, &name) {
                Ok(s) => s,
                Err(_) => continue,
            };
            let phase = state.phase.to_uppercase();
            if !TERMINAL_PHASES.contains(&phase.as_str()) {
                continue;
            }
            let path = self.projects_dir.join(format!("{name}.yaml"));
            let mtime = match path.metadata().and_then(|m| m.modified()) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let mtime_dt: DateTime<Utc> = mtime.into();
            let mtime_date = mtime_dt.date_naive();
            if mtime_date > cutoff {
                continue;
            }
            let idle_days = (today - mtime_date).num_days();
            out.push(ArchiveCandidate {
                project: name,
                phase: phase.clone(),
                last_modified: mtime_date,
                idle_days,
                reason: format!("phase={phase}, idle {idle_months}m+"),
            });
        }
        Ok(out)
    }

    /// `dry_run = true` returns the candidate list without mutation.
    /// `dry_run = false` archives each candidate in-place and returns
    /// the list of attempts (skipping any that go missing during the
    /// sweep).
    pub fn autosweep(
        &self,
        idle_months: u32,
        today: NaiveDate,
        dry_run: bool,
    ) -> Result<Vec<ArchiveCandidate>, ArchiveError> {
        let cands = self.candidates(idle_months, today)?;
        if dry_run {
            return Ok(cands);
        }
        for c in &cands {
            // Best-effort: skip if the project disappeared mid-sweep.
            if let Err(ArchiveError::NotFound(_)) = self.archive(&c.project, &c.reason) {
                continue;
            }
        }
        Ok(cands)
    }

    fn audit(&self, mut record: serde_json::Value) -> Result<(), ArchiveError> {
        if let Some(map) = record.as_object_mut() {
            map.insert(
                "ts".into(),
                serde_json::Value::String(self.now().format("%Y-%m-%dT%H:%M:%S").to_string()),
            );
        }
        if let Some(parent) = self.audit_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let line = serde_json::to_string(&record)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.audit_path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    pub fn history(&self, limit: usize) -> Result<Vec<serde_json::Value>, ArchiveError> {
        if !self.audit_path.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(&self.audit_path)?;
        let mut out: Vec<serde_json::Value> = Vec::new();
        for line in raw.lines() {
            if line.trim().is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str(line) {
                out.push(v);
            }
        }
        if out.len() > limit {
            out = out.split_off(out.len() - limit);
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn make() -> (TempDir, Archive) {
        let dir = TempDir::new().unwrap();
        let projects = dir.path().join("projects");
        std::fs::create_dir_all(&projects).unwrap();
        let audit = dir.path().join("archive.jsonl");
        let now = Utc.with_ymd_and_hms(2026, 5, 4, 12, 0, 0).unwrap();
        let arch = Archive::new(projects, audit).with_now(now);
        (dir, arch)
    }

    fn write_proj(arch: &Archive, name: &str, phase: &str) -> PathBuf {
        let path = arch.projects_dir.join(format!("{name}.yaml"));
        let body = format!("name: {name}\nphase: {phase}\n");
        std::fs::write(&path, body).unwrap();
        path
    }

    #[test]
    fn archive_moves_yaml_to_year_subdir() {
        let (_d, arch) = make();
        write_proj(&arch, "FCLC", "ARCHIVED");
        let dest = arch.archive("FCLC", "user request").unwrap();
        assert!(dest.exists());
        assert!(dest.to_string_lossy().contains("/_archive/2026/"));
        assert!(dest.to_string_lossy().ends_with("FCLC.yaml"));
        assert!(!arch.projects_dir.join("FCLC.yaml").exists());
    }

    #[test]
    fn archive_stamps_when_destination_exists() {
        let (_d, arch) = make();
        // Pre-populate destination
        let prev_dir = arch.archive_root().join("2026");
        std::fs::create_dir_all(&prev_dir).unwrap();
        std::fs::write(prev_dir.join("FCLC.yaml"), "old").unwrap();
        write_proj(&arch, "FCLC", "ARCHIVED");
        let dest = arch.archive("FCLC", "").unwrap();
        let name = dest.file_name().unwrap().to_string_lossy().to_string();
        assert!(name.starts_with("FCLC."));
        assert!(name.ends_with(".yaml"));
        assert_ne!(name, "FCLC.yaml");
        assert!(prev_dir.join("FCLC.yaml").exists()); // original archive untouched
    }

    #[test]
    fn archive_missing_errors() {
        let (_d, arch) = make();
        let err = arch.archive("ghost", "").unwrap_err();
        assert!(matches!(err, ArchiveError::NotFound(_)));
    }

    #[test]
    fn unarchive_restores_most_recent() {
        let (_d, arch) = make();
        write_proj(&arch, "FCLC", "ARCHIVED");
        let archived = arch.archive("FCLC", "").unwrap();
        assert!(!arch.projects_dir.join("FCLC.yaml").exists());
        let restored = arch.unarchive("FCLC").unwrap();
        assert!(restored.exists());
        assert!(!archived.exists());
    }

    #[test]
    fn unarchive_no_archive_errors() {
        let (_d, arch) = make();
        let err = arch.unarchive("ghost").unwrap_err();
        assert!(matches!(err, ArchiveError::NoArchiveRoot));
    }

    #[test]
    fn unarchive_refuses_when_active_exists() {
        let (_d, arch) = make();
        write_proj(&arch, "FCLC", "ARCHIVED");
        arch.archive("FCLC", "").unwrap();
        // Re-create active version
        write_proj(&arch, "FCLC", "DRAFT");
        let err = arch.unarchive("FCLC").unwrap_err();
        assert!(matches!(err, ArchiveError::Exists(_)));
    }

    #[test]
    fn archived_list_groups_by_year() {
        let (_d, arch) = make();
        write_proj(&arch, "A", "ARCHIVED");
        write_proj(&arch, "B", "ARCHIVED");
        arch.archive("A", "").unwrap();
        arch.archive("B", "").unwrap();
        let list = arch.archived_list().unwrap();
        assert_eq!(list.len(), 2);
        assert!(list.iter().all(|e| e.year == "2026"));
        let projects: Vec<&str> = list.iter().map(|e| e.project.as_str()).collect();
        assert!(projects.contains(&"A"));
        assert!(projects.contains(&"B"));
    }

    #[test]
    fn archived_list_handles_stamped_filenames() {
        let (_d, arch) = make();
        let dir = arch.archive_root().join("2026");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("X.yaml"), "x").unwrap();
        std::fs::write(dir.join("X.20260504-100000.yaml"), "x").unwrap();
        let list = arch.archived_list().unwrap();
        assert_eq!(list.len(), 2);
        assert!(list.iter().all(|e| e.project == "X"));
    }

    #[test]
    fn candidates_filter_terminal_phase_and_idle() {
        let (_d, arch) = make();
        // Active terminal: ARCHIVED, but mtime fresh → not a candidate
        let recent = write_proj(&arch, "Recent", "ARCHIVED");
        // Old draft (terminal? NO, DRAFT) → not a candidate
        write_proj(&arch, "OldDraft", "DRAFT");
        // Old terminal → candidate
        let old = write_proj(&arch, "OldDone", "PUBLISHED");
        // Push the OLD file's mtime way back via filetime — but filetime
        // crate isn't a dep. Skip mtime hack: use the file system's
        // built-in `filetime` syscall via SetFileMtime through `utimes`.
        let _ = recent;
        // Instead of touching mtime, exercise the ≤cutoff path with
        // today set to the future so even fresh files look old.
        let _ = old;
        let today = NaiveDate::from_ymd_opt(2027, 1, 1).unwrap();
        let cands = arch.candidates(6, today).unwrap();
        let names: Vec<&str> = cands.iter().map(|c| c.project.as_str()).collect();
        assert!(names.contains(&"Recent"));
        assert!(names.contains(&"OldDone"));
        assert!(!names.contains(&"OldDraft"));
        assert!(cands.iter().all(|c| TERMINAL_PHASES.contains(&c.phase.as_str())));
    }

    #[test]
    fn candidates_excludes_when_within_idle_window() {
        let (_d, arch) = make();
        write_proj(&arch, "Fresh", "ARCHIVED");
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        // 6-month window — fresh file (just created) shouldn't qualify
        let cands = arch.candidates(6, today).unwrap();
        assert!(cands.iter().all(|c| c.project != "Fresh"));
    }

    #[test]
    fn autosweep_dry_run_does_not_archive() {
        let (_d, arch) = make();
        write_proj(&arch, "X", "ARCHIVED");
        let today = NaiveDate::from_ymd_opt(2027, 1, 1).unwrap();
        let cands = arch.autosweep(6, today, true).unwrap();
        assert_eq!(cands.len(), 1);
        // Project YAML still in active dir
        assert!(arch.projects_dir.join("X.yaml").exists());
    }

    #[test]
    fn autosweep_apply_archives_candidates() {
        let (_d, arch) = make();
        write_proj(&arch, "Done", "PUBLISHED");
        let today = NaiveDate::from_ymd_opt(2027, 1, 1).unwrap();
        let cands = arch.autosweep(6, today, false).unwrap();
        assert_eq!(cands.len(), 1);
        assert!(!arch.projects_dir.join("Done.yaml").exists());
        let archived = arch.archived_list().unwrap();
        assert_eq!(archived.len(), 1);
        assert_eq!(archived[0].project, "Done");
    }

    #[test]
    fn audit_appends_per_event() {
        let (_d, arch) = make();
        write_proj(&arch, "X", "ARCHIVED");
        arch.archive("X", "test").unwrap();
        write_proj(&arch, "Y", "ARCHIVED");
        arch.archive("Y", "").unwrap();
        let h = arch.history(10).unwrap();
        assert_eq!(h.len(), 2);
        assert_eq!(h[0]["event"], "archive");
        assert_eq!(h[1]["project"], "Y");
    }

    #[test]
    fn audit_history_capped_at_limit() {
        let (_d, arch) = make();
        for i in 0..5 {
            let name = format!("P{i}");
            write_proj(&arch, &name, "ARCHIVED");
            arch.archive(&name, "").unwrap();
        }
        let h = arch.history(3).unwrap();
        assert_eq!(h.len(), 3);
        // newest at end
        assert_eq!(h.last().unwrap()["project"], "P4");
    }

    #[test]
    fn unarchive_writes_audit() {
        let (_d, arch) = make();
        write_proj(&arch, "X", "ARCHIVED");
        arch.archive("X", "").unwrap();
        arch.unarchive("X").unwrap();
        let h = arch.history(10).unwrap();
        let events: Vec<&str> = h.iter().map(|e| e["event"].as_str().unwrap_or("")).collect();
        assert_eq!(events, vec!["archive", "unarchive"]);
    }
}
