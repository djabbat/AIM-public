//! aim-adaptive-limiter — adaptive token bucket with backpressure.
//!
//! Drop-in replacement for the static `TokenBucket` in `llm.py`. Cuts the rate
//! in half after `error_threshold` consecutive failures, then slowly recovers
//! (+5% per success) up to `target_rpm` once `success_window` successes
//! accumulate.
//!
//! Port of `agents/adaptive_limiter.py`. Env-driven runtime config:
//!
//! ```text
//! AIM_RATE_ADAPTIVE=1
//! AIM_RATE_MIN_RPM=5
//! AIM_RATE_ERR_THRESHOLD=3
//! ```
//!
//! Tests inject a manual [`Clock`] to drive time deterministically — no
//! actual sleep needed.

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LimiterError {
    #[error("rate-limit wait {wait_secs:.1}s > timeout {timeout_secs:.1}s")]
    Timeout {
        wait_secs: f64,
        timeout_secs: f64,
    },
}

/// Pluggable clock used by [`AdaptiveRateLimiter`]. The real impl reads
/// `Instant`-based time; tests use [`ManualClock`] to drive time forward
/// deterministically without sleeping.
pub trait Clock: Send + Sync {
    /// Monotonic seconds since some fixed epoch.
    fn now_secs(&self) -> f64;
    /// Block the caller until `now_secs() >= deadline_secs`. Real clocks
    /// sleep; manual clocks treat this as a no-op (callers advance time
    /// manually after a successful `acquire`).
    fn sleep_until(&self, deadline_secs: f64);
}

#[derive(Debug, Default)]
pub struct SystemClock {
    epoch: parking_lot::Mutex<Option<std::time::Instant>>,
}

impl SystemClock {
    pub fn new() -> Self {
        Self::default()
    }
    fn epoch(&self) -> std::time::Instant {
        let mut g = self.epoch.lock();
        *g.get_or_insert_with(std::time::Instant::now)
    }
}

impl Clock for SystemClock {
    fn now_secs(&self) -> f64 {
        let e = self.epoch();
        e.elapsed().as_secs_f64()
    }
    fn sleep_until(&self, deadline_secs: f64) {
        let now = self.now_secs();
        let wait = deadline_secs - now;
        if wait > 0.0 {
            std::thread::sleep(Duration::from_secs_f64(wait));
        }
    }
}

#[derive(Debug, Default)]
pub struct ManualClock {
    state: Mutex<f64>,
}

impl ManualClock {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set(&self, t: f64) {
        *self.state.lock() = t;
    }
    pub fn advance(&self, delta: f64) {
        *self.state.lock() += delta;
    }
}

impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.state.lock()
    }
    fn sleep_until(&self, deadline_secs: f64) {
        let mut g = self.state.lock();
        if *g < deadline_secs {
            *g = deadline_secs;
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LimiterStats {
    pub current_rpm: f64,
    pub target_rpm: f64,
    pub min_rpm: f64,
    pub error_count: u32,
    pub success_count: u32,
    pub errors_last_5m: u32,
    pub backoff_active: bool,
    pub interval_ms: u32,
}

#[derive(Debug, Clone, Copy)]
pub struct LimiterConfig {
    pub target_rpm: f64,
    pub min_rpm: f64,
    pub error_threshold: u32,
    pub success_window: u32,
    pub history_capacity: usize,
}

impl Default for LimiterConfig {
    fn default() -> Self {
        Self {
            target_rpm: 50.0,
            min_rpm: 5.0,
            error_threshold: 3,
            success_window: 5,
            history_capacity: 100,
        }
    }
}

impl LimiterConfig {
    /// Read overrides from env (`AIM_RATE_MIN_RPM`, `AIM_RATE_ERR_THRESHOLD`).
    pub fn from_env(target_rpm: f64) -> Self {
        let min_rpm = std::env::var("AIM_RATE_MIN_RPM")
            .ok()
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(5.0);
        let error_threshold = std::env::var("AIM_RATE_ERR_THRESHOLD")
            .ok()
            .and_then(|v| v.parse::<u32>().ok())
            .unwrap_or(3);
        Self {
            target_rpm,
            min_rpm,
            error_threshold,
            success_window: 5,
            history_capacity: 100,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum HistoryKind {
    Ok,
    Err,
}

#[derive(Debug)]
struct State {
    cfg: LimiterConfig,
    current_rpm: f64,
    error_count: u32,
    success_count: u32,
    last_token_secs: f64,
    history: VecDeque<(f64, HistoryKind)>,
}

pub struct AdaptiveRateLimiter {
    state: Mutex<State>,
    clock: Arc<dyn Clock>,
}

impl AdaptiveRateLimiter {
    pub fn new(cfg: LimiterConfig) -> Self {
        Self::with_clock(cfg, Arc::new(SystemClock::new()))
    }

    pub fn with_clock(cfg: LimiterConfig, clock: Arc<dyn Clock>) -> Self {
        let now = clock.now_secs();
        // Start the bucket "ready": the next slot is one interval in the
        // past, so the first acquire goes through without waiting.
        let initial_interval = Self::interval_secs(cfg.target_rpm);
        Self {
            state: Mutex::new(State {
                cfg,
                current_rpm: cfg.target_rpm,
                error_count: 0,
                success_count: 0,
                last_token_secs: now - initial_interval,
                history: VecDeque::with_capacity(cfg.history_capacity),
            }),
            clock,
        }
    }

    fn interval_secs(rpm: f64) -> f64 {
        60.0 / rpm.max(0.1)
    }

    /// Block until `n` tokens are available, or fail after `timeout_secs`.
    pub fn acquire(&self, n: u32, timeout_secs: f64) -> Result<(), LimiterError> {
        let deadline = self.clock.now_secs() + timeout_secs;
        for _ in 0..n {
            let (wait, target) = {
                let mut g = self.state.lock();
                let now = self.clock.now_secs();
                let target = g.last_token_secs + Self::interval_secs(g.current_rpm);
                let wait = (target - now).max(0.0);
                g.last_token_secs = target.max(now);
                (wait, target)
            };
            if wait > 0.0 {
                if self.clock.now_secs() + wait > deadline {
                    return Err(LimiterError::Timeout {
                        wait_secs: wait,
                        timeout_secs,
                    });
                }
                self.clock.sleep_until(target);
            }
        }
        Ok(())
    }

    /// Try-acquire: return Ok(true) if the bucket was ready immediately,
    /// Ok(false) if the next token isn't available yet, never sleeps.
    pub fn try_acquire(&self) -> bool {
        let mut g = self.state.lock();
        let now = self.clock.now_secs();
        let target = g.last_token_secs + Self::interval_secs(g.current_rpm);
        if target <= now {
            g.last_token_secs = now;
            true
        } else {
            false
        }
    }

    pub fn record_error(&self) {
        let mut g = self.state.lock();
        g.error_count += 1;
        g.success_count = 0;
        let now = self.clock.now_secs();
        g.history.push_back((now, HistoryKind::Err));
        if g.history.len() > g.cfg.history_capacity {
            g.history.pop_front();
        }
        if g.error_count >= g.cfg.error_threshold {
            let new_rate = (g.current_rpm / 2.0).max(g.cfg.min_rpm);
            if (new_rate - g.current_rpm).abs() > f64::EPSILON {
                tracing::warn!(
                    "backpressure: {:.1} → {:.1} RPM (after {} errors)",
                    g.current_rpm,
                    new_rate,
                    g.error_count
                );
                g.current_rpm = new_rate;
            }
        }
    }

    pub fn record_success(&self) {
        let mut g = self.state.lock();
        g.success_count += 1;
        let now = self.clock.now_secs();
        g.history.push_back((now, HistoryKind::Ok));
        if g.history.len() > g.cfg.history_capacity {
            g.history.pop_front();
        }
        if g.success_count >= g.cfg.success_window && g.error_count > 0 {
            g.error_count = g.error_count.saturating_sub(1);
            g.success_count = 0;
        }
        if g.current_rpm < g.cfg.target_rpm {
            g.current_rpm = (g.current_rpm * 1.05).min(g.cfg.target_rpm);
        }
    }

    pub fn stats(&self) -> LimiterStats {
        let g = self.state.lock();
        let now = self.clock.now_secs();
        let recent_errs = g
            .history
            .iter()
            .filter(|(t, k)| *k == HistoryKind::Err && *t > now - 300.0)
            .count() as u32;
        LimiterStats {
            current_rpm: round1(g.current_rpm),
            target_rpm: g.cfg.target_rpm,
            min_rpm: g.cfg.min_rpm,
            error_count: g.error_count,
            success_count: g.success_count,
            errors_last_5m: recent_errs,
            backoff_active: g.error_count >= g.cfg.error_threshold,
            interval_ms: (Self::interval_secs(g.current_rpm) * 1000.0).round() as u32,
        }
    }

    pub fn current_rpm(&self) -> f64 {
        self.state.lock().current_rpm
    }
}

fn round1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make() -> (Arc<ManualClock>, AdaptiveRateLimiter) {
        let clock = Arc::new(ManualClock::new());
        let lim = AdaptiveRateLimiter::with_clock(LimiterConfig::default(), clock.clone());
        (clock, lim)
    }

    #[test]
    fn first_token_is_immediate() {
        let (_clock, lim) = make();
        // With last_token=now and current_rpm=50, interval=1.2s; first call
        // pushes the next slot to now+1.2 — not actually available yet.
        // Use try_acquire to confirm initial bucket state.
        assert!(lim.try_acquire(), "first token must be ready");
    }

    #[test]
    fn try_acquire_false_within_interval() {
        let (clock, lim) = make();
        clock.set(10.0);
        assert!(lim.try_acquire());
        // Next slot is +1.2s away (60/50 RPM)
        clock.set(10.5);
        assert!(!lim.try_acquire());
    }

    #[test]
    fn try_acquire_true_after_interval() {
        let (clock, lim) = make();
        clock.set(0.0);
        assert!(lim.try_acquire());
        clock.set(1.5); // > 1.2s interval
        assert!(lim.try_acquire());
    }

    #[test]
    fn acquire_advances_clock_in_manual_mode() {
        let (clock, lim) = make();
        clock.set(0.0);
        lim.acquire(2, 60.0).unwrap();
        // Two intervals consumed → clock advanced ≥ 1.2s twice
        assert!(clock.now_secs() >= 1.2, "clock = {}", clock.now_secs());
    }

    #[test]
    fn record_error_halves_rate_at_threshold() {
        let (_clock, lim) = make();
        for _ in 0..3 {
            lim.record_error();
        }
        let s = lim.stats();
        assert_eq!(s.current_rpm, 25.0);
        assert!(s.backoff_active);
    }

    #[test]
    fn record_error_floors_at_min_rpm() {
        let (_clock, lim) = make();
        for _ in 0..50 {
            lim.record_error();
        }
        // Halving from 50 capped at min_rpm=5
        assert_eq!(lim.current_rpm(), 5.0);
    }

    #[test]
    fn success_recovery_increments_5pct() {
        let (_clock, lim) = make();
        // Push to 25
        for _ in 0..3 {
            lim.record_error();
        }
        let before = lim.current_rpm();
        lim.record_success();
        let after = lim.current_rpm();
        assert!(after > before, "{} > {}", after, before);
        let expected = (before * 1.05).min(50.0);
        assert!((after - expected).abs() < 1e-6);
    }

    #[test]
    fn success_window_decrements_error_count() {
        let (_clock, lim) = make();
        for _ in 0..3 {
            lim.record_error();
        }
        assert_eq!(lim.stats().error_count, 3);
        for _ in 0..5 {
            lim.record_success();
        }
        let s = lim.stats();
        assert_eq!(s.error_count, 2);
        assert_eq!(s.success_count, 0);
    }

    #[test]
    fn current_rpm_caps_at_target() {
        let (_clock, lim) = make();
        for _ in 0..200 {
            lim.record_success();
        }
        assert_eq!(lim.current_rpm(), 50.0);
    }

    #[test]
    fn errors_last_5m_window() {
        let (clock, lim) = make();
        clock.set(0.0);
        lim.record_error();
        clock.set(60.0);
        lim.record_error();
        clock.set(400.0); // ⩾ 300s after first error → out of window
        let s = lim.stats();
        // Two errors total, both still <300s back from now=400 (one is at 60,
        // diff = 340 → outside; second at 0, diff = 400 → outside).
        assert_eq!(s.errors_last_5m, 0);
        clock.set(200.0); // bring window back: errors at 0 (diff 200) and 60 (diff 140) both inside
        let s2 = lim.stats();
        assert_eq!(s2.errors_last_5m, 2);
    }

    #[test]
    fn timeout_returns_err_when_wait_exceeds_budget() {
        let (clock, lim) = make();
        clock.set(0.0);
        // Drain initial token to push next slot out
        lim.acquire(1, 60.0).unwrap();
        // Now last_token is at ~1.2s. Asking for another token with timeout=0.1s
        // should fail because wait (1.2s) > 0.1s.
        let err = lim.acquire(1, 0.05).unwrap_err();
        match err {
            LimiterError::Timeout {
                wait_secs,
                timeout_secs,
            } => {
                assert!(wait_secs > timeout_secs);
            }
        }
    }

    #[test]
    fn stats_serialise_to_json() {
        let (_clock, lim) = make();
        let s = lim.stats();
        let raw = serde_json::to_string(&s).unwrap();
        assert!(raw.contains("\"current_rpm\""));
        assert!(raw.contains("\"backoff_active\""));
    }

    #[test]
    fn config_from_env_defaults() {
        let cfg = LimiterConfig::from_env(75.0);
        assert_eq!(cfg.target_rpm, 75.0);
        // min_rpm/threshold defaults when env unset
        assert_eq!(cfg.min_rpm, 5.0);
        assert_eq!(cfg.error_threshold, 3);
    }
}
