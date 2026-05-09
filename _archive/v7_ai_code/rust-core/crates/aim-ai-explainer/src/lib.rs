//! aim-ai-explainer — EX1.
//!
//! When the health score says 67/100 grade C, the user needs to know
//! WHAT to fix. This crate produces per-component recovery suggestions
//! sorted by points lost (highest leverage first).
//!
//! Rust port of `AI/ai/explainer.py`.

use aim_ai_ledger::Ledger;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recovery {
    pub component: String,
    pub pts_lost: i64,
    pub why: String,
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Explanation {
    pub total: i64,
    pub grade: String,
    pub recoveries: Vec<Recovery>,
}

const WEIGHTS: &[(&str, i64)] = &[
    ("wiring", 30),
    ("regression", 25),
    ("compliance", 15),
    ("cases", 20),
    ("prompt_drift", 10),
];

pub fn explain(ledger: &Ledger) -> Result<Explanation, aim_ai_health::HealthError> {
    let score = aim_ai_health::compute(ledger)?;
    let mut recoveries: Vec<Recovery> = Vec::new();
    for (name, full) in WEIGHTS {
        let got = score.components.get(*name).copied().unwrap_or(0);
        if got >= *full {
            continue;
        }
        let pts_lost = full - got;
        let (why, action) = diagnose(name, got, *full, ledger);
        recoveries.push(Recovery {
            component: (*name).into(),
            pts_lost,
            why,
            action,
        });
    }
    recoveries.sort_by(|a, b| b.pts_lost.cmp(&a.pts_lost));
    Ok(Explanation {
        total: score.total,
        grade: score.grade,
        recoveries,
    })
}

fn diagnose(component: &str, _got: i64, _full: i64, ledger: &Ledger) -> (String, String) {
    match component {
        "wiring" => (
            "wiring probe pending Rust port (placeholder credit)".into(),
            "implement aim-ai-doctor smoke crate (per MIGRATION roadmap)".into(),
        ),
        "regression" => match aim_ai_regression::detect(ledger) {
            Ok(r) if !r.have_baseline => (
                "no baseline yet (need ≥2 diagnostic runs)".into(),
                "let the daily cron accumulate runs OR run `aim ai diag` (cost: ~$0.01)".into(),
            ),
            Ok(r) if r.regressed() => (
                format!("{} new finding(s) since previous run", r.new_findings.len()),
                "review with `aim ai regress`; suppress false positives via aim-ai-suppressions".into(),
            ),
            Ok(_) => (
                "regression: signal absent or improvement detected".into(),
                "no action — full credit on next sweep".into(),
            ),
            Err(e) => (format!("regression check failed: {e}"), "see logs".into()),
        },
        "compliance" => match ledger.trend() {
            Ok(t) if t.n_runs == 0 => (
                "no runs in ledger yet".into(),
                "run `aim ai diag` to start populating the ledger".into(),
            ),
            Ok(t) => (
                format!("avg compliance {:.0}%", t.avg_compliance * 100.0),
                "tighten SELF_DIAGNOSTIC_PROMPT.md to require path:line in every finding".into(),
            ),
            Err(e) => (format!("ledger trend failed: {e}"), "see logs".into()),
        },
        "cases" => {
            let r = aim_ai_cases::validate_dir(None);
            if r.n_failed > 0 {
                (
                    format!("{} invalid eval case(s) of {}", r.n_failed, r.n_cases),
                    "run `aim ai validate-cases` and fix yaml schema issues".into(),
                )
            } else {
                (
                    "case validator: all cases passing".into(),
                    "no action".into(),
                )
            }
        }
        "prompt_drift" => match aim_ai_prompt_versions::PromptStore::open_default() {
            Ok(store) => match store.drift_since_last(None) {
                Ok(d) if !d.prompt_present => (
                    "SELF_DIAGNOSTIC_PROMPT.md is missing".into(),
                    "create the file at AI/docs/ — see canonical template".into(),
                ),
                Ok(d) if !d.have_baseline => (
                    "prompt never fingerprinted".into(),
                    "run `aim ai sweep` to record the baseline".into(),
                ),
                Ok(d) if d.changed => (
                    "prompt changed since last record".into(),
                    "run `aim ai sweep` to log the new revision".into(),
                ),
                Ok(_) => (
                    "prompt drift: full credit (no detected drift)".into(),
                    "no action".into(),
                ),
                Err(e) => (format!("drift check failed: {e}"), "see logs".into()),
            },
            Err(e) => (format!("prompt store unavailable: {e}"), "see logs".into()),
        },
        _ => (
            format!("unknown component {component}"),
            "no action".into(),
        ),
    }
}

pub fn summary(e: &Explanation) -> String {
    let mut out = vec![format!("📋 Score explanation — {}/100 {}", e.total, e.grade)];
    if e.recoveries.is_empty() {
        out.push("  ✅ all components at full credit".into());
        return out.join("\n");
    }
    for r in &e.recoveries {
        out.push(format!("  • {} −{} pts: {}", r.component, r.pts_lost, r.why));
        out.push(format!("      → {}", r.action));
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_ai_ledger::Ledger;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        let l = Ledger::open(d.path().join("aim").join("diagnostic_ledger.db")).unwrap();
        (d, l)
    }

    #[test]
    fn explain_empty_state_lists_recoveries_for_partials() {
        let (_d, l) = fresh();
        let e = explain(&l).unwrap();
        // Stub-credit components (regression + compliance) lose 50%
        // each; the rest keep full credit. So recoveries non-empty.
        assert!(!e.recoveries.is_empty());
        // No "wiring" recovery (full credit stub)
        assert!(!e.recoveries.iter().any(|r| r.component == "wiring"));
    }

    #[test]
    fn recoveries_sorted_descending_by_pts_lost() {
        let (_d, l) = fresh();
        let e = explain(&l).unwrap();
        for w in e.recoveries.windows(2) {
            assert!(w[0].pts_lost >= w[1].pts_lost);
        }
    }

    #[test]
    fn summary_renders_format() {
        let e = Explanation {
            total: 67,
            grade: "C".into(),
            recoveries: vec![Recovery {
                component: "regression".into(),
                pts_lost: 12,
                why: "no baseline yet".into(),
                action: "run aim ai diag".into(),
            }],
        };
        let s = summary(&e);
        assert!(s.contains("67/100 C"));
        assert!(s.contains("regression −12 pts"));
        assert!(s.contains("no baseline"));
    }

    #[test]
    fn summary_full_credit_message() {
        let e = Explanation {
            total: 100,
            grade: "A".into(),
            recoveries: vec![],
        };
        let s = summary(&e);
        assert!(s.contains("full credit"));
    }
}
