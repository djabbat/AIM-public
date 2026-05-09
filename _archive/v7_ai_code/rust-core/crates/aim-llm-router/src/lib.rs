//! aim-llm-router — TokenBucket + CircuitBreaker + tier routing from llm.py.
//!
//! Port of the deterministic core of `llm.py`:
//!
//!   * [`TokenBucket`] thread-safe rate limiter (rate_per_minute, capacity).
//!   * [`CircuitBreaker`] 3-state CLOSED/OPEN/HALF_OPEN with recovery.
//!   * `route(prompt) → Tier` using length + reasoning markers.
//!   * `detect_lang(text)` → ru/ka/en/zh/ar/... by Unicode block majority.
//!
//! HTTP clients live in the binary; this crate keeps the policy logic
//! that needs to be deterministic and unit-testable.

use std::collections::BTreeMap;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub trait Clock: Send + Sync {
    fn now_secs(&self) -> f64;
}

pub struct ManualClock {
    inner: Mutex<f64>,
}
impl ManualClock {
    pub fn new(t: f64) -> Self {
        Self { inner: Mutex::new(t) }
    }
    pub fn advance(&self, dt: f64) {
        *self.inner.lock() += dt;
    }
}
impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.inner.lock()
    }
}

// ── token bucket ──────────────────────────────────────────────────────────

#[derive(Debug, Error, PartialEq)]
pub enum AcquireError {
    #[error("rate-limit wait {wait_secs:.1}s exceeds timeout {timeout:.1}s")]
    Timeout { wait_secs: f64, timeout: f64 },
}

pub struct TokenBucket {
    rate_per_sec: f64,
    capacity: f64,
    tokens: Mutex<BucketState>,
}

struct BucketState {
    tokens: f64,
    last_refill: f64,
}

impl TokenBucket {
    pub fn new(rate_per_minute: u32, capacity: u32, clock: &dyn Clock) -> Self {
        let rate = (rate_per_minute.max(1) as f64) / 60.0;
        let cap = capacity.max(1) as f64;
        Self {
            rate_per_sec: rate,
            capacity: cap,
            tokens: Mutex::new(BucketState {
                tokens: cap,
                last_refill: clock.now_secs(),
            }),
        }
    }

    /// Non-blocking step: refill from elapsed time, then either grant
    /// `n` tokens (decrementing) or report how long the caller would
    /// need to wait. The Python version sleeps in a loop; we leave
    /// that to the binary so tests stay deterministic.
    pub fn try_acquire(&self, n: u32, clock: &dyn Clock) -> AcquireResult {
        let now = clock.now_secs();
        let mut g = self.tokens.lock();
        let elapsed = (now - g.last_refill).max(0.0);
        if elapsed > 0.0 {
            g.tokens = (g.tokens + elapsed * self.rate_per_sec).min(self.capacity);
            g.last_refill = now;
        }
        if g.tokens >= n as f64 {
            g.tokens -= n as f64;
            AcquireResult::Granted
        } else {
            let wait = (n as f64 - g.tokens) / self.rate_per_sec;
            AcquireResult::WaitFor { secs: wait }
        }
    }

    pub fn current_tokens(&self) -> f64 {
        self.tokens.lock().tokens
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum AcquireResult {
    Granted,
    WaitFor { secs: f64 },
}

// ── circuit breaker ───────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum BreakerState {
    Closed,
    Open,
    HalfOpen,
}

#[derive(Debug, Error, PartialEq)]
#[error("circuit open; retry in {wait_secs:.0}s")]
pub struct CircuitOpenError {
    pub wait_secs: f64,
}

pub struct CircuitBreaker {
    threshold: u32,
    recovery_secs: f64,
    inner: Mutex<BreakerInner>,
}

struct BreakerInner {
    state: BreakerState,
    failures: u32,
    opened_at: f64,
}

impl CircuitBreaker {
    pub fn new(threshold: u32, recovery_secs: f64) -> Self {
        Self {
            threshold: threshold.max(1),
            recovery_secs: recovery_secs.max(0.0),
            inner: Mutex::new(BreakerInner {
                state: BreakerState::Closed,
                failures: 0,
                opened_at: 0.0,
            }),
        }
    }

    pub fn before_call(&self, clock: &dyn Clock) -> Result<(), CircuitOpenError> {
        let mut g = self.inner.lock();
        if g.state == BreakerState::Open {
            let now = clock.now_secs();
            if now - g.opened_at >= self.recovery_secs {
                g.state = BreakerState::HalfOpen;
                return Ok(());
            }
            return Err(CircuitOpenError {
                wait_secs: self.recovery_secs - (now - g.opened_at),
            });
        }
        Ok(())
    }

    pub fn on_success(&self) {
        let mut g = self.inner.lock();
        g.failures = 0;
        g.state = BreakerState::Closed;
    }

    pub fn on_failure(&self, clock: &dyn Clock) {
        let mut g = self.inner.lock();
        g.failures += 1;
        if g.failures >= self.threshold {
            g.state = BreakerState::Open;
            g.opened_at = clock.now_secs();
        }
    }

    pub fn state(&self) -> BreakerState {
        self.inner.lock().state
    }
    pub fn failures(&self) -> u32 {
        self.inner.lock().failures
    }
}

// ── routing ──────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Tier {
    Fast,
    Default,
    Long,
    Reasoning,
    Critical,
}

const REASONING_MARKERS: &[&str] = &[
    "диагноз",
    "diagnosis",
    "дифференциальный",
    "differential",
    "анализ",
    "analysis",
    "причина",
    "cause",
    "почему",
    "why",
    "объясни механизм",
    "explain mechanism",
    "патогенез",
    "pathogenesis",
];

pub fn count_tokens_approx(text: &str) -> usize {
    text.chars().count() / 4
}

pub fn is_reasoning_task(prompt: &str) -> bool {
    let lower = prompt.to_lowercase();
    REASONING_MARKERS.iter().any(|m| lower.contains(m))
}

pub fn route(prompt: &str, long_threshold_tokens: usize) -> Tier {
    let toks = count_tokens_approx(prompt);
    if toks > long_threshold_tokens {
        return Tier::Long;
    }
    if is_reasoning_task(prompt) {
        return Tier::Reasoning;
    }
    if toks < 30 {
        return Tier::Fast;
    }
    Tier::Default
}

// ── lang detection ────────────────────────────────────────────────────────

pub fn detect_lang(text: &str) -> &'static str {
    let mut counts: BTreeMap<&'static str, u32> = BTreeMap::new();
    for ch in text.chars() {
        let c = ch as u32;
        let lang = match c {
            0x0400..=0x04FF => "ru",
            0x10D0..=0x10FF => "ka",
            0x4E00..=0x9FFF => "zh",
            0x0600..=0x06FF => "ar",
            0x41..=0x5A | 0x61..=0x7A => "en",
            _ => continue,
        };
        *counts.entry(lang).or_insert(0) += 1;
    }
    counts
        .into_iter()
        .max_by_key(|(_, n)| *n)
        .map(|(l, _)| l)
        .unwrap_or("en")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn clock() -> ManualClock {
        ManualClock::new(1000.0)
    }

    #[test]
    fn bucket_starts_full() {
        let c = clock();
        let b = TokenBucket::new(60, 10, &c);
        assert_eq!(b.current_tokens(), 10.0);
    }

    #[test]
    fn bucket_grants_until_empty() {
        let c = clock();
        let b = TokenBucket::new(60, 5, &c);
        for _ in 0..5 {
            assert_eq!(b.try_acquire(1, &c), AcquireResult::Granted);
        }
        assert!(matches!(
            b.try_acquire(1, &c),
            AcquireResult::WaitFor { .. }
        ));
    }

    #[test]
    fn bucket_refills_over_time() {
        let c = clock();
        let b = TokenBucket::new(60, 5, &c);
        for _ in 0..5 {
            b.try_acquire(1, &c);
        }
        c.advance(3.0);
        assert_eq!(b.try_acquire(3, &c), AcquireResult::Granted);
    }

    #[test]
    fn breaker_opens_after_threshold() {
        let c = clock();
        let b = CircuitBreaker::new(3, 60.0);
        b.before_call(&c).unwrap();
        for _ in 0..3 {
            b.on_failure(&c);
        }
        assert!(b.before_call(&c).is_err());
        assert_eq!(b.state(), BreakerState::Open);
    }

    #[test]
    fn breaker_recovers_to_half_open() {
        let c = clock();
        let b = CircuitBreaker::new(2, 30.0);
        b.on_failure(&c);
        b.on_failure(&c);
        c.advance(31.0);
        b.before_call(&c).unwrap();
        assert_eq!(b.state(), BreakerState::HalfOpen);
    }

    #[test]
    fn breaker_success_clears_failures() {
        let c = clock();
        let b = CircuitBreaker::new(3, 60.0);
        b.on_failure(&c);
        b.on_success();
        assert_eq!(b.failures(), 0);
    }

    #[test]
    fn route_reasoning() {
        assert_eq!(route("сравни диагнозы", 30_000), Tier::Reasoning);
    }

    #[test]
    fn route_fast_for_short() {
        assert_eq!(route("hi", 30_000), Tier::Fast);
    }

    #[test]
    fn route_long() {
        let s: String = "x".repeat(200_000);
        assert_eq!(route(&s, 30_000), Tier::Long);
    }

    #[test]
    fn route_default_for_medium() {
        let s: String = "x".repeat(800);
        assert_eq!(route(&s, 30_000), Tier::Default);
    }

    #[test]
    fn count_tokens_approx_chars_div_4() {
        assert_eq!(count_tokens_approx(&"a".repeat(100)), 25);
    }

    #[test]
    fn detect_lang_recognises_5_scripts() {
        assert_eq!(detect_lang("Привет"), "ru");
        assert_eq!(detect_lang("გამარჯობა"), "ka");
        assert_eq!(detect_lang("Hello"), "en");
        assert_eq!(detect_lang("你好"), "zh");
        assert_eq!(detect_lang("مرحبا"), "ar");
        assert_eq!(detect_lang("..."), "en");
    }

    #[test]
    fn detect_lang_majority_wins() {
        assert_eq!(detect_lang("Hello мир мир мир"), "ru");
    }
}
