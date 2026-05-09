//! aim-ai-prompt-impact — PI1.
//!
//! Did tightening the diagnostic prompt actually move metrics?
//!
//! For each recorded prompt revision (`aim_ai_prompt_versions`), join
//! the diagnostic ledger runs (`aim_ai_ledger`) by ts ordering and
//! compute before-vs-after metric averages for that revision's window:
//! - `before` = runs in `(prev_rev_ts .. this_rev_ts)`
//! - `after`  = runs in `[this_rev_ts .. next_rev_ts)` (or unbounded)
//!
//! Surfaces whether avg compliance / avg crit shifted meaningfully
//! after each prompt change.
//!
//! Rust port of `AI/ai/prompt_impact.py`.

use aim_ai_ledger::{Ledger, Row};
use aim_ai_prompt_versions::PromptStore;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ImpactError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
    #[error("prompt versions: {0}")]
    Prompt(#[from] aim_ai_prompt_versions::PromptError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImpactRow {
    pub revision_ts: String,
    pub sha_prefix: String,
    pub n_runs_before: u64,
    pub n_runs_after: u64,
    pub avg_compliance_before: Option<f64>,
    pub avg_compliance_after: Option<f64>,
    pub avg_crit_before: Option<f64>,
    pub avg_crit_after: Option<f64>,
}

impl ImpactRow {
    pub fn compliance_delta(&self) -> Option<f64> {
        match (self.avg_compliance_before, self.avg_compliance_after) {
            (Some(b), Some(a)) => Some(a - b),
            _ => None,
        }
    }
    pub fn crit_delta(&self) -> Option<f64> {
        match (self.avg_crit_before, self.avg_crit_after) {
            (Some(b), Some(a)) => Some(a - b),
            _ => None,
        }
    }
}

fn avg_f(xs: impl IntoIterator<Item = f64>) -> Option<f64> {
    let v: Vec<f64> = xs.into_iter().collect();
    if v.is_empty() {
        None
    } else {
        Some(v.iter().sum::<f64>() / v.len() as f64)
    }
}

/// For each prompt revision, compute window stats from runs whose ts
/// fall before vs. after the revision ts.
pub fn impact_per_revision(
    ledger: &Ledger,
    prompts: &PromptStore,
) -> Result<Vec<ImpactRow>, ImpactError> {
    let revs = prompts.history()?;
    if revs.is_empty() {
        return Ok(Vec::new());
    }
    let runs = ledger.all_rows()?;

    let mut out: Vec<ImpactRow> = Vec::with_capacity(revs.len());
    for (i, rev) in revs.iter().enumerate() {
        let prev_ts: Option<&str> = i.checked_sub(1).and_then(|k| revs[k].ts.as_deref());
        let next_ts: Option<&str> = revs.get(i + 1).and_then(|r| r.ts.as_deref());
        let rev_ts: &str = rev.ts.as_deref().unwrap_or("?");

        let before: Vec<&Row> = runs
            .iter()
            .filter(|r| {
                r.ts.as_str() < rev_ts && (prev_ts.is_none() || r.ts.as_str() >= prev_ts.unwrap())
            })
            .collect();
        let after: Vec<&Row> = runs
            .iter()
            .filter(|r| {
                r.ts.as_str() >= rev_ts && (next_ts.is_none() || r.ts.as_str() < next_ts.unwrap())
            })
            .collect();

        let avg_comp_before = avg_f(before.iter().map(|r| r.compliance));
        let avg_comp_after = avg_f(after.iter().map(|r| r.compliance));
        let crit_before: Vec<f64> = before.iter().filter_map(|r| r.crit.map(|c| c as f64)).collect();
        let crit_after: Vec<f64> = after.iter().filter_map(|r| r.crit.map(|c| c as f64)).collect();

        out.push(ImpactRow {
            revision_ts: rev_ts.to_string(),
            sha_prefix: rev.sha256.chars().take(8).collect::<String>(),
            n_runs_before: before.len() as u64,
            n_runs_after: after.len() as u64,
            avg_compliance_before: avg_comp_before,
            avg_compliance_after: avg_comp_after,
            avg_crit_before: avg_f(crit_before),
            avg_crit_after: avg_f(crit_after),
        });
    }
    Ok(out)
}

pub fn summary(rows: &[ImpactRow]) -> String {
    if rows.is_empty() {
        return "(no prompt revisions recorded — run record_current first)".into();
    }
    let mut out: Vec<String> = vec!["📊 Prompt-impact analysis".into()];
    for r in rows {
        let ts: String = r.revision_ts.chars().take(19).collect();
        out.push(format!("\nrev {}  {}", r.sha_prefix, ts));
        out.push(format!(
            "  runs: {} before / {} after",
            r.n_runs_before, r.n_runs_after
        ));
        out.push(format!(
            "  compliance: {} → {}{}",
            fmt_pct(r.avg_compliance_before),
            fmt_pct(r.avg_compliance_after),
            fmt_delta_pct(r.compliance_delta())
        ));
        out.push(format!(
            "  avg crit:   {} → {}{}",
            fmt_f(r.avg_crit_before),
            fmt_f(r.avg_crit_after),
            fmt_delta_f(r.crit_delta())
        ));
    }
    out.join("\n")
}

fn fmt_pct(v: Option<f64>) -> String {
    match v {
        Some(x) => format!("{:.0}%", x * 100.0),
        None => "-".into(),
    }
}
fn fmt_f(v: Option<f64>) -> String {
    match v {
        Some(x) => format!("{:.1}", x),
        None => "-".into(),
    }
}
fn fmt_delta_pct(v: Option<f64>) -> String {
    match v {
        Some(x) => format!("  ({:+.0}%)", x * 100.0),
        None => String::new(),
    }
}
fn fmt_delta_f(v: Option<f64>) -> String {
    match v {
        Some(x) => format!("  ({:+.1})", x),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger, PromptStore) {
        let d = tempdir().unwrap();
        let p = d.path().join("ledger.db");
        let ledger = Ledger::open(&p).unwrap();
        let store = PromptStore::open(&p).unwrap();
        (d, ledger, store)
    }

    #[test]
    fn no_revisions_returns_empty() {
        let (_d, l, p) = fresh();
        let rows = impact_per_revision(&l, &p).unwrap();
        assert!(rows.is_empty());
    }

    #[test]
    fn split_runs_around_single_revision() {
        let (d, l, p) = fresh();
        let pf = d.path().join("prompt.md");
        // First fingerprint at t=01
        std::fs::write(&pf, "v1\n").unwrap();
        p.record_current(Some(&pf), Some("2026-05-04T01:00:00Z")).unwrap();
        // Add runs before + after
        l.record("m", None, 10, 4, Some(2), None, None, None, false, None,
                 Some("2026-05-04T00:30:00Z")).unwrap();
        l.record("m", None, 10, 9, Some(0), None, None, None, false, None,
                 Some("2026-05-04T02:00:00Z")).unwrap();

        let rows = impact_per_revision(&l, &p).unwrap();
        assert_eq!(rows.len(), 1);
        let r = &rows[0];
        // Before window has 1 run with compliance 0.4
        assert_eq!(r.n_runs_before, 1);
        assert_eq!(r.n_runs_after, 1);
        assert!((r.avg_compliance_before.unwrap() - 0.4).abs() < 1e-9);
        assert!((r.avg_compliance_after.unwrap() - 0.9).abs() < 1e-9);
        assert!((r.compliance_delta().unwrap() - 0.5).abs() < 1e-9);
        assert!((r.crit_delta().unwrap() - (-2.0)).abs() < 1e-9);
    }

    #[test]
    fn windows_partitioned_for_two_revisions() {
        let (d, l, p) = fresh();
        let pf = d.path().join("prompt.md");
        std::fs::write(&pf, "v1\n").unwrap();
        p.record_current(Some(&pf), Some("2026-05-04T01:00:00Z")).unwrap();
        std::fs::write(&pf, "v2\n").unwrap();
        p.record_current(Some(&pf), Some("2026-05-04T03:00:00Z")).unwrap();

        // Run before any revision
        l.record("m", None, 10, 5, None, None, None, None, false, None,
                 Some("2026-05-04T00:30:00Z")).unwrap();
        // Between revs
        l.record("m", None, 10, 7, None, None, None, None, false, None,
                 Some("2026-05-04T02:00:00Z")).unwrap();
        // After both
        l.record("m", None, 10, 9, None, None, None, None, false, None,
                 Some("2026-05-04T04:00:00Z")).unwrap();

        let rows = impact_per_revision(&l, &p).unwrap();
        assert_eq!(rows.len(), 2);
        // Rev 1: before=1 (00:30), after=1 (02:00)
        assert_eq!(rows[0].n_runs_before, 1);
        assert_eq!(rows[0].n_runs_after, 1);
        // Rev 2: before=1 (02:00), after=1 (04:00)
        assert_eq!(rows[1].n_runs_before, 1);
        assert_eq!(rows[1].n_runs_after, 1);
    }

    #[test]
    fn no_runs_avg_is_none() {
        let (d, l, p) = fresh();
        let pf = d.path().join("prompt.md");
        std::fs::write(&pf, "v1\n").unwrap();
        p.record_current(Some(&pf), Some("2026-05-04T01:00:00Z")).unwrap();
        let rows = impact_per_revision(&l, &p).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].avg_compliance_before, None);
        assert_eq!(rows[0].avg_compliance_after, None);
        assert!(rows[0].compliance_delta().is_none());
    }

    #[test]
    fn summary_empty_message() {
        assert!(summary(&[]).contains("no prompt revisions"));
    }

    #[test]
    fn summary_renders_format() {
        let r = ImpactRow {
            revision_ts: "2026-05-04T01:00:00Z".into(),
            sha_prefix: "abcd1234".into(),
            n_runs_before: 1,
            n_runs_after: 1,
            avg_compliance_before: Some(0.4),
            avg_compliance_after: Some(0.9),
            avg_crit_before: Some(2.0),
            avg_crit_after: Some(0.0),
        };
        let s = summary(&[r]);
        assert!(s.contains("rev abcd1234"));
        assert!(s.contains("40%"));
        assert!(s.contains("90%"));
        assert!(s.contains("(+50%)"));
    }
}
