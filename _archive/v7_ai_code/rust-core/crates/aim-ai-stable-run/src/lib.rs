//! aim-ai-stable-run — S13 repeatable diagnostic orchestrator.
//!
//! Adversarial mode produces drift across runs (we observed C → F → D
//! on identical code). Running once is misleading. This module runs
//! the diagnostic N times and surfaces only the high-confidence subset
//! — what the model agrees with itself on.
//!
//! Rust port of `AI/ai/stable_run.py`. The orchestration takes a
//! caller-supplied `run_fn` so tests can inject deterministic stubs;
//! production code wires it to the real LLM-call binary later.

use aim_ai_meta_evaluator::{measure, parse_report, MetaError};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum StableRunError {
    #[error("stable_run needs n >= 2 (otherwise no signal)")]
    TooFewRuns,
    #[error("meta-evaluator: {0}")]
    Meta(#[from] MetaError),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

/// Trait for the per-pass "ask the model" function. Defining it as a
/// trait (rather than a `Fn` closure) keeps the API friendly to test
/// stubs and to async LLM clients later.
pub trait RunFn {
    fn run(&self, model: &str) -> Result<String, StableRunError>;
}

impl<F> RunFn for F
where
    F: Fn(&str) -> Result<String, StableRunError>,
{
    fn run(&self, model: &str) -> Result<String, StableRunError> {
        (self)(model)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StableResult {
    pub n_runs: u32,
    pub raw_reports: Vec<String>,
    pub grades: Vec<Option<String>>,
    pub verdict: String,
    pub shared_findings: Vec<String>,
    pub unique_findings: Vec<String>,
    pub crit_counts: Vec<i64>,
    pub jaccard: f64,
    pub line_compliance: Vec<f64>,
}

impl StableResult {
    pub fn avg_compliance(&self) -> f64 {
        if self.line_compliance.is_empty() {
            return 0.0;
        }
        self.line_compliance.iter().sum::<f64>() / self.line_compliance.len() as f64
    }
    /// ≥80% mean compliance across runs = trustworthy refs.
    pub fn compliance_ok(&self) -> bool {
        self.avg_compliance() >= 0.8
    }
}

#[derive(Debug, Default)]
pub struct StableRunOpts<'a> {
    pub model: &'a str,
    pub save_individual_to: Option<&'a Path>,
}

pub fn stable_run<R: RunFn>(
    n: u32,
    opts: &StableRunOpts<'_>,
    run_fn: &R,
) -> Result<StableResult, StableRunError> {
    if n < 2 {
        return Err(StableRunError::TooFewRuns);
    }

    let model = if opts.model.is_empty() {
        "deepseek-reasoner"
    } else {
        opts.model
    };

    let mut reports: Vec<String> = Vec::with_capacity(n as usize);
    for i in 0..n {
        tracing::info!(pass = i + 1, total = n, model, "stable_run pass");
        reports.push(run_fn.run(model)?);
    }

    if let Some(dir) = opts.save_individual_to {
        std::fs::create_dir_all(dir)?;
        for (i, r) in reports.iter().enumerate() {
            let date = chrono::Utc::now().format("%Y-%m-%d").to_string();
            let p: PathBuf = dir.join(format!("stable_run_{date}_pass{}.md", i + 1));
            std::fs::write(&p, r)?;
        }
    }

    let report_refs: Vec<&str> = reports.iter().map(|s| s.as_str()).collect();
    let m = measure(&report_refs)?;
    let compliance: Vec<f64> = reports
        .iter()
        .map(|r| parse_report(r).line_compliance())
        .collect();

    let mut shared: Vec<String> = m.shared_findings.into_iter().collect();
    shared.sort();
    let mut unique: Vec<String> = m.unique_findings.into_iter().collect();
    unique.sort();

    Ok(StableResult {
        n_runs: n,
        raw_reports: reports,
        grades: m.grades,
        verdict: m.verdict,
        shared_findings: shared,
        unique_findings: unique,
        crit_counts: m.crit_counts,
        jaccard: m.jaccard_findings,
        line_compliance: compliance,
    })
}

/// Render consolidated markdown — one place for the human eye.
pub fn render_markdown(result: &StableResult) -> String {
    let mut out: Vec<String> = Vec::new();
    out.push("# AIM/AI Stable Run — consolidated".into());
    out.push(String::new());
    out.push(format!("**Runs:** {}", result.n_runs));
    out.push(format!("**Verdict:** {}", result.verdict.to_uppercase()));
    out.push(format!("**Average line compliance:** {:.0}%", result.avg_compliance() * 100.0));
    out.push(format!("**Jaccard (avg pairwise):** {:.3}", result.jaccard));
    out.push(format!(
        "**Grades per run:** {}",
        result
            .grades
            .iter()
            .map(|g| g.clone().unwrap_or_else(|| "?".into()))
            .collect::<Vec<_>>()
            .join(", ")
    ));
    out.push(format!(
        "**Crit counts per run:** {}",
        result
            .crit_counts
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>()
            .join(", ")
    ));
    out.push(String::new());

    out.push("## Shared findings (signal)".into());
    if result.shared_findings.is_empty() {
        out.push("_no shared findings — model disagrees with itself, treat as noise_".into());
    } else {
        for r in &result.shared_findings {
            out.push(format!("- `{}`", r));
        }
    }
    out.push(String::new());

    out.push("## Unique findings (noise)".into());
    if result.unique_findings.is_empty() {
        out.push("_no unique findings_".into());
    } else {
        for r in &result.unique_findings {
            out.push(format!("- `{}`", r));
        }
    }
    out.push(String::new());

    out.push("## Recommendation".into());
    match result.verdict.as_str() {
        "stable" => out.push(
            "Trust the shared findings; act on them. Re-run only if a single noisy ref looks high-impact."
                .into(),
        ),
        "noisy" => out.push(
            "Grades or findings drift. Trust signal over individual runs; act on shared findings, ignore unique."
                .into(),
        ),
        "unstable" => out.push(
            "Both grade and findings vary widely. Treat individual reports as noise; act ONLY on shared findings."
                .into(),
        ),
        _ => {}
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fake_run_fn(reports: Vec<String>) -> impl RunFn {
        let cell = std::sync::Mutex::new(reports.into_iter());
        move |_model: &str| -> Result<String, StableRunError> {
            let mut it = cell.lock().unwrap();
            it.next().ok_or(StableRunError::TooFewRuns).map(|s| s)
        }
    }

    #[test]
    fn rejects_too_few_runs() {
        let f = fake_run_fn(vec!["a".into(), "b".into()]);
        assert!(matches!(
            stable_run(1, &StableRunOpts::default(), &f),
            Err(StableRunError::TooFewRuns)
        ));
    }

    #[test]
    fn three_identical_runs_stable() {
        let r = "Grade: A\ncrit: 0\nagents/x.py:1".to_string();
        let f = fake_run_fn(vec![r.clone(), r.clone(), r.clone()]);
        let res = stable_run(3, &StableRunOpts::default(), &f).unwrap();
        assert_eq!(res.n_runs, 3);
        assert_eq!(res.verdict, "stable");
        assert!((res.jaccard - 1.0).abs() < 1e-9);
        assert!(res.shared_findings.contains(&"agents/x.py:1".to_string()));
        assert!(res.unique_findings.is_empty());
    }

    #[test]
    fn divergent_runs_unstable() {
        let f = fake_run_fn(vec![
            "Grade: A\nagents/x.py:1".into(),
            "Grade: F\nagents/y.py:2".into(),
        ]);
        let res = stable_run(2, &StableRunOpts::default(), &f).unwrap();
        assert_eq!(res.verdict, "unstable");
        assert!(res.shared_findings.is_empty());
    }

    #[test]
    fn compliance_calc_consistent_with_meta() {
        let r = "Grade: B\nagents/a.py:1 and agents/b.py".to_string();
        let f = fake_run_fn(vec![r.clone(), r.clone()]);
        let res = stable_run(2, &StableRunOpts::default(), &f).unwrap();
        assert_eq!(res.line_compliance.len(), 2);
        assert!((res.avg_compliance() - 0.5).abs() < 1e-9);
        assert!(!res.compliance_ok());
    }

    #[test]
    fn compliance_ok_at_100pct() {
        let r = "Grade: B\nagents/a.py:1 and agents/b.py:2".to_string();
        let f = fake_run_fn(vec![r.clone(), r.clone()]);
        let res = stable_run(2, &StableRunOpts::default(), &f).unwrap();
        assert!(res.compliance_ok());
    }

    #[test]
    fn save_individual_writes_files() {
        let d = tempdir().unwrap();
        let r = "Grade: A\nagents/x.py:1".to_string();
        let f = fake_run_fn(vec![r.clone(), r.clone()]);
        let opts = StableRunOpts {
            model: "stub",
            save_individual_to: Some(d.path()),
        };
        stable_run(2, &opts, &f).unwrap();
        let count = std::fs::read_dir(d.path()).unwrap().count();
        assert!(count >= 2, "expected at least 2 files written, got {count}");
    }

    #[test]
    fn render_markdown_includes_verdict() {
        let r = "Grade: A\nagents/x.py:1".to_string();
        let f = fake_run_fn(vec![r.clone(), r.clone()]);
        let res = stable_run(2, &StableRunOpts::default(), &f).unwrap();
        let md = render_markdown(&res);
        assert!(md.contains("STABLE"));
        assert!(md.contains("agents/x.py:1"));
    }

    #[test]
    fn render_handles_empty_shared() {
        let f = fake_run_fn(vec!["Grade: A".into(), "Grade: F\nagents/y.py:2".into()]);
        let res = stable_run(2, &StableRunOpts::default(), &f).unwrap();
        let md = render_markdown(&res);
        assert!(md.contains("UNSTABLE"));
        assert!(md.contains("no shared findings"));
    }
}
