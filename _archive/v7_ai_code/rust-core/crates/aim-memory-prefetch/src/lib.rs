//! aim-memory-prefetch — predictive prefetching of related memory.
//!
//! Port of `agents/memory_prefetch.py`.
//!
//! Strategy:
//!   1. Cheap regex NER over the task (people / acronyms / years / IDs).
//!   2. For each entity, kick off `Retriever::retrieve` for `flat` and
//!      `graph` modes — results are stored in an in-memory TTL+LRU cache.
//!   3. Subsequent reads via [`Cache::get`] hit warm.
//!
//! The Python original spawns a `ThreadPoolExecutor` for fire-and-forget
//! warming. The Rust port keeps the I/O model pluggable: callers pick
//! synchronous warming (default), or build their own concurrent warmer
//! around [`Prefetcher::warm_entity`]. This keeps the crate `no-tokio`
//! and trivially testable.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

use once_cell::sync::Lazy;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};

/// Cached hit returned by a retriever — opaque JSON-friendly payload.
pub type Hit = serde_json::Value;

/// Key for the LRU+TTL cache: `mode:lowercase-entity`.
fn cache_key(mode: &str, entity: &str) -> String {
    format!("{}:{}", mode, entity.to_lowercase())
}

// ── entity extraction ───────────────────────────────────────────────────────

static ENT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?x)
        (?:
            [A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}
                (?:[-\s][A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}){0,3}
            | [A-ZА-Я]{3,}
            | \b\d{4}\b
            | PMID[:\s]*\d+
            | DOI[:\s]*[\w./\-]+
            | ORCID[:\s]*[\w\-]+
        )
        ",
    )
    .expect("entity regex compiles")
});

const STOPWORDS: &[&str] = &[
    "The", "This", "That", "Что", "Это", "TODO", "DONE", "READ", "OPEN",
];

/// Regex-based NER. Returns up to `k` deduped entities (case-insensitive).
pub fn extract_entities(text: &str, k: usize) -> Vec<String> {
    if text.is_empty() || k == 0 {
        return Vec::new();
    }
    let mut seen: Vec<String> = Vec::new();
    let mut seen_lower: std::collections::HashSet<String> =
        std::collections::HashSet::new();
    for m in ENT_RE.find_iter(text) {
        let ent = m.as_str().trim().to_string();
        if STOPWORDS.contains(&ent.as_str()) {
            continue;
        }
        let low = ent.to_lowercase();
        if !seen_lower.insert(low) {
            continue;
        }
        seen.push(ent);
        if seen.len() >= k {
            break;
        }
    }
    seen
}

// ── cache ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct CacheEntry {
    inserted: Instant,
    value: Vec<Hit>,
}

/// TTL + LRU cache. The Python original uses `OrderedDict` with `move_to_end`
/// on read and write — we replicate the same eviction semantics with a
/// `VecDeque<String>` of keys plus a side `Vec<(String, CacheEntry)>` map.
///
/// For the modest sizes the prefetcher uses (cap 64), linear scans are
/// cheaper than a full `LinkedHashMap` dependency.
pub struct Cache {
    inner: Mutex<CacheInner>,
    ttl: Duration,
    max: usize,
}

struct CacheInner {
    keys: VecDeque<String>,
    map: Vec<(String, CacheEntry)>,
}

impl CacheInner {
    fn position(&self, key: &str) -> Option<usize> {
        self.map.iter().position(|(k, _)| k == key)
    }

    fn touch(&mut self, key: &str) {
        if let Some(pos) = self.keys.iter().position(|k| k == key) {
            let k = self.keys.remove(pos).expect("position-checked");
            self.keys.push_back(k);
        }
    }
}

impl Cache {
    /// Default Python settings: TTL 5 min, max 64 entries.
    pub fn new(ttl: Duration, max: usize) -> Self {
        Self {
            inner: Mutex::new(CacheInner {
                keys: VecDeque::new(),
                map: Vec::new(),
            }),
            ttl,
            max: max.max(1),
        }
    }

    /// Insert or replace; bumps to MRU; evicts LRU until size ≤ max.
    pub fn set(&self, key: String, value: Vec<Hit>) {
        let mut inner = self.inner.lock();
        let entry = CacheEntry {
            inserted: Instant::now(),
            value,
        };
        if let Some(pos) = inner.position(&key) {
            inner.map[pos].1 = entry;
            inner.touch(&key);
        } else {
            inner.map.push((key.clone(), entry));
            inner.keys.push_back(key);
        }
        while inner.keys.len() > self.max {
            if let Some(old) = inner.keys.pop_front() {
                if let Some(pos) = inner.position(&old) {
                    inner.map.swap_remove(pos);
                }
            }
        }
    }

    /// Retrieve unexpired value; refreshes LRU order on hit.
    pub fn get(&self, key: &str) -> Option<Vec<Hit>> {
        self.get_at(key, Instant::now())
    }

    /// Test-friendly variant: caller supplies "now".
    pub fn get_at(&self, key: &str, now: Instant) -> Option<Vec<Hit>> {
        let mut inner = self.inner.lock();
        let pos = inner.position(key)?;
        let entry = &inner.map[pos].1;
        if now.saturating_duration_since(entry.inserted) > self.ttl {
            inner.map.swap_remove(pos);
            if let Some(kp) = inner.keys.iter().position(|k| k == key) {
                inner.keys.remove(kp);
            }
            return None;
        }
        let value = entry.value.clone();
        inner.touch(key);
        Some(value)
    }

    /// Number of cached entries (regardless of TTL freshness).
    pub fn len(&self) -> usize {
        self.inner.lock().map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Snapshot of MRU→LRU keys (for `stats`).
    pub fn keys(&self) -> Vec<String> {
        self.inner.lock().keys.iter().rev().cloned().collect()
    }
}

// ── retriever trait ─────────────────────────────────────────────────────────

/// Pluggable retriever. The Python original calls
/// `agents.memory_index.retrieve` (flat) and `agents.graphrag.query` (graph).
/// In Rust both are abstracted behind one trait so tests can stub them.
pub trait Retriever: Send + Sync {
    fn retrieve(&self, mode: &str, entity: &str, k: usize) -> Vec<Hit>;
}

/// Always returns empty hits — useful when only one mode is wired up.
pub struct EmptyRetriever;

impl Retriever for EmptyRetriever {
    fn retrieve(&self, _mode: &str, _entity: &str, _k: usize) -> Vec<Hit> {
        Vec::new()
    }
}

// ── config ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrefetchConfig {
    pub enabled: bool,
    pub workers: usize,
    pub max_entities: usize,
    pub ttl_seconds: u64,
    pub cache_max: usize,
    pub k_per_mode: usize,
}

impl Default for PrefetchConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            workers: 3,
            max_entities: 5,
            ttl_seconds: 300,
            cache_max: 64,
            k_per_mode: 6,
        }
    }
}

impl PrefetchConfig {
    /// Mirrors the Python env reading. Testable via [`PrefetchConfig::from_source`].
    pub fn from_env() -> Self {
        Self::from_source(|name| std::env::var(name).ok())
    }

    /// Build a config from a custom env source (closure). Used by tests to
    /// avoid mutating process env (which races under workspace-parallel
    /// `cargo test`).
    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let mut c = Self::default();
        if let Some(v) = get("AIM_PREFETCH") {
            let v = v.to_lowercase();
            c.enabled = matches!(v.as_str(), "1" | "true" | "yes");
        }
        if let Some(v) = get("AIM_PREFETCH_WORKERS") {
            if let Ok(n) = v.parse() {
                c.workers = n;
            }
        }
        if let Some(v) = get("AIM_PREFETCH_MAX_ENTITIES") {
            if let Ok(n) = v.parse() {
                c.max_entities = n;
            }
        }
        c
    }

    pub fn ttl(&self) -> Duration {
        Duration::from_secs(self.ttl_seconds)
    }
}

// ── prefetcher ──────────────────────────────────────────────────────────────

pub struct Prefetcher {
    pub config: PrefetchConfig,
    pub cache: Cache,
}

impl Prefetcher {
    pub fn new(config: PrefetchConfig) -> Self {
        let cache = Cache::new(config.ttl(), config.cache_max);
        Self { config, cache }
    }

    /// Synchronous fire-once warming. Returns the entities that were warmed.
    /// Callers wanting concurrency should wrap [`warm_entity`] in their
    /// own thread/Tokio pool — keeping this crate runtime-agnostic.
    pub fn prefetch_for_task<R: Retriever + ?Sized>(
        &self,
        task: &str,
        retriever: &R,
    ) -> Vec<String> {
        if !self.config.enabled || task.is_empty() {
            return Vec::new();
        }
        let entities = extract_entities(task, self.config.max_entities);
        for ent in &entities {
            self.warm_entity(ent, retriever);
        }
        entities
    }

    /// Warm both `flat` and `graph` modes for one entity.
    pub fn warm_entity<R: Retriever + ?Sized>(&self, entity: &str, retriever: &R) {
        for mode in ["flat", "graph"] {
            let hits = retriever.retrieve(mode, entity, self.config.k_per_mode);
            self.cache.set(cache_key(mode, entity), hits);
        }
    }

    /// Read previously-warmed hits.
    pub fn cached_for(&self, query: &str, mode: &str) -> Option<Vec<Hit>> {
        self.cache.get(&cache_key(mode, query))
    }

    /// Diagnostic snapshot, mirrors Python `stats()`.
    pub fn stats(&self) -> PrefetchStats {
        let mut keys = self.cache.keys();
        keys.truncate(20);
        PrefetchStats {
            enabled: self.config.enabled,
            entries: self.cache.len(),
            workers: self.config.workers,
            ttl_seconds: self.config.ttl_seconds,
            keys,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrefetchStats {
    pub enabled: bool,
    pub entries: usize,
    pub workers: usize,
    pub ttl_seconds: u64,
    pub keys: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    // ── extract_entities ────────────────────────────────────────────────────

    #[test]
    fn extract_entities_picks_capitalised_words() {
        let ents = extract_entities("Tkemaladze published in 2026", 5);
        assert!(ents.iter().any(|e| e == "Tkemaladze"));
        assert!(ents.iter().any(|e| e == "2026"));
    }

    #[test]
    fn extract_entities_dedups_case_insensitive() {
        let ents = extract_entities("Geiger and geiger and GEIGER", 5);
        assert_eq!(ents.iter().filter(|e| e.to_lowercase() == "geiger").count(), 1);
    }

    #[test]
    fn extract_entities_filters_stopwords() {
        let ents = extract_entities("The TODO list is OPEN", 5);
        assert!(!ents.iter().any(|e| e == "The"));
        assert!(!ents.iter().any(|e| e == "TODO"));
        assert!(!ents.iter().any(|e| e == "OPEN"));
    }

    #[test]
    fn extract_entities_caps_at_k() {
        // years are atomic per regex branch — won't merge into multi-word groups
        let text = "2001, 2002, 2003, 2004, 2005, 2006";
        let ents = extract_entities(text, 3);
        assert_eq!(ents.len(), 3);
    }

    #[test]
    fn extract_entities_empty_input() {
        assert!(extract_entities("", 5).is_empty());
        assert!(extract_entities("hello world", 0).is_empty());
    }

    #[test]
    fn extract_entities_pmid_and_doi() {
        let ents = extract_entities("see PMID 12345 and DOI 10.1073/pnas.123 here", 10);
        assert!(ents.iter().any(|e| e.starts_with("PMID")));
        assert!(ents.iter().any(|e| e.starts_with("DOI")));
    }

    #[test]
    fn extract_entities_acronyms() {
        let ents = extract_entities("MCOA and CDATA report", 5);
        assert!(ents.iter().any(|e| e == "MCOA"));
        assert!(ents.iter().any(|e| e == "CDATA"));
    }

    #[test]
    fn extract_entities_cyrillic() {
        let ents = extract_entities("Иванов работал в 2024 году", 5);
        assert!(ents.iter().any(|e| e == "Иванов"));
    }

    // ── Cache ────────────────────────────────────────────────────────────────

    #[test]
    fn cache_set_and_get_roundtrip() {
        let cache = Cache::new(Duration::from_secs(60), 8);
        let val = vec![serde_json::json!({"id": 1})];
        cache.set("flat:foo".into(), val.clone());
        assert_eq!(cache.get("flat:foo"), Some(val));
    }

    #[test]
    fn cache_miss_returns_none() {
        let cache = Cache::new(Duration::from_secs(60), 8);
        assert!(cache.get("nope").is_none());
    }

    #[test]
    fn cache_evicts_lru_when_over_max() {
        let cache = Cache::new(Duration::from_secs(60), 2);
        cache.set("a".into(), vec![]);
        cache.set("b".into(), vec![]);
        cache.set("c".into(), vec![]);
        assert!(cache.get("a").is_none());
        assert!(cache.get("b").is_some());
        assert!(cache.get("c").is_some());
    }

    #[test]
    fn cache_get_promotes_to_mru() {
        let cache = Cache::new(Duration::from_secs(60), 2);
        cache.set("a".into(), vec![]);
        cache.set("b".into(), vec![]);
        let _ = cache.get("a"); // bump a → MRU
        cache.set("c".into(), vec![]); // evicts b, not a
        assert!(cache.get("a").is_some());
        assert!(cache.get("b").is_none());
    }

    #[test]
    fn cache_ttl_expires() {
        let cache = Cache::new(Duration::from_millis(10), 8);
        cache.set("k".into(), vec![serde_json::json!(1)]);
        // simulate clock advance via get_at
        let future = Instant::now() + Duration::from_secs(1);
        assert!(cache.get_at("k", future).is_none());
        // expired entry was purged
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn cache_keys_returned_mru_first() {
        let cache = Cache::new(Duration::from_secs(60), 8);
        cache.set("a".into(), vec![]);
        cache.set("b".into(), vec![]);
        cache.set("c".into(), vec![]);
        let keys = cache.keys();
        assert_eq!(keys[0], "c");
        assert_eq!(keys[2], "a");
    }

    // ── PrefetchConfig ───────────────────────────────────────────────────────

    #[test]
    fn config_defaults_match_python() {
        let c = PrefetchConfig::default();
        assert!(c.enabled);
        assert_eq!(c.workers, 3);
        assert_eq!(c.max_entities, 5);
        assert_eq!(c.ttl_seconds, 300);
        assert_eq!(c.cache_max, 64);
    }

    #[test]
    fn config_from_source_parses_env() {
        let mut env = HashMap::new();
        env.insert("AIM_PREFETCH".to_string(), "0".to_string());
        env.insert("AIM_PREFETCH_WORKERS".to_string(), "8".to_string());
        env.insert("AIM_PREFETCH_MAX_ENTITIES".to_string(), "10".to_string());
        let c = PrefetchConfig::from_source(|k| env.get(k).cloned());
        assert!(!c.enabled);
        assert_eq!(c.workers, 8);
        assert_eq!(c.max_entities, 10);
    }

    #[test]
    fn config_disabled_via_anything_other_than_truthy() {
        let mut env = HashMap::new();
        env.insert("AIM_PREFETCH".to_string(), "no".to_string());
        let c = PrefetchConfig::from_source(|k| env.get(k).cloned());
        assert!(!c.enabled);
    }

    // ── Prefetcher with stub retriever ──────────────────────────────────────

    struct CountingRetriever {
        calls: parking_lot::Mutex<Vec<(String, String, usize)>>,
    }

    impl CountingRetriever {
        fn new() -> Self {
            Self {
                calls: parking_lot::Mutex::new(Vec::new()),
            }
        }
    }

    impl Retriever for CountingRetriever {
        fn retrieve(&self, mode: &str, entity: &str, k: usize) -> Vec<Hit> {
            self.calls.lock().push((mode.into(), entity.into(), k));
            vec![serde_json::json!({"mode": mode, "ent": entity})]
        }
    }

    #[test]
    fn prefetch_warms_both_modes_per_entity() {
        let p = Prefetcher::new(PrefetchConfig::default());
        let r = CountingRetriever::new();
        let ents = p.prefetch_for_task("Tkemaladze worked in 2026", &r);
        assert!(ents.contains(&"Tkemaladze".to_string()));
        assert!(ents.contains(&"2026".to_string()));
        // each entity warmed in 2 modes (flat + graph)
        assert_eq!(r.calls.lock().len(), ents.len() * 2);
    }

    #[test]
    fn prefetch_disabled_returns_empty_and_skips_calls() {
        let mut cfg = PrefetchConfig::default();
        cfg.enabled = false;
        let p = Prefetcher::new(cfg);
        let r = CountingRetriever::new();
        let ents = p.prefetch_for_task("Tkemaladze", &r);
        assert!(ents.is_empty());
        assert!(r.calls.lock().is_empty());
    }

    #[test]
    fn prefetch_empty_task_returns_empty() {
        let p = Prefetcher::new(PrefetchConfig::default());
        let r = CountingRetriever::new();
        assert!(p.prefetch_for_task("", &r).is_empty());
    }

    #[test]
    fn prefetch_writes_to_cache_with_lowercase_key() {
        let p = Prefetcher::new(PrefetchConfig::default());
        let r = CountingRetriever::new();
        p.prefetch_for_task("Geiger", &r);
        assert!(p.cached_for("geiger", "flat").is_some());
        assert!(p.cached_for("GEIGER", "flat").is_some());
        assert!(p.cached_for("Geiger", "graph").is_some());
    }

    #[test]
    fn prefetch_cached_for_unknown_returns_none() {
        let p = Prefetcher::new(PrefetchConfig::default());
        let r = CountingRetriever::new();
        p.prefetch_for_task("Geiger", &r);
        assert!(p.cached_for("Nobody", "flat").is_none());
    }

    #[test]
    fn prefetch_stats_reports_cache_state() {
        let p = Prefetcher::new(PrefetchConfig::default());
        let r = CountingRetriever::new();
        p.prefetch_for_task("Geiger and Janke", &r);
        let s = p.stats();
        assert!(s.enabled);
        assert!(s.entries >= 2);
        assert!(s.keys.iter().any(|k| k.starts_with("flat:")));
        assert!(s.keys.iter().any(|k| k.starts_with("graph:")));
    }

    #[test]
    fn prefetch_max_entities_caps_warming() {
        let mut cfg = PrefetchConfig::default();
        cfg.max_entities = 2;
        let p = Prefetcher::new(cfg);
        let r = CountingRetriever::new();
        // years are atomic — each matches its own regex alternative
        let ents = p.prefetch_for_task("2001 2002 2003 2004", &r);
        assert_eq!(ents.len(), 2);
    }

    #[test]
    fn empty_retriever_yields_empty_hits() {
        let p = Prefetcher::new(PrefetchConfig::default());
        p.prefetch_for_task("Geiger", &EmptyRetriever);
        let hits = p.cached_for("Geiger", "flat").unwrap();
        assert!(hits.is_empty());
    }
}
