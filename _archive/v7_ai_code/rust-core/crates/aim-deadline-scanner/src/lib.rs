//! aim-deadline-scanner — P2 calendar-aware deadline scanner.
//!
//! Walk memory & project core markdown for YYYY-MM-DD dates, filter
//! out historical events (lines containing past-tense markers, table
//! rows, headings, metadata fields, blockquotes, ✅/✔ done prefixes),
//! classify by horizon (overdue / today / this_week / this_month /
//! later).
//!
//! Rust port of `agents/deadline_scanner.py`. Project YAML and
//! Calendar adapters from the Python predecessor are kept as caller
//! plug-ins (see [`scan_all_with`]).

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Kind {
    Milestone,
    Memory,
    Calendar,
}

impl Kind {
    fn weight(&self) -> u8 {
        match self {
            Kind::Milestone => 0,
            Kind::Calendar => 1,
            Kind::Memory => 2,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Criticality {
    Low,
    Medium,
    High,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Deadline {
    pub when: NaiveDate,
    pub label: String,
    pub source: String,
    pub kind: Kind,
    pub criticality: Criticality,
}

impl Deadline {
    pub fn days_from(&self, today: NaiveDate) -> i64 {
        (self.when - today).num_days()
    }
}

// ── filter helpers ──────────────────────────────────────────────

fn is_historical(line: &str) -> bool {
    use once_cell::sync::Lazy;
    use regex::{Regex, RegexBuilder};
    static HEADING: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s*#{1,6}\s+").unwrap());
    static METADATA: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(
            r"^\s*(description|name|note|status|origin\w*|type|quote|source):",
        )
        .case_insensitive(true)
        .build()
        .unwrap()
    });
    static QUOTE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s*>\s").unwrap());
    static DONE_PREFIX: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"^\s*[-*]?\s*[✅✔]\s").unwrap());
    static TABLE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s*\|.*\|\s*$").unwrap());
    static HISTORICAL: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(
            r"\b(consented|sent|submitted|fired|received|replied|approved|signed|published|merged|closed|deployed|completed|done|notified|delivered|invited|confirmed|reversed|reconciled|deferred|established|supersedes|effective|подал|отправлен|подписан|подтверждено|опубликован|завершено|выполнено|отменено|установлено|подтвердил|закрыта|закрыт|закрыто)\b",
        )
        .case_insensitive(true)
        .build()
        .unwrap()
    });

    HEADING.is_match(line)
        || METADATA.is_match(line)
        || QUOTE.is_match(line)
        || DONE_PREFIX.is_match(line)
        || TABLE.is_match(line)
        || HISTORICAL.is_match(line)
}

// ── extraction ──────────────────────────────────────────────────

pub fn extract_deadlines_from_text(text: &str, source: &str) -> Vec<Deadline> {
    use once_cell::sync::Lazy;
    use regex::{Regex, RegexBuilder};
    static DATE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r"\b((?:19|20|21)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b",
        )
        .unwrap()
    });
    static DEADLINE_LINE_RE: Lazy<Regex> = Lazy::new(|| {
        RegexBuilder::new(
            r"(?:deadline|due|by|до|дедлайн)[\s:*\-]*((?:19|20|21)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])",
        )
        .case_insensitive(true)
        .build()
        .unwrap()
    });

    let mut out: Vec<Deadline> = Vec::new();
    let mut seen: BTreeSet<(NaiveDate, String)> = BTreeSet::new();

    for line in text.lines() {
        let trimmed = line.trim();
        let label: String = trimmed.chars().take(160).collect();

        // 1) Strong "deadline: YYYY-MM-DD" markers always count, even
        //    on a "historical-looking" line.
        let mut deadline_dates: BTreeSet<NaiveDate> = BTreeSet::new();
        for cap in DEADLINE_LINE_RE.captures_iter(line) {
            if let Some(d) = parse_ymd(&cap[1], &cap[2], &cap[3]) {
                let prefix: String = label.chars().take(60).collect();
                if seen.insert((d, prefix)) {
                    deadline_dates.insert(d);
                    out.push(Deadline {
                        when: d,
                        label: label.clone(),
                        source: source.to_string(),
                        kind: Kind::Memory,
                        criticality: Criticality::High,
                    });
                }
            }
        }

        // 2) Plain ISO dates only fire when the line looks future-actionable.
        if is_historical(line) {
            continue;
        }
        for cap in DATE_RE.captures_iter(line) {
            if let Some(d) = parse_ymd(&cap[1], &cap[2], &cap[3]) {
                if deadline_dates.contains(&d) {
                    continue;
                }
                let prefix: String = label.chars().take(60).collect();
                if seen.insert((d, prefix)) {
                    out.push(Deadline {
                        when: d,
                        label: label.clone(),
                        source: source.to_string(),
                        kind: Kind::Memory,
                        criticality: Criticality::Medium,
                    });
                }
            }
        }
    }
    out
}

fn parse_ymd(y: &str, m: &str, d: &str) -> Option<NaiveDate> {
    let y = y.parse::<i32>().ok()?;
    let m = m.parse::<u32>().ok()?;
    let d = d.parse::<u32>().ok()?;
    NaiveDate::from_ymd_opt(y, m, d)
}

// ── memory file enumeration ─────────────────────────────────────

pub fn memory_files(home: &Path) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();
    let mem = home
        .join(".claude")
        .join("projects")
        .join("-home-oem")
        .join("memory");
    if mem.exists() {
        if let Ok(rd) = std::fs::read_dir(&mem) {
            for entry in rd.flatten() {
                let n = entry.file_name();
                let s = n.to_string_lossy();
                if (s.starts_with("project_") || s.starts_with("fact_")) && s.ends_with(".md") {
                    out.push(entry.path());
                }
            }
        }
    }
    let desktop = home.join("Desktop");
    if desktop.exists() {
        if let Ok(rd) = std::fs::read_dir(&desktop) {
            for entry in rd.flatten() {
                let p = entry.path();
                if !p.is_dir() {
                    continue;
                }
                let n = entry.file_name();
                if n.to_string_lossy().starts_with('.') {
                    continue;
                }
                for fname in [
                    "TODO.md",
                    "REMINDER.md",
                    "NEEDTOWRITE.md",
                    "CONCEPT.md",
                    "STATE.md",
                ] {
                    let candidate = p.join(fname);
                    if candidate.exists() {
                        out.push(candidate);
                    }
                }
            }
        }
    }
    out
}

// ── public scan functions ──────────────────────────────────────

#[derive(Debug, Clone, Copy)]
pub struct ScanOpts {
    pub horizon_back: i64,
    pub horizon_fwd: i64,
}

impl Default for ScanOpts {
    fn default() -> Self {
        Self {
            horizon_back: 30,
            horizon_fwd: 365,
        }
    }
}

pub fn scan_memory_dir(today: NaiveDate, files: &[PathBuf], opts: &ScanOpts) -> Vec<Deadline> {
    let mut out: Vec<Deadline> = Vec::new();
    for p in files {
        let Ok(text) = std::fs::read_to_string(p) else {
            continue;
        };
        for d in extract_deadlines_from_text(&text, &p.display().to_string()) {
            let delta = d.days_from(today);
            if delta < -opts.horizon_back || delta > opts.horizon_fwd {
                continue;
            }
            // Past-due "high" demoted to medium.
            if delta < 0 && matches!(d.criticality, Criticality::High) {
                let mut cloned = d.clone();
                cloned.criticality = Criticality::Medium;
                out.push(cloned);
            } else {
                out.push(d);
            }
        }
    }
    out
}

pub fn scan_memory(today: NaiveDate, opts: &ScanOpts) -> Vec<Deadline> {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let files = memory_files(&home);
    scan_memory_dir(today, &files, opts)
}

/// Aggregate all sources. The yaml + calendar collectors are caller
/// plug-ins so this crate stays decoupled from project_owner / gcal.
pub fn scan_all_with(
    today: NaiveDate,
    extra: &[Deadline],
    files: &[PathBuf],
) -> Vec<Deadline> {
    let mut out: Vec<Deadline> = Vec::new();
    out.extend(extra.iter().cloned());
    out.extend(scan_memory_dir(today, files, &ScanOpts::default()));
    // de-dupe by (date, label[:80]); prefer milestone over calendar over memory
    let mut seen: BTreeMap<(NaiveDate, String), Deadline> = BTreeMap::new();
    let mut sorted = out;
    sorted.sort_by_key(|d| (d.when, d.kind.weight()));
    for d in sorted {
        let key = (
            d.when,
            d.label.chars().take(80).collect::<String>().to_lowercase(),
        );
        seen.entry(key).or_insert(d);
    }
    let mut result: Vec<Deadline> = seen.into_values().collect();
    result.sort_by_key(|d| d.when);
    result
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Buckets {
    pub overdue: Vec<Deadline>,
    pub today: Vec<Deadline>,
    pub this_week: Vec<Deadline>,
    pub this_month: Vec<Deadline>,
    pub later: Vec<Deadline>,
}

pub fn by_horizon(deadlines: &[Deadline], today: NaiveDate) -> Buckets {
    let mut b = Buckets::default();
    for d in deadlines {
        let delta = d.days_from(today);
        if delta < 0 {
            b.overdue.push(d.clone());
        } else if delta == 0 {
            b.today.push(d.clone());
        } else if delta <= 7 {
            b.this_week.push(d.clone());
        } else if delta <= 30 {
            b.this_month.push(d.clone());
        } else {
            b.later.push(d.clone());
        }
    }
    b
}

/// Days with ≥`min_critical_per_day` deadlines within `window_days` of `today`.
pub fn conflicts(
    deadlines: &[Deadline],
    today: NaiveDate,
    window_days: i64,
    min_critical_per_day: usize,
) -> Vec<(NaiveDate, Vec<Deadline>)> {
    let mut by_date: BTreeMap<NaiveDate, Vec<Deadline>> = BTreeMap::new();
    for d in deadlines {
        let delta = d.days_from(today);
        if delta < 0 || delta > window_days {
            continue;
        }
        by_date.entry(d.when).or_default().push(d.clone());
    }
    by_date
        .into_iter()
        .filter(|(_, v)| v.len() >= min_critical_per_day)
        .collect()
}

pub fn summary(deadlines: &[Deadline], today: NaiveDate) -> String {
    let b = by_horizon(deadlines, today);
    let mut out: Vec<String> = vec![format!(
        "Deadlines as of {} (total {}):",
        today,
        deadlines.len()
    )];
    let sections: [(&str, &Vec<Deadline>, bool); 4] = [
        ("⛔ overdue", &b.overdue, true),
        ("📍 today", &b.today, true),
        ("📅 this week", &b.this_week, true),
        ("🗓  this month", &b.this_month, false),
    ];
    for (header, items, always) in sections {
        if items.is_empty() && !always {
            continue;
        }
        out.push(String::new());
        out.push(format!("{} ({})", header, items.len()));
        for d in items.iter().take(8) {
            let delta = d.days_from(today);
            let tag = if delta < 0 {
                format!("{}d ago", delta.unsigned_abs())
            } else if delta == 0 {
                "today".to_string()
            } else {
                format!("+{}d", delta)
            };
            let label: String = d.label.chars().take(120).collect();
            let kind = match d.kind {
                Kind::Milestone => "milestone",
                Kind::Memory => "memory",
                Kind::Calendar => "calendar",
            };
            out.push(format!("  • {} ({})  {}  [{}]", d.when, tag, label, kind));
        }
    }
    if deadlines.is_empty() {
        out.push("(no deadlines on the radar)".into());
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Datelike, NaiveDate};

    fn date(y: i32, m: u32, d: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, d).unwrap()
    }

    #[test]
    fn extract_simple_iso_date() {
        let ds = extract_deadlines_from_text("Submit by 2026-10-28.", "x.md");
        assert_eq!(ds.len(), 1);
        assert_eq!(ds[0].when, date(2026, 10, 28));
        assert_eq!(ds[0].kind, Kind::Memory);
        // Has "by" deadline marker → high
        assert_eq!(ds[0].criticality, Criticality::High);
    }

    #[test]
    fn extract_plain_date_medium_criticality() {
        let ds = extract_deadlines_from_text("planning sprint 2026-10-28", "x.md");
        assert_eq!(ds.len(), 1);
        assert_eq!(ds[0].criticality, Criticality::Medium);
    }

    #[test]
    fn historical_lines_skipped() {
        let ds = extract_deadlines_from_text("✅ submitted on 2026-04-01", "x.md");
        assert!(ds.is_empty());
        let ds = extract_deadlines_from_text("> quote 2026-05-01 reference", "x.md");
        assert!(ds.is_empty());
        let ds = extract_deadlines_from_text("# Heading 2026-05-01", "x.md");
        assert!(ds.is_empty());
    }

    #[test]
    fn deadline_marker_overrides_historical_filter() {
        // Even a table-cell-looking line with "deadline:" still counts
        let ds = extract_deadlines_from_text("| description: deadline: 2026-10-28 |", "x.md");
        assert_eq!(ds.len(), 1, "deadline marker should win over table-row filter");
    }

    #[test]
    fn historical_keyword_filters_plain_date() {
        let ds = extract_deadlines_from_text("submitted 2026-04-01 by team", "x.md");
        assert!(ds.is_empty());
    }

    #[test]
    fn dedup_same_date_same_line() {
        let ds = extract_deadlines_from_text("plan 2026-10-28 sprint 2026-10-28 again", "x.md");
        assert_eq!(ds.len(), 1);
    }

    #[test]
    fn parse_ymd_rejects_invalid_dates() {
        assert!(parse_ymd("2026", "13", "01").is_none());
        assert!(parse_ymd("2026", "02", "30").is_none());
        assert!(parse_ymd("not", "01", "01").is_none());
    }

    #[test]
    fn date_year_range_only_19_to_21xx() {
        let ds = extract_deadlines_from_text("phone 1234-56-78 plan 2026-10-28", "x.md");
        assert_eq!(ds.len(), 1);
        assert_eq!(ds[0].when, date(2026, 10, 28));
    }

    #[test]
    fn scan_memory_dir_demotes_overdue_high() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("note.md");
        std::fs::write(&p, "Submit by 2026-01-01.\n").unwrap();
        // 14 days past — within horizon_back=30
        let today = date(2026, 1, 15);
        let res = scan_memory_dir(today, &[p], &ScanOpts::default());
        assert!(!res.is_empty(), "horizon=30 should keep a 14d-overdue date");
        assert_eq!(res[0].criticality, Criticality::Medium);
    }

    #[test]
    fn scan_memory_dir_horizon_filter() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("note.md");
        std::fs::write(&p, "very far 2099-01-01\n").unwrap();
        let today = date(2026, 5, 4);
        let res = scan_memory_dir(today, &[p], &ScanOpts::default());
        assert!(res.is_empty());
    }

    #[test]
    fn by_horizon_buckets() {
        let today = date(2026, 5, 4);
        let make = |y, m, d| Deadline {
            when: date(y, m, d),
            label: "x".into(),
            source: "s".into(),
            kind: Kind::Memory,
            criticality: Criticality::Medium,
        };
        let ds = vec![
            make(2026, 4, 30), // overdue
            make(2026, 5, 4),  // today
            make(2026, 5, 6),  // this week
            make(2026, 5, 20), // this month
            make(2027, 1, 1),  // later
        ];
        let b = by_horizon(&ds, today);
        assert_eq!(b.overdue.len(), 1);
        assert_eq!(b.today.len(), 1);
        assert_eq!(b.this_week.len(), 1);
        assert_eq!(b.this_month.len(), 1);
        assert_eq!(b.later.len(), 1);
    }

    #[test]
    fn conflicts_finds_crowded_days() {
        let today = date(2026, 5, 4);
        let make = |day, label: &str| Deadline {
            when: date(2026, 5, day),
            label: label.into(),
            source: "s".into(),
            kind: Kind::Memory,
            criticality: Criticality::Medium,
        };
        let ds = vec![make(5, "a"), make(5, "b"), make(6, "c")];
        let c = conflicts(&ds, today, 7, 2);
        assert_eq!(c.len(), 1);
        assert_eq!(c[0].0, date(2026, 5, 5));
    }

    #[test]
    fn summary_empty_message() {
        let s = summary(&[], date(2026, 5, 4));
        assert!(s.contains("(no deadlines on the radar)"));
    }

    #[test]
    fn summary_renders_buckets() {
        let today = date(2026, 5, 4);
        let ds = vec![Deadline {
            when: date(2026, 5, 5),
            label: "test".into(),
            source: "s".into(),
            kind: Kind::Memory,
            criticality: Criticality::High,
        }];
        let s = summary(&ds, today);
        assert!(s.contains("📅 this week"));
        assert!(s.contains("test"));
        assert!(s.contains("memory"));
    }

    #[test]
    fn scan_all_dedupes_same_date_same_label() {
        let today = date(2026, 5, 4);
        let extra = vec![
            Deadline {
                when: date(2026, 5, 10),
                label: "Same label".into(),
                source: "yaml:p".into(),
                kind: Kind::Milestone,
                criticality: Criticality::High,
            },
            Deadline {
                when: date(2026, 5, 10),
                label: "Same label".into(),
                source: "memory.md".into(),
                kind: Kind::Memory,
                criticality: Criticality::Medium,
            },
        ];
        let res = scan_all_with(today, &extra, &[]);
        assert_eq!(res.len(), 1, "duplicates collapsed");
        assert_eq!(res[0].kind, Kind::Milestone, "milestone wins over memory");
    }

    #[test]
    fn label_truncated_to_160() {
        let long: String = "x".repeat(500);
        let text = format!("{long} 2026-10-28 plan");
        let ds = extract_deadlines_from_text(&text, "x.md");
        assert_eq!(ds.len(), 1);
        assert_eq!(ds[0].label.chars().count(), 160);
    }

    #[allow(dead_code)]
    fn ensure_datelike_used() {
        // suppress warning about unused chrono::Datelike trait import
        let _ = NaiveDate::from_ymd_opt(2026, 1, 1).unwrap().year();
    }
}
