//! aim-project-export — bundle a project into a zip (EX1).
//!
//! Port of `agents/project_export.py`. Composes 6 deterministic project
//! artifacts into a single zip with a JSON manifest. Each artifact
//! source is a [`ContentSource`] trait so the bundle logic is testable
//! without YAML/git/memory backends.

use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;
use zip::{write::FileOptions, CompressionMethod, ZipWriter};

#[derive(Debug, Error)]
pub enum ExportError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("zip error: {0}")]
    Zip(#[from] zip::result::ZipError),
    #[error("not found: {0}")]
    NotFound(String),
}

pub type Result<T> = std::result::Result<T, ExportError>;

// ── manifest ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct MemberInfo {
    pub name: String,
    pub size: usize,
    pub sha: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Manifest {
    pub project: String,
    pub exported_at: String,
    pub members: Vec<MemberInfo>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ExportResult {
    pub project: String,
    pub archive_path: PathBuf,
    pub members: Vec<String>,
    pub bytes_total: u64,
}

// ── content sources ────────────────────────────────────────────────────────

/// Source for one of the 6 named artifacts. Implementations may return
/// fallback messages on failure (mirrors Python's `(brief failed: …)`
/// strings) — the export never aborts because of a missing optional bit.
pub trait ContentSource: Send + Sync {
    fn project_yaml(&self, project: &str) -> Result<String>;
    fn morning_brief(&self, project: &str) -> String;
    fn phase_actions(&self, project: &str) -> String;
    fn readme(&self, project: &str) -> String;
    fn memory_concat(&self, project: &str) -> String;
    fn git_log(&self, project: &str) -> String;
}

// ── helpers ─────────────────────────────────────────────────────────────────

pub fn short_sha(text: &str) -> String {
    let mut h = Sha256::new();
    h.update(text.as_bytes());
    let digest = h.finalize();
    let hex: String = digest.iter().map(|b| format!("{:02x}", b)).collect();
    hex.chars().take(12).collect()
}

pub const MEMBER_NAMES: &[&str] = &[
    "project.yaml",
    "README_AUTO.md",
    "morning_brief.txt",
    "phase_actions.txt",
    "memory.md",
    "git_log.txt",
];

pub fn collect_members(project: &str, source: &dyn ContentSource) -> Result<Vec<(String, String)>> {
    let yaml = source.project_yaml(project)?;
    Ok(vec![
        ("project.yaml".into(), yaml),
        ("README_AUTO.md".into(), source.readme(project)),
        ("morning_brief.txt".into(), source.morning_brief(project)),
        ("phase_actions.txt".into(), source.phase_actions(project)),
        ("memory.md".into(), source.memory_concat(project)),
        ("git_log.txt".into(), source.git_log(project)),
    ])
}

pub fn build_manifest(project: &str, members: &[(String, String)], now: DateTime<Utc>) -> Manifest {
    Manifest {
        project: project.into(),
        exported_at: now.format("%Y-%m-%dT%H:%M:%S").to_string(),
        members: members
            .iter()
            .map(|(name, text)| MemberInfo {
                name: name.clone(),
                size: text.len(),
                sha: short_sha(text),
            })
            .collect(),
    }
}

// ── zip writer ──────────────────────────────────────────────────────────────

pub fn write_zip(
    project: &str,
    members: &[(String, String)],
    manifest: &Manifest,
    dest: &Path,
) -> Result<u64> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::File::create(dest)?;
    let mut zw = ZipWriter::new(file);
    let opts: FileOptions<'_, ()> = FileOptions::default().compression_method(CompressionMethod::Deflated);
    for (name, text) in members {
        zw.start_file(format!("{}/{}", project, name), opts)?;
        zw.write_all(text.as_bytes())?;
    }
    zw.start_file(format!("{}/manifest.json", project), opts)?;
    let manifest_text = serde_json::to_string_pretty(manifest)
        .map_err(|e| ExportError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;
    zw.write_all(manifest_text.as_bytes())?;
    zw.finish()?;
    Ok(std::fs::metadata(dest)?.len())
}

// ── export ──────────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

pub fn default_dest(project: &str, root: &Path, now: DateTime<Utc>) -> PathBuf {
    let stamp = now.format("%Y%m%d-%H%M%S").to_string();
    root.join(format!("{}-{}.zip", project, stamp))
}

pub fn export(
    project: &str,
    source: &dyn ContentSource,
    dest: &Path,
    clock: &dyn Clock,
) -> Result<ExportResult> {
    let members = collect_members(project, source)?;
    let manifest = build_manifest(project, &members, clock.now());
    let bytes = write_zip(project, &members, &manifest, dest)?;
    let mut names: Vec<String> = manifest.members.iter().map(|m| m.name.clone()).collect();
    names.push("manifest.json".into());
    Ok(ExportResult {
        project: project.into(),
        archive_path: dest.to_path_buf(),
        members: names,
        bytes_total: bytes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::io::Read;
    use tempfile::TempDir;

    struct StubSource;
    impl ContentSource for StubSource {
        fn project_yaml(&self, project: &str) -> Result<String> {
            Ok(format!("name: {}\nphase: SUBMITTED\n", project))
        }
        fn morning_brief(&self, project: &str) -> String {
            format!("brief for {}", project)
        }
        fn phase_actions(&self, _project: &str) -> String {
            "Phase: SUBMITTED\n\n- Submit\n".into()
        }
        fn readme(&self, project: &str) -> String {
            format!("# {} README\n", project)
        }
        fn memory_concat(&self, _project: &str) -> String {
            "memory body".into()
        }
        fn git_log(&self, _project: &str) -> String {
            "abc1234 first commit\n".into()
        }
    }

    struct MissingYamlSource;
    impl ContentSource for MissingYamlSource {
        fn project_yaml(&self, project: &str) -> Result<String> {
            Err(ExportError::NotFound(format!(
                "no project YAML for {}",
                project
            )))
        }
        fn morning_brief(&self, _: &str) -> String {
            "".into()
        }
        fn phase_actions(&self, _: &str) -> String {
            "".into()
        }
        fn readme(&self, _: &str) -> String {
            "".into()
        }
        fn memory_concat(&self, _: &str) -> String {
            "".into()
        }
        fn git_log(&self, _: &str) -> String {
            "".into()
        }
    }

    fn ts() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 12, 30, 45).unwrap()
    }

    // ── short_sha ──────────────────────────────────────────────────────────

    #[test]
    fn short_sha_is_12_hex_chars() {
        let h = short_sha("hello");
        assert_eq!(h.chars().count(), 12);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn short_sha_changes_with_content() {
        assert_ne!(short_sha("a"), short_sha("b"));
    }

    // ── MEMBER_NAMES ───────────────────────────────────────────────────────

    #[test]
    fn member_names_match_python_order() {
        assert_eq!(MEMBER_NAMES.len(), 6);
        assert_eq!(MEMBER_NAMES[0], "project.yaml");
        assert_eq!(MEMBER_NAMES[1], "README_AUTO.md");
        assert_eq!(MEMBER_NAMES[5], "git_log.txt");
    }

    // ── collect_members ────────────────────────────────────────────────────

    #[test]
    fn collect_members_returns_six_pairs() {
        let s = StubSource;
        let m = collect_members("FCLC", &s).unwrap();
        assert_eq!(m.len(), 6);
        assert_eq!(m[0].0, "project.yaml");
        assert!(m[0].1.contains("name: FCLC"));
    }

    #[test]
    fn collect_members_propagates_yaml_error() {
        let s = MissingYamlSource;
        let r = collect_members("X", &s);
        assert!(matches!(r, Err(ExportError::NotFound(_))));
    }

    // ── manifest ───────────────────────────────────────────────────────────

    #[test]
    fn manifest_contains_member_metadata() {
        let s = StubSource;
        let m = collect_members("FCLC", &s).unwrap();
        let man = build_manifest("FCLC", &m, ts());
        assert_eq!(man.project, "FCLC");
        assert_eq!(man.members.len(), 6);
        assert!(man.exported_at.starts_with("2026-05-05"));
        for info in &man.members {
            assert_eq!(info.sha.chars().count(), 12);
            assert!(info.size > 0 || info.name == "memory.md" || info.name == "git_log.txt");
        }
    }

    // ── zip writer ─────────────────────────────────────────────────────────

    #[test]
    fn write_zip_creates_archive_with_manifest_and_members() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("FCLC-test.zip");
        let s = StubSource;
        let members = collect_members("FCLC", &s).unwrap();
        let man = build_manifest("FCLC", &members, ts());
        let bytes = write_zip("FCLC", &members, &man, &dest).unwrap();
        assert!(dest.exists());
        assert!(bytes > 0);
        // Check archive contents
        let f = std::fs::File::open(&dest).unwrap();
        let mut z = zip::ZipArchive::new(f).unwrap();
        let names: Vec<String> = (0..z.len()).map(|i| z.by_index(i).unwrap().name().to_string()).collect();
        assert!(names.contains(&"FCLC/project.yaml".to_string()));
        assert!(names.contains(&"FCLC/manifest.json".to_string()));
        // verify manifest is parseable
        let mut man_file = z.by_name("FCLC/manifest.json").unwrap();
        let mut buf = String::new();
        man_file.read_to_string(&mut buf).unwrap();
        let parsed: Manifest = serde_json::from_str(&buf).unwrap();
        assert_eq!(parsed.project, "FCLC");
    }

    // ── default_dest ───────────────────────────────────────────────────────

    #[test]
    fn default_dest_includes_timestamp() {
        let p = default_dest("FCLC", Path::new("/tmp/exports"), ts());
        assert_eq!(
            p,
            PathBuf::from("/tmp/exports/FCLC-20260505-123045.zip")
        );
    }

    // ── export end-to-end ──────────────────────────────────────────────────

    #[test]
    fn export_returns_result_with_member_list() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("FCLC.zip");
        let s = StubSource;
        let clk = FixedClock(ts());
        let r = export("FCLC", &s, &dest, &clk).unwrap();
        assert_eq!(r.project, "FCLC");
        assert_eq!(r.archive_path, dest);
        assert!(r.members.contains(&"manifest.json".to_string()));
        assert_eq!(r.members.len(), 7);
        assert!(r.bytes_total > 0);
    }

    #[test]
    fn export_propagates_yaml_missing() {
        let tmp = TempDir::new().unwrap();
        let dest = tmp.path().join("X.zip");
        let s = MissingYamlSource;
        let clk = FixedClock(ts());
        let r = export("X", &s, &dest, &clk);
        assert!(matches!(r, Err(ExportError::NotFound(_))));
    }
}
