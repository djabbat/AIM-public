//! aim-request-deduplicator — drop accidental duplicate requests within a
//! sliding TTL window.
//!
//! Use case: REPL Enter pressed twice, webhook re-fires after network blip,
//! pre-commit hook running idempotently. We catch the duplicate before it
//! reaches the LLM router (and the cost monitor).
//!
//! Port of `agents/request_deduplicator.py`. Env-driven defaults:
//!
//! ```text
//! AIM_DEDUP_TTL_S=10     # window in seconds (0 = disabled)
//! AIM_DEDUP_MAX=100      # max distinct hashes tracked
//! ```

use md5::{Digest, Md5};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Arc;

#[derive(Debug, Clone, Copy)]
pub struct DedupConfig {
    pub ttl_secs: u64,
    pub max_size: usize,
}

impl Default for DedupConfig {
    fn default() -> Self {
        Self {
            ttl_secs: 10,
            max_size: 100,
        }
    }
}

impl DedupConfig {
    pub fn from_env() -> Self {
        let ttl_secs = std::env::var("AIM_DEDUP_TTL_S")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(10);
        let max_size = std::env::var("AIM_DEDUP_MAX")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(100);
        Self { ttl_secs, max_size }
    }
}

pub trait Clock: Send + Sync {
    fn now_secs(&self) -> f64;
}

#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_secs(&self) -> f64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0)
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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DedupStats {
    pub ttl_secs: u64,
    pub max_size: usize,
    pub tracked: usize,
    pub blocked_total: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DupCheck {
    pub is_duplicate: bool,
    pub seconds_since_first_seen: f64,
}

#[derive(Debug)]
struct State {
    /// (key, ts) — pushed in insertion order; oldest at front.
    queue: VecDeque<(String, f64)>,
    blocked_total: u64,
}

pub struct Deduplicator {
    cfg: DedupConfig,
    state: Mutex<State>,
    clock: Arc<dyn Clock>,
}

impl Deduplicator {
    pub fn new(cfg: DedupConfig) -> Self {
        Self::with_clock(cfg, Arc::new(SystemClock))
    }

    pub fn with_clock(cfg: DedupConfig, clock: Arc<dyn Clock>) -> Self {
        Self {
            cfg,
            state: Mutex::new(State {
                queue: VecDeque::new(),
                blocked_total: 0,
            }),
            clock,
        }
    }

    fn hash_key(text: &str) -> String {
        let mut h = Md5::new();
        h.update(text.trim().as_bytes());
        hex::encode(h.finalize())
    }

    /// Returns `(is_dup, seconds_since_first_seen)`. `is_dup=false` also
    /// marks the request as seen (so subsequent identical calls within TTL hit).
    pub fn check(&self, text: &str) -> DupCheck {
        if self.cfg.ttl_secs == 0 || text.is_empty() {
            return DupCheck {
                is_duplicate: false,
                seconds_since_first_seen: 0.0,
            };
        }
        let key = Self::hash_key(text);
        let now = self.clock.now_secs();
        let cutoff = now - self.cfg.ttl_secs as f64;
        let mut g = self.state.lock();

        // Purge expired entries from the front of the queue
        while let Some((_, t)) = g.queue.front() {
            if *t < cutoff {
                g.queue.pop_front();
            } else {
                break;
            }
        }

        // Look for existing key (queue is small — linear scan is fine)
        if let Some(idx) = g.queue.iter().position(|(k, _)| *k == key) {
            let elapsed = now - g.queue[idx].1;
            g.blocked_total += 1;
            return DupCheck {
                is_duplicate: true,
                seconds_since_first_seen: elapsed,
            };
        }

        g.queue.push_back((key, now));
        if g.queue.len() > self.cfg.max_size {
            g.queue.pop_front();
        }
        DupCheck {
            is_duplicate: false,
            seconds_since_first_seen: 0.0,
        }
    }

    pub fn stats(&self) -> DedupStats {
        let g = self.state.lock();
        DedupStats {
            ttl_secs: self.cfg.ttl_secs,
            max_size: self.cfg.max_size,
            tracked: g.queue.len(),
            blocked_total: g.blocked_total,
        }
    }

    /// Wipe the dedup cache; returns the number of entries removed.
    pub fn clear(&self) -> usize {
        let mut g = self.state.lock();
        let n = g.queue.len();
        g.queue.clear();
        n
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make() -> (Arc<ManualClock>, Deduplicator) {
        let clock = Arc::new(ManualClock::new());
        let d = Deduplicator::with_clock(DedupConfig::default(), clock.clone());
        (clock, d)
    }

    #[test]
    fn first_call_is_not_duplicate() {
        let (clock, d) = make();
        clock.set(100.0);
        let r = d.check("hello world");
        assert!(!r.is_duplicate);
        assert_eq!(d.stats().tracked, 1);
    }

    #[test]
    fn second_identical_within_ttl_is_duplicate() {
        let (clock, d) = make();
        clock.set(100.0);
        d.check("aaa");
        clock.set(105.0);
        let r = d.check("aaa");
        assert!(r.is_duplicate);
        assert!((r.seconds_since_first_seen - 5.0).abs() < 1e-6);
    }

    #[test]
    fn after_ttl_is_not_duplicate() {
        let (clock, d) = make();
        clock.set(100.0);
        d.check("aaa");
        clock.set(120.0); // > 10s TTL
        let r = d.check("aaa");
        assert!(!r.is_duplicate);
    }

    #[test]
    fn empty_text_is_never_duplicate() {
        let (_clock, d) = make();
        assert!(!d.check("").is_duplicate);
        assert!(!d.check("").is_duplicate);
        assert_eq!(d.stats().tracked, 0);
    }

    #[test]
    fn ttl_zero_disables() {
        let cfg = DedupConfig {
            ttl_secs: 0,
            max_size: 100,
        };
        let clock = Arc::new(ManualClock::new());
        let d = Deduplicator::with_clock(cfg, clock.clone());
        clock.set(100.0);
        d.check("aaa");
        let r = d.check("aaa");
        assert!(!r.is_duplicate);
    }

    #[test]
    fn whitespace_normalised() {
        let (clock, d) = make();
        clock.set(100.0);
        d.check("hello world");
        clock.set(101.0);
        let r = d.check("  hello world  ");
        assert!(r.is_duplicate, "leading/trailing ws must hash equal");
    }

    #[test]
    fn case_sensitive() {
        let (clock, d) = make();
        clock.set(100.0);
        d.check("Hello");
        clock.set(101.0);
        // Different case → different hash → not a dup (matches Python)
        assert!(!d.check("hello").is_duplicate);
    }

    #[test]
    fn lru_eviction_when_max_exceeded() {
        let cfg = DedupConfig {
            ttl_secs: 60,
            max_size: 3,
        };
        let clock = Arc::new(ManualClock::new());
        let d = Deduplicator::with_clock(cfg, clock.clone());
        clock.set(0.0);
        d.check("a");
        d.check("b");
        d.check("c");
        d.check("d"); // evicts "a"
        assert_eq!(d.stats().tracked, 3);
        // "a" should now be re-insertable as fresh
        assert!(!d.check("a").is_duplicate);
    }

    #[test]
    fn purge_runs_on_check() {
        let (clock, d) = make();
        clock.set(0.0);
        d.check("aaa"); // ts=0
        d.check("bbb"); // ts=0
        clock.set(50.0); // 50s passed → both expired
        d.check("ccc"); // triggers purge of front
        assert_eq!(d.stats().tracked, 1);
    }

    #[test]
    fn stats_blocked_counter_increments_only_on_dup() {
        let (clock, d) = make();
        clock.set(0.0);
        d.check("a"); // not dup
        d.check("b"); // not dup
        d.check("a"); // dup
        d.check("a"); // dup
        let s = d.stats();
        assert_eq!(s.blocked_total, 2);
        assert_eq!(s.tracked, 2);
    }

    #[test]
    fn clear_returns_count_removed() {
        let (clock, d) = make();
        clock.set(0.0);
        d.check("a");
        d.check("b");
        assert_eq!(d.clear(), 2);
        assert_eq!(d.stats().tracked, 0);
    }

    #[test]
    fn config_from_env_defaults_when_unset() {
        let cfg = DedupConfig::from_env();
        // Defaults match Python module
        assert!(cfg.ttl_secs > 0);
        assert!(cfg.max_size > 0);
    }
}
