//! aim-recall-perf — slow-query detector + LRU cache (SL1).
//!
//! Port of `agents/recall_perf.py`. Wraps any retrieval callable with
//! two non-invasive layers:
//!
//! 1. **Per-call latency log** — anything ≥ `slow_threshold_ms` (default
//!    500) is appended to the JSONL audit at `$AIM_HOME/recall_slow.jsonl`.
//! 2. **Hot-query LRU cache** — same `(query, k)` asked within
//!    `cache_ttl_secs` returns the cached result (capacity-bounded).
//!
//! ## Pluggable
//! Generic over a `Retriever` (closure / trait object) and a [`Clock`] so
//! tests can drive time deterministically.

use chrono::Utc;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PerfError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Copy)]
pub struct PerfConfig {
    pub slow_threshold_ms: u64,
    pub cache_ttl_secs: f64,
    pub cache_max_entries: usize,
}

impl Default for PerfConfig {
    fn default() -> Self {
        Self {
            slow_threshold_ms: 500,
            cache_ttl_secs: 60.0,
            cache_max_entries: 32,
        }
    }
}

impl PerfConfig {
    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        Self {
            slow_threshold_ms: get("AIM_RECALL_SLOW_MS")
                .and_then(|v| v.parse().ok())
                .unwrap_or(500),
            cache_ttl_secs: get("AIM_RECALL_CACHE_TTL")
                .and_then(|v| v.parse().ok())
                .unwrap_or(60.0),
            cache_max_entries: get("AIM_RECALL_CACHE_MAX")
                .and_then(|v| v.parse().ok())
                .unwrap_or(32),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PerfStats {
    pub n_calls: u64,
    pub n_cache_hits: u64,
    pub n_slow: u64,
    pub cache_size: usize,
    /// Up to 20 most recent slow queries: (query_excerpt, latency_ms).
    pub top_slow: Vec<(String, u64)>,
}

pub trait Clock: Send + Sync {
    /// Wall-clock seconds since epoch — used for cache TTL bookkeeping.
    fn now_secs(&self) -> f64;
    /// Monotonic ms — only the *delta* matters; suitable for latency.
    fn now_ms(&self) -> u64;
}

#[derive(Debug, Default)]
pub struct SystemClock {
    epoch: parking_lot::Mutex<Option<std::time::Instant>>,
}

impl SystemClock {
    pub fn new() -> Self {
        Self::default()
    }
    fn instant_epoch(&self) -> std::time::Instant {
        let mut g = self.epoch.lock();
        *g.get_or_insert_with(std::time::Instant::now)
    }
}

impl Clock for SystemClock {
    fn now_secs(&self) -> f64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0)
    }
    fn now_ms(&self) -> u64 {
        self.instant_epoch().elapsed().as_millis() as u64
    }
}

#[derive(Debug)]
pub struct ManualClock {
    secs: Mutex<f64>,
    ms: Mutex<u64>,
}

impl ManualClock {
    pub fn new() -> Self {
        Self {
            secs: Mutex::new(0.0),
            ms: Mutex::new(0),
        }
    }
    pub fn set_secs(&self, t: f64) {
        *self.secs.lock() = t;
    }
    pub fn set_ms(&self, t: u64) {
        *self.ms.lock() = t;
    }
    pub fn advance_secs(&self, d: f64) {
        *self.secs.lock() += d;
    }
    pub fn advance_ms(&self, d: u64) {
        *self.ms.lock() += d;
    }
}

impl Default for ManualClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.secs.lock()
    }
    fn now_ms(&self) -> u64 {
        *self.ms.lock()
    }
}

#[derive(Debug)]
struct CacheEntry<R> {
    inserted_secs: f64,
    value: R,
}

/// Wraps a retriever closure. Generic over the result type so the host
/// can plug whatever `retrieve()` returns (typically `Vec<Chunk>`).
pub struct RecallPerf<R: Clone + Send + Sync> {
    cfg: PerfConfig,
    clock: Arc<dyn Clock>,
    /// (key) → entry. Insertion order encodes LRU; we promote on hit.
    cache: Mutex<Vec<((String, u32), CacheEntry<R>)>>,
    n_calls: Mutex<u64>,
    n_cache_hits: Mutex<u64>,
    n_slow: Mutex<u64>,
    slow_queries: Mutex<VecDeque<(String, u64)>>,
    audit_path: Option<PathBuf>,
}

impl<R: Clone + Send + Sync> RecallPerf<R> {
    pub fn new(cfg: PerfConfig, clock: Arc<dyn Clock>, audit_path: Option<PathBuf>) -> Self {
        Self {
            cfg,
            clock,
            cache: Mutex::new(Vec::new()),
            n_calls: Mutex::new(0),
            n_cache_hits: Mutex::new(0),
            n_slow: Mutex::new(0),
            slow_queries: Mutex::new(VecDeque::with_capacity(20)),
            audit_path,
        }
    }

    /// Cached call to the underlying retriever. The retriever is a
    /// closure that takes `(query, k)` and returns `R`. Cache hits skip
    /// the retriever entirely.
    pub fn retrieve<F>(&self, query: &str, k: u32, retriever: F) -> R
    where
        F: FnOnce(&str, u32) -> R,
    {
        *self.n_calls.lock() += 1;
        let key = (query.to_string(), k);
        let now_secs = self.clock.now_secs();

        // Cache lookup with TTL & LRU promotion
        {
            let mut g = self.cache.lock();
            if let Some(idx) = g.iter().position(|(k_, _)| k_ == &key) {
                let entry = &g[idx].1;
                if (now_secs - entry.inserted_secs) <= self.cfg.cache_ttl_secs {
                    let value = entry.value.clone();
                    // Promote to most-recent end
                    let pair = g.remove(idx);
                    g.push(pair);
                    *self.n_cache_hits.lock() += 1;
                    return value;
                }
                // Stale — drop and refetch
                g.remove(idx);
            }
        }

        let t0 = self.clock.now_ms();
        let value = retriever(query, k);
        let latency_ms = self.clock.now_ms().saturating_sub(t0);

        {
            let mut g = self.cache.lock();
            g.push((
                key,
                CacheEntry {
                    inserted_secs: now_secs,
                    value: value.clone(),
                },
            ));
            while g.len() > self.cfg.cache_max_entries {
                g.remove(0);
            }
            if latency_ms >= self.cfg.slow_threshold_ms {
                *self.n_slow.lock() += 1;
                let mut sq = self.slow_queries.lock();
                let excerpt: String = query.chars().take(120).collect();
                sq.push_back((excerpt.clone(), latency_ms));
                while sq.len() > 20 {
                    sq.pop_front();
                }
                if let Err(e) = self.audit_slow(query, latency_ms, k) {
                    tracing::warn!("recall_perf audit write failed: {e}");
                }
            }
        }
        value
    }

    fn audit_slow(&self, query: &str, latency_ms: u64, k: u32) -> Result<(), PerfError> {
        let Some(path) = &self.audit_path else {
            return Ok(());
        };
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let excerpt: String = query.chars().take(200).collect();
        let entry = serde_json::json!({
            "ts": Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            "query": excerpt,
            "latency_ms": latency_ms,
            "k": k,
        });
        let line = serde_json::to_string(&entry)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    pub fn stats(&self) -> PerfStats {
        let cache_size = self.cache.lock().len();
        let top_slow: Vec<(String, u64)> = self.slow_queries.lock().iter().cloned().collect();
        PerfStats {
            n_calls: *self.n_calls.lock(),
            n_cache_hits: *self.n_cache_hits.lock(),
            n_slow: *self.n_slow.lock(),
            cache_size,
            top_slow,
        }
    }

    pub fn history(&self, limit: usize) -> Result<Vec<serde_json::Value>, PerfError> {
        let Some(path) = &self.audit_path else {
            return Ok(Vec::new());
        };
        if !path.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(path)?;
        let mut out: Vec<serde_json::Value> = Vec::new();
        for line in raw.lines() {
            if line.trim().is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str(line) {
                out.push(v);
            }
        }
        if out.len() > limit {
            out = out.split_off(out.len() - limit);
        }
        Ok(out)
    }

    pub fn reset(&self) {
        self.cache.lock().clear();
        *self.n_calls.lock() = 0;
        *self.n_cache_hits.lock() = 0;
        *self.n_slow.lock() = 0;
        self.slow_queries.lock().clear();
    }
}

pub fn default_audit_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("recall_slow.jsonl")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn perf(cfg: PerfConfig, audit: Option<PathBuf>) -> (Arc<ManualClock>, RecallPerf<Vec<String>>) {
        let clock = Arc::new(ManualClock::new());
        let p = RecallPerf::new(cfg, clock.clone(), audit);
        (clock, p)
    }

    #[test]
    fn config_from_source_defaults() {
        let cfg = PerfConfig::from_source(|_| None);
        assert_eq!(cfg.slow_threshold_ms, 500);
        assert_eq!(cfg.cache_ttl_secs, 60.0);
        assert_eq!(cfg.cache_max_entries, 32);
    }

    #[test]
    fn config_env_overrides() {
        let env: std::collections::HashMap<&str, &str> = [
            ("AIM_RECALL_SLOW_MS", "1000"),
            ("AIM_RECALL_CACHE_TTL", "30"),
            ("AIM_RECALL_CACHE_MAX", "16"),
        ]
        .into_iter()
        .collect();
        let cfg = PerfConfig::from_source(|k| env.get(k).map(|s| s.to_string()));
        assert_eq!(cfg.slow_threshold_ms, 1000);
        assert_eq!(cfg.cache_ttl_secs, 30.0);
        assert_eq!(cfg.cache_max_entries, 16);
    }

    #[test]
    fn cache_hit_skips_retriever() {
        let (clock, p) = perf(PerfConfig::default(), None);
        clock.set_secs(100.0);
        let r1 = p.retrieve("query", 5, |_, _| vec!["a".into(), "b".into()]);
        // Second call within TTL should hit cache, not invoke retriever
        let r2 = p.retrieve("query", 5, |_, _| panic!("retriever must not run"));
        assert_eq!(r1, r2);
        let s = p.stats();
        assert_eq!(s.n_calls, 2);
        assert_eq!(s.n_cache_hits, 1);
    }

    #[test]
    fn cache_miss_after_ttl() {
        let (clock, p) = perf(
            PerfConfig {
                cache_ttl_secs: 60.0,
                ..PerfConfig::default()
            },
            None,
        );
        clock.set_secs(100.0);
        p.retrieve("q", 3, |_, _| vec!["v1".into()]);
        clock.set_secs(200.0); // 100s past TTL
        let v = p.retrieve("q", 3, |_, _| vec!["v2".into()]);
        assert_eq!(v, vec!["v2".to_string()]);
        let s = p.stats();
        assert_eq!(s.n_cache_hits, 0);
    }

    #[test]
    fn cache_keys_distinct_query_and_k() {
        let (clock, p) = perf(PerfConfig::default(), None);
        clock.set_secs(0.0);
        p.retrieve("q", 5, |_, _| vec!["A".into()]);
        p.retrieve("q", 7, |_, _| vec!["B".into()]); // different k
        p.retrieve("other", 5, |_, _| vec!["C".into()]); // different query
        let s = p.stats();
        assert_eq!(s.cache_size, 3);
        assert_eq!(s.n_cache_hits, 0);
    }

    #[test]
    fn lru_eviction_when_max_exceeded() {
        let cfg = PerfConfig {
            cache_max_entries: 3,
            ..PerfConfig::default()
        };
        let (_clock, p) = perf(cfg, None);
        for q in ["a", "b", "c", "d"] {
            p.retrieve(q, 1, |q_, _| vec![q_.to_string()]);
        }
        let s = p.stats();
        assert_eq!(s.cache_size, 3);
    }

    #[test]
    fn slow_query_recorded_in_stats_and_audit() {
        let dir = TempDir::new().unwrap();
        let audit = dir.path().join("slow.jsonl");
        let cfg = PerfConfig {
            slow_threshold_ms: 100,
            ..PerfConfig::default()
        };
        let (clock, p) = perf(cfg, Some(audit.clone()));
        clock.set_ms(0);
        // Retriever advances the clock by 250ms — exceeds 100ms threshold
        let cl = clock.clone();
        let _ = p.retrieve("slow query", 5, move |_, _| {
            cl.advance_ms(250);
            vec!["result".to_string()]
        });
        let s = p.stats();
        assert_eq!(s.n_slow, 1);
        assert_eq!(s.top_slow.len(), 1);
        assert_eq!(s.top_slow[0].0, "slow query");
        assert!(s.top_slow[0].1 >= 250);
        // Audit log written
        assert!(audit.exists());
        let body = std::fs::read_to_string(&audit).unwrap();
        assert!(body.contains("slow query"));
        assert!(body.contains("\"latency_ms\""));
    }

    #[test]
    fn fast_query_not_logged() {
        let dir = TempDir::new().unwrap();
        let audit = dir.path().join("slow.jsonl");
        let (_clock, p) = perf(PerfConfig::default(), Some(audit.clone()));
        let _ = p.retrieve("fast query", 5, |_, _| vec!["r".into()]);
        let s = p.stats();
        assert_eq!(s.n_slow, 0);
        assert!(!audit.exists() || std::fs::read_to_string(&audit).unwrap().is_empty());
    }

    #[test]
    fn slow_queries_capped_at_20() {
        let cfg = PerfConfig {
            slow_threshold_ms: 1,
            ..PerfConfig::default()
        };
        let (clock, p) = perf(cfg, None);
        clock.set_ms(0);
        for i in 0..30 {
            let cl = clock.clone();
            let _ = p.retrieve(&format!("q{i}"), 1, move |_, _| {
                cl.advance_ms(5);
                vec!["x".to_string()]
            });
        }
        let s = p.stats();
        assert_eq!(s.top_slow.len(), 20);
        // First 10 evicted; last batch should start from "q10"
        assert!(s.top_slow[0].0.starts_with("q1"));
    }

    #[test]
    fn reset_clears_state() {
        let (clock, p) = perf(PerfConfig::default(), None);
        clock.set_secs(0.0);
        p.retrieve("q", 1, |_, _| vec!["x".into()]);
        p.reset();
        let s = p.stats();
        assert_eq!(s.n_calls, 0);
        assert_eq!(s.cache_size, 0);
    }

    #[test]
    fn history_returns_recent_entries_within_limit() {
        let dir = TempDir::new().unwrap();
        let audit = dir.path().join("slow.jsonl");
        let cfg = PerfConfig {
            slow_threshold_ms: 1,
            ..PerfConfig::default()
        };
        let (clock, p) = perf(cfg, Some(audit));
        clock.set_ms(0);
        for i in 0..5 {
            let cl = clock.clone();
            let _ = p.retrieve(&format!("q{i}"), 1, move |_, _| {
                cl.advance_ms(10);
                vec![]
            });
        }
        let h = p.history(3).unwrap();
        assert_eq!(h.len(), 3);
        // Most recent at the end
        assert!(h.last().unwrap()["query"].as_str().unwrap().contains("q4"));
    }

    #[test]
    fn promotion_on_hit_keeps_entry_alive() {
        let cfg = PerfConfig {
            cache_max_entries: 2,
            ..PerfConfig::default()
        };
        let (clock, p) = perf(cfg, None);
        clock.set_secs(0.0);
        p.retrieve("a", 1, |_, _| vec!["A".into()]);
        p.retrieve("b", 1, |_, _| vec!["B".into()]);
        // Hit "a" — promotes it to MRU
        p.retrieve("a", 1, |_, _| panic!("must hit"));
        // Insert "c" — should evict "b" (oldest), not "a"
        p.retrieve("c", 1, |_, _| vec!["C".into()]);
        // "a" hit again still cached
        p.retrieve("a", 1, |_, _| panic!("must still be cached"));
        let s = p.stats();
        assert_eq!(s.cache_size, 2);
        assert_eq!(s.n_cache_hits, 2);
    }
}
