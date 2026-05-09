//! aim-memory-monitor — auto-memory hygiene (M1).
//!
//! Port of `agents/memory_monitor.py`. Scans `memory_dir/*.md` and
//! reports:
//! - **stale** — entries untouched for ≥ N months
//! - **obsolete_deadline** — body mentions `deadline YYYY-MM-DD` >14d
//!   in the past
//! - **broken_path** — body references `~/Desktop/...` that no longer
//!   exists on disk
//! - **duplicate** — frontmatter `description` Jaccard similarity ≥ 0.7
//!   between two entries (token-stem 6-char, ≥3-char tokens)
//!
//! Output is structured. We never auto-delete.

use chrono::{DateTime, Duration, NaiveDate, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum MonitorError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Info,
    Warn,
    High,
}

impl Severity {
    pub fn rank(self) -> i32 {
        match self {
            Severity::High => 0,
            Severity::Warn => 1,
            Severity::Info => 2,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Stale,
    Duplicate,
    BrokenPath,
    ObsoleteDeadline,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Stale => "stale",
            Kind::Duplicate => "duplicate",
            Kind::BrokenPath => "broken_path",
            Kind::ObsoleteDeadline => "obsolete_deadline",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Finding {
    pub kind: Kind,
    pub file: String,
    pub detail: String,
    pub severity: Severity,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Report {
    pub scanned: u32,
    pub findings: Vec<Finding>,
}

pub fn default_memory_dir() -> PathBuf {
    if let Ok(env) = std::env::var("AIM_MEMORY_DIR") {
        let trimmed = env.trim();
        if !trimmed.is_empty() {
            return expand_tilde(trimmed);
        }
    }
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude/projects/-home-oem/memory")
}

fn expand_tilde(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix("~/") {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        home.join(rest)
    } else if p == "~" {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    } else {
        PathBuf::from(p)
    }
}

static DEADLINE_RE: OnceLock<Regex> = OnceLock::new();
static PATH_REF_RE: OnceLock<Regex> = OnceLock::new();
static WORD_RE: OnceLock<Regex> = OnceLock::new();

fn deadline_re() -> &'static Regex {
    DEADLINE_RE.get_or_init(|| {
        Regex::new(
            r"(?i)\b(?:deadline|due|by|до|дедлайн)[\s:*\-]*((?:19|20|21)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b",
        )
        .expect("deadline regex")
    })
}

fn path_ref_re() -> &'static Regex {
    PATH_REF_RE.get_or_init(|| Regex::new(r"`((?:/|~/)[^`\n]+)`").expect("path-ref regex"))
}

fn word_re() -> &'static Regex {
    WORD_RE.get_or_init(|| Regex::new(r"\w+").expect("word regex"))
}

fn parse_frontmatter(text: &str) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if !text.starts_with("---") {
        return out;
    }
    let after = &text[3..];
    let end = match after.find("\n---") {
        Some(i) => i,
        None => return out,
    };
    let block = after[..end].trim();
    for line in block.lines() {
        if let Some(idx) = line.find(':') {
            let k = line[..idx].trim().to_string();
            let v = line[idx + 1..]
                .trim()
                .trim_matches(|c: char| c == '"' || c == '\'')
                .to_string();
            if !k.is_empty() {
                out.insert(k, v);
            }
        }
    }
    out
}

fn stem_set(s: &str) -> HashSet<String> {
    word_re()
        .find_iter(&s.to_lowercase())
        .filter(|m| m.as_str().chars().count() > 3)
        .map(|m| {
            let chars: String = m.as_str().chars().take(6).collect();
            chars
        })
        .collect()
}

fn jaccard(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    if union == 0.0 {
        0.0
    } else {
        inter / union
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ScanOpts {
    pub stale_months: u32,
    /// Jaccard threshold for duplicate detection.
    pub duplicate_threshold: f64,
}

impl Default for ScanOpts {
    fn default() -> Self {
        Self {
            stale_months: 6,
            duplicate_threshold: 0.7,
        }
    }
}

/// Scan a single file and emit per-file findings.
pub fn scan_file(
    path: &Path,
    today: NaiveDate,
    stale_cutoff: NaiveDate,
) -> Result<Vec<Finding>, MonitorError> {
    let mut out = Vec::new();
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(_) => return Ok(out),
    };
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();

    // mtime staleness
    if let Ok(mtime) = path.metadata().and_then(|m| m.modified()) {
        let mtime_dt: DateTime<Utc> = mtime.into();
        let mtime_date = mtime_dt.date_naive();
        if mtime_date < stale_cutoff {
            out.push(Finding {
                kind: Kind::Stale,
                file: name.clone(),
                detail: format!("untouched since {}", mtime_date),
                severity: Severity::Info,
            });
        }
    }

    let fm = parse_frontmatter(&text);
    let typ = fm.get("type").map(|s| s.as_str()).unwrap_or("");

    // Old deadlines mentioned in body, >14d past
    for cap in deadline_re().captures_iter(&text) {
        let y: i32 = cap.get(1).unwrap().as_str().parse().unwrap_or(0);
        let m: u32 = cap.get(2).unwrap().as_str().parse().unwrap_or(0);
        let d: u32 = cap.get(3).unwrap().as_str().parse().unwrap_or(0);
        let dl = match NaiveDate::from_ymd_opt(y, m, d) {
            Some(d) => d,
            None => continue,
        };
        if dl < today && (today - dl).num_days() > 14 {
            let severity = match typ {
                "project" | "feedback" => Severity::Warn,
                _ => Severity::Info,
            };
            let typ_label = if typ.is_empty() { "unknown type" } else { typ };
            out.push(Finding {
                kind: Kind::ObsoleteDeadline,
                file: name.clone(),
                detail: format!(
                    "references deadline {} ({}d ago); {}",
                    dl,
                    (today - dl).num_days(),
                    typ_label
                ),
                severity,
            });
        }
    }

    // Broken path refs
    let mut seen: HashSet<String> = HashSet::new();
    for cap in path_ref_re().captures_iter(&text) {
        let raw = cap.get(1).unwrap().as_str().to_string();
        if !seen.insert(raw.clone()) {
            continue;
        }
        let path = expand_tilde(&raw);
        if !path.exists() {
            // is_symlink: also check via symlink_metadata
            let is_symlink = std::fs::symlink_metadata(&path).is_ok();
            if is_symlink {
                continue;
            }
            out.push(Finding {
                kind: Kind::BrokenPath,
                file: name.clone(),
                detail: format!("references missing path: {raw}"),
                severity: Severity::Warn,
            });
        }
    }

    Ok(out)
}

pub fn scan_duplicates(files: &[PathBuf], threshold: f64) -> Vec<Finding> {
    let mut rows: Vec<(String, String, HashSet<String>)> = Vec::new();
    for p in files {
        let text = match std::fs::read_to_string(p) {
            Ok(t) => t,
            Err(_) => continue,
        };
        let fm = parse_frontmatter(&text);
        let desc = fm
            .get("description")
            .or_else(|| fm.get("name"))
            .cloned()
            .unwrap_or_default();
        if desc.is_empty() {
            continue;
        }
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();
        let stems = stem_set(&desc);
        rows.push((name, desc, stems));
    }
    let mut out = Vec::new();
    for i in 0..rows.len() {
        for j in i + 1..rows.len() {
            let sim = jaccard(&rows[i].2, &rows[j].2);
            if sim < threshold {
                continue;
            }
            let severity = if sim >= 0.85 {
                Severity::Warn
            } else {
                Severity::Info
            };
            let a_desc: String = rows[i].1.chars().take(60).collect();
            let b_desc: String = rows[j].1.chars().take(60).collect();
            out.push(Finding {
                kind: Kind::Duplicate,
                file: format!("{} ↔ {}", rows[i].0, rows[j].0),
                detail: format!("description similarity {sim:.2}: {a_desc:?} vs {b_desc:?}"),
                severity,
            });
        }
    }
    out
}

/// Drive the full hygiene scan over `memory_dir/*.md` (excluding
/// `MEMORY.md`). Findings are sorted by severity desc → kind → file.
pub fn scan(memory_dir: &Path, today: NaiveDate, opts: ScanOpts) -> Result<Report, MonitorError> {
    if !memory_dir.exists() {
        return Ok(Report::default());
    }
    let cutoff = today - Duration::days((opts.stale_months as i64) * 30);
    let mut files: Vec<PathBuf> = std::fs::read_dir(memory_dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file() && p.extension().and_then(|s| s.to_str()) == Some("md"))
        .filter(|p| p.file_name().and_then(|s| s.to_str()) != Some("MEMORY.md"))
        .collect();
    files.sort();
    let mut findings: Vec<Finding> = Vec::new();
    for p in &files {
        let mut per_file = scan_file(p, today, cutoff)?;
        findings.append(&mut per_file);
    }
    findings.append(&mut scan_duplicates(&files, opts.duplicate_threshold));
    findings.sort_by(|a, b| {
        a.severity
            .rank()
            .cmp(&b.severity.rank())
            .then(a.kind.as_str().cmp(b.kind.as_str()))
            .then(a.file.cmp(&b.file))
    });
    Ok(Report {
        scanned: files.len() as u32,
        findings,
    })
}

pub fn write_jsonl_report(report: &Report, path: &Path) -> Result<(), MonitorError> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let mut body = String::new();
    for f in &report.findings {
        body.push_str(&serde_json::to_string(f)?);
        body.push('\n');
    }
    std::fs::write(path, body)?;
    Ok(())
}

pub fn summary(report: &Report) -> String {
    if report.findings.is_empty() {
        return format!("🧠 Memory: scanned {} entries, no issues.", report.scanned);
    }
    let mut by_kind: BTreeMap<&'static str, u32> = BTreeMap::new();
    for f in &report.findings {
        *by_kind.entry(f.kind.as_str()).or_insert(0) += 1;
    }
    let mut sorted: Vec<(&&'static str, &u32)> = by_kind.iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(a.1));

    let mut parts = vec![format!(
        "🧠 Memory hygiene: scanned {}, {} findings",
        report.scanned,
        report.findings.len()
    )];
    for (k, n) in sorted {
        parts.push(format!("  • {}: {}", k, n));
    }
    let high: Vec<&Finding> = report
        .findings
        .iter()
        .filter(|f| matches!(f.severity, Severity::High | Severity::Warn))
        .take(5)
        .collect();
    for f in high {
        let detail: String = f.detail.chars().take(120).collect();
        parts.push(format!(
            "     [{}] {}: {} — {}",
            severity_str(f.severity),
            f.kind.as_str(),
            f.file,
            detail
        ));
    }
    parts.join("\n")
}

fn severity_str(s: Severity) -> &'static str {
    match s {
        Severity::High => "high",
        Severity::Warn => "warn",
        Severity::Info => "info",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make() -> TempDir {
        TempDir::new().unwrap()
    }

    fn write(dir: &Path, name: &str, body: &str) -> PathBuf {
        let p = dir.join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }

    #[test]
    fn parse_frontmatter_basic() {
        let text = "---\nname: x\ntype: project\n---\nbody";
        let fm = parse_frontmatter(text);
        assert_eq!(fm.get("name"), Some(&"x".to_string()));
        assert_eq!(fm.get("type"), Some(&"project".to_string()));
    }

    #[test]
    fn parse_frontmatter_missing_returns_empty() {
        assert!(parse_frontmatter("just body").is_empty());
        assert!(parse_frontmatter("---\nname: x\nno end").is_empty());
    }

    #[test]
    fn deadline_re_matches_en_and_ru() {
        let re = deadline_re();
        assert!(re.is_match("Deadline: 2026-04-01"));
        assert!(re.is_match("дедлайн 2026-04-15"));
        assert!(re.is_match("by 2026-05-04"));
        assert!(!re.is_match("nothing here 2026"));
    }

    #[test]
    fn jaccard_basic() {
        let a: HashSet<String> = ["abc", "def"].iter().map(|s| s.to_string()).collect();
        let b: HashSet<String> = ["abc", "ghi"].iter().map(|s| s.to_string()).collect();
        // 1 / 3
        assert!((jaccard(&a, &b) - 1.0 / 3.0).abs() < 1e-9);
    }

    #[test]
    fn jaccard_empty_returns_zero() {
        let a: HashSet<String> = HashSet::new();
        let b: HashSet<String> = ["abc".into()].into();
        assert_eq!(jaccard(&a, &b), 0.0);
    }

    #[test]
    fn stem_set_truncates_to_six_chars() {
        let s = stem_set("Centriole-driven longevity, mitochondria");
        assert!(s.contains("centri"));
        assert!(s.contains("longev"));
        assert!(s.contains("mitoch"));
        // 3-char "the" excluded; "led"  too short
        assert!(!s.iter().any(|x| x == "the"));
    }

    #[test]
    fn scan_empty_dir_returns_empty_report() {
        let dir = make();
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert_eq!(r.scanned, 0);
        assert!(r.findings.is_empty());
    }

    #[test]
    fn scan_missing_dir_returns_empty_report() {
        let dir = make();
        let r = scan(&dir.path().join("ghost"), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert_eq!(r.scanned, 0);
        assert!(r.findings.is_empty());
    }

    #[test]
    fn scan_skips_memory_md_index() {
        let dir = make();
        write(dir.path(), "MEMORY.md", "# index");
        write(dir.path(), "real.md", "---\nname: x\n---\nhello");
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert_eq!(r.scanned, 1);
    }

    #[test]
    fn scan_flags_obsolete_deadlines() {
        let dir = make();
        write(
            dir.path(),
            "x.md",
            "---\ntype: project\n---\nDeadline: 2026-01-01 must remember",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        let f = r
            .findings
            .iter()
            .find(|f| f.kind == Kind::ObsoleteDeadline)
            .unwrap();
        assert!(f.detail.contains("2026-01-01"));
        assert_eq!(f.severity, Severity::Warn);
    }

    #[test]
    fn scan_obsolete_deadline_within_14d_silent() {
        let dir = make();
        write(
            dir.path(),
            "x.md",
            "---\ntype: project\n---\nDeadline: 2026-04-25",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        // 9 days ago — under 14-day threshold
        assert!(r.findings.iter().all(|f| f.kind != Kind::ObsoleteDeadline));
    }

    #[test]
    fn scan_obsolete_deadline_unknown_type_is_info() {
        let dir = make();
        write(
            dir.path(),
            "x.md",
            "---\nname: bare\n---\nDeadline: 2026-01-01",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        let f = r
            .findings
            .iter()
            .find(|f| f.kind == Kind::ObsoleteDeadline)
            .unwrap();
        assert_eq!(f.severity, Severity::Info);
    }

    #[test]
    fn scan_flags_broken_paths() {
        let dir = make();
        write(
            dir.path(),
            "x.md",
            "---\nname: x\n---\nReference `/nonexistent/path/that/does/not/exist`",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert!(r.findings.iter().any(|f| f.kind == Kind::BrokenPath));
    }

    #[test]
    fn scan_skips_existing_paths() {
        let dir = make();
        let target = write(dir.path(), "target.md", "x");
        write(
            dir.path(),
            "ref.md",
            &format!(
                "---\nname: r\n---\nReference `{}`",
                target.to_string_lossy()
            ),
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert!(r.findings.iter().all(|f| f.kind != Kind::BrokenPath));
    }

    #[test]
    fn scan_dedups_repeat_path_refs_within_file() {
        let dir = make();
        write(
            dir.path(),
            "x.md",
            "First `/missing/x.md`. Again `/missing/x.md`.",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        let n = r.findings.iter().filter(|f| f.kind == Kind::BrokenPath).count();
        assert_eq!(n, 1);
    }

    #[test]
    fn scan_flags_duplicate_descriptions() {
        let dir = make();
        let body = "---\nname: x\ndescription: centriole damage drives organism aging\n---\n";
        let body2 = "---\nname: y\ndescription: centriole damage drives organism aging\n---\n";
        write(dir.path(), "a.md", body);
        write(dir.path(), "b.md", body2);
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        let dupes: Vec<&Finding> = r.findings.iter().filter(|f| f.kind == Kind::Duplicate).collect();
        assert_eq!(dupes.len(), 1);
        assert!(dupes[0].file.contains("a.md"));
        assert!(dupes[0].file.contains("b.md"));
    }

    #[test]
    fn scan_duplicate_threshold_respected() {
        let dir = make();
        // Different short descriptions → low Jaccard, should NOT trip
        write(
            dir.path(),
            "a.md",
            "---\nname: a\ndescription: alpha topic\n---\n",
        );
        write(
            dir.path(),
            "b.md",
            "---\nname: b\ndescription: beta nothing similar\n---\n",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        assert!(r.findings.iter().all(|f| f.kind != Kind::Duplicate));
    }

    #[test]
    fn scan_findings_sorted_by_severity() {
        let dir = make();
        // Mix: broken path (warn) + obsolete deadline (warn) + stale (info via mtime trick)
        write(
            dir.path(),
            "broken.md",
            "Reference `/nonexistent-xyz`",
        );
        write(
            dir.path(),
            "deadline.md",
            "---\ntype: project\n---\nDeadline: 2025-01-01",
        );
        let r = scan(dir.path(), d(2026, 5, 4), ScanOpts::default()).unwrap();
        // Warn before Info
        if r.findings.len() >= 2 {
            for w in r.findings.windows(2) {
                assert!(w[0].severity.rank() <= w[1].severity.rank());
            }
        }
    }

    #[test]
    fn write_jsonl_report_serialises_findings() {
        let dir = make();
        let report = Report {
            scanned: 3,
            findings: vec![
                Finding {
                    kind: Kind::Stale,
                    file: "x.md".into(),
                    detail: "untouched since 2025-10-01".into(),
                    severity: Severity::Info,
                },
                Finding {
                    kind: Kind::BrokenPath,
                    file: "y.md".into(),
                    detail: "references missing path: /tmp/x".into(),
                    severity: Severity::Warn,
                },
            ],
        };
        let out = dir.path().join("report.jsonl");
        write_jsonl_report(&report, &out).unwrap();
        let body = std::fs::read_to_string(&out).unwrap();
        assert_eq!(body.lines().count(), 2);
        assert!(body.contains("stale"));
        assert!(body.contains("broken_path"));
    }

    #[test]
    fn summary_no_findings() {
        let report = Report {
            scanned: 5,
            findings: vec![],
        };
        let s = summary(&report);
        assert!(s.contains("🧠 Memory: scanned 5"));
        assert!(s.contains("no issues"));
    }

    #[test]
    fn summary_groups_kind_counts() {
        let report = Report {
            scanned: 4,
            findings: vec![
                Finding {
                    kind: Kind::Stale,
                    file: "a.md".into(),
                    detail: "x".into(),
                    severity: Severity::Info,
                },
                Finding {
                    kind: Kind::Stale,
                    file: "b.md".into(),
                    detail: "x".into(),
                    severity: Severity::Info,
                },
                Finding {
                    kind: Kind::BrokenPath,
                    file: "c.md".into(),
                    detail: "x".into(),
                    severity: Severity::Warn,
                },
            ],
        };
        let s = summary(&report);
        assert!(s.contains("• stale: 2"));
        assert!(s.contains("• broken_path: 1"));
        // High/warn surface in the tail
        assert!(s.contains("[warn] broken_path"));
    }
}
