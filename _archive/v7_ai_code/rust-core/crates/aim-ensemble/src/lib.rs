//! aim-ensemble — multi-model ensemble with adjudication.
//!
//! Port of `agents/ensemble.py`. For high-stakes decisions ask N models in
//! parallel; if they agree (k-shingle Jaccard ≥ threshold), return the
//! consensus; if they diverge, route to the highest-tier adjudicator
//! (Claude Opus → Gemini Pro → DeepSeek-V4-pro → Ollama).
//!
//! ## Public API
//! - [`is_critical`] — heuristic regex on the prompt; surfaces the same
//!   triggers as the Python (RU + EN: grant / submission / diagnosis /
//!   patient / dose / contract / deadline …)
//! - [`Ensemble::ask`] — fan out across tiers, score agreement, optionally
//!   adjudicate. Tiers and the adjudicator are pluggable [`Tier`] impls
//!   so the LLM HTTP layer doesn't leak in here. Tests inject stubs.
//! - [`agreement_score`] — average pairwise Jaccard over 5-shingles
//!   (exposed for separate calibration jobs).

use async_trait::async_trait;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum EnsembleError {
    #[error("no tiers configured")]
    NoTiers,
    #[error("tier {0}: {1}")]
    Tier(String, String),
}

/// One tier in the ensemble — typically backed by a single LLM provider
/// at a known temperature. The trait abstracts the HTTP layer so this
/// crate stays free of provider deps; production wires Anthropic / Gemini
/// / DeepSeek / Ollama clients.
#[async_trait]
pub trait Tier: Send + Sync {
    fn name(&self) -> &str;
    /// Returns `Ok("")` to signal "I'm not configured / unavailable" —
    /// matches the Python `_call_*` shape — without aborting the ensemble.
    async fn ask(&self, prompt: &str, system: &str) -> Result<String, EnsembleError>;
}

pub struct StubTier {
    name: String,
    queue: Mutex<Vec<Result<String, EnsembleError>>>,
}

impl StubTier {
    pub fn new(name: impl Into<String>, responses: Vec<&str>) -> Self {
        Self {
            name: name.into(),
            queue: Mutex::new(responses.into_iter().map(|s| Ok(s.to_string())).collect()),
        }
    }
    pub fn with_errors(name: impl Into<String>, responses: Vec<Result<String, &str>>) -> Self {
        Self {
            name: name.into(),
            queue: Mutex::new(
                responses
                    .into_iter()
                    .map(|r| match r {
                        Ok(s) => Ok(s),
                        Err(e) => Err(EnsembleError::Tier("stub".into(), e.to_string())),
                    })
                    .collect(),
            ),
        }
    }
}

#[async_trait]
impl Tier for StubTier {
    fn name(&self) -> &str {
        &self.name
    }
    async fn ask(&self, _prompt: &str, _system: &str) -> Result<String, EnsembleError> {
        let mut q = self.queue.lock();
        if q.is_empty() {
            return Err(EnsembleError::Tier(
                self.name.clone(),
                "stub queue exhausted".into(),
            ));
        }
        q.remove(0)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnsembleResult {
    pub answer: String,
    pub consensus: bool,
    pub individual: Vec<(String, String)>,
    pub adjudicator: Option<String>,
    /// Agreement score in [0.0, 1.0] (mean pairwise Jaccard).
    pub agreement: f64,
}

// ── Critical heuristic ──────────────────────────────────────────────────

const CRITICAL_PATTERNS: &[&str] = &[
    r"\bgrant\b",
    r"\bsubmission\b",
    r"\bdiagnos[ie]s\b",
    r"\btreatment\b",
    r"\bpatient\b",
    r"\bclinical\b",
    r"\bsurger",
    r"\bdose",
    r"\bcontraindicat",
    r"\bpublish\b",
    r"\baccept\b.*reject",
    r"\baudit\b",
    r"\bbillion\b|\bmillion\b",
    r"\bsign\b.*contract",
    r"\bdeadline\b.*today",
    r"\bdiagn",
    r"\bлеч[еи]",
    r"\bпациент",
    r"\bоперац",
    r"\bдоз[ау]",
    r"\bконтракт",
    r"\bподпис",
    r"\bдедлайн",
];

static CRITICAL_RE: OnceLock<Regex> = OnceLock::new();
fn critical_re() -> &'static Regex {
    CRITICAL_RE.get_or_init(|| {
        Regex::new(&format!("(?i){}", CRITICAL_PATTERNS.join("|")))
            .expect("critical regex must compile")
    })
}

pub fn is_critical(prompt: &str) -> bool {
    critical_re().is_match(prompt)
}

// ── Agreement score ─────────────────────────────────────────────────────

static WS_RE: OnceLock<Regex> = OnceLock::new();
static PUNCT_RE: OnceLock<Regex> = OnceLock::new();

fn normalise(s: &str) -> String {
    let ws = WS_RE.get_or_init(|| Regex::new(r"\s+").unwrap());
    let punct = PUNCT_RE.get_or_init(|| Regex::new(r"[^\w\s]").unwrap());
    let lc = s.trim().to_lowercase();
    let no_punct = punct.replace_all(&lc, "");
    let collapsed = ws.replace_all(&no_punct, " ");
    collapsed.trim().to_string()
}

fn shingle_set(s: &str, k: usize) -> HashSet<String> {
    let normalised = normalise(s);
    let toks: Vec<String> = normalised
        .split_whitespace()
        .map(String::from)
        .collect();
    if toks.len() < k {
        if toks.is_empty() {
            return HashSet::new();
        }
        let mut s = HashSet::new();
        s.insert(toks.join(" "));
        return s;
    }
    let mut out = HashSet::new();
    for i in 0..=toks.len() - k {
        out.insert(toks[i..i + k].join(" "));
    }
    out
}

fn jaccard(a: &str, b: &str) -> f64 {
    let sa = shingle_set(a, 5);
    let sb = shingle_set(b, 5);
    if sa.is_empty() || sb.is_empty() {
        return 0.0;
    }
    let inter = sa.intersection(&sb).count() as f64;
    let union = sa.union(&sb).count() as f64;
    if union == 0.0 {
        0.0
    } else {
        inter / union
    }
}

/// Average pairwise Jaccard over 5-shingles. `1.0` = identical answers,
/// `0.0` = no shared 5-grams. Empty-only inputs return 0.0; a single
/// non-empty answer trivially returns 1.0 (matches Python).
pub fn agreement_score(answers: &[String]) -> f64 {
    let filtered: Vec<&String> = answers.iter().filter(|a| !a.trim().is_empty()).collect();
    if filtered.len() < 2 {
        return if filtered.is_empty() { 0.0 } else { 1.0 };
    }
    let mut total = 0.0_f64;
    let mut pairs = 0_usize;
    for i in 0..filtered.len() {
        for j in i + 1..filtered.len() {
            total += jaccard(filtered[i], filtered[j]);
            pairs += 1;
        }
    }
    total / pairs.max(1) as f64
}

// ── Ensemble ────────────────────────────────────────────────────────────

pub struct Ensemble {
    tiers: Vec<std::sync::Arc<dyn Tier>>,
    adjudicator: Option<std::sync::Arc<dyn Tier>>,
    pub agreement_threshold: f64,
}

impl Ensemble {
    pub fn new(tiers: Vec<std::sync::Arc<dyn Tier>>) -> Self {
        Self {
            tiers,
            adjudicator: None,
            agreement_threshold: 0.35,
        }
    }

    pub fn with_threshold(mut self, t: f64) -> Self {
        self.agreement_threshold = t;
        self
    }

    pub fn with_adjudicator(mut self, a: std::sync::Arc<dyn Tier>) -> Self {
        self.adjudicator = Some(a);
        self
    }

    /// Read `AIM_ENSEMBLE_AGREE` to override the threshold. Default 0.35.
    pub fn from_env(tiers: Vec<std::sync::Arc<dyn Tier>>) -> Self {
        let t = std::env::var("AIM_ENSEMBLE_AGREE")
            .ok()
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(0.35);
        Self::new(tiers).with_threshold(t)
    }

    /// Fan out the prompt across all configured tiers in parallel; score
    /// agreement; optionally adjudicate. `force_adjudicator=true` skips
    /// the consensus check and always routes through the adjudicator.
    pub async fn ask(
        &self,
        prompt: &str,
        system: &str,
        force_adjudicator: bool,
    ) -> Result<EnsembleResult, EnsembleError> {
        if self.tiers.is_empty() {
            return Err(EnsembleError::NoTiers);
        }
        let mut futures = Vec::with_capacity(self.tiers.len());
        for tier in &self.tiers {
            let t = tier.clone();
            let p = prompt.to_string();
            let s = system.to_string();
            futures.push(tokio::spawn(async move {
                let name = t.name().to_string();
                match t.ask(&p, &s).await {
                    Ok(a) => (name, a),
                    Err(e) => {
                        tracing::warn!("tier raised: {e}");
                        (name, String::new())
                    }
                }
            }));
        }
        let mut individual: Vec<(String, String)> = Vec::with_capacity(futures.len());
        for f in futures {
            match f.await {
                Ok(pair) => individual.push(pair),
                Err(e) => tracing::warn!("join error: {e}"),
            }
        }

        let answers: Vec<String> = individual
            .iter()
            .filter_map(|(_, a)| if a.trim().is_empty() { None } else { Some(a.clone()) })
            .collect();
        let score = agreement_score(&answers);
        let consensus = !force_adjudicator && score >= self.agreement_threshold && !answers.is_empty();

        if consensus {
            // Pick the longest answer — matches Python's `max(answers, key=len)`.
            let answer = answers.iter().max_by_key(|a| a.len()).cloned().unwrap();
            return Ok(EnsembleResult {
                answer,
                consensus: true,
                individual,
                adjudicator: None,
                agreement: round3(score),
            });
        }

        // Disagreement (or forced) → route to adjudicator.
        let blocks: String = individual
            .iter()
            .filter(|(_, a)| !a.trim().is_empty())
            .map(|(t, a)| format!("=== {t} answer ===\n{a}\n"))
            .collect::<Vec<_>>()
            .join("\n");
        let adj_prompt = format!(
            "Multiple models answered the same question with conflicting outputs. \
            Read all answers, identify points of agreement and divergence, then \
            produce the best consolidated answer that resolves the disagreement. \
            Be explicit about which claims you accept, reject, or refine.\n\n\
            === ORIGINAL QUESTION ===\n{prompt}\n\n{blocks}"
        );
        let (adj_name, final_answer) = if let Some(adj) = &self.adjudicator {
            let n = adj.name().to_string();
            let a = adj.ask(&adj_prompt, system).await.unwrap_or_default();
            (n, a)
        } else {
            // No explicit adjudicator → fall back to first non-empty tier name.
            let n = individual
                .iter()
                .find(|(_, a)| !a.trim().is_empty())
                .map(|(t, _)| t.clone())
                .unwrap_or_else(|| "fallback".into());
            (n, String::new())
        };
        let answer = if !final_answer.trim().is_empty() {
            final_answer
        } else if let Some(first) = answers.first() {
            first.clone()
        } else {
            "[ensemble: no model returned an answer]".into()
        };
        Ok(EnsembleResult {
            answer,
            consensus: false,
            individual,
            adjudicator: Some(adj_name),
            agreement: round3(score),
        })
    }
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[test]
    fn is_critical_matches_grant() {
        assert!(is_critical("we need to submit the EIC grant by Friday"));
        assert!(is_critical("can the patient continue treatment with this dose?"));
        assert!(!is_critical("hello world"));
    }

    #[test]
    fn is_critical_matches_cyrillic() {
        assert!(is_critical("операция назначена на завтра"));
        assert!(is_critical("подпиши контракт"));
        assert!(is_critical("дедлайн послезавтра"));
        assert!(!is_critical("привет всем"));
    }

    #[test]
    fn agreement_identical_is_one() {
        let xs = vec!["the cat sat on the mat".to_string(); 3];
        assert!((agreement_score(&xs) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn agreement_unrelated_is_low() {
        let a = "the cat sat on the mat".to_string();
        let b = "completely different sentence about hydroponics".to_string();
        let s = agreement_score(&[a, b]);
        assert!(s < 0.05, "got {s}");
    }

    #[test]
    fn agreement_single_answer_is_one() {
        let xs = vec!["only one".to_string()];
        assert_eq!(agreement_score(&xs), 1.0);
    }

    #[test]
    fn agreement_empty_is_zero() {
        let xs: Vec<String> = vec![];
        assert_eq!(agreement_score(&xs), 0.0);
        let blanks = vec!["  ".to_string(), "".to_string()];
        assert_eq!(agreement_score(&blanks), 0.0);
    }

    #[test]
    fn shingle_short_input() {
        let s = shingle_set("hi there", 5);
        assert_eq!(s.len(), 1);
        assert!(s.contains("hi there"));
    }

    #[tokio::test]
    async fn ask_returns_consensus_when_aligned() {
        let answer = "five token deterministic answer for testing";
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new("a", vec![answer])),
            Arc::new(StubTier::new("b", vec![answer])),
            Arc::new(StubTier::new("c", vec![answer])),
        ];
        let adj = Arc::new(StubTier::new("adj", vec!["should not be called"]));
        let ens = Ensemble::new(tiers).with_adjudicator(adj.clone());
        let r = ens.ask("Q?", "", false).await.unwrap();
        assert!(r.consensus);
        assert_eq!(r.answer, answer);
        assert!(r.adjudicator.is_none());
        assert!(r.agreement >= 0.99);
    }

    #[tokio::test]
    async fn ask_routes_to_adjudicator_on_disagreement() {
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new(
                "a",
                vec!["completely separate answer about apples and oranges"],
            )),
            Arc::new(StubTier::new(
                "b",
                vec!["a totally different statement on hydroponics methods"],
            )),
            Arc::new(StubTier::new(
                "c",
                vec!["yet another unrelated sentence about astrophysics"],
            )),
        ];
        let adj = Arc::new(StubTier::new("adjudicator", vec!["consolidated final answer"]));
        let ens = Ensemble::new(tiers).with_adjudicator(adj.clone());
        let r = ens.ask("Q?", "", false).await.unwrap();
        assert!(!r.consensus);
        assert_eq!(r.adjudicator.as_deref(), Some("adjudicator"));
        assert_eq!(r.answer, "consolidated final answer");
    }

    #[tokio::test]
    async fn force_adjudicator_skips_consensus() {
        let answer = "five token deterministic answer for testing";
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new("a", vec![answer])),
            Arc::new(StubTier::new("b", vec![answer])),
        ];
        let adj = Arc::new(StubTier::new("adj", vec!["adjudicated"]));
        let ens = Ensemble::new(tiers).with_adjudicator(adj.clone());
        let r = ens.ask("Q?", "", true).await.unwrap();
        assert!(!r.consensus);
        assert_eq!(r.answer, "adjudicated");
    }

    #[tokio::test]
    async fn empty_tier_skipped_but_doesnt_break_consensus() {
        let answer = "five token deterministic answer for testing";
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new("a", vec![answer])),
            Arc::new(StubTier::new("b", vec![""])), // unconfigured
            Arc::new(StubTier::new("c", vec![answer])),
        ];
        let ens = Ensemble::new(tiers);
        let r = ens.ask("Q?", "", false).await.unwrap();
        assert!(r.consensus);
        assert_eq!(r.individual.len(), 3);
        // Only 2 non-empty answers contributed
        assert_eq!(
            r.individual
                .iter()
                .filter(|(_, a)| !a.is_empty())
                .count(),
            2
        );
    }

    #[tokio::test]
    async fn no_tiers_errors_loudly() {
        let ens = Ensemble::new(vec![]);
        let r = ens.ask("Q?", "", false).await;
        assert!(matches!(r, Err(EnsembleError::NoTiers)));
    }

    #[tokio::test]
    async fn tier_failure_treated_as_empty() {
        let answer = "five token deterministic answer for testing";
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new("a", vec![answer])),
            Arc::new(StubTier::with_errors(
                "b",
                vec![Err::<String, _>("simulated failure")],
            )),
            Arc::new(StubTier::new("c", vec![answer])),
        ];
        let ens = Ensemble::new(tiers);
        let r = ens.ask("Q?", "", false).await.unwrap();
        assert!(r.consensus);
    }

    #[tokio::test]
    async fn no_adjudicator_falls_back_to_first_answer() {
        let tiers: Vec<Arc<dyn Tier>> = vec![
            Arc::new(StubTier::new(
                "a",
                vec!["something about apples"],
            )),
            Arc::new(StubTier::new(
                "b",
                vec!["something completely different about oranges and lemons"],
            )),
        ];
        let ens = Ensemble::new(tiers); // no adjudicator
        let r = ens.ask("Q?", "", false).await.unwrap();
        assert!(!r.consensus);
        // First answer or "no model returned an answer" surfaces
        assert!(!r.answer.is_empty());
    }

    #[test]
    fn threshold_override_via_env() {
        std::env::set_var("AIM_ENSEMBLE_AGREE", "0.75");
        let tiers: Vec<Arc<dyn Tier>> = vec![Arc::new(StubTier::new("a", vec![""]))];
        let ens = Ensemble::from_env(tiers);
        assert!((ens.agreement_threshold - 0.75).abs() < 1e-9);
        std::env::remove_var("AIM_ENSEMBLE_AGREE");
    }
}
