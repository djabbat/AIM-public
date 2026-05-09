//! aim-prompt-evolver — eval-gated prompt self-improvement (S3).
//!
//! Port of `agents/prompt_evolver.py`. Closes the loop reflexion → mutate →
//! measure → ship. Persistence is `<root>/<key>/v<n>.md` files; mutation +
//! eval are pluggable via [`ReflexionSource`], [`Mutator`], and [`Runner`].
//!
//! Welch's t-test p-value is borrowed from `aim-ab-router::welch_t_p`.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use aim_ab_router::welch_t_p;

#[derive(Debug, Error)]
pub enum EvolverError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, EvolverError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CandidateResult {
    pub text: String,
    pub score: f64,
    pub cost: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    Promoted,
    Rejected,
    InsufficientReflections,
    NoChange,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProposalResult {
    pub key: String,
    pub baseline_version: i64,
    pub new_version: Option<i64>,
    pub verdict: Verdict,
    pub delta: f64,
    pub p_value: Option<f64>,
    pub note: String,
}

// ── filesystem persistence ──────────────────────────────────────────────────

pub fn current_version(root: &Path, key: &str) -> i64 {
    let dir = root.join(key);
    if !dir.exists() {
        return 0;
    }
    let mut max = 0i64;
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for e in entries.flatten() {
            if let Some(stem) = e.path().file_stem().and_then(|s| s.to_str()) {
                if let Some(rest) = stem.strip_prefix('v') {
                    if let Ok(n) = rest.parse::<i64>() {
                        if n > max {
                            max = n;
                        }
                    }
                }
            }
        }
    }
    max
}

pub fn baseline_path(root: &Path, key: &str, version: Option<i64>) -> PathBuf {
    let dir = root.join(key);
    let n = version.unwrap_or_else(|| current_version(root, key));
    dir.join(format!("v{}.md", n))
}

pub fn load_baseline(root: &Path, key: &str) -> String {
    let path = baseline_path(root, key, None);
    std::fs::read_to_string(path).unwrap_or_default()
}

pub fn persist_patch(root: &Path, key: &str, text: &str) -> Result<i64> {
    let n = current_version(root, key) + 1;
    let path = baseline_path(root, key, Some(n));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, text)?;
    Ok(n)
}

pub fn revert(root: &Path, key: &str) -> Result<Option<i64>> {
    let n = current_version(root, key);
    if n == 0 {
        return Ok(None);
    }
    let path = baseline_path(root, key, Some(n));
    if path.exists() {
        std::fs::remove_file(path)?;
    }
    Ok(Some(n))
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait ReflexionSource: Send + Sync {
    fn recent(&self, key: &str, n: usize) -> Vec<String>;
}

pub struct EmptyReflexion;
impl ReflexionSource for EmptyReflexion {
    fn recent(&self, _: &str, _: usize) -> Vec<String> {
        Vec::new()
    }
}

pub trait Mutator: Send + Sync {
    fn generate(&self, base: &str, reflections: &[String], k: usize) -> Vec<String>;
}

pub trait Runner: Send + Sync {
    /// Returns `(score: [0.0, 1.0], cost_usd)`.
    fn evaluate(&self, prompt: &str) -> (f64, f64);
}

pub trait AuditSink: Send + Sync {
    fn record(&self, result: &ProposalResult);
}

pub struct NoopAudit;
impl AuditSink for NoopAudit {
    fn record(&self, _: &ProposalResult) {}
}

// ── orchestrator ───────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct EvolverConfig {
    pub repeats: usize,
    pub k_candidates: usize,
    pub min_reflections: usize,
    pub min_delta: f64,
    pub min_p: f64,
}

impl Default for EvolverConfig {
    fn default() -> Self {
        Self {
            repeats: 3,
            k_candidates: 4,
            min_reflections: 3,
            min_delta: 0.01,
            min_p: 0.05,
        }
    }
}

pub struct Evolver<'a> {
    pub root: PathBuf,
    pub reflexion: &'a dyn ReflexionSource,
    pub mutator: &'a dyn Mutator,
    pub runner: &'a dyn Runner,
    pub audit: &'a dyn AuditSink,
}

impl<'a> Evolver<'a> {
    pub fn new(
        root: PathBuf,
        reflexion: &'a dyn ReflexionSource,
        mutator: &'a dyn Mutator,
        runner: &'a dyn Runner,
        audit: &'a dyn AuditSink,
    ) -> Self {
        Self {
            root,
            reflexion,
            mutator,
            runner,
            audit,
        }
    }

    pub fn propose(&self, key: &str, config: &EvolverConfig) -> ProposalResult {
        let base_version = current_version(&self.root, key);
        let base = load_baseline(&self.root, key);

        let reflections = self.reflexion.recent(key, 8);
        if reflections.len() < config.min_reflections {
            let r = ProposalResult {
                key: key.into(),
                baseline_version: base_version,
                new_version: None,
                verdict: Verdict::InsufficientReflections,
                delta: 0.0,
                p_value: None,
                note: format!(
                    "have {} reflections, need {}",
                    reflections.len(),
                    config.min_reflections
                ),
            };
            self.audit.record(&r);
            return r;
        }

        let candidates = self.mutator.generate(&base, &reflections, config.k_candidates);
        if candidates.is_empty() {
            let r = ProposalResult {
                key: key.into(),
                baseline_version: base_version,
                new_version: None,
                verdict: Verdict::NoChange,
                delta: 0.0,
                p_value: None,
                note: "no mutation candidates produced".into(),
            };
            self.audit.record(&r);
            return r;
        }

        let evaluate = |prompt: &str| -> Vec<CandidateResult> {
            let n = config.repeats.max(2);
            let mut runs = Vec::with_capacity(n);
            for _ in 0..n {
                let (score, cost) = self.runner.evaluate(prompt);
                runs.push(CandidateResult {
                    text: prompt.to_string(),
                    score,
                    cost,
                });
            }
            runs
        };

        let base_runs = evaluate(&base);
        let mut best: Option<(String, Vec<CandidateResult>)> = None;
        for cand in candidates {
            if cand.trim().is_empty() {
                continue;
            }
            let runs = evaluate(&cand);
            let avg = mean_score(&runs);
            match &best {
                None => best = Some((cand, runs)),
                Some((_, prev)) if avg > mean_score(prev) => {
                    best = Some((cand, runs));
                }
                _ => {}
            }
        }

        let (cand_text, cand_runs) = match best {
            Some(b) => b,
            None => {
                let r = ProposalResult {
                    key: key.into(),
                    baseline_version: base_version,
                    new_version: None,
                    verdict: Verdict::NoChange,
                    delta: 0.0,
                    p_value: None,
                    note: "no evaluable candidate".into(),
                };
                self.audit.record(&r);
                return r;
            }
        };

        let base_scores: Vec<f64> = base_runs.iter().map(|r| r.score).collect();
        let cand_scores: Vec<f64> = cand_runs.iter().map(|r| r.score).collect();
        let delta = mean(&cand_scores) - mean(&base_scores);
        let p_value = welch_t_p(&base_scores, &cand_scores);
        let cost_delta = mean(&cand_runs.iter().map(|r| r.cost).collect::<Vec<_>>())
            - mean(&base_runs.iter().map(|r| r.cost).collect::<Vec<_>>());

        let promote = delta >= config.min_delta && p_value.map_or(false, |p| p <= config.min_p);

        let r = if promote {
            let new_v = persist_patch(&self.root, key, &cand_text)
                .unwrap_or(base_version + 1);
            ProposalResult {
                key: key.into(),
                baseline_version: base_version,
                new_version: Some(new_v),
                verdict: Verdict::Promoted,
                delta,
                p_value,
                note: format!(
                    "Δ={:.3} p={:.3} cost_Δ={:.4}",
                    delta,
                    p_value.unwrap_or(f64::NAN),
                    cost_delta
                ),
            }
        } else {
            let p_str = match p_value {
                Some(p) => format!("{:.3}", p),
                None => "n/a".into(),
            };
            ProposalResult {
                key: key.into(),
                baseline_version: base_version,
                new_version: None,
                verdict: Verdict::Rejected,
                delta,
                p_value,
                note: format!("Δ={:.3} p={}", delta, p_str),
            }
        };
        self.audit.record(&r);
        r
    }
}

fn mean(xs: &[f64]) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    xs.iter().sum::<f64>() / xs.len() as f64
}

fn mean_score(runs: &[CandidateResult]) -> f64 {
    if runs.is_empty() {
        return 0.0;
    }
    runs.iter().map(|r| r.score).sum::<f64>() / runs.len() as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use tempfile::TempDir;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct FixedReflections(Vec<String>);
    impl ReflexionSource for FixedReflections {
        fn recent(&self, _: &str, _: usize) -> Vec<String> {
            self.0.clone()
        }
    }

    struct FixedMutator(Vec<String>);
    impl Mutator for FixedMutator {
        fn generate(&self, _base: &str, _r: &[String], _k: usize) -> Vec<String> {
            self.0.clone()
        }
    }

    /// Runner that returns deterministic scores per prompt prefix.
    struct ScriptedRunner {
        responses: Mutex<std::collections::HashMap<String, (f64, f64)>>,
    }
    impl ScriptedRunner {
        fn new() -> Self {
            Self {
                responses: Mutex::new(std::collections::HashMap::new()),
            }
        }
        fn set(&self, prompt: &str, score: f64, cost: f64) {
            self.responses.lock().insert(prompt.into(), (score, cost));
        }
    }
    impl Runner for ScriptedRunner {
        fn evaluate(&self, prompt: &str) -> (f64, f64) {
            self.responses
                .lock()
                .get(prompt)
                .copied()
                .unwrap_or((0.5, 0.001))
        }
    }

    #[derive(Default)]
    struct CountingAudit(Mutex<Vec<ProposalResult>>);
    impl AuditSink for CountingAudit {
        fn record(&self, r: &ProposalResult) {
            self.0.lock().push(r.clone());
        }
    }

    // ── filesystem helpers ─────────────────────────────────────────────────

    #[test]
    fn current_version_zero_when_dir_missing() {
        let tmp = TempDir::new().unwrap();
        assert_eq!(current_version(tmp.path(), "key1"), 0);
    }

    #[test]
    fn current_version_finds_max() {
        let tmp = TempDir::new().unwrap();
        let dir = tmp.path().join("k");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("v1.md"), "a").unwrap();
        std::fs::write(dir.join("v3.md"), "c").unwrap();
        std::fs::write(dir.join("v2.md"), "b").unwrap();
        std::fs::write(dir.join("notes.md"), "ignored").unwrap();
        assert_eq!(current_version(tmp.path(), "k"), 3);
    }

    #[test]
    fn persist_patch_increments_version() {
        let tmp = TempDir::new().unwrap();
        let n1 = persist_patch(tmp.path(), "k", "first").unwrap();
        let n2 = persist_patch(tmp.path(), "k", "second").unwrap();
        assert_eq!(n1, 1);
        assert_eq!(n2, 2);
        assert_eq!(load_baseline(tmp.path(), "k"), "second");
    }

    #[test]
    fn revert_drops_latest_version() {
        let tmp = TempDir::new().unwrap();
        persist_patch(tmp.path(), "k", "v1").unwrap();
        persist_patch(tmp.path(), "k", "v2").unwrap();
        let v = revert(tmp.path(), "k").unwrap();
        assert_eq!(v, Some(2));
        assert_eq!(current_version(tmp.path(), "k"), 1);
        assert_eq!(load_baseline(tmp.path(), "k"), "v1");
    }

    #[test]
    fn revert_returns_none_when_no_versions() {
        let tmp = TempDir::new().unwrap();
        assert_eq!(revert(tmp.path(), "k").unwrap(), None);
    }

    #[test]
    fn load_baseline_empty_when_missing() {
        let tmp = TempDir::new().unwrap();
        assert_eq!(load_baseline(tmp.path(), "missing"), "");
    }

    // ── propose insufficient reflections ───────────────────────────────────

    #[test]
    fn propose_insufficient_reflections_short_circuits() {
        let tmp = TempDir::new().unwrap();
        let refl = FixedReflections(vec!["one".into(), "two".into()]);
        let mut_ = FixedMutator(vec!["x".into()]);
        let runner = ScriptedRunner::new();
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let r = evo.propose("k", &EvolverConfig::default());
        assert_eq!(r.verdict, Verdict::InsufficientReflections);
        assert!(r.note.contains("have 2 reflections"));
        assert_eq!(aud.0.lock().len(), 1);
    }

    // ── propose no candidates ──────────────────────────────────────────────

    #[test]
    fn propose_no_candidates_returns_no_change() {
        let tmp = TempDir::new().unwrap();
        let refl = FixedReflections(vec!["a".into(), "b".into(), "c".into()]);
        let mut_ = FixedMutator(vec![]);
        let runner = ScriptedRunner::new();
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let r = evo.propose("k", &EvolverConfig::default());
        assert_eq!(r.verdict, Verdict::NoChange);
    }

    // ── promotion path ─────────────────────────────────────────────────────

    fn three_reflections() -> FixedReflections {
        FixedReflections(vec!["a".into(), "b".into(), "c".into()])
    }

    #[test]
    fn propose_promotes_significantly_better_candidate() {
        let tmp = TempDir::new().unwrap();
        let refl = three_reflections();
        let mut_ = FixedMutator(vec!["BETTER".into()]);
        let runner = ScriptedRunner::new();
        runner.set("", 0.50, 0.001);
        runner.set("BETTER", 0.95, 0.002);
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let mut cfg = EvolverConfig::default();
        cfg.repeats = 5;
        let r = evo.propose("k", &cfg);
        assert_eq!(r.verdict, Verdict::Promoted);
        assert!(r.delta > 0.4);
        assert!(r.p_value.unwrap() < 0.05);
        assert_eq!(r.new_version, Some(1));
        assert_eq!(load_baseline(tmp.path(), "k"), "BETTER");
    }

    #[test]
    fn propose_rejects_below_min_delta() {
        let tmp = TempDir::new().unwrap();
        let refl = three_reflections();
        let mut_ = FixedMutator(vec!["MARGINAL".into()]);
        let runner = ScriptedRunner::new();
        runner.set("", 0.50, 0.001);
        runner.set("MARGINAL", 0.505, 0.001); // tiny improvement
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let mut cfg = EvolverConfig::default();
        cfg.min_delta = 0.10;
        cfg.repeats = 5;
        let r = evo.propose("k", &cfg);
        assert_eq!(r.verdict, Verdict::Rejected);
        assert!(r.new_version.is_none());
        assert_eq!(current_version(tmp.path(), "k"), 0);
    }

    #[test]
    fn propose_picks_best_candidate_among_many() {
        let tmp = TempDir::new().unwrap();
        let refl = three_reflections();
        let mut_ = FixedMutator(vec!["LOW".into(), "MID".into(), "HIGH".into()]);
        let runner = ScriptedRunner::new();
        runner.set("", 0.30, 0.001);
        runner.set("LOW", 0.40, 0.001);
        runner.set("MID", 0.55, 0.001);
        runner.set("HIGH", 0.95, 0.001);
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let mut cfg = EvolverConfig::default();
        cfg.repeats = 5;
        let r = evo.propose("k", &cfg);
        assert_eq!(r.verdict, Verdict::Promoted);
        assert_eq!(load_baseline(tmp.path(), "k"), "HIGH");
    }

    #[test]
    fn propose_skips_empty_candidate_strings() {
        let tmp = TempDir::new().unwrap();
        let refl = three_reflections();
        let mut_ = FixedMutator(vec![
            "".into(),
            "   ".into(),
            "REAL".into(),
        ]);
        let runner = ScriptedRunner::new();
        runner.set("", 0.10, 0.001);
        runner.set("REAL", 0.90, 0.001);
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        let mut cfg = EvolverConfig::default();
        cfg.repeats = 5;
        let r = evo.propose("k", &cfg);
        assert_eq!(r.verdict, Verdict::Promoted);
        assert_eq!(load_baseline(tmp.path(), "k"), "REAL");
    }

    // ── audit sink ─────────────────────────────────────────────────────────

    #[test]
    fn audit_receives_every_proposal_outcome() {
        let tmp = TempDir::new().unwrap();
        let refl = FixedReflections(vec![]);
        let mut_ = FixedMutator(vec![]);
        let runner = ScriptedRunner::new();
        let aud = CountingAudit::default();
        let evo = Evolver::new(tmp.path().to_path_buf(), &refl, &mut_, &runner, &aud);
        evo.propose("k1", &EvolverConfig::default());
        evo.propose("k2", &EvolverConfig::default());
        assert_eq!(aud.0.lock().len(), 2);
    }
}
