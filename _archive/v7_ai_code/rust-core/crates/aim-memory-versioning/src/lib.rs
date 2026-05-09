//! aim-memory-versioning — git-like snapshots of AIM memory.
//!
//! Port of `agents/memory_versioning.py`. Snapshots capture every `*.md`
//! under `memory_dir/` (top-level + nested), plus a manifest with file
//! sha1 / size / mtime + LanceDB row counts. Enough to restore the
//! source-of-truth side; LanceDB is rebuildable from the .md files.
//!
//! ## Public API
//! - [`Versioning::snapshot`] — capture current state, return version id
//! - [`Versioning::rollback`] — restore a prior snapshot (auto-takes a
//!   safety snapshot first)
//! - [`Versioning::diff`] — added/removed/changed between two versions
//! - [`Versioning::list_versions`] — sorted manifest summaries

use chrono::{DateTime, Utc};
use md5::{Digest as Md5Digest, Md5};
use serde::{Deserialize, Serialize};
use sha1::Sha1;
// Sha1::new()/update()/finalize() work via inherent impls; Digest trait not imported.
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum VersionError {
    #[error("version not found: {0}")]
    NotFound(String),
    #[error("manifest missing for {0}")]
    NoManifest(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FileEntry {
    pub rel: String,
    pub size: u64,
    pub mtime: f64,
    pub sha1: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub version_id: String,
    pub timestamp: String,
    pub description: String,
    pub memory_files: Vec<FileEntry>,
    pub total_files: usize,
    #[serde(default)]
    pub index_chunks: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionSummary {
    pub version_id: String,
    pub timestamp: String,
    pub description: String,
    pub files: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Diff {
    pub added: Vec<FileEntry>,
    pub removed: Vec<FileEntry>,
    pub changed: Vec<FileEntry>,
    pub total_added: usize,
    pub total_removed: usize,
    pub total_changed: usize,
}

pub struct Versioning {
    pub memory_dir: PathBuf,
    pub versions_dir: PathBuf,
    /// Test seam: explicit Utc now for deterministic ids + timestamps.
    pub now_override: Option<DateTime<Utc>>,
}

impl Versioning {
    pub fn new(memory_dir: impl Into<PathBuf>, versions_dir: impl Into<PathBuf>) -> Self {
        Self {
            memory_dir: memory_dir.into(),
            versions_dir: versions_dir.into(),
            now_override: None,
        }
    }

    pub fn from_default() -> Self {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        Self::new(
            home.join(".claude/projects/-home-oem/memory"),
            home.join(".claude/memory_versions"),
        )
    }

    pub fn with_now(mut self, t: DateTime<Utc>) -> Self {
        self.now_override = Some(t);
        self
    }

    fn now(&self) -> DateTime<Utc> {
        self.now_override.unwrap_or_else(Utc::now)
    }

    fn current_version_path(&self) -> PathBuf {
        self.versions_dir.join("current.txt")
    }

    pub fn current_version(&self) -> Option<String> {
        std::fs::read_to_string(self.current_version_path())
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    }

    fn save_current(&self, id: &str) -> Result<(), VersionError> {
        std::fs::create_dir_all(&self.versions_dir)?;
        std::fs::write(self.current_version_path(), id)?;
        Ok(())
    }

    fn version_id(&self, description: &str) -> String {
        let mut h = Md5::new();
        h.update(format!("{}:{description}", self.now().to_rfc3339()).as_bytes());
        let raw = hex::encode(h.finalize());
        raw.chars().take(8).collect()
    }

    /// Capture every `*.md` under `memory_dir`. Manifest carries
    /// `index_chunks = 0` unless the caller passes a count from the
    /// host LanceDB inspector.
    pub fn snapshot(
        &self,
        description: &str,
        index_chunks: u64,
    ) -> Result<String, VersionError> {
        std::fs::create_dir_all(&self.versions_dir)?;
        let version_id = self.version_id(description);
        let target = self.versions_dir.join(&version_id);
        std::fs::create_dir_all(target.join("memory"))?;

        let mut files: Vec<FileEntry> = Vec::new();
        if self.memory_dir.exists() {
            walk_md(&self.memory_dir, &mut |path: &Path| {
                let rel = path
                    .strip_prefix(&self.memory_dir)
                    .unwrap_or(path)
                    .to_string_lossy()
                    .to_string();
                let dst = target.join("memory").join(&rel);
                if let Some(parent) = dst.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::copy(path, &dst)?;
                let meta = path.metadata()?;
                let mtime = meta
                    .modified()
                    .ok()
                    .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                    .map(|d| d.as_secs_f64())
                    .unwrap_or(0.0);
                let bytes = std::fs::read(path)?;
                let mut hasher = Sha1::new();
                hasher.update(&bytes);
                let sha1 = hex::encode(hasher.finalize());
                files.push(FileEntry {
                    rel,
                    size: meta.len(),
                    mtime,
                    sha1,
                });
                Ok(())
            })?;
        }

        let manifest = Manifest {
            version_id: version_id.clone(),
            timestamp: self.now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            description: description.to_string(),
            total_files: files.len(),
            memory_files: files,
            index_chunks,
        };
        std::fs::write(
            target.join("manifest.json"),
            serde_json::to_string_pretty(&manifest)?,
        )?;
        self.save_current(&version_id)?;
        Ok(version_id)
    }

    /// Restore a prior snapshot. Auto-takes a safety snapshot first
    /// labelled `safety-pre-rollback-from-<current>`. After the restore
    /// the host should reindex (LanceDB) — this crate does not.
    pub fn rollback(&self, version_id: &str) -> Result<Manifest, VersionError> {
        let target = self.versions_dir.join(version_id);
        if !target.exists() {
            return Err(VersionError::NotFound(version_id.to_string()));
        }
        let manifest = self.load_manifest(version_id)?;

        // Safety snapshot of the current state
        let from = self.current_version().unwrap_or_else(|| "unknown".to_string());
        let _safety = self.snapshot(&format!("safety-pre-rollback-from-{from}"), 0)?;

        // Wipe + restore
        if self.memory_dir.exists() {
            walk_md(&self.memory_dir, &mut |p: &Path| {
                std::fs::remove_file(p)?;
                Ok(())
            })?;
            std::fs::create_dir_all(self.memory_dir.join("user_memories"))?;
        } else {
            std::fs::create_dir_all(&self.memory_dir)?;
        }
        let memory_src = target.join("memory");
        if memory_src.exists() {
            walk_md(&memory_src, &mut |p: &Path| {
                let rel = p.strip_prefix(&memory_src).unwrap_or(p);
                let dst = self.memory_dir.join(rel);
                if let Some(parent) = dst.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::copy(p, &dst)?;
                Ok(())
            })?;
        }
        self.save_current(version_id)?;
        Ok(manifest)
    }

    pub fn diff(&self, version_a: &str, version_b: &str) -> Result<Diff, VersionError> {
        let ma = self.load_manifest(version_a)?;
        let mb = self.load_manifest(version_b)?;
        let a: std::collections::HashMap<String, &FileEntry> =
            ma.memory_files.iter().map(|f| (f.rel.clone(), f)).collect();
        let b: std::collections::HashMap<String, &FileEntry> =
            mb.memory_files.iter().map(|f| (f.rel.clone(), f)).collect();
        let mut added: Vec<FileEntry> = b
            .iter()
            .filter(|(k, _)| !a.contains_key(*k))
            .map(|(_, v)| (*v).clone())
            .collect();
        let mut removed: Vec<FileEntry> = a
            .iter()
            .filter(|(k, _)| !b.contains_key(*k))
            .map(|(_, v)| (*v).clone())
            .collect();
        let mut changed: Vec<FileEntry> = a
            .iter()
            .filter_map(|(k, av)| {
                b.get(k)
                    .filter(|bv| av.sha1 != bv.sha1)
                    .map(|bv| (*bv).clone())
            })
            .collect();
        added.sort_by(|a, b| a.rel.cmp(&b.rel));
        removed.sort_by(|a, b| a.rel.cmp(&b.rel));
        changed.sort_by(|a, b| a.rel.cmp(&b.rel));
        Ok(Diff {
            total_added: added.len(),
            total_removed: removed.len(),
            total_changed: changed.len(),
            added,
            removed,
            changed,
        })
    }

    pub fn list_versions(&self) -> Result<Vec<VersionSummary>, VersionError> {
        if !self.versions_dir.exists() {
            return Ok(Vec::new());
        }
        let mut dirs: Vec<PathBuf> = std::fs::read_dir(&self.versions_dir)?
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        dirs.sort();
        let mut out = Vec::new();
        for d in dirs {
            let mf = d.join("manifest.json");
            if !mf.exists() {
                continue;
            }
            let raw = std::fs::read_to_string(&mf)?;
            let m: Manifest = serde_json::from_str(&raw)?;
            out.push(VersionSummary {
                version_id: m.version_id,
                timestamp: m.timestamp,
                description: m.description,
                files: m.total_files,
            });
        }
        Ok(out)
    }

    fn load_manifest(&self, version_id: &str) -> Result<Manifest, VersionError> {
        let f = self.versions_dir.join(version_id).join("manifest.json");
        if !f.exists() {
            return Err(VersionError::NoManifest(version_id.to_string()));
        }
        let raw = std::fs::read_to_string(&f)?;
        Ok(serde_json::from_str(&raw)?)
    }
}

fn walk_md<F>(root: &Path, visit: &mut F) -> Result<(), VersionError>
where
    F: FnMut(&Path) -> Result<(), VersionError>,
{
    if !root.exists() {
        return Ok(());
    }
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let p = entry.path();
        if p.is_dir() {
            walk_md(&p, visit)?;
        } else if p.extension().and_then(|s| s.to_str()) == Some("md") {
            visit(&p)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn make() -> (TempDir, Versioning) {
        let dir = TempDir::new().unwrap();
        let mem = dir.path().join("memory");
        let vers = dir.path().join("memory_versions");
        std::fs::create_dir_all(&mem).unwrap();
        let now = Utc.with_ymd_and_hms(2026, 5, 4, 12, 0, 0).unwrap();
        let v = Versioning::new(mem, vers).with_now(now);
        (dir, v)
    }

    fn write(dir: &Path, rel: &str, body: &str) -> PathBuf {
        let p = dir.join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn snapshot_captures_md_files_and_manifest() {
        let (_d, v) = make();
        write(&v.memory_dir, "MEMORY.md", "# index");
        write(&v.memory_dir, "user_memories/note.md", "note body");
        let id = v.snapshot("first", 42).unwrap();
        assert_eq!(id.len(), 8);
        let target = v.versions_dir.join(&id);
        assert!(target.join("manifest.json").exists());
        assert!(target.join("memory/MEMORY.md").exists());
        assert!(target.join("memory/user_memories/note.md").exists());

        let raw = std::fs::read_to_string(target.join("manifest.json")).unwrap();
        let manifest: Manifest = serde_json::from_str(&raw).unwrap();
        assert_eq!(manifest.version_id, id);
        assert_eq!(manifest.description, "first");
        assert_eq!(manifest.total_files, 2);
        assert_eq!(manifest.index_chunks, 42);
    }

    #[test]
    fn snapshot_records_sha1_for_each_file() {
        let (_d, v) = make();
        let p = write(&v.memory_dir, "x.md", "hello");
        let _ = v.snapshot("snap", 0).unwrap();
        let summary = v.list_versions().unwrap();
        let manifest = v.load_manifest(&summary[0].version_id).unwrap();
        assert_eq!(manifest.memory_files.len(), 1);
        let entry = &manifest.memory_files[0];
        assert_eq!(entry.rel, "x.md");
        assert_eq!(entry.sha1, "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d");
        assert_eq!(entry.size, std::fs::metadata(&p).unwrap().len());
    }

    #[test]
    fn snapshot_updates_current_version() {
        let (_d, v) = make();
        write(&v.memory_dir, "a.md", "x");
        let id = v.snapshot("first", 0).unwrap();
        assert_eq!(v.current_version().as_deref(), Some(id.as_str()));
    }

    #[test]
    fn snapshot_empty_memory_dir() {
        let (_d, v) = make();
        // Ensure dir exists but empty
        std::fs::create_dir_all(&v.memory_dir).unwrap();
        let id = v.snapshot("empty", 0).unwrap();
        let manifest = v.load_manifest(&id).unwrap();
        assert_eq!(manifest.total_files, 0);
        assert!(manifest.memory_files.is_empty());
    }

    #[test]
    fn diff_added_removed_changed() {
        let (_d, v) = make();
        write(&v.memory_dir, "shared.md", "v1");
        write(&v.memory_dir, "removed.md", "old");
        let id_a = v.snapshot("a", 0).unwrap();

        // Mutate: change shared, drop removed, add new
        std::fs::remove_file(v.memory_dir.join("removed.md")).unwrap();
        write(&v.memory_dir, "shared.md", "v2");
        write(&v.memory_dir, "added.md", "new");
        // Bump now to get distinct version id
        let v2 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 1, 0).unwrap());
        let id_b = v2.snapshot("b", 0).unwrap();
        assert_ne!(id_a, id_b);

        let diff = v.diff(&id_a, &id_b).unwrap();
        assert_eq!(diff.total_added, 1);
        assert_eq!(diff.added[0].rel, "added.md");
        assert_eq!(diff.total_removed, 1);
        assert_eq!(diff.removed[0].rel, "removed.md");
        assert_eq!(diff.total_changed, 1);
        assert_eq!(diff.changed[0].rel, "shared.md");
    }

    #[test]
    fn diff_identical_snapshots_have_zero_changes() {
        let (_d, v) = make();
        write(&v.memory_dir, "a.md", "x");
        let id_a = v.snapshot("a", 0).unwrap();
        let v2 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 5, 0).unwrap());
        let id_b = v2.snapshot("b", 0).unwrap();
        let diff = v.diff(&id_a, &id_b).unwrap();
        assert_eq!(diff.total_added, 0);
        assert_eq!(diff.total_removed, 0);
        assert_eq!(diff.total_changed, 0);
    }

    #[test]
    fn rollback_restores_prior_state() {
        let (_d, v) = make();
        write(&v.memory_dir, "keep.md", "kept");
        let id_a = v.snapshot("a", 0).unwrap();

        // Mutate: delete keep, add foo
        std::fs::remove_file(v.memory_dir.join("keep.md")).unwrap();
        write(&v.memory_dir, "foo.md", "new");
        let v2 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 2, 0).unwrap());
        v2.snapshot("b", 0).unwrap();

        // Rollback to A
        let v3 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 3, 0).unwrap());
        let manifest = v3.rollback(&id_a).unwrap();
        assert_eq!(manifest.version_id, id_a);
        assert!(v.memory_dir.join("keep.md").exists());
        assert!(!v.memory_dir.join("foo.md").exists());
        assert_eq!(v.current_version().as_deref(), Some(id_a.as_str()));
    }

    #[test]
    fn rollback_takes_safety_snapshot() {
        let (_d, v) = make();
        write(&v.memory_dir, "x.md", "first");
        let id_a = v.snapshot("a", 0).unwrap();
        write(&v.memory_dir, "y.md", "second");
        let v2 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 4, 0).unwrap());
        v2.snapshot("b", 0).unwrap();

        let before_count = v.list_versions().unwrap().len();
        let v3 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 12, 5, 0).unwrap());
        v3.rollback(&id_a).unwrap();
        let after_count = v.list_versions().unwrap().len();
        // At least one extra version (the safety snapshot) appeared
        assert!(after_count > before_count);
        let safety = v
            .list_versions()
            .unwrap()
            .into_iter()
            .find(|s| s.description.starts_with("safety-pre-rollback-from-"));
        assert!(safety.is_some(), "safety snapshot must be recorded");
    }

    #[test]
    fn rollback_unknown_id_errors() {
        let (_d, v) = make();
        let err = v.rollback("00000000").unwrap_err();
        assert!(matches!(err, VersionError::NotFound(_)));
    }

    #[test]
    fn list_versions_sorted_and_summarised() {
        let (_d, v) = make();
        write(&v.memory_dir, "a.md", "x");
        let id1 = v.snapshot("first", 0).unwrap();
        let v2 = Versioning::new(v.memory_dir.clone(), v.versions_dir.clone())
            .with_now(Utc.with_ymd_and_hms(2026, 5, 4, 13, 0, 0).unwrap());
        let id2 = v2.snapshot("second", 0).unwrap();
        let summary = v.list_versions().unwrap();
        assert!(summary.iter().any(|s| s.version_id == id1 && s.description == "first"));
        assert!(summary.iter().any(|s| s.version_id == id2 && s.description == "second"));
    }

    #[test]
    fn list_versions_empty_when_no_snapshots() {
        let (_d, v) = make();
        let s = v.list_versions().unwrap();
        assert!(s.is_empty());
    }

    #[test]
    fn diff_unknown_version_errors() {
        let (_d, v) = make();
        write(&v.memory_dir, "a.md", "x");
        let id = v.snapshot("a", 0).unwrap();
        let err = v.diff(&id, "deadbeef").unwrap_err();
        assert!(matches!(err, VersionError::NoManifest(_)));
    }

    #[test]
    fn current_version_initially_none() {
        let (_d, v) = make();
        assert!(v.current_version().is_none());
    }

    #[test]
    fn version_id_is_8_chars_hex() {
        let (_d, v) = make();
        write(&v.memory_dir, "x.md", "x");
        let id = v.snapshot("test", 0).unwrap();
        assert_eq!(id.len(), 8);
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn snapshot_descends_recursively() {
        let (_d, v) = make();
        write(&v.memory_dir, "deep/sub/very_deep.md", "x");
        let id = v.snapshot("deep", 0).unwrap();
        let m = v.load_manifest(&id).unwrap();
        assert_eq!(m.total_files, 1);
        assert_eq!(m.memory_files[0].rel, "deep/sub/very_deep.md");
    }

    #[test]
    fn snapshot_skips_non_md() {
        let (_d, v) = make();
        write(&v.memory_dir, "a.md", "x");
        write(&v.memory_dir, "b.txt", "y"); // ignored
        let id = v.snapshot("filter", 0).unwrap();
        let m = v.load_manifest(&id).unwrap();
        assert_eq!(m.total_files, 1);
        assert_eq!(m.memory_files[0].rel, "a.md");
    }
}
