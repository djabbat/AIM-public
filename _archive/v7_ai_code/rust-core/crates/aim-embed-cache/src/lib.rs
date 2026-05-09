//! aim-embed-cache — semantic LRU cache for embeddings.
//!
//! Port of `agents/embed_cache.py`. On top of an exact-MD5 cache the
//! embed daemon already maintains, this layer adds *semantic* hits:
//! returns a stored vector when its cosine similarity to the query
//! vector clears `threshold`. LRU-bounded, thread-safe.

use std::collections::VecDeque;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("dimension mismatch: stored={stored}, query={query}")]
    DimensionMismatch { stored: usize, query: usize },
}

// ── config ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CacheConfig {
    pub enabled: bool,
    pub threshold: f32,
    pub max_size: usize,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            threshold: 0.95,
            max_size: 1024,
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
        if let Some(v) = get("AIM_EMBED_SEMCACHE") {
            c.enabled = matches!(v.to_lowercase().as_str(), "1" | "true" | "yes");
        }
        if let Some(v) = get("AIM_EMBED_SEMCACHE_THRESHOLD") {
            if let Ok(n) = v.parse() {
                c.threshold = n;
            }
        }
        if let Some(v) = get("AIM_EMBED_SEMCACHE_MAX") {
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
    pub size: usize,
    pub max_size: usize,
    pub threshold: f32,
    pub hits: u64,
    pub misses: u64,
    pub hit_rate: f64,
}

// ── cosine ─────────────────────────────────────────────────────────────────

pub fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.is_empty() || b.is_empty() || a.len() != b.len() {
        return 0.0;
    }
    let mut dot = 0.0_f32;
    let mut na = 0.0_f32;
    let mut nb = 0.0_f32;
    for (x, y) in a.iter().zip(b.iter()) {
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    if na == 0.0 || nb == 0.0 {
        return 0.0;
    }
    dot / (na.sqrt() * nb.sqrt())
}

// ── cache ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Entry {
    key: String,
    vec: Vec<f32>,
}

pub struct EmbedCache {
    pub config: CacheConfig,
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    /// MRU-last; LRU-first. `key` -> position handled via linear scan
    /// (small N, ≤1024 by default).
    entries: VecDeque<Entry>,
    hits: u64,
    misses: u64,
}

impl EmbedCache {
    pub fn new(config: CacheConfig) -> Self {
        Self {
            config,
            inner: Mutex::new(Inner::default()),
        }
    }

    fn key_for(text: &str) -> String {
        let head: String = text.chars().take(160).collect();
        format!("{}#{}", head, text.len())
    }

    /// Look up by semantic similarity. Returns the cached vector when any
    /// stored entry has cosine ≥ threshold to `query_vec`. Updates hits/
    /// misses + LRU order on hit.
    pub fn semantic_get(&self, _text: &str, query_vec: &[f32]) -> Option<Vec<f32>> {
        if !self.config.enabled || query_vec.is_empty() {
            return None;
        }
        let mut inner = self.inner.lock();
        let mut best_idx: Option<usize> = None;
        let mut best_sim = 0.0_f32;
        for (i, e) in inner.entries.iter().enumerate() {
            let sim = cosine(query_vec, &e.vec);
            if sim > best_sim {
                best_sim = sim;
                best_idx = Some(i);
            }
        }
        if let Some(i) = best_idx {
            if best_sim >= self.config.threshold {
                let entry = inner.entries.remove(i).expect("idx valid");
                let vec = entry.vec.clone();
                inner.entries.push_back(entry);
                inner.hits += 1;
                return Some(vec);
            }
        }
        inner.misses += 1;
        None
    }

    /// Insert or update; bumps to MRU; trims LRU until size ≤ max_size.
    pub fn semantic_put(&self, text: &str, vec: Vec<f32>) {
        if !self.config.enabled || text.is_empty() || vec.is_empty() {
            return;
        }
        let key = Self::key_for(text);
        let mut inner = self.inner.lock();
        if let Some(pos) = inner.entries.iter().position(|e| e.key == key) {
            inner.entries.remove(pos);
        }
        inner.entries.push_back(Entry { key, vec });
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
            size: inner.entries.len(),
            max_size: self.config.max_size,
            threshold: self.config.threshold,
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

    fn unit(v: Vec<f32>) -> Vec<f32> {
        let mag: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if mag == 0.0 {
            v
        } else {
            v.into_iter().map(|x| x / mag).collect()
        }
    }

    // ── cosine ─────────────────────────────────────────────────────────────

    #[test]
    fn cosine_identical_vectors_equals_one() {
        let v = vec![1.0_f32, 2.0, 3.0];
        let s = cosine(&v, &v);
        assert!((s - 1.0).abs() < 1e-6);
    }

    #[test]
    fn cosine_orthogonal_zero() {
        let a = vec![1.0_f32, 0.0];
        let b = vec![0.0_f32, 1.0];
        assert!(cosine(&a, &b).abs() < 1e-6);
    }

    #[test]
    fn cosine_dimension_mismatch_zero() {
        let a = vec![1.0_f32, 2.0];
        let b = vec![1.0_f32, 2.0, 3.0];
        assert_eq!(cosine(&a, &b), 0.0);
    }

    #[test]
    fn cosine_zero_vector_yields_zero() {
        let a = vec![0.0_f32, 0.0];
        let b = vec![1.0_f32, 1.0];
        assert_eq!(cosine(&a, &b), 0.0);
    }

    // ── CacheConfig ────────────────────────────────────────────────────────

    #[test]
    fn config_defaults_match_python() {
        let c = CacheConfig::default();
        assert!(c.enabled);
        assert!((c.threshold - 0.95).abs() < 1e-6);
        assert_eq!(c.max_size, 1024);
    }

    #[test]
    fn config_from_source_reads_env() {
        let mut env: HashMap<String, String> = HashMap::new();
        env.insert("AIM_EMBED_SEMCACHE".into(), "0".into());
        env.insert("AIM_EMBED_SEMCACHE_THRESHOLD".into(), "0.80".into());
        env.insert("AIM_EMBED_SEMCACHE_MAX".into(), "16".into());
        let c = CacheConfig::from_source(|k: &str| env.get(k).cloned());
        assert!(!c.enabled);
        assert!((c.threshold - 0.80).abs() < 1e-6);
        assert_eq!(c.max_size, 16);
    }

    // ── EmbedCache ─────────────────────────────────────────────────────────

    #[test]
    fn put_get_round_trip_when_query_identical() {
        let cache = EmbedCache::new(CacheConfig::default());
        let v = unit(vec![1.0, 0.0, 0.0]);
        cache.semantic_put("CDATA fact", v.clone());
        let got = cache.semantic_get("anything", &v).unwrap();
        assert_eq!(got, v);
        let s = cache.stats();
        assert_eq!(s.hits, 1);
        assert_eq!(s.size, 1);
    }

    #[test]
    fn near_neighbour_above_threshold_hits() {
        let cache = EmbedCache::new(CacheConfig {
            enabled: true,
            threshold: 0.90,
            max_size: 8,
        });
        cache.semantic_put("base", unit(vec![1.0, 0.0, 0.0]));
        // Slightly perturbed → cosine still ~0.99
        let q = unit(vec![1.0, 0.05, 0.0]);
        assert!(cache.semantic_get("near", &q).is_some());
    }

    #[test]
    fn far_neighbour_below_threshold_misses() {
        let cache = EmbedCache::new(CacheConfig {
            enabled: true,
            threshold: 0.99,
            max_size: 8,
        });
        cache.semantic_put("a", unit(vec![1.0, 0.0]));
        // Clearly different direction → cosine ≈ 0
        let q = unit(vec![0.0, 1.0]);
        assert!(cache.semantic_get("b", &q).is_none());
        assert_eq!(cache.stats().misses, 1);
    }

    #[test]
    fn put_evicts_oldest_when_full() {
        let cache = EmbedCache::new(CacheConfig {
            enabled: true,
            threshold: 0.95,
            max_size: 2,
        });
        cache.semantic_put("a", vec![1.0, 0.0]);
        cache.semantic_put("b", vec![0.0, 1.0]);
        assert_eq!(cache.len(), 2);
        cache.semantic_put("c", vec![1.0, 1.0]);
        assert_eq!(cache.len(), 2);
        // "a" was inserted first → evicted
        let stats = cache.stats();
        assert_eq!(stats.size, 2);
    }

    #[test]
    fn get_promotes_entry_to_mru() {
        let cache = EmbedCache::new(CacheConfig {
            enabled: true,
            threshold: 0.95,
            max_size: 2,
        });
        let v_a = unit(vec![1.0, 0.0]);
        let v_b = unit(vec![0.0, 1.0]);
        cache.semantic_put("a", v_a.clone());
        cache.semantic_put("b", v_b.clone());
        // Hit on 'a' → bumps to MRU
        cache.semantic_get("any", &v_a).unwrap();
        // Insert 'c' should evict 'b' (now LRU)
        let v_c = unit(vec![1.0, 1.0]);
        cache.semantic_put("c", v_c);
        // 'a' still hits, 'b' should miss
        assert!(cache.semantic_get("any", &v_a).is_some());
        assert!(cache.semantic_get("any", &v_b).is_none());
    }

    #[test]
    fn put_replaces_existing_key() {
        let cache = EmbedCache::new(CacheConfig::default());
        cache.semantic_put("same", vec![1.0, 0.0]);
        cache.semantic_put("same", vec![0.0, 1.0]);
        assert_eq!(cache.len(), 1);
    }

    #[test]
    fn disabled_cache_get_and_put_are_noops() {
        let cache = EmbedCache::new(CacheConfig {
            enabled: false,
            threshold: 0.5,
            max_size: 4,
        });
        cache.semantic_put("x", vec![1.0, 1.0]);
        assert_eq!(cache.len(), 0);
        let r = cache.semantic_get("x", &vec![1.0, 1.0]);
        assert!(r.is_none());
    }

    #[test]
    fn put_skips_empty_inputs() {
        let cache = EmbedCache::new(CacheConfig::default());
        cache.semantic_put("", vec![1.0, 0.0]);
        cache.semantic_put("text", Vec::new());
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn stats_hit_rate_reported_to_three_dp() {
        let cache = EmbedCache::new(CacheConfig::default());
        let v = unit(vec![1.0, 0.0]);
        cache.semantic_put("a", v.clone());
        // 2 hits, 1 miss
        cache.semantic_get("x", &v).unwrap();
        cache.semantic_get("x", &v).unwrap();
        cache.semantic_get("y", &unit(vec![0.0, 1.0]));
        let s = cache.stats();
        assert!((s.hit_rate - 0.667).abs() < 0.005);
    }

    #[test]
    fn clear_drops_all_entries() {
        let cache = EmbedCache::new(CacheConfig::default());
        cache.semantic_put("a", vec![1.0, 0.0]);
        cache.semantic_put("b", vec![0.0, 1.0]);
        let n = cache.clear();
        assert_eq!(n, 2);
        assert!(cache.is_empty());
    }
}
