//! aim-disk-monitor — disk-usage watchdog with graduated cleanup.
//!
//! Port of `scripts/disk_monitor.py`. The deterministic part is:
//!
//!   * thresholds (10 GB warning, 5 GB critical),
//!   * status classification + `human` byte formatter,
//!   * per-watched-dir size collection and descending sort,
//!   * suggestion + emergency-cleanup planning (pure: returns the list
//!     of would-be actions, no actual deletes).
//!
//! Real disk reads + filesystem mutations stay behind the [`DiskQuery`]
//! and [`Cleaner`] traits so unit tests don't touch the real disk.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Ok,
    Warning,
    Critical,
}

impl Status {
    pub fn as_str(&self) -> &'static str {
        match self {
            Status::Ok => "ok",
            Status::Warning => "warning",
            Status::Critical => "critical",
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct Thresholds {
    pub warning_gb: f64,
    pub critical_gb: f64,
}

impl Default for Thresholds {
    fn default() -> Self {
        Self {
            warning_gb: 10.0,
            critical_gb: 5.0,
        }
    }
}

pub fn classify(free_gb: f64, t: &Thresholds) -> Status {
    if free_gb < t.critical_gb {
        Status::Critical
    } else if free_gb < t.warning_gb {
        Status::Warning
    } else {
        Status::Ok
    }
}

pub fn human_bytes(n: i64) -> String {
    let mut x = n as f64;
    for unit in ["B", "KB", "MB", "GB", "TB"] {
        if x.abs() < 1024.0 {
            return format!("{:.1} {}", x, unit);
        }
        x /= 1024.0;
    }
    format!("{:.1} PB", x)
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct DirEntry {
    pub path: String,
    pub size: i64,
    pub human: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DiskUsage {
    pub free_bytes: i64,
    pub total_bytes: i64,
}

impl DiskUsage {
    pub fn free_gb(&self) -> f64 {
        self.free_bytes as f64 / (1024.0 * 1024.0 * 1024.0)
    }
    pub fn total_gb(&self) -> f64 {
        self.total_bytes as f64 / (1024.0 * 1024.0 * 1024.0)
    }
    pub fn used_pct(&self) -> f64 {
        if self.total_bytes == 0 {
            return 0.0;
        }
        ((self.total_bytes - self.free_bytes) as f64 / self.total_bytes as f64 * 1000.0).round()
            / 10.0
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CheckReport {
    pub status: Status,
    pub timestamp: String,
    pub free_gb: f64,
    pub total_gb: f64,
    pub used_pct: f64,
    pub watched: Vec<DirEntry>,
}

pub trait DiskQuery: Send + Sync {
    fn home_usage(&self) -> DiskUsage;
    fn dir_size(&self, path: &str) -> i64;
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub fn check(
    disk: &dyn DiskQuery,
    clock: &dyn Clock,
    watched: &[String],
    t: &Thresholds,
) -> CheckReport {
    let usage = disk.home_usage();
    let free_gb = (usage.free_gb() * 10.0).round() / 10.0;
    let total_gb = (usage.total_gb() * 10.0).round() / 10.0;
    let mut entries: Vec<DirEntry> = watched
        .iter()
        .map(|p| {
            let size = disk.dir_size(p);
            DirEntry {
                path: p.clone(),
                size,
                human: human_bytes(size),
            }
        })
        .collect();
    entries.sort_by(|a, b| b.size.cmp(&a.size));
    CheckReport {
        status: classify(free_gb, t),
        timestamp: clock.now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        free_gb,
        total_gb,
        used_pct: usage.used_pct(),
        watched: entries,
    }
}

// ── cleanup planning ──────────────────────────────────────────────────────

pub fn suggestions() -> Vec<String> {
    vec![
        "aim-memory dedup --apply         # merge near-duplicate memories".into(),
        "aim-graph-gc 3                    # prune old LangGraph checkpoints".into(),
        "aim-backup prune --keep 3         # keep only 3 latest backups".into(),
        "find ~/.claude -name '*.log' -size +50M -delete".into(),
    ]
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CleanupItem {
    pub path: String,
    pub action: String,
    pub bytes: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CleanupPlan {
    pub items: Vec<CleanupItem>,
}

pub trait CleanupCatalog: Send + Sync {
    /// Old → new ordered list of (subdir_name, mtime, size_bytes) under
    /// `~/.claude/memory_versions/`.
    fn memory_versions(&self) -> Vec<(String, i64)>;
    /// Old → new ordered list of (filename, size_bytes) under
    /// `~/Desktop/AIM_backups/` matching `aim_backup_*.tar.gz*`.
    fn backups(&self) -> Vec<(String, i64)>;
    /// Size of `~/.claude/embed.log` if present, else `None`.
    fn embed_log_size(&self) -> Option<i64>;
}

pub fn plan_emergency(catalog: &dyn CleanupCatalog, keep_versions: usize) -> CleanupPlan {
    let mut items = Vec::new();

    // 1. Prune older memory_versions, keep the most-recent N.
    let versions = catalog.memory_versions();
    if versions.len() > keep_versions {
        let to_remove = &versions[..versions.len() - keep_versions];
        for (name, size) in to_remove {
            items.push(CleanupItem {
                path: format!("memory_versions/{}", name),
                action: "rmtree".into(),
                bytes: *size,
            });
        }
    }

    // 2. Truncate large embed.log (>100 MB).
    if let Some(sz) = catalog.embed_log_size() {
        if sz > 100 * 1024 * 1024 {
            items.push(CleanupItem {
                path: "~/.claude/embed.log".into(),
                action: "truncate".into(),
                bytes: sz,
            });
        }
    }

    // 3. Rotate AIM_backups, keep most-recent 5.
    let backups = catalog.backups();
    if backups.len() > 5 {
        let to_remove = &backups[..backups.len() - 5];
        for (name, size) in to_remove {
            items.push(CleanupItem {
                path: format!("AIM_backups/{}", name),
                action: "unlink".into(),
                bytes: *size,
            });
        }
    }

    CleanupPlan { items }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::sync::Mutex;

    struct FakeDisk {
        free: i64,
        total: i64,
        sizes: std::collections::BTreeMap<String, i64>,
    }
    impl FakeDisk {
        fn new(free: i64, total: i64) -> Self {
            Self { free, total, sizes: Default::default() }
        }
        fn set(mut self, p: &str, n: i64) -> Self {
            self.sizes.insert(p.to_string(), n);
            self
        }
    }
    impl DiskQuery for FakeDisk {
        fn home_usage(&self) -> DiskUsage {
            DiskUsage { free_bytes: self.free, total_bytes: self.total }
        }
        fn dir_size(&self, path: &str) -> i64 {
            *self.sizes.get(path).unwrap_or(&0)
        }
    }

    struct FakeClock(DateTime<Utc>);
    impl Clock for FakeClock {
        fn now(&self) -> DateTime<Utc> {
            self.0
        }
    }

    fn t() -> Thresholds {
        Thresholds::default()
    }

    // ── classify ──────────────────────────────────────────────────────────

    #[test]
    fn classify_buckets() {
        let th = t();
        assert_eq!(classify(20.0, &th), Status::Ok);
        assert_eq!(classify(8.0, &th), Status::Warning);
        assert_eq!(classify(2.0, &th), Status::Critical);
    }

    #[test]
    fn classify_boundary_inclusive_warning() {
        let th = t();
        // free == warning threshold → still Ok (strict <)
        assert_eq!(classify(10.0, &th), Status::Ok);
        // free just under warning → Warning
        assert_eq!(classify(9.9, &th), Status::Warning);
        assert_eq!(classify(5.0, &th), Status::Warning);
        assert_eq!(classify(4.99, &th), Status::Critical);
    }

    // ── human_bytes ───────────────────────────────────────────────────────

    #[test]
    fn human_bytes_units() {
        assert_eq!(human_bytes(0), "0.0 B");
        assert_eq!(human_bytes(1023), "1023.0 B");
        assert_eq!(human_bytes(1024), "1.0 KB");
        assert_eq!(human_bytes(1024 * 1024), "1.0 MB");
        assert_eq!(human_bytes(1024_i64.pow(3)), "1.0 GB");
    }

    // ── check ─────────────────────────────────────────────────────────────

    #[test]
    fn check_sorts_watched_dirs_descending() {
        let disk = FakeDisk::new(20 * 1024_i64.pow(3), 100 * 1024_i64.pow(3))
            .set("/a", 10)
            .set("/b", 1000)
            .set("/c", 500);
        let watched = vec!["/a".into(), "/b".into(), "/c".into()];
        let clock = FakeClock(Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap());
        let r = check(&disk, &clock, &watched, &t());
        assert_eq!(r.watched[0].path, "/b");
        assert_eq!(r.watched[1].path, "/c");
        assert_eq!(r.watched[2].path, "/a");
        assert_eq!(r.status, Status::Ok);
        assert_eq!(r.free_gb, 20.0);
    }

    #[test]
    fn check_critical_when_free_below_5gb() {
        let disk = FakeDisk::new(2 * 1024_i64.pow(3), 100 * 1024_i64.pow(3));
        let clock = FakeClock(Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap());
        let r = check(&disk, &clock, &[], &t());
        assert_eq!(r.status, Status::Critical);
    }

    // ── suggestions / cleanup plan ────────────────────────────────────────

    #[test]
    fn suggestions_non_empty() {
        let s = suggestions();
        assert!(s.iter().any(|x| x.contains("aim-memory dedup")));
        assert_eq!(s.len(), 4);
    }

    struct FakeCatalog {
        versions: Mutex<Vec<(String, i64)>>,
        backups: Mutex<Vec<(String, i64)>>,
        embed_log: Mutex<Option<i64>>,
    }

    impl FakeCatalog {
        fn empty() -> Self {
            Self {
                versions: Mutex::new(vec![]),
                backups: Mutex::new(vec![]),
                embed_log: Mutex::new(None),
            }
        }
    }

    impl CleanupCatalog for FakeCatalog {
        fn memory_versions(&self) -> Vec<(String, i64)> {
            self.versions.lock().unwrap().clone()
        }
        fn backups(&self) -> Vec<(String, i64)> {
            self.backups.lock().unwrap().clone()
        }
        fn embed_log_size(&self) -> Option<i64> {
            *self.embed_log.lock().unwrap()
        }
    }

    #[test]
    fn plan_keeps_most_recent_versions() {
        let cat = FakeCatalog::empty();
        *cat.versions.lock().unwrap() = (0..6)
            .map(|i| (format!("v{}", i), (i + 1) as i64 * 1_000_000))
            .collect();
        let plan = plan_emergency(&cat, 3);
        assert_eq!(plan.items.len(), 3);
        assert_eq!(plan.items[0].path, "memory_versions/v0");
        assert_eq!(plan.items[2].path, "memory_versions/v2");
    }

    #[test]
    fn plan_truncates_oversize_embed_log() {
        let cat = FakeCatalog::empty();
        *cat.embed_log.lock().unwrap() = Some(150 * 1024 * 1024);
        let plan = plan_emergency(&cat, 3);
        assert_eq!(plan.items.len(), 1);
        assert_eq!(plan.items[0].action, "truncate");
    }

    #[test]
    fn plan_skips_small_embed_log() {
        let cat = FakeCatalog::empty();
        *cat.embed_log.lock().unwrap() = Some(50 * 1024 * 1024);
        let plan = plan_emergency(&cat, 3);
        assert!(plan.items.is_empty());
    }

    #[test]
    fn plan_keeps_top5_backups() {
        let cat = FakeCatalog::empty();
        *cat.backups.lock().unwrap() = (0..7)
            .map(|i| (format!("aim_backup_{}.tar.gz", i), (i + 1) as i64 * 1_000_000))
            .collect();
        let plan = plan_emergency(&cat, 3);
        assert_eq!(plan.items.len(), 2);
        assert!(plan.items[0].path.contains("aim_backup_0"));
        assert!(plan.items[1].path.contains("aim_backup_1"));
    }
}
