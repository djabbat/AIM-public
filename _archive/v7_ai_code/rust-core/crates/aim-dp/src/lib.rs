//! aim-dp — (ε, δ)-Differential Privacy accountant for AIM Hive.
//!
//! Linear (basic-composition) ε-budget accountant, persisted to a JSON
//! file under `~/.cache/aim/dp_accountant.json`. Cross-process safety
//! via advisory file locking (`fs2::FileExt::lock_exclusive`).
//!
//! Each `hive_telemetry::contribute()` call should `spend(eps_per_round)`
//! before the worker payload leaves the process. When the budget is
//! exhausted, the worker switches to *read-only* mode (pulls updates,
//! stops sending).
//!
//! Port of `fclc-core/src/dp/mod.rs::LinearDpAccountant`, adapted to
//! AIM's persistence + concurrency requirements.
//!
//! # Quick start
//!
//! ```no_run
//! use aim_dp::DpAccountant;
//!
//! let mut acc = DpAccountant::new(1.0)?;       // ε budget = 1.0
//! acc.spend(0.1)?;                              // one contribute() call
//! assert!(acc.remaining() > 0.0);
//! # Ok::<(), aim_dp::DpError>(())
//! ```
//!
//! # References
//!
//! - Mironov 2017, *Rényi Differential Privacy*.
//! - Dwork & Roth 2014, *Algorithmic Foundations of DP*, §3.5.1
//!   (basic composition theorem).

use rand::thread_rng;
use rand_distr::{Distribution, Normal};
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;
use fs2::FileExt;

// ---------------------------------------------------------------- defaults

const DEFAULT_BUDGET: f64 = 1.0;
const DEFAULT_EPS_PER_ROUND: f64 = 0.1;
const DEFAULT_DELTA: f64 = 1e-5;

const ENV_BUDGET: &str = "AIM_HIVE_DP_BUDGET";
const ENV_EPS_PER_ROUND: &str = "AIM_HIVE_DP_EPS_PER_ROUND";
const ENV_DELTA: &str = "AIM_HIVE_DP_DELTA";

// ---------------------------------------------------------------- errors

#[derive(Debug, Error)]
pub enum DpError {
    #[error("DP budget exhausted: requested {requested:.4}, remaining {remaining:.4}")]
    BudgetExhausted { requested: f64, remaining: f64 },

    #[error("Invalid DP parameters: {0}")]
    InvalidParams(String),

    #[error("DP accountant I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("DP accountant state corrupt: {0}")]
    Corrupt(#[from] serde_json::Error),
}

// ---------------------------------------------------------------- on-disk state

#[derive(Debug, Clone, Serialize, Deserialize)]
struct State {
    total_epsilon: f64,
    budget: f64,
}

impl State {
    fn fresh(budget: f64) -> Self {
        Self {
            total_epsilon: 0.0,
            budget,
        }
    }
}

// ---------------------------------------------------------------- accountant

/// Linear (basic-composition) ε-budget accountant.
///
/// Persists state to a JSON file. `spend()` is atomic across processes
/// on the same host via `fs2` advisory file locking.
pub struct DpAccountant {
    path: PathBuf,
    state: State,
    /// Configured budget from `new(budget)` / env. Used to detect
    /// budget changes vs. the on-disk value.
    configured_budget: f64,
}

impl DpAccountant {
    /// Create or load the accountant at the default path
    /// (`~/.cache/aim/dp_accountant.json`).
    ///
    /// `budget` overrides `AIM_HIVE_DP_BUDGET`; pass the env-resolved
    /// value via [`DpAccountant::from_env`] to honour the env.
    pub fn new(budget: f64) -> Result<Self, DpError> {
        Self::with_path(default_state_path()?, budget)
    }

    /// Read the budget from `AIM_HIVE_DP_BUDGET` (default 1.0).
    pub fn from_env() -> Result<Self, DpError> {
        Self::new(env_f64(ENV_BUDGET, DEFAULT_BUDGET, |v| v > 0.0))
    }

    /// Open / create at an explicit path.
    pub fn with_path(path: impl Into<PathBuf>, budget: f64) -> Result<Self, DpError> {
        let path = path.into();
        if budget <= 0.0 {
            return Err(DpError::InvalidParams(format!(
                "budget must be positive, got {budget}"
            )));
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let state = load_or_init(&path, budget)?;
        Ok(Self {
            path,
            state,
            configured_budget: budget,
        })
    }

    /// Atomically debit `epsilon` from the budget.
    ///
    /// Re-reads on-disk state under an exclusive lock to pick up
    /// other-process spends, then writes the new total.
    ///
    /// Errors:
    /// - [`DpError::InvalidParams`] if `epsilon <= 0`.
    /// - [`DpError::BudgetExhausted`] if the new total would exceed budget.
    pub fn spend(&mut self, epsilon: f64) -> Result<(), DpError> {
        if epsilon <= 0.0 {
            return Err(DpError::InvalidParams(format!(
                "epsilon must be positive, got {epsilon}"
            )));
        }
        let mut f = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&self.path)?;
        f.lock_exclusive()?;
        // Re-read under lock — another process may have spent.
        let mut buf = String::new();
        f.read_to_string(&mut buf)?;
        let mut state = if buf.trim().is_empty() {
            State::fresh(self.configured_budget)
        } else {
            serde_json::from_str(&buf)?
        };
        // If env-configured budget changed since last load, prefer the
        // new value (caller may have raised the limit) but keep spent.
        if state.budget != self.configured_budget {
            state.budget = self.configured_budget;
        }
        let new_total = state.total_epsilon + epsilon;
        if new_total > state.budget {
            // Don't write; release lock and report.
            let remaining = (state.budget - state.total_epsilon).max(0.0);
            f.unlock()?;
            self.state = state;
            return Err(DpError::BudgetExhausted {
                requested: epsilon,
                remaining,
            });
        }
        state.total_epsilon = new_total;
        // Atomic write: truncate + rewind + write.
        f.set_len(0)?;
        f.seek(SeekFrom::Start(0))?;
        f.write_all(serde_json::to_string(&state)?.as_bytes())?;
        f.sync_all()?;
        f.unlock()?;
        self.state = state;
        Ok(())
    }

    /// Cumulative epsilon spent so far.
    pub fn total_epsilon(&self) -> f64 {
        self.state.total_epsilon
    }

    /// Configured total budget (may differ from on-disk if env changed).
    pub fn budget(&self) -> f64 {
        self.state.budget
    }

    /// Remaining ε in the budget, clamped to ≥ 0.
    pub fn remaining(&self) -> f64 {
        (self.state.budget - self.state.total_epsilon).max(0.0)
    }

    /// Fraction of the budget consumed (clamped to ≤ 1).
    pub fn fraction_consumed(&self) -> f64 {
        if self.state.budget <= 0.0 {
            return 1.0;
        }
        (self.state.total_epsilon / self.state.budget).min(1.0)
    }

    /// Project cumulative ε after `rounds` more rounds at `eps_per_round`.
    /// Returns `(projected_total, will_exceed)`.
    pub fn epsilon_projection(&self, rounds: u32, eps_per_round: f64) -> (f64, bool) {
        let projected = self.state.total_epsilon + eps_per_round * rounds as f64;
        (projected, projected > self.state.budget)
    }

    /// Zero out the spent counter. Use for testing or a new privacy period.
    pub fn reset(&mut self) -> Result<(), DpError> {
        self.state.total_epsilon = 0.0;
        let mut f = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&self.path)?;
        f.lock_exclusive()?;
        f.write_all(serde_json::to_string(&self.state)?.as_bytes())?;
        f.sync_all()?;
        f.unlock()?;
        Ok(())
    }
}

fn load_or_init(path: &Path, configured_budget: f64) -> Result<State, DpError> {
    if !path.exists() {
        let s = State::fresh(configured_budget);
        let mut f = File::create(path)?;
        f.write_all(serde_json::to_string(&s)?.as_bytes())?;
        return Ok(s);
    }
    let s = std::fs::read_to_string(path)?;
    if s.trim().is_empty() {
        return Ok(State::fresh(configured_budget));
    }
    let mut state: State = match serde_json::from_str(&s) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!(
                error = ?e,
                path = %path.display(),
                "DP accountant state unreadable; reinitialising"
            );
            State::fresh(configured_budget)
        }
    };
    if state.budget != configured_budget {
        tracing::info!(
            old = state.budget,
            new = configured_budget,
            spent = state.total_epsilon,
            "DP budget changed; spent counter preserved"
        );
        state.budget = configured_budget;
    }
    Ok(state)
}

fn default_state_path() -> Result<PathBuf, DpError> {
    // Prefer XDG_CACHE_HOME, fall back to ~/.cache/aim.
    if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
        return Ok(PathBuf::from(xdg).join("aim").join("dp_accountant.json"));
    }
    let home = std::env::var("HOME").map_err(|_| {
        DpError::InvalidParams("HOME not set; cannot resolve default DP state path".to_string())
    })?;
    Ok(PathBuf::from(home).join(".cache").join("aim").join("dp_accountant.json"))
}

fn env_f64(name: &str, default: f64, valid: impl Fn(f64) -> bool) -> f64 {
    match std::env::var(name) {
        Ok(s) => s.parse::<f64>().ok().filter(|v| valid(*v)).unwrap_or_else(|| {
            tracing::warn!(env = name, value = %s, default, "env value invalid, using default");
            default
        }),
        Err(_) => default,
    }
}

// ---------------------------------------------------------------- noise primitives

/// σ for (ε, δ)-DP via the Gaussian mechanism, given L2 sensitivity.
///
/// `σ = sensitivity * sqrt(2 · ln(1.25 / δ)) / ε`
pub fn gaussian_noise_sigma(sensitivity: f64, epsilon: f64, delta: f64) -> Result<f64, DpError> {
    if sensitivity <= 0.0 {
        return Err(DpError::InvalidParams(format!(
            "sensitivity must be positive, got {sensitivity}"
        )));
    }
    if epsilon <= 0.0 {
        return Err(DpError::InvalidParams(format!(
            "epsilon must be positive, got {epsilon}"
        )));
    }
    if !(0.0 < delta && delta < 1.0) {
        return Err(DpError::InvalidParams(format!(
            "delta must be in (0, 1), got {delta}"
        )));
    }
    Ok(sensitivity * (2.0 * (1.25_f64 / delta).ln()).sqrt() / epsilon)
}

/// One Gaussian noise sample with σ from [`gaussian_noise_sigma`].
pub fn gaussian_noise(sensitivity: f64, epsilon: f64, delta: f64) -> Result<f64, DpError> {
    let sigma = gaussian_noise_sigma(sensitivity, epsilon, delta)?;
    let normal = Normal::new(0.0, sigma).expect("σ ≥ 0 here");
    Ok(normal.sample(&mut thread_rng()))
}

/// Add calibrated noise to every value (in-place), returning the same vec.
pub fn add_gaussian_noise(
    mut values: Vec<f64>,
    sensitivity: f64,
    epsilon: f64,
    delta: f64,
) -> Result<Vec<f64>, DpError> {
    let sigma = gaussian_noise_sigma(sensitivity, epsilon, delta)?;
    let normal = Normal::new(0.0, sigma).expect("σ ≥ 0 here");
    let mut rng = thread_rng();
    for v in values.iter_mut() {
        *v += normal.sample(&mut rng);
    }
    Ok(values)
}

/// Default per-round ε from `AIM_HIVE_DP_EPS_PER_ROUND` or 0.1.
pub fn default_eps_per_round() -> f64 {
    env_f64(ENV_EPS_PER_ROUND, DEFAULT_EPS_PER_ROUND, |v| v > 0.0)
}

/// Default δ from `AIM_HIVE_DP_DELTA` or 1e-5.
pub fn default_delta() -> f64 {
    env_f64(ENV_DELTA, DEFAULT_DELTA, |v| v > 0.0 && v < 1.0)
}

// ---------------------------------------------------------------- tests

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn spend_basic() {
        let d = tempdir().unwrap();
        let mut acc = DpAccountant::with_path(d.path().join("s.json"), 10.0).unwrap();
        acc.spend(2.0).unwrap();
        acc.spend(2.0).unwrap();
        assert_eq!(acc.total_epsilon(), 4.0);
        assert_eq!(acc.remaining(), 6.0);
    }

    #[test]
    fn budget_exhausted() {
        let d = tempdir().unwrap();
        let mut acc = DpAccountant::with_path(d.path().join("s.json"), 5.0).unwrap();
        acc.spend(4.0).unwrap();
        assert!(matches!(
            acc.spend(2.0),
            Err(DpError::BudgetExhausted { .. })
        ));
        // Failed spend must not change state.
        assert_eq!(acc.total_epsilon(), 4.0);
    }

    #[test]
    fn invalid_epsilon() {
        let d = tempdir().unwrap();
        let mut acc = DpAccountant::with_path(d.path().join("s.json"), 1.0).unwrap();
        assert!(matches!(acc.spend(0.0), Err(DpError::InvalidParams(_))));
        assert!(matches!(acc.spend(-0.1), Err(DpError::InvalidParams(_))));
    }

    #[test]
    fn fraction_and_projection() {
        let d = tempdir().unwrap();
        let mut acc = DpAccountant::with_path(d.path().join("s.json"), 1.0).unwrap();
        acc.spend(0.3).unwrap();
        assert!((acc.fraction_consumed() - 0.3).abs() < 1e-9);
        let (proj, exceed) = acc.epsilon_projection(10, 0.1);
        assert!((proj - 1.3).abs() < 1e-9);
        assert!(exceed);
    }

    #[test]
    fn persistence() {
        let d = tempdir().unwrap();
        let p = d.path().join("s.json");
        {
            let mut a = DpAccountant::with_path(&p, 5.0).unwrap();
            a.spend(2.0).unwrap();
        }
        let b = DpAccountant::with_path(&p, 5.0).unwrap();
        assert_eq!(b.total_epsilon(), 2.0);
    }

    #[test]
    fn reset() {
        let d = tempdir().unwrap();
        let p = d.path().join("s.json");
        let mut a = DpAccountant::with_path(&p, 5.0).unwrap();
        a.spend(3.0).unwrap();
        a.reset().unwrap();
        assert_eq!(a.total_epsilon(), 0.0);
    }

    #[test]
    fn gaussian_sigma() {
        let s = gaussian_noise_sigma(1.0, 1.0, 1e-5).unwrap();
        // sqrt(2 * ln(125000)) ≈ 4.84
        assert!((4.0..6.0).contains(&s));
    }

    #[test]
    fn gaussian_sigma_invalid() {
        assert!(matches!(
            gaussian_noise_sigma(0.0, 1.0, 1e-5),
            Err(DpError::InvalidParams(_))
        ));
        assert!(matches!(
            gaussian_noise_sigma(1.0, 0.0, 1e-5),
            Err(DpError::InvalidParams(_))
        ));
        assert!(matches!(
            gaussian_noise_sigma(1.0, 1.0, 0.0),
            Err(DpError::InvalidParams(_))
        ));
        assert!(matches!(
            gaussian_noise_sigma(1.0, 1.0, 1.0),
            Err(DpError::InvalidParams(_))
        ));
    }

    #[test]
    fn add_noise_changes_values() {
        let v = vec![0.0; 100];
        let noisy = add_gaussian_noise(v.clone(), 1.0, 0.1, 1e-5).unwrap();
        // With σ ≈ 48, almost no chance every value stays exactly zero.
        let n_changed = noisy.iter().filter(|x| **x != 0.0).count();
        assert!(n_changed > 90);
    }

    #[test]
    fn invalid_budget() {
        let d = tempdir().unwrap();
        assert!(matches!(
            DpAccountant::with_path(d.path().join("s.json"), 0.0),
            Err(DpError::InvalidParams(_))
        ));
    }
}
