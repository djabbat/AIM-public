//! aim-memory-date-correction — auto-correct stale TTL / expires_at fields.
//!
//! Port of `agents/memory_date_correction.py`. Walks `user_memories/`,
//! parses frontmatter, and:
//!   1. Flags `created` more than 1 day in the future.
//!   2. Notes `ttl_hours` that fail to parse as int.
//!   3. Recomputes `expires_at` when it drifts >1h from `created + ttl_hours`,
//!      or fills it in if missing.
//!   4. Notes `expires_at` already past unless `priority: CRITICAL`.
//!
//! Frontmatter is treated as ordered key/value pairs (one per line). Pure
//! YAML structures are out of scope — same as Python.

use std::path::{Path, PathBuf};

use chrono::{DateTime, Duration, Local, NaiveDate, NaiveDateTime, TimeZone};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use walkdir::WalkDir;

#[derive(Debug, Error)]
pub enum DateCorrectionError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, DateCorrectionError>;

// ── frontmatter ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedFrontmatter {
    pub fields: Vec<(String, String)>,
    pub head: String,
    pub tail_marker: String,
    pub body: String,
}

impl ParsedFrontmatter {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.fields
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }

    pub fn set(&mut self, key: &str, value: &str) {
        if let Some((_, v)) = self.fields.iter_mut().find(|(k, _)| k == key) {
            *v = value.to_string();
        } else {
            self.fields.push((key.to_string(), value.to_string()));
        }
    }

    pub fn serialize(&self) -> String {
        self.fields
            .iter()
            .map(|(k, v)| format!("{}: {}", k, v))
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn render_full(&self) -> String {
        format!(
            "{}{}{}{}",
            self.head,
            self.serialize(),
            self.tail_marker,
            self.body
        )
    }
}

/// Parse `---\n…\n---\n…body` into ordered fields.
/// Mirrors the Python `_FM_RE` regex but without the regex crate dependency.
pub fn parse_frontmatter(text: &str) -> Option<ParsedFrontmatter> {
    let rest = text.strip_prefix("---")?;
    // accept `---` followed by optional spaces and a newline
    let rest = trim_optional_inline_ws(rest);
    let rest = rest.strip_prefix('\n')?;
    let head = {
        let head_len = text.len() - rest.len();
        text[..head_len].to_string()
    };

    // find closing `---` on its own line (with optional trailing ws + newline)
    let (fm_block, tail_marker, body) = split_closing(rest)?;

    let mut fields = Vec::new();
    for line in fm_block.lines() {
        if let Some((k, v)) = line.split_once(':') {
            fields.push((k.trim().to_string(), v.trim().to_string()));
        }
    }

    Some(ParsedFrontmatter {
        fields,
        head,
        tail_marker,
        body,
    })
}

fn trim_optional_inline_ws(s: &str) -> &str {
    let mut idx = 0;
    for (i, ch) in s.char_indices() {
        if ch == ' ' || ch == '\t' {
            idx = i + ch.len_utf8();
        } else {
            return &s[idx..];
        }
    }
    &s[idx..]
}

/// Split `fm_block\n---\s*\n?body`. Returns `(fm_block, tail_marker, body)`
/// where `tail_marker` includes the leading newline so that
/// `head + fm_block + tail_marker + body` reconstructs the original.
fn split_closing(rest: &str) -> Option<(String, String, String)> {
    let mut search_from = 0;
    let bytes = rest.as_bytes();
    while let Some(pos) = rest[search_from..].find("---") {
        let abs = search_from + pos;
        // must be at start-of-line: either at idx 0 of `rest`, or preceded by `\n`
        if abs == 0 || bytes.get(abs - 1) == Some(&b'\n') {
            let after_dashes = &rest[abs + 3..];
            let after_ws = trim_optional_inline_ws(after_dashes);
            let after_nl = after_ws.strip_prefix('\n').unwrap_or(after_ws);
            let marker_end = rest.len() - after_nl.len();

            // include leading newline in tail_marker so concat round-trips
            let (fm_end, marker_start) = if abs > 0 && bytes[abs - 1] == b'\n' {
                (abs - 1, abs - 1)
            } else {
                (abs, abs)
            };
            let fm_block = rest[..fm_end].to_string();
            let tail_marker = rest[marker_start..marker_end].to_string();
            let body = after_nl.to_string();
            return Some((fm_block, tail_marker, body));
        }
        search_from = abs + 3;
    }
    None
}

// ── ISO date parsing ────────────────────────────────────────────────────────

/// Parse ISO-8601 datetime or `YYYY-MM-DD` date. Returns `None` on failure.
/// Mirrors Python `_parse_iso`.
pub fn parse_iso(s: &str) -> Option<DateTime<Local>> {
    if s.is_empty() {
        return None;
    }
    // Try with timezone offset
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return Some(dt.with_timezone(&Local));
    }
    // Try plain ISO datetime (no tz)
    for fmt in &[
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(ndt) = NaiveDateTime::parse_from_str(s, fmt) {
            return Local.from_local_datetime(&ndt).single();
        }
    }
    // Try date-only
    if let Ok(d) = NaiveDate::parse_from_str(s, "%Y-%m-%d") {
        let ndt = d.and_hms_opt(0, 0, 0)?;
        return Local.from_local_datetime(&ndt).single();
    }
    None
}

// ── audit ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AuditReport {
    pub issues: Vec<String>,
    pub changed: bool,
    pub skipped: Option<String>,
}

/// Audit one frontmatter block. Mutates `fm` in place when corrections apply
/// (caller can decide whether to write back).
pub fn audit(fm: &mut ParsedFrontmatter, now: DateTime<Local>) -> AuditReport {
    let original_fields = fm.fields.clone();
    let mut issues = Vec::new();

    let created = fm.get("created").and_then(parse_iso);
    let ttl = fm.get("ttl_hours").map(|s| s.to_string());
    let exp = fm.get("expires_at").and_then(parse_iso);

    // 1. created > now + 1d
    if let Some(c) = created {
        if c > now + Duration::days(1) {
            let raw = fm.get("created").unwrap_or("").to_string();
            issues.push(format!(
                "created in the future: {} vs now {}",
                raw,
                now.format("%Y-%m-%dT%H:%M:%S")
            ));
        }
    }

    // 2. ttl_hours numeric
    let mut ttl_int: Option<i64> = None;
    if let Some(t) = ttl.as_deref() {
        if !t.is_empty() {
            match t.parse::<i64>() {
                Ok(n) => ttl_int = Some(n),
                Err(_) => issues.push(format!("ttl_hours not int: {:?}", t)),
            }
        }
    }

    // 3. expires_at consistency
    if let (Some(c), Some(t)) = (created, ttl_int) {
        let expected = c + Duration::hours(t);
        let expected_str = expected.format("%Y-%m-%dT%H:%M:%S%:z").to_string();
        match exp {
            None => {
                fm.set("expires_at", &expected_str);
                issues.push("missing expires_at — computed from created + ttl_hours".into());
            }
            Some(e) => {
                let delta_h = (e - expected).num_seconds().abs() as f64 / 3600.0;
                if delta_h > 1.0 {
                    fm.set("expires_at", &expected_str);
                    issues.push(format!("expires_at drift {:.1}h — corrected", delta_h));
                }
            }
        }
    }

    // 4. already-expired note (no auto-fix)
    let pri = fm
        .get("priority")
        .map(|s| s.to_uppercase())
        .unwrap_or_else(|| "NORMAL".to_string());
    if let Some(e) = exp {
        // re-read after potential update
        let e2 = fm
            .get("expires_at")
            .and_then(parse_iso)
            .unwrap_or(e);
        if e2 < now && pri != "CRITICAL" {
            let raw = fm.get("expires_at").unwrap_or("").to_string();
            issues.push(format!(
                "already expired ({}); prune_expired will collect",
                raw
            ));
        }
    }

    let changed = fm.fields != original_fields;
    AuditReport {
        issues,
        changed,
        skipped: None,
    }
}

// ── walking ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DirectoryReport {
    pub checked: usize,
    pub with_issues: usize,
    pub total_issues: usize,
    pub would_rewrite: usize,
    pub rewritten: usize,
    pub files: Vec<FileReport>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FileReport {
    pub file: PathBuf,
    pub issues: Vec<String>,
    pub rewritten: bool,
}

/// Walk every `*.md` under `root`, audit + optionally rewrite.
pub fn correct_all(root: &Path, apply: bool, now: DateTime<Local>) -> Result<DirectoryReport> {
    let mut report = DirectoryReport {
        checked: 0,
        with_issues: 0,
        total_issues: 0,
        would_rewrite: 0,
        rewritten: 0,
        files: Vec::new(),
    };
    if !root.exists() {
        return Ok(report);
    }
    for entry in WalkDir::new(root).into_iter().filter_map(|e| e.ok()) {
        if !entry.file_type().is_file() {
            continue;
        }
        if entry.path().extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }
        report.checked += 1;
        let text = std::fs::read_to_string(entry.path())?;
        let Some(mut fm) = parse_frontmatter(&text) else {
            continue;
        };
        let audit_report = audit(&mut fm, now);
        if !audit_report.issues.is_empty() {
            report.with_issues += 1;
            report.total_issues += audit_report.issues.len();
        }
        if audit_report.changed {
            if apply {
                std::fs::write(entry.path(), fm.render_full())?;
                report.rewritten += 1;
            } else {
                report.would_rewrite += 1;
            }
        }
        if !audit_report.issues.is_empty() && report.files.len() < 30 {
            report.files.push(FileReport {
                file: entry.path().to_path_buf(),
                issues: audit_report.issues,
                rewritten: apply && audit_report.changed,
            });
        }
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn t(y: i32, mo: u32, d: u32, h: u32, mi: u32) -> DateTime<Local> {
        Local.with_ymd_and_hms(y, mo, d, h, mi, 0).single().unwrap()
    }

    // ── parse_frontmatter ───────────────────────────────────────────────────

    #[test]
    fn parse_simple_frontmatter() {
        let text = "---\nname: foo\nage: 7\n---\nbody here\n";
        let fm = parse_frontmatter(text).unwrap();
        assert_eq!(fm.get("name"), Some("foo"));
        assert_eq!(fm.get("age"), Some("7"));
        assert_eq!(fm.body, "body here\n");
    }

    #[test]
    fn parse_returns_none_for_missing_frontmatter() {
        assert!(parse_frontmatter("just body").is_none());
        assert!(parse_frontmatter("---\nno close\n").is_none());
    }

    #[test]
    fn parse_preserves_order() {
        let text = "---\nz: 1\na: 2\nm: 3\n---\n";
        let fm = parse_frontmatter(text).unwrap();
        assert_eq!(fm.fields[0].0, "z");
        assert_eq!(fm.fields[1].0, "a");
        assert_eq!(fm.fields[2].0, "m");
    }

    #[test]
    fn render_full_roundtrips() {
        let text = "---\nk: v\n---\nhello\n";
        let fm = parse_frontmatter(text).unwrap();
        assert_eq!(fm.render_full(), text);
    }

    #[test]
    fn set_updates_existing_key_in_place() {
        let mut fm = parse_frontmatter("---\na: 1\nb: 2\n---\n").unwrap();
        fm.set("a", "99");
        assert_eq!(fm.fields[0], ("a".into(), "99".into()));
    }

    #[test]
    fn set_appends_new_key() {
        let mut fm = parse_frontmatter("---\na: 1\n---\n").unwrap();
        fm.set("b", "2");
        assert_eq!(fm.fields.last().unwrap().0, "b");
    }

    // ── parse_iso ───────────────────────────────────────────────────────────

    #[test]
    fn parse_iso_full_datetime() {
        assert!(parse_iso("2026-05-04T21:30:00").is_some());
    }

    #[test]
    fn parse_iso_date_only() {
        assert!(parse_iso("2026-05-04").is_some());
    }

    #[test]
    fn parse_iso_with_timezone() {
        assert!(parse_iso("2026-05-04T21:30:00+04:00").is_some());
    }

    #[test]
    fn parse_iso_empty_returns_none() {
        assert!(parse_iso("").is_none());
        assert!(parse_iso("garbage").is_none());
    }

    // ── audit ───────────────────────────────────────────────────────────────

    #[test]
    fn audit_clean_file_has_no_issues() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-05-01T00:00:00\nttl_hours: 24\nexpires_at: 2026-05-02T00:00:00\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 4, 0, 0));
        // expires_at is in past, so we get the "already expired" note but no rewrite
        assert!(!r.changed);
        assert!(r.issues.iter().any(|i| i.contains("already expired")));
    }

    #[test]
    fn audit_flags_future_created() {
        let mut fm = parse_frontmatter("---\ncreated: 2030-01-01T00:00:00\n---\n").unwrap();
        let r = audit(&mut fm, t(2026, 5, 4, 0, 0));
        assert!(r.issues.iter().any(|i| i.contains("created in the future")));
    }

    #[test]
    fn audit_flags_non_int_ttl() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: forever\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 5, 0, 0));
        assert!(r.issues.iter().any(|i| i.contains("ttl_hours not int")));
    }

    #[test]
    fn audit_fills_missing_expires_at() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 4, 1, 0));
        assert!(r.changed);
        assert!(fm.get("expires_at").unwrap().starts_with("2026-05-05"));
        assert!(r.issues.iter().any(|i| i.contains("missing expires_at")));
    }

    #[test]
    fn audit_corrects_drift_over_one_hour() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\nexpires_at: 2026-05-04T20:00:00\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 5, 0, 0));
        assert!(r.changed);
        assert!(r.issues.iter().any(|i| i.contains("drift")));
        // expected = 2026-05-05T00:00:00, drift = 4h
        assert!(fm.get("expires_at").unwrap().starts_with("2026-05-05"));
    }

    #[test]
    fn audit_keeps_within_one_hour_drift() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\nexpires_at: 2026-05-05T00:30:00\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 4, 1, 0));
        assert!(!r.changed);
    }

    #[test]
    fn audit_critical_priority_skips_expired_note() {
        let mut fm = parse_frontmatter(
            "---\ncreated: 2026-01-01T00:00:00\nttl_hours: 24\nexpires_at: 2026-01-02T00:00:00\npriority: CRITICAL\n---\n",
        )
        .unwrap();
        let r = audit(&mut fm, t(2026, 5, 4, 0, 0));
        assert!(!r.issues.iter().any(|i| i.contains("already expired")));
    }

    // ── correct_all ─────────────────────────────────────────────────────────

    #[test]
    fn correct_all_dry_run_does_not_rewrite() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(
            tmp.path().join("a.md"),
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\n---\nbody\n",
        )
        .unwrap();
        let r = correct_all(tmp.path(), false, t(2026, 5, 5, 0, 0)).unwrap();
        assert_eq!(r.checked, 1);
        assert_eq!(r.would_rewrite, 1);
        assert_eq!(r.rewritten, 0);
        let after = std::fs::read_to_string(tmp.path().join("a.md")).unwrap();
        assert!(!after.contains("expires_at"));
    }

    #[test]
    fn correct_all_apply_writes_changes() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(
            tmp.path().join("a.md"),
            "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\n---\nbody\n",
        )
        .unwrap();
        let r = correct_all(tmp.path(), true, t(2026, 5, 5, 0, 0)).unwrap();
        assert_eq!(r.rewritten, 1);
        let after = std::fs::read_to_string(tmp.path().join("a.md")).unwrap();
        assert!(after.contains("expires_at"));
        assert!(after.contains("body"));
    }

    #[test]
    fn correct_all_skips_non_md() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("a.txt"), "not markdown").unwrap();
        let r = correct_all(tmp.path(), false, t(2026, 5, 4, 0, 0)).unwrap();
        assert_eq!(r.checked, 0);
    }

    #[test]
    fn correct_all_returns_zero_when_root_missing() {
        let tmp = TempDir::new().unwrap();
        let missing = tmp.path().join("does_not_exist");
        let r = correct_all(&missing, false, t(2026, 5, 4, 0, 0)).unwrap();
        assert_eq!(r.checked, 0);
        assert_eq!(r.with_issues, 0);
    }

    #[test]
    fn correct_all_caps_files_array_at_30() {
        let tmp = TempDir::new().unwrap();
        for i in 0..40 {
            std::fs::write(
                tmp.path().join(format!("f{:03}.md", i)),
                "---\ncreated: 2026-05-04T00:00:00\nttl_hours: 24\n---\n",
            )
            .unwrap();
        }
        let r = correct_all(tmp.path(), false, t(2026, 5, 5, 0, 0)).unwrap();
        assert_eq!(r.checked, 40);
        assert_eq!(r.files.len(), 30);
    }
}
