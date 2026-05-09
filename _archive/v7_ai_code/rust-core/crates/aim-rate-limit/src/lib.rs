//! aim-rate-limit — sliding-window per-user / per-IP rate limiter.
//!
//! Port of `web/rate_limit.py`. Pluggable [`Clock`] so tests don't
//! sleep. Same semantics as Python: 60 s window, drops events older
//! than `now - 60`, returns `retry_after = max(1, oldest + 60 - now)`.

use std::collections::{BTreeMap, VecDeque};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    pub global_rpm: u32,
    pub webhook_rpm: u32,
    pub burst: u32,
    pub user_mult: u32,
    pub trust_proxy: bool,
    pub whitelist: Vec<String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            global_rpm: 60,
            webhook_rpm: 10,
            burst: 20,
            user_mult: 2,
            trust_proxy: false,
            whitelist: vec!["127.0.0.1".into(), "::1".into()],
        }
    }
}

impl Config {
    pub fn from_env<F: Fn(&str) -> Option<String>>(get: F) -> Self {
        let mut c = Self::default();
        if let Some(v) = get("AIM_API_RATE_LIMIT").and_then(|s| s.parse().ok()) {
            c.global_rpm = v;
        }
        if let Some(v) = get("AIM_API_RATE_WEBHOOK").and_then(|s| s.parse().ok()) {
            c.webhook_rpm = v;
        }
        if let Some(v) = get("AIM_API_RATE_BURST").and_then(|s| s.parse().ok()) {
            c.burst = v;
        }
        if let Some(v) = get("AIM_API_RATE_USER_MULT").and_then(|s| s.parse().ok()) {
            c.user_mult = v;
        }
        if let Some(v) = get("AIM_API_RATE_TRUST_PROXY") {
            c.trust_proxy = matches!(v.to_lowercase().as_str(), "1" | "true" | "yes");
        }
        if let Some(v) = get("AIM_API_RATE_WHITELIST") {
            c.whitelist = v
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
        }
        c
    }
}

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
    pub fn set(&self, t: f64) {
        *self.inner.lock() = t;
    }
}
impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.inner.lock()
    }
}

#[derive(Default)]
pub struct Limiter {
    buckets: Mutex<BTreeMap<String, VecDeque<f64>>>,
    blocked_total: Mutex<u64>,
}

impl Limiter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn check(
        &self,
        key: &str,
        ip: &str,
        rpm: u32,
        cfg: &Config,
        clock: &dyn Clock,
    ) -> CheckResult {
        if rpm == 0 || self.is_whitelisted(ip, cfg) {
            return CheckResult::Allowed { remaining: rpm };
        }
        let now = clock.now_secs();
        let cutoff = now - 60.0;
        let mut g = self.buckets.lock();
        let bucket = g.entry(key.to_string()).or_default();
        while let Some(&t) = bucket.front() {
            if t < cutoff {
                bucket.pop_front();
            } else {
                break;
            }
        }
        if (bucket.len() as u32) >= rpm {
            *self.blocked_total.lock() += 1;
            let oldest = *bucket.front().unwrap();
            let retry = ((oldest + 60.0 - now) as i64).max(1) as u32;
            return CheckResult::Denied { retry_secs: retry };
        }
        bucket.push_back(now);
        CheckResult::Allowed {
            remaining: rpm - bucket.len() as u32,
        }
    }

    pub fn is_whitelisted(&self, ip: &str, cfg: &Config) -> bool {
        if cfg.whitelist.iter().any(|w| w == ip) {
            return true;
        }
        // CIDR / ip_network parsing is left to the binary; here we only
        // do exact string matching, sufficient for unit tests and the
        // common 127.0.0.1 / ::1 case.
        false
    }

    pub fn tracked_keys(&self) -> usize {
        self.buckets.lock().len()
    }

    pub fn blocked_total(&self) -> u64 {
        *self.blocked_total.lock()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum CheckResult {
    Allowed { remaining: u32 },
    Denied { retry_secs: u32 },
}

pub fn rpm_for_path(cfg: &Config, path: &str, mult: u32) -> u32 {
    let base = if path.starts_with("/webhook/") {
        cfg.webhook_rpm
    } else {
        cfg.global_rpm
    };
    base * mult
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> Config {
        Config::default()
    }

    // ── config ────────────────────────────────────────────────────────────

    #[test]
    fn config_from_env_overrides() {
        let env = vec![
            ("AIM_API_RATE_LIMIT", "100"),
            ("AIM_API_RATE_USER_MULT", "5"),
            ("AIM_API_RATE_TRUST_PROXY", "true"),
            ("AIM_API_RATE_WHITELIST", "10.0.0.1,10.0.0.2"),
        ];
        let c = Config::from_env(|k| {
            env.iter()
                .find(|(name, _)| *name == k)
                .map(|(_, v)| v.to_string())
        });
        assert_eq!(c.global_rpm, 100);
        assert_eq!(c.user_mult, 5);
        assert!(c.trust_proxy);
        assert_eq!(c.whitelist, vec!["10.0.0.1", "10.0.0.2"]);
    }

    // ── rpm_for_path ──────────────────────────────────────────────────────

    #[test]
    fn webhook_path_uses_webhook_rpm() {
        let c = cfg();
        assert_eq!(rpm_for_path(&c, "/webhook/telegram", 1), 10);
    }

    #[test]
    fn user_mult_applied() {
        let c = cfg();
        assert_eq!(rpm_for_path(&c, "/api/x", 2), 120);
    }

    // ── limiter ───────────────────────────────────────────────────────────

    #[test]
    fn first_request_allowed() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let r = l.check("user:1", "10.0.0.1", 60, &cfg(), &clock);
        assert!(matches!(r, CheckResult::Allowed { .. }));
    }

    #[test]
    fn excess_requests_denied() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let c = cfg();
        for _ in 0..60 {
            assert!(matches!(
                l.check("user:1", "10.0.0.1", 60, &c, &clock),
                CheckResult::Allowed { .. }
            ));
        }
        let r = l.check("user:1", "10.0.0.1", 60, &c, &clock);
        let CheckResult::Denied { retry_secs } = r else {
            panic!("expected denial");
        };
        assert!(retry_secs >= 1);
        assert_eq!(l.blocked_total(), 1);
    }

    #[test]
    fn old_events_evicted_after_60s() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let c = cfg();
        for _ in 0..60 {
            l.check("user:1", "10.0.0.1", 60, &c, &clock);
        }
        // Past the window — bucket cleared
        clock.advance(61.0);
        let r = l.check("user:1", "10.0.0.1", 60, &c, &clock);
        assert!(matches!(r, CheckResult::Allowed { .. }));
    }

    #[test]
    fn whitelist_skips_check() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let c = cfg();
        for _ in 0..200 {
            assert!(matches!(
                l.check("ip:127.0.0.1", "127.0.0.1", 1, &c, &clock),
                CheckResult::Allowed { .. }
            ));
        }
    }

    #[test]
    fn separate_keys_have_independent_buckets() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let c = cfg();
        for _ in 0..60 {
            l.check("user:1", "10.0.0.1", 60, &c, &clock);
        }
        // user:2 should still be allowed
        assert!(matches!(
            l.check("user:2", "10.0.0.2", 60, &c, &clock),
            CheckResult::Allowed { .. }
        ));
    }

    #[test]
    fn rpm_zero_means_no_limit() {
        let l = Limiter::new();
        let clock = ManualClock::new(1000.0);
        let c = cfg();
        for _ in 0..1000 {
            assert!(matches!(
                l.check("k", "1.2.3.4", 0, &c, &clock),
                CheckResult::Allowed { .. }
            ));
        }
    }
}
