//! aim-resilient-llm — retry + checkpoint wrapper around an LLM call.
//!
//! Port of `agents/resilient_llm.py`. The Python module wraps `llm.ask`
//! with tenacity (5 attempts, exponential backoff 2s..30s) and a
//! checkpoint file under `/tmp` so a crashed call can be resumed by
//! task_id. Here we keep all of that as pluggable traits — the actual
//! HTTP / filesystem stays in the binary; the retry math, the
//! checkpoint state machine, and the safe-task-id sanitiser are unit
//! tested.

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use thiserror::Error;

// ── safe task id ──────────────────────────────────────────────────────────

/// Mirrors Python: keep alphanumerics, hyphen, underscore; everything
/// else dropped; empty result becomes "noid".
pub fn safe_task_id(raw: &str) -> String {
    let s: String = raw
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect();
    if s.is_empty() {
        "noid".to_string()
    } else {
        s
    }
}

// ── checkpoint shape ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Checkpoint {
    pub task_id: String,
    pub started: Option<String>,
    pub finished: Option<String>,
    pub failed_at: Option<String>,
    pub error: Option<String>,
    pub response: Option<String>,
    pub completed: bool,
}

pub trait CheckpointStore: Send + Sync {
    fn load(&self, task_id: &str) -> Option<Checkpoint>;
    fn save(&self, ckpt: &Checkpoint);
    fn drop(&self, task_id: &str);
    fn pending(&self) -> Vec<Checkpoint>;
}

#[derive(Default)]
pub struct InMemCheckpointStore {
    inner: Mutex<BTreeMap<String, Checkpoint>>,
}

impl InMemCheckpointStore {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn len(&self) -> usize {
        self.inner.lock().len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

impl CheckpointStore for InMemCheckpointStore {
    fn load(&self, task_id: &str) -> Option<Checkpoint> {
        self.inner.lock().get(&safe_task_id(task_id)).cloned()
    }
    fn save(&self, ckpt: &Checkpoint) {
        self.inner
            .lock()
            .insert(safe_task_id(&ckpt.task_id), ckpt.clone());
    }
    fn drop(&self, task_id: &str) {
        self.inner.lock().remove(&safe_task_id(task_id));
    }
    fn pending(&self) -> Vec<Checkpoint> {
        self.inner
            .lock()
            .values()
            .filter(|c| !c.completed)
            .cloned()
            .collect()
    }
}

// ── retry ─────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum CallError {
    /// Worth retrying — flaky network, 5xx, timeout.
    #[error("transient: {0}")]
    Transient(String),
    /// Permanent — caller should not retry.
    #[error("fatal: {0}")]
    Fatal(String),
}

pub trait LlmCaller: Send + Sync {
    fn call(&self, prompt: &str, deep: bool) -> Result<String, CallError>;
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RetryPolicy {
    pub max_attempts: u32,
    pub min_wait_ms: u64,
    pub max_wait_ms: u64,
    pub multiplier: f64,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 5,
            min_wait_ms: 2_000,
            max_wait_ms: 30_000,
            multiplier: 1.0,
        }
    }
}

impl RetryPolicy {
    /// Tenacity's `wait_exponential(multiplier=m, min, max)` formula:
    /// wait = clamp(m * 2^(attempt-1), min, max), where attempt is 1-based.
    pub fn wait_for(&self, attempt: u32) -> u64 {
        if attempt <= 1 {
            return self.min_wait_ms;
        }
        let exp = 2u64
            .checked_pow(attempt.saturating_sub(1))
            .unwrap_or(u64::MAX);
        let raw = (self.multiplier * exp as f64) as u64;
        let raw = raw.saturating_mul(1_000); // multiplier is in seconds in Python
        raw.clamp(self.min_wait_ms, self.max_wait_ms)
    }
}

pub trait Sleeper: Send + Sync {
    fn sleep_ms(&self, ms: u64);
}

/// Test sleeper: records each sleep instead of blocking.
#[derive(Default)]
pub struct RecordingSleeper {
    pub waits: Mutex<Vec<u64>>,
}
impl Sleeper for RecordingSleeper {
    fn sleep_ms(&self, ms: u64) {
        self.waits.lock().push(ms);
    }
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct ManualClock {
    inner: Mutex<DateTime<Utc>>,
}
impl ManualClock {
    pub fn new(t: DateTime<Utc>) -> Self {
        Self { inner: Mutex::new(t) }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.inner.lock() = t;
    }
}
impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.inner.lock()
    }
}

pub fn retry_call(
    caller: &dyn LlmCaller,
    sleeper: &dyn Sleeper,
    policy: &RetryPolicy,
    prompt: &str,
    deep: bool,
) -> Result<String, CallError> {
    let mut last: Option<CallError> = None;
    for attempt in 1..=policy.max_attempts {
        match caller.call(prompt, deep) {
            Ok(v) => return Ok(v),
            Err(CallError::Fatal(m)) => return Err(CallError::Fatal(m)),
            Err(CallError::Transient(m)) => {
                last = Some(CallError::Transient(m));
                if attempt < policy.max_attempts {
                    sleeper.sleep_ms(policy.wait_for(attempt));
                }
            }
        }
    }
    Err(last.unwrap_or_else(|| CallError::Transient("exhausted".into())))
}

// ── resilient_ask ─────────────────────────────────────────────────────────

pub struct ResilientLlm<'a> {
    pub caller: &'a dyn LlmCaller,
    pub store: &'a dyn CheckpointStore,
    pub sleeper: &'a dyn Sleeper,
    pub clock: &'a dyn Clock,
    pub policy: RetryPolicy,
}

fn iso(now: DateTime<Utc>) -> String {
    now.format("%Y-%m-%dT%H:%M:%S").to_string()
}

impl<'a> ResilientLlm<'a> {
    pub fn ask(
        &self,
        prompt: &str,
        task_id: Option<&str>,
        deep: bool,
    ) -> Result<String, CallError> {
        if let Some(tid) = task_id {
            if let Some(ckpt) = self.store.load(tid) {
                if ckpt.completed {
                    return Ok(ckpt.response.unwrap_or_default());
                }
            }
            self.store.save(&Checkpoint {
                task_id: tid.to_string(),
                started: Some(iso(self.clock.now())),
                completed: false,
                ..Default::default()
            });
        }
        match retry_call(self.caller, self.sleeper, &self.policy, prompt, deep) {
            Ok(resp) => {
                if let Some(tid) = task_id {
                    self.store.save(&Checkpoint {
                        task_id: tid.to_string(),
                        finished: Some(iso(self.clock.now())),
                        completed: true,
                        response: Some(resp.clone()),
                        ..Default::default()
                    });
                    self.store.drop(tid);
                }
                Ok(resp)
            }
            Err(e) => {
                if let Some(tid) = task_id {
                    self.store.save(&Checkpoint {
                        task_id: tid.to_string(),
                        failed_at: Some(iso(self.clock.now())),
                        error: Some(e.to_string()),
                        completed: false,
                        ..Default::default()
                    });
                }
                Err(e)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    fn fixed_clock() -> ManualClock {
        ManualClock::new(Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap())
    }

    // ── safe_task_id ──────────────────────────────────────────────────────

    #[test]
    fn safe_id_keeps_alnum_dash_underscore() {
        assert_eq!(safe_task_id("peerrev-2026_04-29"), "peerrev-2026_04-29");
    }

    #[test]
    fn safe_id_strips_unsafe_chars() {
        assert_eq!(safe_task_id("a/b../c"), "abc");
    }

    #[test]
    fn safe_id_empty_becomes_noid() {
        assert_eq!(safe_task_id(""), "noid");
        assert_eq!(safe_task_id("/.."), "noid");
    }

    // ── retry policy ──────────────────────────────────────────────────────

    #[test]
    fn wait_for_starts_at_min() {
        let p = RetryPolicy::default();
        assert_eq!(p.wait_for(1), 2_000);
    }

    #[test]
    fn wait_for_doubles_until_max() {
        let p = RetryPolicy::default();
        assert_eq!(p.wait_for(2), 2_000);
        assert_eq!(p.wait_for(3), 4_000);
        assert_eq!(p.wait_for(4), 8_000);
        assert_eq!(p.wait_for(5), 16_000);
    }

    #[test]
    fn wait_for_clamps_to_max() {
        let p = RetryPolicy::default();
        assert_eq!(p.wait_for(10), 30_000);
    }

    // ── retry_call ────────────────────────────────────────────────────────

    struct FlakyCaller {
        fail_n: u32,
        calls: AtomicU32,
    }
    impl LlmCaller for FlakyCaller {
        fn call(&self, _: &str, _: bool) -> Result<String, CallError> {
            let n = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
            if n <= self.fail_n {
                Err(CallError::Transient("flaky".into()))
            } else {
                Ok(format!("ok after {} attempts", n))
            }
        }
    }

    struct FatalCaller;
    impl LlmCaller for FatalCaller {
        fn call(&self, _: &str, _: bool) -> Result<String, CallError> {
            Err(CallError::Fatal("bad request".into()))
        }
    }

    #[test]
    fn retry_succeeds_after_transient_failures() {
        let c = FlakyCaller {
            fail_n: 2,
            calls: AtomicU32::new(0),
        };
        let s = RecordingSleeper::default();
        let r = retry_call(&c, &s, &RetryPolicy::default(), "p", false).unwrap();
        assert!(r.starts_with("ok after 3"));
        assert_eq!(s.waits.lock().len(), 2);
    }

    #[test]
    fn retry_gives_up_after_max_attempts() {
        let c = FlakyCaller {
            fail_n: 99,
            calls: AtomicU32::new(0),
        };
        let s = RecordingSleeper::default();
        let err = retry_call(&c, &s, &RetryPolicy::default(), "p", false).unwrap_err();
        assert!(matches!(err, CallError::Transient(_)));
    }

    #[test]
    fn retry_does_not_retry_fatal() {
        let s = RecordingSleeper::default();
        let err = retry_call(&FatalCaller, &s, &RetryPolicy::default(), "p", false).unwrap_err();
        assert!(matches!(err, CallError::Fatal(_)));
        assert_eq!(s.waits.lock().len(), 0);
    }

    // ── ResilientLlm ──────────────────────────────────────────────────────

    struct OkCaller;
    impl LlmCaller for OkCaller {
        fn call(&self, p: &str, _: bool) -> Result<String, CallError> {
            Ok(format!("answer:{}", p))
        }
    }

    #[test]
    fn ask_with_no_task_id_skips_checkpoint() {
        let store = InMemCheckpointStore::new();
        let sleeper = RecordingSleeper::default();
        let clock = fixed_clock();
        let r = ResilientLlm {
            caller: &OkCaller,
            store: &store,
            sleeper: &sleeper,
            clock: &clock,
            policy: RetryPolicy::default(),
        };
        let v = r.ask("hi", None, false).unwrap();
        assert_eq!(v, "answer:hi");
        assert_eq!(store.len(), 0);
    }

    #[test]
    fn ask_resumes_completed_checkpoint() {
        let store = InMemCheckpointStore::new();
        store.save(&Checkpoint {
            task_id: "t1".into(),
            completed: true,
            response: Some("cached".into()),
            ..Default::default()
        });
        // Caller would error if called; should never run.
        struct Boom;
        impl LlmCaller for Boom {
            fn call(&self, _: &str, _: bool) -> Result<String, CallError> {
                panic!("must not be called");
            }
        }
        let sleeper = RecordingSleeper::default();
        let clock = fixed_clock();
        let r = ResilientLlm {
            caller: &Boom,
            store: &store,
            sleeper: &sleeper,
            clock: &clock,
            policy: RetryPolicy::default(),
        };
        let v = r.ask("hi", Some("t1"), false).unwrap();
        assert_eq!(v, "cached");
    }

    #[test]
    fn ask_drops_checkpoint_after_success() {
        let store = InMemCheckpointStore::new();
        let sleeper = RecordingSleeper::default();
        let clock = fixed_clock();
        let r = ResilientLlm {
            caller: &OkCaller,
            store: &store,
            sleeper: &sleeper,
            clock: &clock,
            policy: RetryPolicy::default(),
        };
        r.ask("hi", Some("t-success"), false).unwrap();
        assert!(store.load("t-success").is_none());
    }

    #[test]
    fn ask_records_failure_in_checkpoint() {
        struct AlwaysFatal;
        impl LlmCaller for AlwaysFatal {
            fn call(&self, _: &str, _: bool) -> Result<String, CallError> {
                Err(CallError::Fatal("denied".into()))
            }
        }
        let store = InMemCheckpointStore::new();
        let sleeper = RecordingSleeper::default();
        let clock = fixed_clock();
        let r = ResilientLlm {
            caller: &AlwaysFatal,
            store: &store,
            sleeper: &sleeper,
            clock: &clock,
            policy: RetryPolicy::default(),
        };
        let err = r.ask("hi", Some("t-fail"), false);
        assert!(err.is_err());
        let ck = store.load("t-fail").unwrap();
        assert!(!ck.completed);
        assert!(ck.failed_at.is_some());
        assert!(ck.error.unwrap().contains("denied"));
    }

    #[test]
    fn pending_lists_only_incomplete() {
        let store = InMemCheckpointStore::new();
        store.save(&Checkpoint {
            task_id: "ok".into(),
            completed: true,
            ..Default::default()
        });
        store.save(&Checkpoint {
            task_id: "running".into(),
            completed: false,
            ..Default::default()
        });
        let p = store.pending();
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].task_id, "running");
    }

    // ── unused — silence warnings ─────────────────────────────────────────

    #[test]
    fn arc_compat() {
        let _: Arc<dyn LlmCaller> = Arc::new(OkCaller);
    }
}
