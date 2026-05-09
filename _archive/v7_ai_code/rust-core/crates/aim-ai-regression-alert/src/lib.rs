//! aim-ai-regression-alert — RA1.
//!
//! When a regression is detected by `aim-ai-regression`, format an
//! alert payload (title + body + dedup key). Wiring to an actual
//! notify mux (Telegram / email / log) is the caller's job — this
//! crate is intentionally side-effect-free so it stays unit-testable
//! and can be reused by the Phoenix UI as well.
//!
//! Rust port of `AI/ai/regression_alert.py` minus the `agents.notify`
//! coupling.

use aim_ai_ledger::Ledger;
use aim_ai_regression::{detect, Regression};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AlertError {
    #[error("regression: {0}")]
    Regression(#[from] aim_ai_regression::RegressionError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Alert {
    pub title: String,
    pub body: String,
    /// Stable dedup key over the curr ts day, so two alerts within a
    /// day collapse to one delivery downstream.
    pub dedup_key: String,
    /// Suggested dedup window in minutes (downstream notify mux honours
    /// this if it supports per-message dedup windows).
    pub dedup_window_minutes: f64,
}

/// Build alert from a detected regression. Returns `None` if there is
/// no baseline or no regression.
pub fn build(r: &Regression) -> Option<Alert> {
    if !r.have_baseline || !r.regressed() {
        return None;
    }
    let n_new = r.new_findings.len();
    let title = format!("AIM/AI regression — {n_new} new finding(s)");

    let mut body = String::new();
    body.push_str(&format!(
        "between {} and {}:\n",
        truncate_ts(r.prev_ts.as_deref().unwrap_or("?")),
        truncate_ts(r.curr_ts.as_deref().unwrap_or("?"))
    ));
    body.push_str(&format!(
        "grade: {} → {}",
        r.prev_grade.as_deref().unwrap_or("?"),
        r.curr_grade.as_deref().unwrap_or("?")
    ));
    if let (Some(p), Some(c)) = (r.prev_crit, r.curr_crit) {
        body.push_str(&format!("\ncrit: {} → {} (Δ {:+})", p, c, c - p));
    }
    body.push_str("\n\nnew findings:\n");
    let mut sorted: Vec<&String> = r.new_findings.iter().collect();
    sorted.sort();
    for f in sorted.iter().take(10) {
        body.push_str(&format!("  • {f}\n"));
    }
    if n_new > 10 {
        body.push_str(&format!("  (+{} more)\n", n_new - 10));
    }
    let body = body.trim_end().to_string();

    let day = r
        .curr_ts
        .as_deref()
        .map(|s| s.chars().take(10).collect::<String>())
        .unwrap_or_else(|| "unknown".into());
    Some(Alert {
        title,
        body,
        dedup_key: format!("regression:{day}"),
        dedup_window_minutes: 720.0,
    })
}

/// Convenience: pull the latest two ledger rows, detect, build alert.
pub fn check(ledger: &Ledger) -> Result<Option<Alert>, AlertError> {
    let r = detect(ledger)?;
    Ok(build(&r))
}

fn truncate_ts(s: &str) -> String {
    s.chars().take(19).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_ai_ledger::Ledger;
    use std::collections::BTreeSet;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        let l = Ledger::open(d.path().join("ledger.db")).unwrap();
        (d, l)
    }

    fn write_report(dir: &std::path::Path, name: &str, body: &str) -> String {
        let p = dir.join(name);
        std::fs::write(&p, body).unwrap();
        p.to_string_lossy().to_string()
    }

    #[test]
    fn no_baseline_no_alert() {
        let r = Regression {
            have_baseline: false,
            prev_ts: None,
            curr_ts: None,
            prev_grade: None,
            curr_grade: None,
            prev_crit: None,
            curr_crit: None,
            prev_findings: BTreeSet::new(),
            curr_findings: BTreeSet::new(),
            new_findings: BTreeSet::new(),
            fixed_findings: BTreeSet::new(),
        };
        assert!(build(&r).is_none());
    }

    #[test]
    fn no_regression_no_alert() {
        let r = Regression {
            have_baseline: true,
            prev_ts: Some("2026-05-04T00:00:00Z".into()),
            curr_ts: Some("2026-05-04T01:00:00Z".into()),
            prev_grade: Some("B".into()),
            curr_grade: Some("B".into()),
            prev_crit: Some(0),
            curr_crit: Some(0),
            prev_findings: BTreeSet::new(),
            curr_findings: BTreeSet::new(),
            new_findings: BTreeSet::new(),
            fixed_findings: BTreeSet::new(),
        };
        assert!(build(&r).is_none());
    }

    #[test]
    fn regression_yields_alert() {
        let mut nf = BTreeSet::new();
        nf.insert("agents/x.py:42".to_string());
        nf.insert("lib.rs:7".to_string());
        let r = Regression {
            have_baseline: true,
            prev_ts: Some("2026-05-04T00:00:00Z".into()),
            curr_ts: Some("2026-05-04T01:00:00Z".into()),
            prev_grade: Some("B".into()),
            curr_grade: Some("B".into()),
            prev_crit: Some(2),
            curr_crit: Some(5),
            prev_findings: BTreeSet::new(),
            curr_findings: nf.clone(),
            new_findings: nf,
            fixed_findings: BTreeSet::new(),
        };
        let alert = build(&r).unwrap();
        assert!(alert.title.contains("2 new finding"));
        assert!(alert.body.contains("crit: 2 → 5 (Δ +3)"));
        assert!(alert.body.contains("agents/x.py:42"));
        assert_eq!(alert.dedup_key, "regression:2026-05-04");
        assert_eq!(alert.dedup_window_minutes, 720.0);
    }

    #[test]
    fn regression_truncates_after_ten_findings() {
        let mut nf = BTreeSet::new();
        for i in 0..15 {
            nf.insert(format!("a/x.py:{i}"));
        }
        let r = Regression {
            have_baseline: true,
            prev_ts: Some("2026-05-04T00:00:00Z".into()),
            curr_ts: Some("2026-05-04T01:00:00Z".into()),
            prev_grade: Some("A".into()),
            curr_grade: Some("A".into()),
            prev_crit: Some(0),
            curr_crit: Some(0),
            prev_findings: BTreeSet::new(),
            curr_findings: nf.clone(),
            new_findings: nf,
            fixed_findings: BTreeSet::new(),
        };
        let alert = build(&r).unwrap();
        assert!(alert.body.contains("(+5 more)"));
    }

    #[test]
    fn check_with_real_ledger_round_trip() {
        let (d, l) = fresh();
        let p1 = write_report(d.path(), "p.md", "clean");
        let p2 = write_report(d.path(), "c.md", "boom at lib.rs:1");
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(&p1), Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(&p2), Some("2026-05-04T01:00:00Z")).unwrap();
        let alert = check(&l).unwrap().unwrap();
        assert!(alert.body.contains("lib.rs:1"));
    }
}
