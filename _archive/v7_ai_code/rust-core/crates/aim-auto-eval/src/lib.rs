//! aim-auto-eval — daily eval orchestrator + regression detector.
//!
//! Port of `scripts/auto_eval.py`. The Python entry point runs the
//! eval suite, persists scores by `version=YYYY-MM-DD`, compares to
//! the previous version, and pushes a notification when the
//! aggregate score regresses by ≥ threshold.
//!
//! This crate keeps the orchestration + regression-detection logic
//! and pushes I/O behind pluggable traits.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};

// ── eval data ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct EvalRun {
    pub version: String,
    pub aggregate_score: f64,
    pub n_cases: usize,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CompareResult {
    pub a: f64,
    pub b: f64,
    pub delta: f64,
    pub verdict: String,
}

pub trait EvalRunner: Send + Sync {
    fn run_all(&self, version: &str, tag_filter: Option<&str>) -> EvalRun;
    fn previous_version(&self, today: &str) -> Option<String>;
    fn compare(&self, a: &str, b: &str) -> CompareResult;
}

pub trait Notifier: Send + Sync {
    fn alert(&self, subject: &str, body: &str, dedup_key: &str);
}

#[derive(Default)]
pub struct CapturingNotifier {
    pub calls: parking_lot::Mutex<Vec<(String, String, String)>>,
}

impl CapturingNotifier {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn calls(&self) -> Vec<(String, String, String)> {
        self.calls.lock().clone()
    }
}

impl Notifier for CapturingNotifier {
    fn alert(&self, subject: &str, body: &str, dedup_key: &str) {
        self.calls
            .lock()
            .push((subject.to_string(), body.to_string(), dedup_key.to_string()));
    }
}

// ── config ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AutoEvalConfig {
    pub regression_threshold: f64,
    pub tag_filter: Option<String>,
    pub dry_run: bool,
}

impl Default for AutoEvalConfig {
    fn default() -> Self {
        Self {
            regression_threshold: 0.05,
            tag_filter: None,
            dry_run: false,
        }
    }
}

impl AutoEvalConfig {
    pub fn from_env<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let mut cfg = Self::default();
        if let Some(v) = get("AIM_EVAL_REGRESSION_THRESHOLD") {
            if let Ok(n) = v.parse::<f64>() {
                cfg.regression_threshold = n;
            }
        }
        if let Some(v) = get("AIM_EVAL_TAG_FILTER") {
            if !v.is_empty() {
                cfg.tag_filter = Some(v);
            }
        }
        if matches!(get("AIM_TG_DRYRUN").as_deref(), Some("1")) {
            cfg.dry_run = true;
        }
        cfg
    }
}

// ── exit codes (mirror the Python script) ─────────────────────────────────

pub const EXIT_OK: i32 = 0;
pub const EXIT_REGRESSION: i32 = 1;

// ── orchestration ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AutoEvalOutcome {
    pub run: EvalRun,
    pub previous: Option<String>,
    pub compare: Option<CompareResult>,
    pub regressed: bool,
    pub message: Option<String>,
    pub exit_code: i32,
}

pub fn render_regression_message(
    prev: &str,
    curr: &str,
    cmp: &CompareResult,
    threshold: f64,
    n_cases: usize,
) -> String {
    format!(
        "⚠️ Eval regression: {} → {}\n  prev_score = {:.3}\n  curr_score = {:.3}\n  Δ          = {:+.3}\n  threshold  = -{}\n  cases      = {}",
        prev, curr, cmp.a, cmp.b, cmp.delta, threshold, n_cases
    )
}

pub fn run_auto_eval(
    runner: &dyn EvalRunner,
    notifier: Option<&dyn Notifier>,
    today: NaiveDate,
    cfg: &AutoEvalConfig,
) -> AutoEvalOutcome {
    let version = today.format("%Y-%m-%d").to_string();
    let run = runner.run_all(&version, cfg.tag_filter.as_deref());
    let prev = runner.previous_version(&version);
    let mut outcome = AutoEvalOutcome {
        run: run.clone(),
        previous: prev.clone(),
        compare: None,
        regressed: false,
        message: None,
        exit_code: EXIT_OK,
    };
    let prev = match prev {
        Some(p) => p,
        None => return outcome,
    };
    let cmp = runner.compare(&prev, &version);
    outcome.compare = Some(cmp.clone());
    if cmp.delta <= -cfg.regression_threshold && cmp.verdict != "improved" {
        let msg = render_regression_message(
            &prev,
            &version,
            &cmp,
            cfg.regression_threshold,
            run.n_cases,
        );
        outcome.regressed = true;
        outcome.exit_code = EXIT_REGRESSION;
        outcome.message = Some(msg.clone());
        if !cfg.dry_run {
            if let Some(n) = notifier {
                n.alert(
                    "🩺 AIM eval regression",
                    &msg,
                    &format!("regression:{}", version),
                );
            }
        }
    }
    outcome
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    struct StubRunner {
        agg_today: f64,
        n_cases: usize,
        previous: Option<String>,
        cmp: Option<CompareResult>,
        last_tag: Mutex<Option<String>>,
    }

    impl StubRunner {
        fn new(agg: f64, n: usize, prev: Option<&str>, cmp: Option<CompareResult>) -> Self {
            Self {
                agg_today: agg,
                n_cases: n,
                previous: prev.map(String::from),
                cmp,
                last_tag: Mutex::new(None),
            }
        }
    }

    impl EvalRunner for StubRunner {
        fn run_all(&self, version: &str, tag_filter: Option<&str>) -> EvalRun {
            *self.last_tag.lock() = tag_filter.map(String::from);
            EvalRun {
                version: version.to_string(),
                aggregate_score: self.agg_today,
                n_cases: self.n_cases,
            }
        }
        fn previous_version(&self, _today: &str) -> Option<String> {
            self.previous.clone()
        }
        fn compare(&self, _a: &str, _b: &str) -> CompareResult {
            self.cmp.clone().unwrap_or_default()
        }
    }

    fn d(s: &str) -> NaiveDate {
        NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
    }

    // ── config ────────────────────────────────────────────────────────────

    #[test]
    fn config_default_values() {
        let cfg = AutoEvalConfig::default();
        assert_eq!(cfg.regression_threshold, 0.05);
        assert!(cfg.tag_filter.is_none());
        assert!(!cfg.dry_run);
    }

    #[test]
    fn config_reads_env() {
        let env = vec![
            ("AIM_EVAL_REGRESSION_THRESHOLD", "0.10"),
            ("AIM_EVAL_TAG_FILTER", "diagnosis"),
            ("AIM_TG_DRYRUN", "1"),
        ];
        let cfg = AutoEvalConfig::from_env(|k| {
            env.iter()
                .find(|(name, _)| *name == k)
                .map(|(_, v)| v.to_string())
        });
        assert_eq!(cfg.regression_threshold, 0.10);
        assert_eq!(cfg.tag_filter.as_deref(), Some("diagnosis"));
        assert!(cfg.dry_run);
    }

    #[test]
    fn config_ignores_invalid_threshold() {
        let cfg = AutoEvalConfig::from_env(|k| {
            if k == "AIM_EVAL_REGRESSION_THRESHOLD" {
                Some("nope".into())
            } else {
                None
            }
        });
        assert_eq!(cfg.regression_threshold, 0.05);
    }

    // ── orchestration ─────────────────────────────────────────────────────

    #[test]
    fn baseline_first_run_no_compare() {
        let runner = StubRunner::new(0.85, 30, None, None);
        let cfg = AutoEvalConfig::default();
        let out = run_auto_eval(&runner, None, d("2026-05-05"), &cfg);
        assert!(out.previous.is_none());
        assert!(out.compare.is_none());
        assert!(!out.regressed);
        assert_eq!(out.exit_code, EXIT_OK);
    }

    #[test]
    fn improvement_does_not_regress() {
        let cmp = CompareResult {
            a: 0.80,
            b: 0.90,
            delta: 0.10,
            verdict: "improved".into(),
        };
        let runner = StubRunner::new(0.90, 30, Some("2026-05-04"), Some(cmp));
        let out = run_auto_eval(&runner, None, d("2026-05-05"), &AutoEvalConfig::default());
        assert!(!out.regressed);
        assert_eq!(out.exit_code, EXIT_OK);
    }

    #[test]
    fn small_regression_below_threshold_silent() {
        let cmp = CompareResult {
            a: 0.85,
            b: 0.83,
            delta: -0.02,
            verdict: "stable".into(),
        };
        let runner = StubRunner::new(0.83, 30, Some("2026-05-04"), Some(cmp));
        let out = run_auto_eval(&runner, None, d("2026-05-05"), &AutoEvalConfig::default());
        assert!(!out.regressed);
    }

    #[test]
    fn big_regression_triggers_alert() {
        let cmp = CompareResult {
            a: 0.90,
            b: 0.78,
            delta: -0.12,
            verdict: "regressed".into(),
        };
        let runner = StubRunner::new(0.78, 30, Some("2026-05-04"), Some(cmp));
        let notif = CapturingNotifier::new();
        let out = run_auto_eval(
            &runner,
            Some(&notif),
            d("2026-05-05"),
            &AutoEvalConfig::default(),
        );
        assert!(out.regressed);
        assert_eq!(out.exit_code, EXIT_REGRESSION);
        let calls = notif.calls();
        assert_eq!(calls.len(), 1);
        assert!(calls[0].0.contains("regression"));
        assert_eq!(calls[0].2, "regression:2026-05-05");
    }

    #[test]
    fn dry_run_skips_notifier() {
        let cmp = CompareResult {
            a: 0.90,
            b: 0.78,
            delta: -0.12,
            verdict: "regressed".into(),
        };
        let runner = StubRunner::new(0.78, 30, Some("2026-05-04"), Some(cmp));
        let notif = CapturingNotifier::new();
        let cfg = AutoEvalConfig { dry_run: true, ..Default::default() };
        let out = run_auto_eval(&runner, Some(&notif), d("2026-05-05"), &cfg);
        assert!(out.regressed);
        assert_eq!(out.exit_code, EXIT_REGRESSION);
        assert!(out.message.is_some());
        assert_eq!(notif.calls().len(), 0);
    }

    #[test]
    fn improved_verdict_overrides_negative_delta() {
        // Edge case: delta is very negative but verdict says improved
        // (e.g., one outlier case fixed). Python's check requires both
        // delta ≤ -threshold AND verdict != improved.
        let cmp = CompareResult {
            a: 0.90,
            b: 0.78,
            delta: -0.12,
            verdict: "improved".into(),
        };
        let runner = StubRunner::new(0.78, 30, Some("2026-05-04"), Some(cmp));
        let out = run_auto_eval(&runner, None, d("2026-05-05"), &AutoEvalConfig::default());
        assert!(!out.regressed);
    }

    #[test]
    fn version_comes_from_today() {
        let runner = StubRunner::new(0.85, 30, None, None);
        let out = run_auto_eval(&runner, None, d("2026-05-05"), &AutoEvalConfig::default());
        assert_eq!(out.run.version, "2026-05-05");
    }

    #[test]
    fn tag_filter_passed_through() {
        let runner = StubRunner::new(0.85, 30, None, None);
        let cfg = AutoEvalConfig {
            tag_filter: Some("regimen".into()),
            ..Default::default()
        };
        let _ = run_auto_eval(&runner, None, d("2026-05-05"), &cfg);
        assert_eq!(runner.last_tag.lock().as_deref(), Some("regimen"));
    }

    // ── render_regression_message ─────────────────────────────────────────

    #[test]
    fn message_contains_versions_and_threshold() {
        let cmp = CompareResult {
            a: 0.90,
            b: 0.78,
            delta: -0.12,
            verdict: "regressed".into(),
        };
        let m = render_regression_message("2026-05-04", "2026-05-05", &cmp, 0.05, 30);
        assert!(m.contains("2026-05-04 → 2026-05-05"));
        assert!(m.contains("threshold  = -0.05"));
        assert!(m.contains("cases      = 30"));
    }
}
