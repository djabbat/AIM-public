//! aim-ai-regression — RD1.
//!
//! Compare the two most recent self-diagnostic runs in the ledger and
//! flag NEW critical findings: file:line refs that appear in the
//! latest report but did NOT appear in the previous one.
//!
//! Use case: the morning brief checks whether the last 24 h introduced
//! new high-severity issues since the last run.
//!
//! Rust port of `AI/ai/regression_detector.py`. Behaviour parity:
//! - When grade IMPROVED (e.g. D → C in letter ordering), do NOT flag
//!   regression even if new refs appear — a more thorough model finds
//!   more issues; that's quality going up, not down.
//! - "Regression" trigger: any NEW finding, OR `crit` count went up.
//! - "Improved" trigger: `(not regressed) AND (grade_improved OR
//!    fixed_findings non-empty OR crit count went down)`.
//!
//! Public API:
//! - [`detect`] — pull the last two ledger rows; diff their findings.
//! - [`Regression::regressed` / `improved`] — boolean signals.

use aim_ai_ledger::Ledger;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RegressionError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
}

/// Diff result between the previous and current ledger row.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Regression {
    pub have_baseline: bool,
    pub prev_ts: Option<String>,
    pub curr_ts: Option<String>,
    pub prev_grade: Option<String>,
    pub curr_grade: Option<String>,
    pub prev_crit: Option<i64>,
    pub curr_crit: Option<i64>,
    pub prev_findings: BTreeSet<String>,
    pub curr_findings: BTreeSet<String>,
    pub new_findings: BTreeSet<String>,
    pub fixed_findings: BTreeSet<String>,
}

impl Regression {
    /// Letter grade ordering: A < B < C < D < F. Lower is better.
    /// `None` on either side ⇒ no signal.
    pub fn grade_improved(&self) -> bool {
        match (&self.prev_grade, &self.curr_grade) {
            (Some(p), Some(c)) => c < p,
            _ => false,
        }
    }

    pub fn grade_worsened(&self) -> bool {
        match (&self.prev_grade, &self.curr_grade) {
            (Some(p), Some(c)) => c > p,
            _ => false,
        }
    }

    /// True if NEW critical issues appeared OR `crit` count went up,
    /// **unless** the overall grade improved.
    pub fn regressed(&self) -> bool {
        if self.grade_improved() {
            return false;
        }
        if !self.new_findings.is_empty() {
            return true;
        }
        if let (Some(p), Some(c)) = (self.prev_crit, self.curr_crit) {
            if c > p {
                return true;
            }
        }
        false
    }

    /// True if grade improved, fixes happened, or `crit` count fell —
    /// and we are not regressed.
    pub fn improved(&self) -> bool {
        if self.regressed() {
            return false;
        }
        if self.grade_improved() {
            return true;
        }
        if !self.fixed_findings.is_empty() {
            return true;
        }
        if let (Some(p), Some(c)) = (self.prev_crit, self.curr_crit) {
            if c < p {
                return true;
            }
        }
        false
    }
}

/// Pull the last two ledger rows; diff their finding sets. Findings are
/// extracted from the `report_path` file (if any) by scanning for
/// `file:line` patterns in the report body — a minimal port of the
/// Python `meta_evaluator::parse_report().findings` extraction.
pub fn detect(ledger: &Ledger) -> Result<Regression, RegressionError> {
    let rows = ledger.recent(2)?;
    if rows.len() < 2 {
        return Ok(Regression {
            have_baseline: false,
            prev_ts: rows.first().map(|r| r.ts.clone()),
            curr_ts: None,
            prev_grade: None,
            curr_grade: None,
            prev_crit: None,
            curr_crit: None,
            prev_findings: BTreeSet::new(),
            curr_findings: BTreeSet::new(),
            new_findings: BTreeSet::new(),
            fixed_findings: BTreeSet::new(),
        });
    }
    let prev = &rows[0];
    let curr = &rows[1];
    let pf = findings_for(prev.report_path.as_deref());
    let cf = findings_for(curr.report_path.as_deref());
    let new_set: BTreeSet<String> = cf.difference(&pf).cloned().collect();
    let fixed_set: BTreeSet<String> = pf.difference(&cf).cloned().collect();
    Ok(Regression {
        have_baseline: true,
        prev_ts: Some(prev.ts.clone()),
        curr_ts: Some(curr.ts.clone()),
        prev_grade: prev.grade.clone(),
        curr_grade: curr.grade.clone(),
        prev_crit: prev.crit,
        curr_crit: curr.crit,
        prev_findings: pf,
        curr_findings: cf,
        new_findings: new_set,
        fixed_findings: fixed_set,
    })
}

// ── findings extractor ──────────────────────────────────────────

fn findings_for(path: Option<&str>) -> BTreeSet<String> {
    let Some(p) = path else { return BTreeSet::new() };
    let Ok(text) = std::fs::read_to_string(p) else {
        return BTreeSet::new();
    };
    parse_findings(&text)
}

/// Extract `file:line` style refs from a report body.
///
/// We accept tokens of the form `<word>(.<word>)*:<digits>` — common
/// shapes are `agents/foo.py:42`, `lib.rs:101`, `path/to/x.ex:7`. The
/// Python predecessor calls `meta_evaluator::parse_report` which uses a
/// similar regex; we reproduce just the finding-token extraction here.
pub fn parse_findings(text: &str) -> BTreeSet<String> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"[A-Za-z0-9_./\-]+\.(?:py|rs|ex|exs|md|toml|yaml|yml|json|sh):\d+").unwrap()
    });
    RE.find_iter(text).map(|m| m.as_str().to_string()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_ai_ledger::Ledger;
    use tempfile::tempdir;

    fn fresh_ledger() -> (tempfile::TempDir, Ledger) {
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
    fn parse_findings_extracts_refs() {
        let body = "issue at agents/foo.py:42 and crates/aim-x/src/lib.rs:101 plus README.md:7";
        let s = parse_findings(body);
        assert!(s.contains("agents/foo.py:42"));
        assert!(s.contains("crates/aim-x/src/lib.rs:101"));
        assert!(s.contains("README.md:7"));
    }

    #[test]
    fn parse_findings_rejects_non_files() {
        let body = "version 1.2:0 is not a finding";
        let s = parse_findings(body);
        assert!(s.is_empty());
    }

    #[test]
    fn detect_no_baseline_when_zero_rows() {
        let (_d, l) = fresh_ledger();
        let r = detect(&l).unwrap();
        assert!(!r.have_baseline);
    }

    #[test]
    fn detect_no_baseline_when_one_row() {
        let (_d, l) = fresh_ledger();
        l.record("m", Some("A"), 0, 0, None, None, None, None, false, None,
                 Some("2026-05-04T00:00:00Z")).unwrap();
        let r = detect(&l).unwrap();
        assert!(!r.have_baseline);
    }

    #[test]
    fn detect_new_findings_flag_regression() {
        let (d, l) = fresh_ledger();
        let prev = write_report(d.path(), "prev.md", "no issues");
        let curr = write_report(
            d.path(),
            "curr.md",
            "regression in agents/x.py:42 and lib.rs:7",
        );
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(&prev), Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(&curr), Some("2026-05-04T01:00:00Z")).unwrap();
        let r = detect(&l).unwrap();
        assert!(r.have_baseline);
        assert_eq!(r.new_findings.len(), 2);
        assert!(r.regressed());
        assert!(!r.improved());
    }

    #[test]
    fn detect_grade_improvement_suppresses_regression_flag() {
        // Even when curr has more findings, an A grade↓ → B-style
        // wait — letter ordering: A < B < C < D < F so c < p means
        // letter VALUE went down, which means quality went UP.
        // To "improve" we want curr_grade < prev_grade. Use D → C.
        let (d, l) = fresh_ledger();
        let prev = write_report(d.path(), "prev.md", "old issue lib.rs:1");
        let curr = write_report(
            d.path(),
            "curr.md",
            "old issue lib.rs:1 plus new lib.rs:2",
        );
        l.record("m", Some("D"), 0, 0, Some(0), None, None, None, false,
                 Some(&prev), Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("C"), 0, 0, Some(0), None, None, None, false,
                 Some(&curr), Some("2026-05-04T01:00:00Z")).unwrap();
        let r = detect(&l).unwrap();
        assert!(!r.regressed(), "grade improvement should suppress regression flag");
        assert!(r.grade_improved());
        assert!(r.improved());
    }

    #[test]
    fn detect_fixed_findings_show_improvement() {
        let (d, l) = fresh_ledger();
        let prev = write_report(d.path(), "prev.md", "issue lib.rs:1 and lib.rs:2");
        let curr = write_report(d.path(), "curr.md", "only lib.rs:1 left");
        l.record("m", Some("B"), 0, 0, Some(2), None, None, None, false,
                 Some(&prev), Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("B"), 0, 0, Some(1), None, None, None, false,
                 Some(&curr), Some("2026-05-04T01:00:00Z")).unwrap();
        let r = detect(&l).unwrap();
        assert!(!r.regressed());
        assert!(r.improved());
        assert_eq!(r.fixed_findings.len(), 1);
        assert!(r.new_findings.is_empty());
    }

    #[test]
    fn detect_crit_count_increase_flags_regression() {
        let (_d, l) = fresh_ledger();
        l.record("m", Some("B"), 0, 0, Some(2), None, None, None, false, None,
                 Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("B"), 0, 0, Some(5), None, None, None, false, None,
                 Some("2026-05-04T01:00:00Z")).unwrap();
        let r = detect(&l).unwrap();
        assert!(r.regressed());
        assert!(!r.improved());
    }
}
