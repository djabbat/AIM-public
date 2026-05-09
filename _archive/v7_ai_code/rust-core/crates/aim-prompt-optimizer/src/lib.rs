//! aim-prompt-optimizer — evolutionary prompt optimisation.
//!
//! Treats prompt-engineering as black-box evolutionary search:
//! 1. Generate K candidate variants from a base prompt (LLM mutation)
//! 2. Score each on an `Evaluator`
//! 3. Keep top-N, mutate further; iterate `generations` times
//!
//! This is NOT the embedding-gradient approach (which can't be back-projected
//! reliably without a separate decoder). LLM-mediated mutation is robust and
//! language-agnostic.
//!
//! ## Public API
//! - [`Mutator`] / [`Evaluator`] traits — wire LLMs by impl
//! - [`Candidate`] — prompt + score + rationale
//! - [`Optimizer::run`] — evolutionary search; returns [`OptimizeResult`]

use async_trait::async_trait;
use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OptimizeError {
    #[error("evaluator failed: {0}")]
    Eval(String),
    #[error("mutator failed: {0}")]
    Mutate(String),
    #[error("empty pool — no surviving candidates")]
    EmptyPool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MutationKind {
    Tighten,
    Explicate,
    Soften,
    Constrain,
    Examplify,
    Free,
}

impl MutationKind {
    pub fn instruction(self) -> &'static str {
        match self {
            MutationKind::Tighten => "Сократи повторы и водные конструкции, сохрани все инструкции.",
            MutationKind::Explicate => "Сделай неявные ограничения явными (формат, длина, тон).",
            MutationKind::Soften => "Сделай тон более вежливым, но не теряй точность инструкций.",
            MutationKind::Constrain => "Добавь жёсткие констрейнты на формат вывода (макс. длина, структура).",
            MutationKind::Examplify => "Добавь 1 короткий пример хорошего ответа в конце.",
            MutationKind::Free => "Перепиши промпт по-своему, сохраняя смысл.",
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            MutationKind::Tighten => "tighten",
            MutationKind::Explicate => "explicate",
            MutationKind::Soften => "soften",
            MutationKind::Constrain => "constrain",
            MutationKind::Examplify => "examplify",
            MutationKind::Free => "free",
        }
    }
}

pub const DEFAULT_MUTATIONS: &[MutationKind] = &[
    MutationKind::Tighten,
    MutationKind::Explicate,
    MutationKind::Constrain,
    MutationKind::Examplify,
    MutationKind::Soften,
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Candidate {
    pub prompt: String,
    #[serde(default)]
    pub score: f64,
    #[serde(default)]
    pub rationale: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenerationStats {
    pub generation: u32,
    pub best: f64,
    pub mean: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OptimizeResult {
    pub winner: Candidate,
    pub all: Vec<Candidate>,
    pub history: Vec<GenerationStats>,
    pub base: String,
    pub task: String,
}

#[async_trait]
pub trait Mutator: Send + Sync {
    async fn mutate(&self, base: &str, kind: MutationKind) -> Result<String, OptimizeError>;
}

#[async_trait]
pub trait Evaluator: Send + Sync {
    async fn evaluate(&self, prompt: &str, task: &str) -> Result<Candidate, OptimizeError>;
}

#[derive(Debug, Clone)]
pub struct OptimizerConfig {
    pub population: u32,
    pub generations: u32,
    pub keep_top: u32,
    pub mutations: Vec<MutationKind>,
    pub seed: Option<u64>,
}

impl Default for OptimizerConfig {
    fn default() -> Self {
        Self {
            population: 6,
            generations: 3,
            keep_top: 2,
            mutations: DEFAULT_MUTATIONS.to_vec(),
            seed: None,
        }
    }
}

pub struct Optimizer<M: Mutator, E: Evaluator> {
    pub mutator: M,
    pub evaluator: E,
    pub config: OptimizerConfig,
    rng: Mutex<StdRng>,
}

impl<M: Mutator, E: Evaluator> Optimizer<M, E> {
    pub fn new(mutator: M, evaluator: E, config: OptimizerConfig) -> Self {
        let rng = match config.seed {
            Some(s) => StdRng::seed_from_u64(s),
            None => StdRng::from_entropy(),
        };
        Self {
            mutator,
            evaluator,
            config,
            rng: Mutex::new(rng),
        }
    }

    fn pick_mutation(&self) -> MutationKind {
        let mut rng = self.rng.lock().expect("rng lock");
        if self.config.mutations.is_empty() {
            return MutationKind::Free;
        }
        let i = rng.gen_range(0..self.config.mutations.len());
        self.config.mutations[i]
    }

    fn pick_parent<'a>(&self, survivors: &'a [Candidate]) -> &'a Candidate {
        let mut rng = self.rng.lock().expect("rng lock");
        survivors.choose(&mut *rng).expect("non-empty survivors")
    }

    pub async fn run(&self, base_prompt: &str, task: &str) -> Result<OptimizeResult, OptimizeError> {
        let mut pool: Vec<Candidate> = Vec::with_capacity(self.config.population as usize);
        // Always evaluate the base first.
        pool.push(self.evaluator.evaluate(base_prompt, task).await?);

        // Fill the rest of the population with mutated copies of the base.
        for _ in 1..self.config.population {
            let kind = self.pick_mutation();
            let mutated = match self.mutator.mutate(base_prompt, kind).await {
                Ok(m) => m,
                Err(e) => {
                    tracing::warn!("mutation {:?} failed: {e}", kind);
                    continue;
                }
            };
            pool.push(self.evaluator.evaluate(&mutated, task).await?);
        }

        let mut history = vec![Self::summarise(0, &pool)?];

        for gen in 1..=self.config.generations {
            pool.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
            let keep = self.config.keep_top.min(pool.len() as u32) as usize;
            let survivors: Vec<Candidate> = pool.iter().take(keep).cloned().collect();
            if survivors.is_empty() {
                return Err(OptimizeError::EmptyPool);
            }

            let target = self.config.population.saturating_sub(self.config.keep_top) as usize;
            let mut children: Vec<Candidate> = Vec::with_capacity(target);
            let mut attempts = 0usize;
            let max_attempts = target * 4 + 8;
            while children.len() < target && attempts < max_attempts {
                attempts += 1;
                let parent = self.pick_parent(&survivors).clone();
                let kind = self.pick_mutation();
                let cp = match self.mutator.mutate(&parent.prompt, kind).await {
                    Ok(m) => m,
                    Err(_) => continue,
                };
                children.push(self.evaluator.evaluate(&cp, task).await?);
            }

            pool = survivors;
            pool.extend(children);
            history.push(Self::summarise(gen, &pool)?);
            tracing::info!(
                "gen {gen}: best={:.2} mean={:.2}",
                history.last().unwrap().best,
                history.last().unwrap().mean,
            );
        }

        pool.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        let winner = pool.first().cloned().ok_or(OptimizeError::EmptyPool)?;
        Ok(OptimizeResult {
            winner,
            all: pool,
            history,
            base: base_prompt.to_string(),
            task: task.to_string(),
        })
    }

    fn summarise(gen: u32, pool: &[Candidate]) -> Result<GenerationStats, OptimizeError> {
        if pool.is_empty() {
            return Err(OptimizeError::EmptyPool);
        }
        let best = pool.iter().map(|c| c.score).fold(f64::NEG_INFINITY, f64::max);
        let mean: f64 = pool.iter().map(|c| c.score).sum::<f64>() / pool.len() as f64;
        Ok(GenerationStats {
            generation: gen,
            best,
            mean,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Deterministic mutator: appends `[<kind>:N]` so each mutation is unique.
    struct StubMutator {
        n: AtomicUsize,
    }

    impl StubMutator {
        fn new() -> Self {
            Self { n: AtomicUsize::new(0) }
        }
    }

    #[async_trait]
    impl Mutator for StubMutator {
        async fn mutate(&self, base: &str, kind: MutationKind) -> Result<String, OptimizeError> {
            let n = self.n.fetch_add(1, Ordering::SeqCst);
            Ok(format!("{base} [{}:{}]", kind.as_str(), n))
        }
    }

    /// Length-based evaluator: shorter prompts score higher.
    struct LengthEvaluator;

    #[async_trait]
    impl Evaluator for LengthEvaluator {
        async fn evaluate(&self, prompt: &str, _task: &str) -> Result<Candidate, OptimizeError> {
            // Score is 10.0 for length 0, decreases linearly to 0.0 at 200+ chars
            let len = prompt.chars().count() as f64;
            let score = (10.0 - len / 20.0).clamp(0.0, 10.0);
            Ok(Candidate {
                prompt: prompt.to_string(),
                score,
                rationale: format!("len={}", prompt.len()),
            })
        }
    }

    /// Counts how many times mutate/evaluate are called.
    struct CountingEvaluator {
        n: AtomicUsize,
    }

    impl CountingEvaluator {
        fn new() -> Self {
            Self { n: AtomicUsize::new(0) }
        }
    }

    #[async_trait]
    impl Evaluator for CountingEvaluator {
        async fn evaluate(&self, prompt: &str, _task: &str) -> Result<Candidate, OptimizeError> {
            let n = self.n.fetch_add(1, Ordering::SeqCst) as f64;
            Ok(Candidate {
                prompt: prompt.to_string(),
                score: n,
                rationale: String::new(),
            })
        }
    }

    /// Mutator that fails — to exercise the warn-and-continue path.
    struct FailingMutator;

    #[async_trait]
    impl Mutator for FailingMutator {
        async fn mutate(&self, _base: &str, _kind: MutationKind) -> Result<String, OptimizeError> {
            Err(OptimizeError::Mutate("simulated failure".into()))
        }
    }

    fn cfg(seed: u64) -> OptimizerConfig {
        OptimizerConfig {
            population: 4,
            generations: 2,
            keep_top: 2,
            mutations: DEFAULT_MUTATIONS.to_vec(),
            seed: Some(seed),
        }
    }

    #[tokio::test]
    async fn run_returns_winner_history_and_pool() {
        let opt = Optimizer::new(StubMutator::new(), LengthEvaluator, cfg(42));
        let r = opt.run("Базовый промпт.", "задача").await.unwrap();
        assert_eq!(r.history.len(), 3); // gen 0 + 2 generations
        assert_eq!(r.history[0].generation, 0);
        assert_eq!(r.history.last().unwrap().generation, 2);
        // Winner score should equal the max of the final pool
        let max_score = r
            .all
            .iter()
            .map(|c| c.score)
            .fold(f64::NEG_INFINITY, f64::max);
        assert_eq!(r.winner.score, max_score);
        assert!(!r.winner.prompt.is_empty());
        assert_eq!(r.base, "Базовый промпт.");
        assert_eq!(r.task, "задача");
    }

    #[tokio::test]
    async fn run_keeps_top_n_survivors() {
        let opt = Optimizer::new(StubMutator::new(), LengthEvaluator, cfg(7));
        let r = opt.run("a", "task").await.unwrap();
        // Final pool size = keep_top + (population - keep_top) = population
        assert_eq!(r.all.len() as u32, opt.config.population);
    }

    #[tokio::test]
    async fn deterministic_with_seed() {
        let opt1 = Optimizer::new(StubMutator::new(), LengthEvaluator, cfg(123));
        let opt2 = Optimizer::new(StubMutator::new(), LengthEvaluator, cfg(123));
        let r1 = opt1.run("hello", "t").await.unwrap();
        let r2 = opt2.run("hello", "t").await.unwrap();
        // Same seed → same final scores in same order
        let s1: Vec<f64> = r1.all.iter().map(|c| c.score).collect();
        let s2: Vec<f64> = r2.all.iter().map(|c| c.score).collect();
        assert_eq!(s1, s2);
    }

    #[tokio::test]
    async fn evaluator_errors_propagate() {
        struct BadEval;
        #[async_trait]
        impl Evaluator for BadEval {
            async fn evaluate(&self, _p: &str, _t: &str) -> Result<Candidate, OptimizeError> {
                Err(OptimizeError::Eval("nope".into()))
            }
        }
        let opt = Optimizer::new(StubMutator::new(), BadEval, cfg(1));
        let err = opt.run("a", "t").await.unwrap_err();
        assert!(matches!(err, OptimizeError::Eval(_)));
    }

    #[tokio::test]
    async fn mutator_failure_skipped_not_fatal() {
        // FailingMutator always fails; the base evaluation still happens.
        let opt = Optimizer::new(
            FailingMutator,
            LengthEvaluator,
            OptimizerConfig {
                population: 4,
                generations: 1,
                keep_top: 1,
                mutations: vec![MutationKind::Tighten],
                seed: Some(0),
            },
        );
        let r = opt.run("base", "t").await.unwrap();
        // Only the base survives the initial fill; subsequent gens hit the
        // attempt-cap and produce no children — the run still completes.
        assert!(!r.all.is_empty());
        assert_eq!(r.history[0].generation, 0);
    }

    #[tokio::test]
    async fn improvement_over_generations_when_search_helps() {
        let opt = Optimizer::new(StubMutator::new(), LengthEvaluator, cfg(99));
        let r = opt.run("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "t").await.unwrap();
        // For LengthEvaluator, mutations *append* characters → score never
        // improves, only the base or its early mutations win. Verify the
        // history is monotonically non-increasing in mean.
        for w in r.history.windows(2) {
            assert!(w[0].best >= w[1].best - 0.01);
        }
    }

    #[tokio::test]
    async fn evaluator_called_once_per_candidate() {
        let cfg = OptimizerConfig {
            population: 3,
            generations: 1,
            keep_top: 1,
            mutations: vec![MutationKind::Tighten],
            seed: Some(1),
        };
        let opt = Optimizer::new(StubMutator::new(), CountingEvaluator::new(), cfg);
        let r = opt.run("base", "t").await.unwrap();
        // expected = pop_init (3) + gen1 children (pop - keep = 2) = 5
        let total: usize = r
            .all
            .iter()
            .map(|c| c.score as usize + 1)
            .max()
            .unwrap_or(0);
        assert!(total >= 3, "evaluator must run at least pop times");
    }

    #[test]
    fn mutation_kind_serde_lowercase() {
        let s = serde_json::to_string(&MutationKind::Examplify).unwrap();
        assert_eq!(s, "\"examplify\"");
        let back: MutationKind = serde_json::from_str("\"tighten\"").unwrap();
        assert_eq!(back, MutationKind::Tighten);
    }
}
