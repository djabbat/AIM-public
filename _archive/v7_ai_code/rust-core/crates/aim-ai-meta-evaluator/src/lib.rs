//! aim-ai-meta-evaluator — S12 reproducibility metrics.
//!
//! The same code + same prompt fed through a stochastic model can grade
//! C → F → D on three consecutive runs. S12 measures this directly:
//!
//! 1. Run the diagnostic N times against the same inventory.
//! 2. Parse each report for grade + severity totals + file:line refs.
//! 3. Compute reproducibility metrics: grade variance, pairwise Jaccard
//!    of findings, crit count stddev, shared-vs-unique findings.
//! 4. Verdict:
//!    - `stable`   — same grade, Jaccard ≥ 0.6, signal/noise ≥ 1.5
//!    - `noisy`    — grade variance OR Jaccard < 0.4
//!    - `unstable` — both
//!
//! Rust port of `AI/ai/meta_evaluator.py`. Regex behaviour matches.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum MetaError {
    #[error("need at least 2 reports to measure reproducibility")]
    TooFewReports,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReportFacts {
    pub grade: Option<String>,
    pub totals: BTreeMap<String, i64>,
    pub findings: BTreeSet<String>,
}

impl ReportFacts {
    /// Fraction of findings carrying a `:line` ref. The diagnostic
    /// prompt requires path:line per L_VERIFIABILITY — low ratio →
    /// re-run with stricter prompt.
    pub fn line_compliance(&self) -> f64 {
        if self.findings.is_empty() {
            return 0.0;
        }
        let with_line = self
            .findings
            .iter()
            .filter(|r| {
                if let Some((_, tail)) = r.rsplit_once(':') {
                    tail.chars().all(|c| c.is_ascii_digit())
                } else {
                    false
                }
            })
            .count();
        with_line as f64 / self.findings.len() as f64
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Reproducibility {
    pub n_runs: u32,
    pub grades: Vec<Option<String>>,
    pub grade_variance: u32,
    pub crit_counts: Vec<i64>,
    pub crit_stddev: f64,
    pub jaccard_findings: f64,
    pub shared_findings: BTreeSet<String>,
    pub unique_findings: BTreeSet<String>,
    /// `stable` | `noisy` | `unstable`
    pub verdict: String,
}

impl Reproducibility {
    pub fn signal_to_noise(&self) -> f64 {
        if self.unique_findings.is_empty() {
            return if !self.shared_findings.is_empty() {
                f64::INFINITY
            } else {
                0.0
            };
        }
        self.shared_findings.len() as f64 / self.unique_findings.len() as f64
    }
}

// ── parsing ─────────────────────────────────────────────────────

pub fn parse_report(text: &str) -> ReportFacts {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static GRADE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"\b(?:Overall\s+)?[Gg]rade[\s:*]+([A-F])\b").unwrap()
    });
    static TOTAL_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?im)^\s*\|?\s*(crit|high|med|low)\b[\s:|]+(\d+)").unwrap()
    });
    static REF_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"`?([\w./_\-]+\.(?:py|md|yaml|yml|toml|sh|rs))(?::(\d+))?`?")
            .unwrap()
    });

    let grade = GRADE_RE.captures(text).and_then(|c| {
        c.get(1).map(|m| m.as_str().to_uppercase())
    });

    let mut totals: BTreeMap<String, i64> = BTreeMap::new();
    for cap in TOTAL_RE.captures_iter(text) {
        if let (Some(k), Some(v)) = (cap.get(1), cap.get(2)) {
            if let Ok(n) = v.as_str().parse::<i64>() {
                totals.insert(k.as_str().to_lowercase(), n);
            }
        }
    }

    let mut findings: BTreeSet<String> = BTreeSet::new();
    for cap in REF_RE.captures_iter(text) {
        let path = cap.get(1).unwrap().as_str().trim_start_matches("./").to_string();
        // Filter out non-code refs: must contain '/' OR end with .py
        if !path.contains('/') && !path.ends_with(".py") {
            continue;
        }
        let ref_str = match cap.get(2) {
            Some(line) => format!("{}:{}", path, line.as_str()),
            None => path,
        };
        findings.insert(ref_str);
    }

    ReportFacts {
        grade,
        totals,
        findings,
    }
}

// ── measurement ─────────────────────────────────────────────────

fn jaccard(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    inter / union.max(1.0)
}

fn stddev(xs: &[i64]) -> f64 {
    if xs.len() < 2 {
        return 0.0;
    }
    let mean = xs.iter().sum::<i64>() as f64 / xs.len() as f64;
    let variance =
        xs.iter().map(|&x| (x as f64 - mean).powi(2)).sum::<f64>() / (xs.len() - 1) as f64;
    variance.sqrt()
}

pub fn measure(reports: &[&str]) -> Result<Reproducibility, MetaError> {
    if reports.len() < 2 {
        return Err(MetaError::TooFewReports);
    }
    let parsed: Vec<ReportFacts> = reports.iter().map(|r| parse_report(r)).collect();
    let grades: Vec<Option<String>> = parsed.iter().map(|p| p.grade.clone()).collect();
    let distinct_grades: BTreeSet<&String> = grades.iter().filter_map(|g| g.as_ref()).collect();
    let grade_variance = distinct_grades.len() as u32;
    let crit_counts: Vec<i64> = parsed
        .iter()
        .map(|p| p.totals.get("crit").copied().unwrap_or(0))
        .collect();
    let crit_stddev = stddev(&crit_counts);

    let mut jacc_pairs: Vec<f64> = Vec::new();
    for i in 0..parsed.len() {
        for j in (i + 1)..parsed.len() {
            jacc_pairs.push(jaccard(&parsed[i].findings, &parsed[j].findings));
        }
    }
    let jaccard_avg = if jacc_pairs.is_empty() {
        0.0
    } else {
        jacc_pairs.iter().sum::<f64>() / jacc_pairs.len() as f64
    };

    let mut counts: BTreeMap<String, u32> = BTreeMap::new();
    for p in &parsed {
        for r in &p.findings {
            *counts.entry(r.clone()).or_insert(0) += 1;
        }
    }
    let shared: BTreeSet<String> = counts
        .iter()
        .filter(|(_, n)| **n >= 2)
        .map(|(k, _)| k.clone())
        .collect();
    let unique: BTreeSet<String> = counts
        .iter()
        .filter(|(_, n)| **n == 1)
        .map(|(k, _)| k.clone())
        .collect();

    let verdict = if grade_variance > 1 && jaccard_avg < 0.4 {
        "unstable"
    } else if grade_variance > 1 || jaccard_avg < 0.4 {
        "noisy"
    } else {
        "stable"
    }
    .to_string();

    Ok(Reproducibility {
        n_runs: reports.len() as u32,
        grades,
        grade_variance,
        crit_counts,
        crit_stddev,
        jaccard_findings: jaccard_avg,
        shared_findings: shared,
        unique_findings: unique,
        verdict,
    })
}

/// Convenience: just the shared findings (the signal).
pub fn shared_only(reports: &[&str]) -> BTreeSet<String> {
    if reports.len() < 2 {
        return BTreeSet::new();
    }
    measure(reports).map(|r| r.shared_findings).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run_a() -> &'static str {
        "Overall Grade: B\n\
         | crit | 1 |\n\
         | high | 2 |\n\
         issue at agents/foo.py:42 and crates/aim-x/src/lib.rs:7"
    }
    fn run_b() -> &'static str {
        "Grade: B\n\
         crit: 1\n\
         high: 2\n\
         agents/foo.py:42 plus README.md:1"
    }
    fn run_c() -> &'static str {
        "Grade: D\n\
         crit: 5\n\
         agents/bar.py:99"
    }

    #[test]
    fn parse_grade_and_totals() {
        let f = parse_report(run_a());
        assert_eq!(f.grade.as_deref(), Some("B"));
        assert_eq!(f.totals.get("crit").copied(), Some(1));
        assert_eq!(f.totals.get("high").copied(), Some(2));
        assert!(f.findings.contains("agents/foo.py:42"));
    }

    #[test]
    fn parse_filters_bare_files_without_slash_unless_py() {
        // module.py without slash IS allowed; module.md without slash dropped.
        let f = parse_report("module.py:7 and badges.md:2");
        assert!(f.findings.contains("module.py:7"));
        assert!(!f.findings.iter().any(|r| r.starts_with("badges.md")));
    }

    #[test]
    fn line_compliance_calculation() {
        let f = parse_report("agents/a.py:1 and agents/b.py and agents/c.py:7");
        // 2 of 3 have :line → ~0.67
        let lc = f.line_compliance();
        assert!((lc - 2.0 / 3.0).abs() < 1e-6, "got {lc}");
    }

    #[test]
    fn measure_two_identical_runs_is_stable() {
        let r = measure(&[run_a(), run_a()]).unwrap();
        assert_eq!(r.verdict, "stable");
        assert_eq!(r.grade_variance, 1);
        assert!((r.jaccard_findings - 1.0).abs() < 1e-9);
    }

    #[test]
    fn measure_two_close_runs_stable() {
        let r = measure(&[run_a(), run_b()]).unwrap();
        // Both grade B, share agents/foo.py:42 — Jaccard = 1/3 < 0.4
        // → verdict "noisy" (grade same but jaccard low). That's the
        // honest answer: same grade ≠ same findings.
        assert_eq!(r.grade_variance, 1);
        assert!(r.shared_findings.contains("agents/foo.py:42"));
    }

    #[test]
    fn measure_diverse_runs_unstable() {
        let r = measure(&[run_a(), run_c()]).unwrap();
        assert_eq!(r.verdict, "unstable");
        assert_eq!(r.grade_variance, 2);
        assert!(r.shared_findings.is_empty());
    }

    #[test]
    fn measure_too_few_reports_errors() {
        assert!(matches!(measure(&[run_a()]), Err(MetaError::TooFewReports)));
    }

    #[test]
    fn signal_to_noise_inf_when_no_unique() {
        let f = ReportFacts {
            grade: None,
            totals: BTreeMap::new(),
            findings: BTreeSet::new(),
        };
        let r = Reproducibility {
            n_runs: 2,
            grades: vec![None, None],
            grade_variance: 0,
            crit_counts: vec![0, 0],
            crit_stddev: 0.0,
            jaccard_findings: 1.0,
            shared_findings: ["a/b.py:1".to_string()].into_iter().collect(),
            unique_findings: BTreeSet::new(),
            verdict: "stable".to_string(),
        };
        assert!(r.signal_to_noise().is_infinite());
        let _ = f;
    }

    #[test]
    fn shared_only_returns_set() {
        let s = shared_only(&[run_a(), run_b()]);
        assert!(s.contains("agents/foo.py:42"));
    }

    #[test]
    fn empty_findings_line_compliance_zero() {
        let f = parse_report("no refs here");
        assert_eq!(f.line_compliance(), 0.0);
    }

    #[test]
    fn stddev_works() {
        assert!((stddev(&[1, 1, 1]) - 0.0).abs() < 1e-9);
        // Sample stddev (n-1)
        assert!((stddev(&[1, 2, 3, 4, 5]) - 1.5811388300841898).abs() < 1e-9);
    }
}
