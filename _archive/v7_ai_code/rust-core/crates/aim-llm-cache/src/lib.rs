//! aim-llm-cache — semantic cache for LLM responses.
//!
//! Port of `agents/llm_cache.py`. Stores `(prompt+system)` embeddings in
//! SQLite. On lookup, computes cosine similarity against the most-recent N
//! entries and returns the response if it exceeds the configured threshold.
//! Saves 30-50% tokens on workflows with repeated queries (peer reviews,
//! batch summarisation, repeated planner prompts).
//!
//! ## Wire-in (opt-in via env)
//!
//! ```text
//! AIM_LLM_CACHE=1                  # enable
//! AIM_LLM_CACHE_THRESHOLD=0.95     # cosine threshold
//! AIM_LLM_CACHE_TTL_HOURS=24       # drop entries older than N hours
//! AIM_LLM_CACHE_MAX=5000           # cap on table size
//! AIM_LLM_CACHE_SCAN_LIMIT=1000    # entries scanned per lookup
//! ```
//!
//! Embedding is pluggable via the [`Embedder`] trait — production wires
//! the running embed daemon, tests use [`StubEmbedder`].

use md5::{Digest, Md5};
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("embed failed: {0}")]
    Embed(String),
}

/// Pluggable embedder. Production wires the embed daemon; tests use
/// the [`StubEmbedder`] (deterministic vectors derived from the input).
pub trait Embedder: Send + Sync {
    fn embed(&self, text: &str) -> Result<Vec<f32>, CacheError>;
}

/// Test-friendly embedder: hashes the input and projects to a fixed-dim
/// pseudo-random vector. Identical text → identical vector. Similar text
/// → nothing useful: the only similarity tests should use the same string.
pub struct StubEmbedder {
    pub dim: usize,
}

impl Default for StubEmbedder {
    fn default() -> Self {
        Self { dim: 32 }
    }
}

impl Embedder for StubEmbedder {
    fn embed(&self, text: &str) -> Result<Vec<f32>, CacheError> {
        let mut h = Md5::new();
        h.update(text.as_bytes());
        let seed = h.finalize();
        let mut v = Vec::with_capacity(self.dim);
        for i in 0..self.dim {
            let b = seed[i % seed.len()];
            v.push((b as f32 - 128.0) / 128.0);
        }
        Ok(v)
    }
}

#[derive(Debug, Clone, Copy)]
pub struct CacheConfig {
    pub enabled: bool,
    pub threshold: f64,
    pub ttl_hours: f64,
    pub max_entries: u32,
    pub scan_limit: u32,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            threshold: 0.95,
            ttl_hours: 24.0,
            max_entries: 5000,
            scan_limit: 1000,
        }
    }
}

impl CacheConfig {
    pub fn from_env() -> Self {
        let enabled = std::env::var("AIM_LLM_CACHE")
            .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);
        let threshold = std::env::var("AIM_LLM_CACHE_THRESHOLD")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(0.95);
        let ttl_hours = std::env::var("AIM_LLM_CACHE_TTL_HOURS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(24.0);
        let max_entries = std::env::var("AIM_LLM_CACHE_MAX")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(5000);
        let scan_limit = std::env::var("AIM_LLM_CACHE_SCAN_LIMIT")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1000);
        Self {
            enabled,
            threshold,
            ttl_hours,
            max_entries,
            scan_limit,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheStats {
    pub enabled: bool,
    pub threshold: f64,
    pub ttl_hours: f64,
    pub entries: u32,
    pub total_hits: u64,
    pub fresh: u32,
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
    pub fn set(&self, t: f64) {
        *self.state.lock() = t;
    }
}

impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.state.lock()
    }
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    prompt_preview TEXT,
    embedding TEXT,
    response TEXT,
    model TEXT,
    provider TEXT,
    created_at REAL,
    hits INTEGER DEFAULT 0,
    last_hit REAL
);
CREATE INDEX IF NOT EXISTS idx_created ON cache(created_at);
";

pub struct Cache {
    cfg: CacheConfig,
    conn: Arc<Mutex<Connection>>,
    embedder: Arc<dyn Embedder>,
    clock: Arc<dyn Clock>,
}

impl Cache {
    pub fn open(
        db: impl AsRef<Path>,
        cfg: CacheConfig,
        embedder: Arc<dyn Embedder>,
    ) -> Result<Self, CacheError> {
        Self::with_clock(db, cfg, embedder, Arc::new(SystemClock))
    }

    pub fn with_clock(
        db: impl AsRef<Path>,
        cfg: CacheConfig,
        embedder: Arc<dyn Embedder>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, CacheError> {
        let p = db.as_ref();
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let conn = Connection::open(p)?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self {
            cfg,
            conn: Arc::new(Mutex::new(conn)),
            embedder,
            clock,
        })
    }

    fn key(prompt: &str, system: &str) -> String {
        let mut h = Md5::new();
        h.update(format!("{system}\n--\n{prompt}").as_bytes());
        hex::encode(h.finalize())
    }

    fn full(prompt: &str, system: &str) -> String {
        if system.is_empty() {
            prompt.to_string()
        } else {
            format!("{system}\n{prompt}")
        }
    }

    /// Returns a cached response if any prior entry exceeds the cosine
    /// threshold (or `override_threshold` if set). `Ok(None)` for misses.
    pub fn maybe_cached(
        &self,
        prompt: &str,
        system: &str,
        override_threshold: Option<f64>,
    ) -> Result<Option<String>, CacheError> {
        if !self.cfg.enabled {
            return Ok(None);
        }
        let qvec = self.embedder.embed(&Self::full(prompt, system))?;
        let now = self.clock.now_secs();
        let cutoff = now - self.cfg.ttl_hours * 3600.0;
        let thr = override_threshold.unwrap_or(self.cfg.threshold);

        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT key, embedding, response FROM cache \
             WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
        )?;
        let rows = stmt.query_map(params![cutoff, self.cfg.scan_limit as i64], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?;
        let mut best: (f64, Option<(String, String)>) = (0.0, None);
        for row in rows {
            let (k, emb_str, resp) = match row {
                Ok(t) => t,
                Err(_) => continue,
            };
            let emb: Vec<f32> = match serde_json::from_str(&emb_str) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let sim = cosine(&qvec, &emb);
            if sim > best.0 {
                best = (sim, Some((k, resp)));
            }
        }
        if let (sim, Some((k, resp))) = best {
            if sim >= thr {
                con.execute(
                    "UPDATE cache SET hits = hits + 1, last_hit = ? WHERE key = ?",
                    params![now, k],
                )?;
                tracing::info!("hit: similarity={:.3} key={}", sim, &k[..k.len().min(8)]);
                return Ok(Some(resp));
            }
        }
        Ok(None)
    }

    /// Insert (or replace) a cached entry. Returns `Ok(true)` on success,
    /// `Ok(false)` if caching is disabled.
    pub fn store(
        &self,
        prompt: &str,
        system: &str,
        response: &str,
        model: &str,
        provider: &str,
    ) -> Result<bool, CacheError> {
        if !self.cfg.enabled {
            return Ok(false);
        }
        let full = Self::full(prompt, system);
        let vec = self.embedder.embed(&full)?;
        let key = Self::key(prompt, system);
        let preview: String = full.chars().take(160).collect();
        let emb_str = serde_json::to_string(&vec)?;
        let now = self.clock.now_secs();
        let con = self.conn.lock();
        con.execute(
            "INSERT OR REPLACE INTO cache (key, prompt_preview, embedding, response, model, provider, created_at) \
             VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![key, preview, emb_str, response, model, provider, now],
        )?;
        // Cap size: keep the most-recent `max_entries`.
        con.execute(
            "DELETE FROM cache WHERE key NOT IN \
             (SELECT key FROM cache ORDER BY created_at DESC LIMIT ?)",
            params![self.cfg.max_entries as i64],
        )?;
        Ok(true)
    }

    pub fn stats(&self) -> Result<CacheStats, CacheError> {
        let con = self.conn.lock();
        let (total, total_hits): (u32, u64) = con
            .query_row(
                "SELECT COUNT(*), COALESCE(SUM(hits),0) FROM cache",
                [],
                |r| Ok((r.get::<_, i64>(0)? as u32, r.get::<_, i64>(1)? as u64)),
            )
            .optional()?
            .unwrap_or((0, 0));
        let cutoff = self.clock.now_secs() - self.cfg.ttl_hours * 3600.0;
        let fresh: u32 = con
            .query_row(
                "SELECT COUNT(*) FROM cache WHERE created_at > ?",
                params![cutoff],
                |r| r.get::<_, i64>(0).map(|n| n as u32),
            )
            .optional()?
            .unwrap_or(0);
        Ok(CacheStats {
            enabled: self.cfg.enabled,
            threshold: self.cfg.threshold,
            ttl_hours: self.cfg.ttl_hours,
            entries: total,
            total_hits,
            fresh,
        })
    }

    /// Wipe cache; returns count of entries removed.
    pub fn clear(&self) -> Result<u32, CacheError> {
        let con = self.conn.lock();
        let n = con.execute("DELETE FROM cache", [])?;
        Ok(n as u32)
    }
}

pub fn cosine(a: &[f32], b: &[f32]) -> f64 {
    if a.is_empty() || b.is_empty() || a.len() != b.len() {
        return 0.0;
    }
    let dot: f64 = a.iter().zip(b.iter()).map(|(x, y)| (*x as f64) * (*y as f64)).sum();
    let na: f64 = a.iter().map(|x| (*x as f64).powi(2)).sum::<f64>().sqrt();
    let nb: f64 = b.iter().map(|y| (*y as f64).powi(2)).sum::<f64>().sqrt();
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na * nb)
    }
}

pub fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude").join("llm_cache.db")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fresh(enabled: bool) -> (TempDir, Cache, Arc<ManualClock>) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("c.db");
        let cfg = CacheConfig {
            enabled,
            threshold: 0.95,
            ttl_hours: 24.0,
            max_entries: 100,
            scan_limit: 100,
        };
        let clock = Arc::new(ManualClock::default());
        let cache =
            Cache::with_clock(&db, cfg, Arc::new(StubEmbedder::default()), clock.clone()).unwrap();
        (dir, cache, clock)
    }

    #[test]
    fn cosine_basic() {
        let a = [1.0f32, 0.0];
        let b = [1.0f32, 0.0];
        assert!((cosine(&a, &b) - 1.0).abs() < 1e-9);
        let c = [0.0f32, 1.0];
        assert!(cosine(&a, &c).abs() < 1e-9);
        let d = [-1.0f32, 0.0];
        assert!((cosine(&a, &d) + 1.0).abs() < 1e-9);
    }

    #[test]
    fn cosine_zero_vector_returns_zero() {
        assert_eq!(cosine(&[0.0f32, 0.0], &[1.0, 1.0]), 0.0);
        assert_eq!(cosine(&[], &[1.0]), 0.0);
        assert_eq!(cosine(&[1.0, 0.0], &[1.0]), 0.0);
    }

    #[test]
    fn disabled_cache_short_circuits_store_and_fetch() {
        let (_d, cache, clock) = fresh(false);
        clock.set(100.0);
        assert!(!cache.store("q", "", "r", "m", "p").unwrap());
        assert!(cache.maybe_cached("q", "", None).unwrap().is_none());
    }

    #[test]
    fn store_then_lookup_hits() {
        let (_d, cache, clock) = fresh(true);
        clock.set(100.0);
        cache.store("hello", "system", "world", "ds", "deepseek").unwrap();
        let got = cache.maybe_cached("hello", "system", None).unwrap();
        assert_eq!(got.as_deref(), Some("world"));
    }

    #[test]
    fn lookup_miss_when_text_differs() {
        let (_d, cache, clock) = fresh(true);
        clock.set(100.0);
        cache.store("hello", "system", "world", "ds", "deepseek").unwrap();
        // StubEmbedder: identical text → identical vector. Different text →
        // unrelated. So a different prompt must NOT cross the 0.95 threshold.
        let got = cache
            .maybe_cached("totally different prompt text", "system", None)
            .unwrap();
        assert!(got.is_none());
    }

    #[test]
    fn expired_entries_skipped() {
        let (_d, cache, clock) = fresh(true);
        clock.set(0.0);
        cache.store("q", "", "r", "m", "p").unwrap();
        // 25 hours later (TTL = 24h)
        clock.set(25.0 * 3600.0);
        let got = cache.maybe_cached("q", "", None).unwrap();
        assert!(got.is_none());
    }

    #[test]
    fn override_threshold_lowers_bar() {
        let (_d, cache, clock) = fresh(true);
        clock.set(100.0);
        cache.store("aaa", "", "answer", "m", "p").unwrap();
        // Pass through the same key; default threshold hits anyway. Verify
        // override path works without breaking the basic flow.
        let got = cache.maybe_cached("aaa", "", Some(0.5)).unwrap();
        assert_eq!(got.as_deref(), Some("answer"));
    }

    #[test]
    fn store_increments_hits_on_lookup() {
        let (_d, cache, clock) = fresh(true);
        clock.set(100.0);
        cache.store("aaa", "", "answer", "m", "p").unwrap();
        cache.maybe_cached("aaa", "", None).unwrap();
        cache.maybe_cached("aaa", "", None).unwrap();
        let s = cache.stats().unwrap();
        assert_eq!(s.entries, 1);
        assert_eq!(s.total_hits, 2);
    }

    #[test]
    fn stats_fresh_window() {
        let (_d, cache, clock) = fresh(true);
        clock.set(0.0);
        cache.store("a", "", "x", "m", "p").unwrap();
        clock.set(48.0 * 3600.0); // 48h later — outside 24h fresh window
        cache.store("b", "", "y", "m", "p").unwrap();
        let s = cache.stats().unwrap();
        assert_eq!(s.entries, 2);
        assert_eq!(s.fresh, 1);
    }

    #[test]
    fn clear_returns_count() {
        let (_d, cache, clock) = fresh(true);
        clock.set(0.0);
        cache.store("a", "", "x", "", "").unwrap();
        cache.store("b", "", "y", "", "").unwrap();
        assert_eq!(cache.clear().unwrap(), 2);
        assert_eq!(cache.stats().unwrap().entries, 0);
    }

    #[test]
    fn max_entries_caps_table_size() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("c.db");
        let cfg = CacheConfig {
            enabled: true,
            threshold: 0.95,
            ttl_hours: 24.0,
            max_entries: 3,
            scan_limit: 100,
        };
        let clock = Arc::new(ManualClock::default());
        let cache =
            Cache::with_clock(&db, cfg, Arc::new(StubEmbedder::default()), clock.clone()).unwrap();
        for (i, q) in ["a", "b", "c", "d", "e"].iter().enumerate() {
            clock.set(i as f64);
            cache.store(q, "", q, "", "").unwrap();
        }
        assert_eq!(cache.stats().unwrap().entries, 3);
    }

    #[test]
    fn key_is_deterministic_for_same_input() {
        let k1 = Cache::key("hello", "sys");
        let k2 = Cache::key("hello", "sys");
        assert_eq!(k1, k2);
        let k3 = Cache::key("hello", "");
        assert_ne!(k1, k3);
    }

    #[test]
    fn config_from_env_defaults() {
        let cfg = CacheConfig::from_env();
        assert!(cfg.threshold > 0.0);
        assert!(cfg.ttl_hours > 0.0);
    }
}
