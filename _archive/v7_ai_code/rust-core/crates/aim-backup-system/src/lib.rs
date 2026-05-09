//! aim-backup-system — full-system backup orchestrator.
//!
//! Port of `scripts/backup_system.py`. The Python module bundles
//! tar/gzip + GPG + filesystem walks; here we keep the deterministic
//! parts (path expansion, manifest assembly, prune ordering, archive
//! filename templates) and abstract I/O behind traits.
//!
//! The actual `tar`, `gpg`, `shutil.copytree` etc. live in the binary.

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{Deserialize, Serialize};

pub const VERSION: &str = "7.0";

pub const BACKUP_PATHS: &[&str] = &[
    "~/.claude/memory_index/",
    "~/.claude/memory_versions/",
    "~/.claude/aim_graph_state.db",
    "~/.claude/memory_import_log.json",
    "~/.claude/projects/-home-oem/memory/",
    "~/Desktop/AIM/aim.db",
    "~/Desktop/AIM/agents/",
    "~/Desktop/AIM/scripts/",
    "~/Desktop/AIM/web/",
    "~/Desktop/AIM/export/",
    "~/Desktop/AIM/experiments/",
    "~/Desktop/AIM/llm.py",
    "~/Desktop/AIM/config.py",
    "~/Desktop/AIM/i18n.py",
    "~/Desktop/AIM/db.py",
    "~/Desktop/AIM/lab_reference.py",
    "~/Desktop/AIM/CLAUDE.md",
    "~/Desktop/AIM/CONCEPT.md",
    "~/Desktop/AIM/MAP.md",
];

// ── traits ────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Kind {
    File,
    Dir,
    Missing,
}

pub trait FilesystemView: Send + Sync {
    fn kind(&self, expanded: &str) -> Kind;
    fn size(&self, expanded: &str) -> i64;
    fn home(&self) -> String;
    fn hostname(&self) -> String;
}

pub fn expand_user(home: &str, path: &str) -> String {
    if let Some(rest) = path.strip_prefix("~/") {
        format!("{}/{}", home.trim_end_matches('/'), rest)
    } else if path == "~" {
        home.to_string()
    } else {
        path.to_string()
    }
}

pub fn make_archive_name(now: DateTime<Utc>) -> String {
    format!("aim_backup_{}", now.format("%Y%m%d_%H%M%S"))
}

pub fn parse_archive_ts(filename: &str) -> Option<NaiveDateTime> {
    // Accepts:
    //   aim_backup_20260505_120000.tar.gz
    //   aim_backup_20260505_120000.tar.gz.gpg
    let stripped = filename
        .strip_prefix("aim_backup_")?
        .trim_end_matches(".gpg")
        .trim_end_matches(".tar.gz");
    NaiveDateTime::parse_from_str(stripped, "%Y%m%d_%H%M%S").ok()
}

// ── manifest ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ManifestEntry {
    pub path: String,
    pub kind: String, // "file" | "dir"
    pub size: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Manifest {
    pub name: String,
    pub created: String,
    pub version: String,
    pub host: String,
    pub encrypted: bool,
    pub include_keys: bool,
    pub files: Vec<ManifestEntry>,
    pub total_size: i64,
}

pub fn collect_manifest(
    fs: &dyn FilesystemView,
    name: &str,
    created: DateTime<Utc>,
    encrypt: bool,
    include_keys: bool,
    paths: &[&str],
    keys_path: Option<&str>,
) -> Manifest {
    let home = fs.home();
    let mut files: Vec<ManifestEntry> = Vec::new();
    for p in paths {
        let expanded = expand_user(&home, p);
        let kind = fs.kind(&expanded);
        if matches!(kind, Kind::Missing) {
            continue;
        }
        let kind_str = match kind {
            Kind::Dir => "dir",
            Kind::File => "file",
            Kind::Missing => unreachable!(),
        };
        files.push(ManifestEntry {
            path: expanded.clone(),
            kind: kind_str.to_string(),
            size: fs.size(&expanded),
        });
    }
    if include_keys {
        if let Some(kp) = keys_path {
            let expanded = expand_user(&home, kp);
            if matches!(fs.kind(&expanded), Kind::File) {
                files.push(ManifestEntry {
                    path: expanded.clone(),
                    kind: "file".to_string(),
                    size: fs.size(&expanded),
                });
            }
        }
    }
    let total_size: i64 = files.iter().map(|f| f.size).sum();
    Manifest {
        name: name.to_string(),
        created: created.format("%Y-%m-%dT%H:%M:%S").to_string(),
        version: VERSION.to_string(),
        host: fs.hostname(),
        encrypted: encrypt,
        include_keys,
        files,
        total_size,
    }
}

// ── prune planner ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ArchiveSnapshot {
    pub filename: String,
    pub size: i64,
    pub mtime_unix: i64,
}

pub fn list_archives_sorted(rows: &[ArchiveSnapshot]) -> Vec<ArchiveSnapshot> {
    let mut sorted: Vec<ArchiveSnapshot> = rows
        .iter()
        .filter(|s| s.filename.starts_with("aim_backup_"))
        .filter(|s| {
            s.filename.ends_with(".tar.gz") || s.filename.ends_with(".tar.gz.gpg")
        })
        .cloned()
        .collect();
    sorted.sort_by_key(|a| a.mtime_unix);
    sorted
}

pub fn plan_prune(rows: &[ArchiveSnapshot], keep: usize) -> Vec<ArchiveSnapshot> {
    let sorted = list_archives_sorted(rows);
    if sorted.len() <= keep {
        return vec![];
    }
    let cut = sorted.len() - keep;
    sorted[..cut].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts_unix(s: &str) -> i64 {
        NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S")
            .unwrap()
            .and_utc()
            .timestamp()
    }

    // ── expand_user ───────────────────────────────────────────────────────

    #[test]
    fn expand_user_replaces_tilde() {
        assert_eq!(expand_user("/home/jaba", "~/Desktop/x"), "/home/jaba/Desktop/x");
    }

    #[test]
    fn expand_user_passthrough_when_no_tilde() {
        assert_eq!(expand_user("/home/jaba", "/etc/passwd"), "/etc/passwd");
    }

    #[test]
    fn expand_user_handles_bare_tilde() {
        assert_eq!(expand_user("/home/jaba", "~"), "/home/jaba");
    }

    // ── archive name templating ───────────────────────────────────────────

    #[test]
    fn make_archive_name_format() {
        let dt = Utc.with_ymd_and_hms(2026, 5, 5, 12, 30, 45).unwrap();
        assert_eq!(make_archive_name(dt), "aim_backup_20260505_123045");
    }

    #[test]
    fn parse_archive_ts_round_trip() {
        let dt = Utc.with_ymd_and_hms(2026, 5, 5, 12, 30, 45).unwrap();
        let name = format!("{}.tar.gz", make_archive_name(dt));
        let parsed = parse_archive_ts(&name).unwrap();
        assert_eq!(parsed.format("%Y-%m-%dT%H:%M:%S").to_string(), "2026-05-05T12:30:45");
    }

    #[test]
    fn parse_archive_ts_handles_gpg_suffix() {
        let parsed = parse_archive_ts("aim_backup_20260505_120000.tar.gz.gpg").unwrap();
        assert_eq!(parsed.format("%Y").to_string(), "2026");
    }

    #[test]
    fn parse_archive_ts_rejects_unknown() {
        assert!(parse_archive_ts("random_file.tar.gz").is_none());
    }

    // ── manifest ──────────────────────────────────────────────────────────

    struct FakeFs;
    impl FilesystemView for FakeFs {
        fn kind(&self, p: &str) -> Kind {
            if p.ends_with('/') {
                Kind::Dir
            } else if p.contains("missing") {
                Kind::Missing
            } else {
                Kind::File
            }
        }
        fn size(&self, p: &str) -> i64 {
            if p.ends_with('/') {
                10_000
            } else {
                1_000
            }
        }
        fn home(&self) -> String {
            "/home/jaba".into()
        }
        fn hostname(&self) -> String {
            "test-host".into()
        }
    }

    #[test]
    fn collect_manifest_skips_missing_paths() {
        let now = Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap();
        let m = collect_manifest(
            &FakeFs,
            "aim_backup_test",
            now,
            false,
            false,
            &["~/Desktop/AIM/llm.py", "~/Desktop/AIM/missing_file.py"],
            None,
        );
        assert_eq!(m.files.len(), 1);
        assert_eq!(m.files[0].path, "/home/jaba/Desktop/AIM/llm.py");
    }

    #[test]
    fn collect_manifest_records_dir_kind_correctly() {
        let now = Utc::now();
        let m = collect_manifest(
            &FakeFs,
            "x",
            now,
            false,
            false,
            &["~/Desktop/AIM/agents/"],
            None,
        );
        assert_eq!(m.files[0].kind, "dir");
    }

    #[test]
    fn collect_manifest_includes_keys_when_requested() {
        let now = Utc::now();
        let m = collect_manifest(
            &FakeFs,
            "x",
            now,
            true,
            true,
            &["~/Desktop/AIM/llm.py"],
            Some("~/.aim_env"),
        );
        assert_eq!(m.files.len(), 2);
        assert!(m.encrypted);
        assert!(m.include_keys);
    }

    #[test]
    fn collect_manifest_total_size_is_sum() {
        let now = Utc::now();
        let m = collect_manifest(
            &FakeFs,
            "x",
            now,
            false,
            false,
            &[
                "~/Desktop/AIM/llm.py",
                "~/Desktop/AIM/agents/",
                "~/Desktop/AIM/config.py",
            ],
            None,
        );
        assert_eq!(m.total_size, 1_000 + 10_000 + 1_000);
    }

    #[test]
    fn collect_manifest_serializes_to_python_compatible_shape() {
        let now = Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap();
        let m = collect_manifest(
            &FakeFs,
            "test",
            now,
            false,
            false,
            &["~/Desktop/AIM/llm.py"],
            None,
        );
        let s = serde_json::to_string(&m).unwrap();
        assert!(s.contains("\"version\":\"7.0\""));
        assert!(s.contains("\"host\":\"test-host\""));
        assert!(s.contains("\"created\":\"2026-05-05T12:00:00\""));
    }

    // ── prune planner ─────────────────────────────────────────────────────

    fn snap(name: &str, mt: &str) -> ArchiveSnapshot {
        ArchiveSnapshot {
            filename: name.to_string(),
            size: 1_000,
            mtime_unix: ts_unix(mt),
        }
    }

    #[test]
    fn list_sorted_picks_aim_backups_only() {
        let rows = vec![
            snap("aim_backup_a.tar.gz", "2026-05-01 12:00:00"),
            snap("random_file.tar.gz", "2026-05-02 12:00:00"),
            snap("aim_backup_b.tar.gz.gpg", "2026-05-03 12:00:00"),
        ];
        let sorted = list_archives_sorted(&rows);
        assert_eq!(sorted.len(), 2);
        assert!(sorted[0].filename.starts_with("aim_backup_"));
        assert!(sorted[1].filename.contains(".gpg"));
    }

    #[test]
    fn prune_keeps_most_recent_n() {
        let rows = vec![
            snap("aim_backup_1.tar.gz", "2026-04-30 12:00:00"),
            snap("aim_backup_2.tar.gz", "2026-05-01 12:00:00"),
            snap("aim_backup_3.tar.gz", "2026-05-02 12:00:00"),
            snap("aim_backup_4.tar.gz", "2026-05-03 12:00:00"),
            snap("aim_backup_5.tar.gz", "2026-05-04 12:00:00"),
        ];
        let to_drop = plan_prune(&rows, 3);
        assert_eq!(to_drop.len(), 2);
        assert_eq!(to_drop[0].filename, "aim_backup_1.tar.gz");
        assert_eq!(to_drop[1].filename, "aim_backup_2.tar.gz");
    }

    #[test]
    fn prune_no_op_when_under_limit() {
        let rows = vec![snap("aim_backup_1.tar.gz", "2026-05-01 12:00:00")];
        assert!(plan_prune(&rows, 7).is_empty());
    }
}
