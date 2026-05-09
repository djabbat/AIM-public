//! aim-graphrag-cache — TTL+LRU cache for GraphRAG queries.
//!
//! Port of `agents/graphrag_cache.py`. Keyed on `(normalised_query, k,
//! hops)`, default TTL 600s, default max 128. Pluggable [`Clock`] so
//! TTL eviction is testable without sleeping.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

// ── config ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CacheConfig {
    pub enabled: bool,
    pub ttl: Duration,
    pub max_size: usize,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            ttl: Duration::from_secs(600),
            max_size: 128,
        }
    }
}

impl CacheConfig {
    pub fn from_env() -> Self {
        Self::from_source(|n| std::env::var(n).ok())
    }

    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let mut c = Self::default();
        if let Some(v) = get("AIM_GRAPHRAG_CACHE") {
            c.enabled = matches!(v.to_lowercase().as_str(), "1" | "true" | "yes");
        }
        if let Some(v) = get("AIM_GRAPHRAG_CACHE_TTL_S") {
            if let Ok(n) = v.parse::<u64>() {
                c.ttl = Duration::from_secs(n);
            }
        }
        if let Some(v) = get("AIM_GRAPHRAG_CACHE_MAX") {
            if let Ok(n) = v.parse() {
                c.max_size = n;
            }
        }
        c
    }
}

// ── stats ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CacheStats {
    pub enabled: bool,
    pub ttl_seconds: u64,
    pub max_size: usize,
    pub size: usize,
    pub hits: u64,
    pub misses: u64,
    pub hit_rate: f64,
}

// ── key ────────────────────────────────────────────────────────────────────

pub fn cache_key(query: &str, k: usize, hops: usize) -> String {
    format!(
        "{}::k={}::h={}",
        query.trim().to_lowercase(),
        k,
        hops
    )
}

// ── clock ──────────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> Instant;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> Instant {
        Instant::now()
    }
}

pub struct ManualClock {
    inner: Mutex<Instant>,
}

impl ManualClock {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(Instant::now()),
        }
    }
    pub fn advance(&self, d: Duration) {
        let mut t = self.inner.lock();
        *t = *t + d;
    }
}

impl Default for ManualClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for ManualClock {
    fn now(&self) -> Instant {
        *self.inner.lock()
    }
}

// ── cache ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct Entry<V: Clone> {
    key: String,
    inserted: Instant,
    value: V,
}

pub struct GraphRagCache<'a, V: Clone + Send + Sync + 'static> {
    pub config: CacheConfig,
    pub clock: &'a dyn Clock,
    inner: Mutex<Inner<V>>,
}

#[derive(Default)]
struct Inner<V: Clone> {
    /// LRU order: front = oldest, back = newest.
    entries: VecDeque<Entry<V>>,
    hits: u64,
    misses: u64,
}

impl<'a, V: Clone + Send + Sync + 'static> GraphRagCache<'a, V> {
    pub fn new(config: CacheConfig, clock: &'a dyn Clock) -> Self {
        Self {
            config,
            clock,
            inner: Mutex::new(Inner {
                entries: VecDeque::new(),
                hits: 0,
                misses: 0,
            }),
        }
    }

    pub fn get(&self, query: &str, k: usize, hops: usize) -> Option<V> {
        if !self.config.enabled {
            return None;
        }
        let key = cache_key(query, k, hops);
        let now = self.clock.now();
        let mut inner = self.inner.lock();
        if let Some(pos) = inner.entries.iter().position(|e| e.key == key) {
            let elapsed = now.saturating_duration_since(inner.entries[pos].inserted);
            if elapsed > self.config.ttl {
                inner.entries.remove(pos);
                inner.misses += 1;
                return None;
            }
            // bump to MRU
            let entry = inner.entries.remove(pos).expect("pos valid");
            let value = entry.value.clone();
            inner.entries.push_back(entry);
            inner.hits += 1;
            return Some(value);
        }
        inner.misses += 1;
        None
    }

    pub fn store(&self, query: &str, k: usize, hops: usize, value: V) {
        if !self.config.enabled {
            return;
        }
        let key = cache_key(query, k, hops);
        let now = self.clock.now();
        let mut inner = self.inner.lock();
        if let Some(pos) = inner.entries.iter().position(|e| e.key == key) {
            inner.entries.remove(pos);
        }
        inner.entries.push_back(Entry {
            key,
            inserted: now,
            value,
        });
        let max = self.config.max_size.max(1);
        while inner.entries.len() > max {
            inner.entries.pop_front();
        }
    }

    pub fn stats(&self) -> CacheStats {
        let inner = self.inner.lock();
        let total = inner.hits + inner.misses;
        CacheStats {
            enabled: self.config.enabled,
            ttl_seconds: self.config.ttl.as_secs(),
            max_size: self.config.max_size,
            size: inner.entries.len(),
            hits: inner.hits,
            misses: inner.misses,
            hit_rate: if total > 0 {
                (inner.hits as f64 / total as f64 * 1000.0).round() / 1000.0
            } else {
                0.0
            },
        }
    }

    pub fn clear(&self) -> usize {
        let mut inner = self.inner.lock();
        let n = inner.entries.len();
        inner.entries.clear();
        n
    }

    pub fn len(&self) -> usize {
        self.inner.lock().entries.len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn cfg(ttl_secs: u64, max: usize) -> CacheConfig {
        CacheConfig {
            enabled: true,
            ttl: Duration::from_secs(ttl_secs),
            max_size: max,
        }
    }

    // ── cache_key ──────────────────────────────────────────────────────────

    #[test]
    fn cache_key_normalises_query() {
        let a = cache_key("  CDATA Query  ", 5, 1);
        let b = cache_key("cdata query", 5, 1);
        assert_eq!(a, b);
    }

    #[test]
    fn cache_key_includes_k_and_hops() {
        let a = cache_key("q", 5, 1);
        let b = cache_key("q", 5, 2);
        let c = cache_key("q", 6, 1);
        assert_ne!(a, b);
        assert_ne!(a, c);
    }

    // ── CacheConfig ────────────────────────────────────────────────────────

    #[test]
    fn config_defaults_match_python() {
        let c = CacheConfig::default();
        assert!(c.enabled);
        assert_eq!(c.ttl, Duration::from_secs(600));
        assert_eq!(c.max_size, 128);
    }

    #[test]
    fn config_from_source_reads_env() {
        let mut env: HashMap<String, String> = HashMap::new();
        env.insert("AIM_GRAPHRAG_CACHE".into(), "1".into());
        env.insert("AIM_GRAPHRAG_CACHE_TTL_S".into(), "30".into());
        env.insert("AIM_GRAPHRAG_CACHE_MAX".into(), "8".into());
        let c = CacheConfig::from_source(|k: &str| env.get(k).cloned());
        assert_eq!(c.ttl, Duration::from_secs(30));
        assert_eq!(c.max_size, 8);
    }

    // ── store / get ────────────────────────────────────────────────────────

    #[test]
    fn store_then_get_round_trip() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<Vec<String>> = GraphRagCache::new(cfg(60, 8), &clk);
        cache.store("q", 5, 1, vec!["hit-1".into()]);
        let v = cache.get("q", 5, 1).unwrap();
        assert_eq!(v, vec!["hit-1".to_string()]);
        let s = cache.stats();
        assert_eq!(s.hits, 1);
        assert_eq!(s.misses, 0);
        assert_eq!(s.size, 1);
    }

    #[test]
    fn miss_increments_misses() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<Vec<String>> = GraphRagCache::new(cfg(60, 8), &clk);
        assert!(cache.get("missing", 5, 1).is_none());
        assert_eq!(cache.stats().misses, 1);
    }

    #[test]
    fn ttl_eviction_after_clock_advance() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(10, 8), &clk);
        cache.store("q", 5, 1, 42);
        clk.advance(Duration::from_secs(15));
        assert!(cache.get("q", 5, 1).is_none());
        assert_eq!(cache.stats().misses, 1);
        // Expired entry removed
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn lru_eviction_when_over_max() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(60, 2), &clk);
        cache.store("a", 5, 1, 1);
        cache.store("b", 5, 1, 2);
        cache.store("c", 5, 1, 3);
        assert_eq!(cache.len(), 2);
        // 'a' evicted (oldest)
        assert!(cache.get("a", 5, 1).is_none());
        assert!(cache.get("b", 5, 1).is_some());
        assert!(cache.get("c", 5, 1).is_some());
    }

    #[test]
    fn get_promotes_entry_to_mru() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(60, 2), &clk);
        cache.store("a", 5, 1, 1);
        cache.store("b", 5, 1, 2);
        cache.get("a", 5, 1).unwrap(); // bumps a → MRU
        cache.store("c", 5, 1, 3); // evicts b
        assert!(cache.get("a", 5, 1).is_some());
        assert!(cache.get("b", 5, 1).is_none());
    }

    #[test]
    fn store_replaces_existing_key() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(60, 8), &clk);
        cache.store("q", 5, 1, 1);
        cache.store("q", 5, 1, 99);
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.get("q", 5, 1).unwrap(), 99);
    }

    #[test]
    fn disabled_cache_skips_store_and_get() {
        let clk = ManualClock::new();
        let cfg = CacheConfig {
            enabled: false,
            ttl: Duration::from_secs(60),
            max_size: 4,
        };
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg, &clk);
        cache.store("q", 5, 1, 99);
        assert_eq!(cache.len(), 0);
        assert!(cache.get("q", 5, 1).is_none());
    }

    #[test]
    fn stats_hit_rate_three_decimals() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(60, 8), &clk);
        cache.store("q", 5, 1, 1);
        cache.get("q", 5, 1).unwrap(); // hit
        cache.get("q", 5, 1).unwrap(); // hit
        cache.get("nope", 5, 1); // miss
        let s = cache.stats();
        assert!((s.hit_rate - 0.667).abs() < 0.005);
    }

    #[test]
    fn clear_drops_all_entries() {
        let clk = ManualClock::new();
        let cache: GraphRagCache<i32> = GraphRagCache::new(cfg(60, 8), &clk);
        cache.store("a", 5, 1, 1);
        cache.store("b", 5, 1, 2);
        let n = cache.clear();
        assert_eq!(n, 2);
        assert!(cache.is_empty());
    }
}
