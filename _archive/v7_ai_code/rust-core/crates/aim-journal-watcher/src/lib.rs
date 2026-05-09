//! aim-journal-watcher — NDJSON experiment journal poller (Phase B, 2026-05-06).
//!
//! AutomatedMicroscopy / E0 Claude-Code workers append events to
//! `~/.cache/aim/microscopy/sessions/<run_id>.ndjson` (one JSON object
//! per line). This crate scans those files, parses the latest events,
//! and computes uptime / decisions-per-hour / contamination counters
//! that `aim-experiment-owner` uses for KPI tracking and morning_brief.
//!
//! Pure-stdlib polling — no inotify dependency. Run from `serve_daemon`
//! tick (every minute) is enough; events are append-only so re-reading
//! is cheap.
//!
//! Expected event shape (loose; we parse what's present):
//! ```json
//! {"ts":"2026-05-06T22:14:00Z","kind":"decision","detail":"adjust_focus","outcome":"ok"}
//! {"ts":"2026-05-06T22:15:00Z","kind":"observation","detail":"contamination_suspected"}
//! {"ts":"2026-05-06T22:16:00Z","kind":"alert","detail":"interlock_tripped"}
//! ```

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum JournalError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub ts: DateTime<Utc>,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub outcome: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Stats {
    pub n_events: usize,
    pub n_decisions: usize,
    pub n_alerts: usize,
    pub n_contaminations: usize,
    pub first_ts: Option<DateTime<Utc>>,
    pub last_ts: Option<DateTime<Utc>>,
}

impl Stats {
    pub fn span_hours(&self) -> Option<f64> {
        match (self.first_ts, self.last_ts) {
            (Some(a), Some(b)) if b > a => {
                Some((b - a).num_seconds() as f64 / 3600.0)
            }
            _ => None,
        }
    }

    pub fn decisions_per_hour(&self) -> Option<f64> {
        let h = self.span_hours()?;
        if h <= 0.0 {
            return None;
        }
        Some(self.n_decisions as f64 / h)
    }
}

/// Read every `.ndjson` file under `root` and aggregate stats.
/// Files older than `older_than_hours` are skipped.
pub fn scan(root: &Path, older_than_hours: Option<i64>) -> Result<Stats, JournalError> {
    let mut stats = Stats::default();
    if !root.exists() {
        return Ok(stats);
    }
    let cutoff = older_than_hours.map(|h| Utc::now() - chrono::Duration::hours(h));
    for entry in std::fs::read_dir(root)?.flatten() {
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) != Some("ndjson") {
            continue;
        }
        let raw = match std::fs::read_to_string(&p) {
            Ok(s) => s,
            Err(_) => continue,
        };
        for line in raw.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let ev: Event = match serde_json::from_str(line) {
                Ok(e) => e,
                Err(_) => continue,
            };
            if let Some(c) = cutoff {
                if ev.ts < c {
                    continue;
                }
            }
            stats.n_events += 1;
            match ev.kind.as_str() {
                "decision" => stats.n_decisions += 1,
                "alert" => stats.n_alerts += 1,
                _ => {}
            }
            if ev.detail.contains("contamination") {
                stats.n_contaminations += 1;
            }
            if stats.first_ts.is_none() || stats.first_ts.map(|t| ev.ts < t).unwrap_or(false)
            {
                stats.first_ts = Some(ev.ts);
            }
            if stats.last_ts.map(|t| ev.ts > t).unwrap_or(true) {
                stats.last_ts = Some(ev.ts);
            }
        }
    }
    Ok(stats)
}

/// Default journal path: `$AIM_HOME/microscopy/sessions/`.
pub fn default_journal_root() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("microscopy").join("sessions")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn write_jsonl(dir: &Path, name: &str, lines: &[&str]) {
        std::fs::write(dir.join(name), lines.join("\n") + "\n").unwrap();
    }

    #[test]
    fn empty_root_returns_zero_stats() {
        let tmp = TempDir::new().unwrap();
        let s = scan(tmp.path(), None).unwrap();
        assert_eq!(s.n_events, 0);
    }

    #[test]
    fn missing_root_does_not_error() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("ghost");
        let s = scan(&p, None).unwrap();
        assert_eq!(s.n_events, 0);
    }

    #[test]
    fn counts_decisions_and_alerts() {
        let tmp = TempDir::new().unwrap();
        write_jsonl(tmp.path(), "run.ndjson", &[
            r#"{"ts":"2026-05-06T10:00:00Z","kind":"decision","detail":"focus","outcome":"ok"}"#,
            r#"{"ts":"2026-05-06T10:30:00Z","kind":"decision","detail":"channel_switch"}"#,
            r#"{"ts":"2026-05-06T11:00:00Z","kind":"alert","detail":"interlock_tripped"}"#,
            r#"{"ts":"2026-05-06T12:00:00Z","kind":"observation","detail":"contamination_suspected"}"#,
        ]);
        let s = scan(tmp.path(), None).unwrap();
        assert_eq!(s.n_events, 4);
        assert_eq!(s.n_decisions, 2);
        assert_eq!(s.n_alerts, 1);
        assert_eq!(s.n_contaminations, 1);
    }

    #[test]
    fn skips_non_ndjson() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("ignore.txt"), "{}").unwrap();
        let s = scan(tmp.path(), None).unwrap();
        assert_eq!(s.n_events, 0);
    }

    #[test]
    fn skips_unparseable_lines() {
        let tmp = TempDir::new().unwrap();
        write_jsonl(tmp.path(), "run.ndjson", &[
            r#"{"ts":"2026-05-06T10:00:00Z","kind":"decision"}"#,
            "not json",
            r#"{"ts":"2026-05-06T11:00:00Z","kind":"alert"}"#,
        ]);
        let s = scan(tmp.path(), None).unwrap();
        assert_eq!(s.n_events, 2);
    }

    #[test]
    fn decisions_per_hour_basic() {
        let tmp = TempDir::new().unwrap();
        // 4 decisions over 2 hours = 2.0/h
        write_jsonl(tmp.path(), "run.ndjson", &[
            r#"{"ts":"2026-05-06T10:00:00Z","kind":"decision"}"#,
            r#"{"ts":"2026-05-06T10:30:00Z","kind":"decision"}"#,
            r#"{"ts":"2026-05-06T11:00:00Z","kind":"decision"}"#,
            r#"{"ts":"2026-05-06T12:00:00Z","kind":"decision"}"#,
        ]);
        let s = scan(tmp.path(), None).unwrap();
        let dph = s.decisions_per_hour().unwrap();
        assert!((dph - 2.0).abs() < 0.01);
    }

    #[test]
    fn span_hours_none_for_single_event() {
        let tmp = TempDir::new().unwrap();
        write_jsonl(tmp.path(), "run.ndjson", &[
            r#"{"ts":"2026-05-06T10:00:00Z","kind":"decision"}"#,
        ]);
        let s = scan(tmp.path(), None).unwrap();
        // first_ts == last_ts → span_hours returns None
        assert!(s.span_hours().is_none());
    }

    #[test]
    fn cutoff_filters_old_events() {
        let tmp = TempDir::new().unwrap();
        // One ancient + one recent event
        let recent = Utc::now()
            .format("%Y-%m-%dT%H:%M:%SZ")
            .to_string();
        write_jsonl(tmp.path(), "run.ndjson", &[
            r#"{"ts":"2020-01-01T00:00:00Z","kind":"decision"}"#,
            &format!(r#"{{"ts":"{}","kind":"decision"}}"#, recent),
        ]);
        // 24h cutoff drops the 2020 event
        let s = scan(tmp.path(), Some(24)).unwrap();
        assert_eq!(s.n_decisions, 1);
    }

    #[test]
    fn first_last_ts_correct_order() {
        let tmp = TempDir::new().unwrap();
        write_jsonl(tmp.path(), "a.ndjson", &[
            r#"{"ts":"2026-05-06T12:00:00Z","kind":"decision"}"#,
        ]);
        write_jsonl(tmp.path(), "b.ndjson", &[
            r#"{"ts":"2026-05-06T10:00:00Z","kind":"decision"}"#,
            r#"{"ts":"2026-05-06T14:00:00Z","kind":"decision"}"#,
        ]);
        let s = scan(tmp.path(), None).unwrap();
        let first = s.first_ts.unwrap();
        let last = s.last_ts.unwrap();
        assert_eq!(first, Utc.with_ymd_and_hms(2026, 5, 6, 10, 0, 0).unwrap());
        assert_eq!(last, Utc.with_ymd_and_hms(2026, 5, 6, 14, 0, 0).unwrap());
    }
}
