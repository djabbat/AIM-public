//! aim-memory-priority — priority levels + TTL for AIM memory facts.
//!
//! Port of `agents/memory_priority.py`. Priority + TTL live in YAML
//! frontmatter (no schema migration in LanceDB needed). At search time,
//! expired facts are filtered out and results are re-ordered by
//! priority desc → distance asc.
//!
//! ## Priority classes (numeric values match Python)
//! - `Critical = 100` — never delete, always surface
//! - `High     = 70`  — delete only on space pressure
//! - `Normal   = 40`  — default
//! - `Low      = 10`  — delete first, surface only on high relevance
//! - `Ephemeral = 1`  — auto-delete after 24h regardless of access count

use chrono::{DateTime, Duration, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PriorityError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Priority {
    Ephemeral,
    Low,
    Normal,
    High,
    Critical,
}

impl Priority {
    pub fn value(self) -> i32 {
        match self {
            Priority::Critical => 100,
            Priority::High => 70,
            Priority::Normal => 40,
            Priority::Low => 10,
            Priority::Ephemeral => 1,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Priority::Critical => "CRITICAL",
            Priority::High => "HIGH",
            Priority::Normal => "NORMAL",
            Priority::Low => "LOW",
            Priority::Ephemeral => "EPHEMERAL",
        }
    }

    pub fn parse(s: &str) -> Self {
        match s.to_uppercase().as_str() {
            "CRITICAL" => Priority::Critical,
            "HIGH" => Priority::High,
            "LOW" => Priority::Low,
            "EPHEMERAL" => Priority::Ephemeral,
            _ => Priority::Normal,
        }
    }

    pub fn from_value(v: i32) -> Self {
        if v >= 100 {
            Priority::Critical
        } else if v >= 70 {
            Priority::High
        } else if v >= 40 {
            Priority::Normal
        } else if v >= 10 {
            Priority::Low
        } else {
            Priority::Ephemeral
        }
    }
}

/// Build the metadata block for `remember(fact, metadata=…)`. EPHEMERAL
/// defaults to a 24h TTL when no `ttl_hours` is supplied.
pub fn build_metadata(
    priority: Priority,
    ttl_hours: Option<u32>,
    tags: &[String],
    now: DateTime<Utc>,
) -> BTreeMap<String, serde_yaml::Value> {
    let mut md = BTreeMap::new();
    md.insert(
        "priority".into(),
        serde_yaml::Value::String(priority.name().into()),
    );
    md.insert(
        "priority_value".into(),
        serde_yaml::Value::Number(serde_yaml::Number::from(priority.value())),
    );
    let ttl = match ttl_hours {
        Some(t) => Some(t),
        None if priority == Priority::Ephemeral => Some(24),
        _ => None,
    };
    if let Some(t) = ttl {
        md.insert(
            "ttl_hours".into(),
            serde_yaml::Value::Number(serde_yaml::Number::from(t)),
        );
        let expires = now + Duration::hours(t as i64);
        md.insert(
            "expires_at".into(),
            serde_yaml::Value::String(expires.format("%Y-%m-%dT%H:%M:%S").to_string()),
        );
    }
    if !tags.is_empty() {
        md.insert(
            "tags".into(),
            serde_yaml::Value::Sequence(
                tags.iter()
                    .map(|t| serde_yaml::Value::String(t.clone()))
                    .collect(),
            ),
        );
    }
    md
}

// ── frontmatter scan ────────────────────────────────────────────────────

static FM_RE: OnceLock<Regex> = OnceLock::new();
fn fm_re() -> &'static Regex {
    FM_RE.get_or_init(|| Regex::new(r"(?s)^---\s*\n(.*?)\n---").unwrap())
}

/// Read the YAML frontmatter as a flat string-key string-value map.
pub fn read_frontmatter(text: &str) -> BTreeMap<String, String> {
    let cap = match fm_re().captures(text) {
        Some(c) => c,
        None => return BTreeMap::new(),
    };
    let body = cap.get(1).map(|m| m.as_str()).unwrap_or("");
    let mut out = BTreeMap::new();
    for line in body.lines() {
        if let Some(idx) = line.find(':') {
            let k = line[..idx].trim().to_string();
            let v = line[idx + 1..].trim().to_string();
            if !k.is_empty() {
                out.insert(k, v);
            }
        }
    }
    out
}

pub fn read_frontmatter_file(path: &Path) -> BTreeMap<String, String> {
    match std::fs::read_to_string(path) {
        Ok(t) => read_frontmatter(&t),
        Err(_) => BTreeMap::new(),
    }
}

/// True when `expires_at` is set AND lies in the past. Missing / malformed
/// expires_at returns false (not expired).
pub fn is_expired(fm: &BTreeMap<String, String>, now: DateTime<Utc>) -> bool {
    let exp = match fm.get("expires_at") {
        Some(s) if !s.is_empty() => s,
        _ => return false,
    };
    if let Ok(dt) = DateTime::parse_from_rfc3339(exp) {
        return dt.with_timezone(&Utc) < now;
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(exp, "%Y-%m-%dT%H:%M:%S") {
        return naive.and_utc() < now;
    }
    false
}

pub fn priority_value_of(fm: &BTreeMap<String, String>) -> i32 {
    fm.get("priority_value")
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| Priority::Normal.value())
}

// ── pruning ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PruneReport {
    pub deleted: Vec<String>,
    pub kept_critical: Vec<String>,
}

/// Walk `root` recursively, drop `*.md` files whose expires_at is past
/// AND priority < CRITICAL. CRITICAL files are kept regardless of TTL.
pub fn prune_expired(
    root: &Path,
    dry_run: bool,
    now: DateTime<Utc>,
) -> Result<PruneReport, PriorityError> {
    let mut report = PruneReport::default();
    if !root.exists() {
        return Ok(report);
    }
    walk_md_files(root, &mut |path| {
        let fm = read_frontmatter_file(path);
        if !is_expired(&fm, now) {
            return Ok(());
        }
        let prio = priority_value_of(&fm);
        if prio >= Priority::Critical.value() {
            report.kept_critical.push(path.to_string_lossy().to_string());
            return Ok(());
        }
        report.deleted.push(path.to_string_lossy().to_string());
        if !dry_run {
            std::fs::remove_file(path)?;
        }
        Ok(())
    })?;
    Ok(report)
}

fn walk_md_files<F>(root: &Path, visit: &mut F) -> Result<(), PriorityError>
where
    F: FnMut(&Path) -> Result<(), PriorityError>,
{
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let p = entry.path();
        if p.is_dir() {
            walk_md_files(&p, visit)?;
        } else if p.extension().and_then(|s| s.to_str()) == Some("md") {
            visit(&p)?;
        }
    }
    Ok(())
}

// ── filter + rank retrieval hits ────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Hit {
    pub file: String,
    /// Lower distance = closer match.
    pub distance: f64,
    /// Optional pre-resolved frontmatter — when None, host wires a path
    /// resolver and `read_frontmatter_file` is called by `filter_and_rank`.
    #[serde(default)]
    pub frontmatter: Option<BTreeMap<String, String>>,
}

/// Drop expired hits, sort by (priority desc, distance asc).
///
/// The Python module reads frontmatter from disk during ranking; the
/// Rust port lets the caller pre-attach `frontmatter` per hit (cheaper
/// when the index already carries metadata) OR pass a resolver closure.
pub fn filter_and_rank(
    hits: Vec<Hit>,
    now: DateTime<Utc>,
    resolve: impl Fn(&str) -> Option<BTreeMap<String, String>>,
) -> Vec<Hit> {
    let mut enriched: Vec<(i32, f64, Hit)> = Vec::new();
    for h in hits {
        let fm = h.frontmatter.clone().or_else(|| resolve(&h.file));
        let fm = fm.unwrap_or_default();
        if is_expired(&fm, now) {
            continue;
        }
        let prio = priority_value_of(&fm);
        let dist = h.distance;
        let mut h2 = h;
        if h2.frontmatter.is_none() {
            h2.frontmatter = Some(fm);
        }
        enriched.push((prio, dist, h2));
    }
    enriched.sort_by(|a, b| {
        b.0.cmp(&a.0)
            .then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
    });
    enriched.into_iter().map(|(_, _, h)| h).collect()
}

/// Helper: resolve a file basename to a full path under `root` by
/// recursive glob. Mirrors Python `_locate`.
pub fn locate_under(root: &Path, file_name: &str) -> Option<PathBuf> {
    if !root.exists() {
        return None;
    }
    let mut found = None;
    let _ = walk_md_files(root, &mut |p: &Path| {
        if found.is_some() {
            return Ok(());
        }
        if let Some(name) = p.file_name().and_then(|s| s.to_str()) {
            if name == file_name {
                found = Some(p.to_path_buf());
            }
        }
        Ok(())
    });
    found
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 4, 12, 0, 0).unwrap()
    }

    fn write(dir: &TempDir, rel: &str, body: &str) -> PathBuf {
        let p = dir.path().join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn priority_parse_round_trip() {
        for p in [
            Priority::Critical,
            Priority::High,
            Priority::Normal,
            Priority::Low,
            Priority::Ephemeral,
        ] {
            assert_eq!(Priority::parse(p.name()), p);
            assert_eq!(Priority::from_value(p.value()), p);
        }
    }

    #[test]
    fn priority_parse_unknown_falls_back_to_normal() {
        assert_eq!(Priority::parse("garbage"), Priority::Normal);
    }

    #[test]
    fn build_metadata_ephemeral_default_ttl() {
        let md = build_metadata(Priority::Ephemeral, None, &[], now());
        assert_eq!(
            md.get("priority").and_then(|v| v.as_str()),
            Some("EPHEMERAL")
        );
        assert_eq!(md.get("ttl_hours").and_then(|v| v.as_u64()), Some(24));
        assert!(md.get("expires_at").is_some());
    }

    #[test]
    fn build_metadata_normal_no_ttl() {
        let md = build_metadata(Priority::Normal, None, &[], now());
        assert!(md.get("ttl_hours").is_none());
        assert!(md.get("expires_at").is_none());
    }

    #[test]
    fn build_metadata_explicit_ttl_wins() {
        let md = build_metadata(Priority::High, Some(720), &[], now());
        assert_eq!(md.get("ttl_hours").and_then(|v| v.as_u64()), Some(720));
        // expires_at = now + 720h
        let expected = (now() + Duration::hours(720))
            .format("%Y-%m-%dT%H:%M:%S")
            .to_string();
        assert_eq!(
            md.get("expires_at").and_then(|v| v.as_str()),
            Some(expected.as_str())
        );
    }

    #[test]
    fn build_metadata_includes_tags() {
        let tags = vec!["centriole".to_string(), "aging".to_string()];
        let md = build_metadata(Priority::Normal, None, &tags, now());
        let arr = md.get("tags").and_then(|v| v.as_sequence()).unwrap();
        assert_eq!(arr.len(), 2);
    }

    #[test]
    fn read_frontmatter_basic() {
        let text = "---\npriority: HIGH\nttl_hours: 720\n---\nbody";
        let fm = read_frontmatter(text);
        assert_eq!(fm.get("priority"), Some(&"HIGH".to_string()));
        assert_eq!(fm.get("ttl_hours"), Some(&"720".to_string()));
    }

    #[test]
    fn read_frontmatter_missing_returns_empty() {
        let fm = read_frontmatter("just body");
        assert!(fm.is_empty());
    }

    #[test]
    fn is_expired_past_returns_true() {
        let mut fm = BTreeMap::new();
        fm.insert("expires_at".into(), "2026-04-01T00:00:00".into());
        assert!(is_expired(&fm, now()));
    }

    #[test]
    fn is_expired_future_returns_false() {
        let mut fm = BTreeMap::new();
        fm.insert("expires_at".into(), "2027-01-01T00:00:00".into());
        assert!(!is_expired(&fm, now()));
    }

    #[test]
    fn is_expired_missing_returns_false() {
        let fm = BTreeMap::new();
        assert!(!is_expired(&fm, now()));
    }

    #[test]
    fn is_expired_malformed_returns_false() {
        let mut fm = BTreeMap::new();
        fm.insert("expires_at".into(), "not-a-date".into());
        assert!(!is_expired(&fm, now()));
    }

    #[test]
    fn priority_value_of_default() {
        let fm = BTreeMap::new();
        assert_eq!(priority_value_of(&fm), 40); // NORMAL
    }

    #[test]
    fn priority_value_of_explicit() {
        let mut fm = BTreeMap::new();
        fm.insert("priority_value".into(), "100".into());
        assert_eq!(priority_value_of(&fm), 100);
    }

    #[test]
    fn prune_drops_expired_non_critical() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "expired.md",
            "---\npriority_value: 40\nexpires_at: 2026-01-01T00:00:00\n---\nold",
        );
        write(
            &dir,
            "fresh.md",
            "---\npriority_value: 40\nexpires_at: 2027-01-01T00:00:00\n---\nstill good",
        );
        write(&dir, "no_ttl.md", "---\npriority_value: 40\n---\nforever");
        let r = prune_expired(dir.path(), false, now()).unwrap();
        assert_eq!(r.deleted.len(), 1);
        assert!(r.deleted[0].ends_with("expired.md"));
        assert!(!dir.path().join("expired.md").exists());
        assert!(dir.path().join("fresh.md").exists());
        assert!(dir.path().join("no_ttl.md").exists());
    }

    #[test]
    fn prune_keeps_expired_critical() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "critical_expired.md",
            "---\npriority_value: 100\nexpires_at: 2026-01-01T00:00:00\n---\nimportant",
        );
        let r = prune_expired(dir.path(), false, now()).unwrap();
        assert!(r.deleted.is_empty());
        assert_eq!(r.kept_critical.len(), 1);
        assert!(dir.path().join("critical_expired.md").exists());
    }

    #[test]
    fn prune_dry_run_lists_but_does_not_delete() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "x.md",
            "---\npriority_value: 10\nexpires_at: 2026-01-01T00:00:00\n---\n",
        );
        let r = prune_expired(dir.path(), true, now()).unwrap();
        assert_eq!(r.deleted.len(), 1);
        assert!(dir.path().join("x.md").exists());
    }

    #[test]
    fn prune_descends_recursively() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "subA/old.md",
            "---\npriority_value: 40\nexpires_at: 2026-01-01T00:00:00\n---\n",
        );
        write(
            &dir,
            "subB/sub2/older.md",
            "---\npriority_value: 40\nexpires_at: 2026-02-01T00:00:00\n---\n",
        );
        let r = prune_expired(dir.path(), false, now()).unwrap();
        assert_eq!(r.deleted.len(), 2);
    }

    #[test]
    fn prune_root_missing_returns_empty() {
        let dir = TempDir::new().unwrap();
        let r = prune_expired(&dir.path().join("ghost"), false, now()).unwrap();
        assert!(r.deleted.is_empty());
        assert!(r.kept_critical.is_empty());
    }

    #[test]
    fn filter_and_rank_drops_expired() {
        let mut fresh = BTreeMap::new();
        fresh.insert("priority_value".into(), "40".into());
        let mut expired = BTreeMap::new();
        expired.insert("priority_value".into(), "70".into());
        expired.insert("expires_at".into(), "2026-01-01T00:00:00".into());

        let hits = vec![
            Hit {
                file: "expired.md".into(),
                distance: 0.1,
                frontmatter: Some(expired),
            },
            Hit {
                file: "fresh.md".into(),
                distance: 0.5,
                frontmatter: Some(fresh),
            },
        ];
        let out = filter_and_rank(hits, now(), |_| None);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].file, "fresh.md");
    }

    #[test]
    fn filter_and_rank_priority_beats_distance() {
        let mut high = BTreeMap::new();
        high.insert("priority_value".into(), "100".into());
        let mut low = BTreeMap::new();
        low.insert("priority_value".into(), "10".into());
        let hits = vec![
            Hit {
                file: "low_close.md".into(),
                distance: 0.05,
                frontmatter: Some(low),
            },
            Hit {
                file: "high_far.md".into(),
                distance: 0.50,
                frontmatter: Some(high),
            },
        ];
        let out = filter_and_rank(hits, now(), |_| None);
        // CRITICAL (100) wins despite worse distance
        assert_eq!(out[0].file, "high_far.md");
        assert_eq!(out[1].file, "low_close.md");
    }

    #[test]
    fn filter_and_rank_uses_resolver_when_no_attached_fm() {
        let hits = vec![
            Hit {
                file: "a.md".into(),
                distance: 0.5,
                frontmatter: None,
            },
            Hit {
                file: "b.md".into(),
                distance: 0.1,
                frontmatter: None,
            },
        ];
        let out = filter_and_rank(hits, now(), |name| {
            let mut fm = BTreeMap::new();
            if name == "a.md" {
                fm.insert("priority_value".into(), "100".into());
            } else {
                fm.insert("priority_value".into(), "10".into());
            }
            Some(fm)
        });
        assert_eq!(out[0].file, "a.md");
    }

    #[test]
    fn filter_and_rank_sorts_distance_ties() {
        let mut p = BTreeMap::new();
        p.insert("priority_value".into(), "40".into());
        let hits = vec![
            Hit {
                file: "far.md".into(),
                distance: 0.6,
                frontmatter: Some(p.clone()),
            },
            Hit {
                file: "close.md".into(),
                distance: 0.2,
                frontmatter: Some(p),
            },
        ];
        let out = filter_and_rank(hits, now(), |_| None);
        assert_eq!(out[0].file, "close.md");
    }

    #[test]
    fn locate_under_finds_md() {
        let dir = TempDir::new().unwrap();
        let p = write(&dir, "subA/wanted.md", "x");
        let found = locate_under(dir.path(), "wanted.md");
        assert_eq!(found, Some(p));
    }

    #[test]
    fn locate_under_missing_returns_none() {
        let dir = TempDir::new().unwrap();
        assert!(locate_under(dir.path(), "ghost.md").is_none());
    }
}
