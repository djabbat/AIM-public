//! aim-ai-self-modify — S6 (framework only, gate closed).
//!
//! Closes the loop: AIM modifies its own `agents/` (or now Rust crate)
//! code based on diagnostic findings + eval gate.
//!
//! This crate is intentionally **scaffolded but disabled** until the
//! baseline is mature: ≥ 28 ledger rows AND ≥ 28 days of wall-clock
//! coverage. Both conditions must hold (one cron firing all month
//! with no real responses must NOT unlock the gate).
//!
//! Hard kill-switch: `AI_SELF_MODIFY_DISABLED=1` env always denies.
//!
//! Direction rule: S6 LIVES in the AI subproject but its WRITE TARGET
//! is `agents/` (or any other crate path) — worktree isolation makes
//! that one-way. We never short-circuit and mutate the live tree.
//!
//! Rust port of `AI/ai/self_modify.py`.

use aim_ai_ledger::Ledger;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

const MIN_BASELINE_RUNS: u64 = 28;
const MIN_BASELINE_AGE_DAYS: f64 = 28.0;

#[derive(Debug, Error)]
pub enum SelfModifyError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Verdict {
    pub allowed: bool,
    pub reasons: Vec<String>,
    pub n_baseline_runs: u64,
    pub baseline_age_days: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Proposal {
    pub finding_ref: String,
    pub target_path: PathBuf,
    pub summary: String,
    pub patch_unified: String,
    pub eval_case_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApplyResult {
    pub proposal: Proposal,
    pub applied: bool,
    pub worktree_path: Option<PathBuf>,
    pub pre_eval_score: Option<f64>,
    pub post_eval_score: Option<f64>,
    pub notes: Vec<String>,
}

pub fn can_self_modify(ledger: &Ledger) -> Result<Verdict, SelfModifyError> {
    let mut reasons: Vec<String> = Vec::new();
    let rows = ledger.all_rows()?;
    let n_runs = rows.len() as u64;
    let age_days = match rows.first() {
        Some(first) => parse_age_days(&first.ts).unwrap_or(0.0),
        None => 0.0,
    };

    if n_runs < MIN_BASELINE_RUNS {
        reasons.push(format!(
            "baseline runs {n_runs} < {MIN_BASELINE_RUNS} required"
        ));
    }
    if age_days < MIN_BASELINE_AGE_DAYS {
        reasons.push(format!(
            "baseline age {age_days:.1}d < {MIN_BASELINE_AGE_DAYS}d required"
        ));
    }
    if std::env::var("AI_SELF_MODIFY_DISABLED").is_ok() {
        reasons.push("AI_SELF_MODIFY_DISABLED env set".into());
    }

    Ok(Verdict {
        allowed: reasons.is_empty(),
        reasons,
        n_baseline_runs: n_runs,
        baseline_age_days: age_days,
    })
}

fn parse_age_days(ts: &str) -> Option<f64> {
    let parsed = DateTime::parse_from_rfc3339(ts)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S%.f")
                .or_else(|_| chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S"))
                .ok()
                .map(|n| n.and_utc())
        })?;
    let now = Utc::now();
    let secs = (now - parsed).num_seconds() as f64;
    Some((secs / 86400.0).max(0.0))
}

pub fn propose(finding_ref: &str) -> Proposal {
    let path = finding_ref
        .split(':')
        .next()
        .unwrap_or(finding_ref)
        .to_string();
    Proposal {
        finding_ref: finding_ref.to_string(),
        target_path: PathBuf::from(path),
        summary: format!("(stub) framework proposal for {finding_ref}"),
        patch_unified: String::new(),
        eval_case_id: None,
    }
}

pub fn apply(
    ledger: &Ledger,
    proposal: Proposal,
    dry_run: bool,
) -> Result<ApplyResult, SelfModifyError> {
    let mut notes: Vec<String> = Vec::new();
    let v = can_self_modify(ledger)?;
    if !v.allowed {
        notes.push(format!(
            "can_self_modify denied: {}",
            v.reasons.join("; ")
        ));
        return Ok(ApplyResult {
            proposal,
            applied: false,
            worktree_path: None,
            pre_eval_score: None,
            post_eval_score: None,
            notes,
        });
    }
    if !dry_run {
        notes.push("forced to dry_run — live mutation not yet enabled".into());
    }
    notes.push(
        "(framework: would isolate worktree, apply patch, run S1 evals pre/post, merge if Δscore ≥ 0.05 & p ≤ 0.05)".into(),
    );
    Ok(ApplyResult {
        proposal,
        applied: false,
        worktree_path: None,
        pre_eval_score: None,
        post_eval_score: None,
        notes,
    })
}

pub fn summary(v: &Verdict) -> String {
    if v.allowed {
        return format!(
            "🟢 self-modify gate OPEN — baseline mature.\n  runs={}  age={:.1}d",
            v.n_baseline_runs, v.baseline_age_days
        );
    }
    let mut parts = vec![
        "🔒 self-modify gate CLOSED".to_string(),
        format!(
            "  runs={}  age={:.1}d",
            v.n_baseline_runs, v.baseline_age_days
        ),
    ];
    for r in &v.reasons {
        parts.push(format!("  - {r}"));
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_ai_ledger::Ledger;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        let l = Ledger::open(d.path().join("ledger.db")).unwrap();
        (d, l)
    }

    #[test]
    fn empty_ledger_blocks_with_baseline_reasons() {
        let (_d, l) = fresh();
        let v = can_self_modify(&l).unwrap();
        assert!(!v.allowed);
        assert!(v.reasons.iter().any(|r| r.contains("baseline runs")));
        assert!(v.reasons.iter().any(|r| r.contains("baseline age")));
    }

    #[test]
    fn env_kill_switch_blocks_even_when_baseline_mature() {
        let (_d, l) = fresh();
        // Insert enough rows
        for i in 0..30 {
            let ts = format!("2025-04-04T{:02}:00:00Z", i % 24);
            l.record("m", None, 10, 9, None, None, None, None, false, None, Some(&ts))
                .unwrap();
        }
        std::env::set_var("AI_SELF_MODIFY_DISABLED", "1");
        let v = can_self_modify(&l).unwrap();
        assert!(!v.allowed);
        assert!(v.reasons.iter().any(|r| r.contains("DISABLED")));
        std::env::remove_var("AI_SELF_MODIFY_DISABLED");
    }

    #[test]
    fn propose_extracts_path_from_ref() {
        let p = propose("agents/foo.py:42");
        assert_eq!(p.target_path, PathBuf::from("agents/foo.py"));
        assert_eq!(p.finding_ref, "agents/foo.py:42");
    }

    #[test]
    fn propose_handles_no_line() {
        let p = propose("README.md");
        assert_eq!(p.target_path, PathBuf::from("README.md"));
    }

    #[test]
    fn apply_blocked_when_baseline_immature() {
        let (_d, l) = fresh();
        let p = propose("agents/foo.py:1");
        let r = apply(&l, p, false).unwrap();
        assert!(!r.applied);
        assert!(r.notes.iter().any(|n| n.contains("denied")));
    }

    #[test]
    fn summary_open_when_allowed() {
        let v = Verdict {
            allowed: true,
            reasons: vec![],
            n_baseline_runs: 30,
            baseline_age_days: 30.0,
        };
        assert!(summary(&v).contains("OPEN"));
    }

    #[test]
    fn summary_closed_lists_reasons() {
        let v = Verdict {
            allowed: false,
            reasons: vec!["because reasons".into()],
            n_baseline_runs: 1,
            baseline_age_days: 0.5,
        };
        let s = summary(&v);
        assert!(s.contains("CLOSED"));
        assert!(s.contains("because reasons"));
    }
}
