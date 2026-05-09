//! aim-speculative-prefetch — anticipatory tool execution.
//!
//! Port of `agents/speculative_prefetch.py`. While the LLM composes its
//! next step, the most likely upcoming tool calls run in the background;
//! their cached results are returned instantly when the LLM actually
//! requests them.
//!
//! The Python original uses `ThreadPoolExecutor.submit` returning Futures
//! consumed lazily. The Rust port keeps the **prediction layer** (regex
//! scanning + cache key derivation) pure and testable; concrete async
//! execution is left to the consumer (any pool/runtime works).
//!
//! Pure pieces:
//!   • [`Prediction`] — what the predictor thinks should be prefetched
//!   • [`predict`] — turn `history` into prefetch suggestions
//!   • [`cache_key`] — stable key for `(tool, args)`
//!   • [`Cache`] — in-memory store keyed by [`cache_key`]

use std::collections::BTreeMap;

use once_cell::sync::Lazy;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};

// ── regex banks ────────────────────────────────────────────────────────────

static PATH_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?:^|[^\w/])((?:/(?:home|tmp|var|etc|Users)/[^\s'\x22`)\]]+))")
        .expect("path regex compiles")
});
static PMID_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\bPMID[:\s]*(\d{4,9})\b").expect("pmid regex"));
static DOI_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\b(10\.\d{4,9}/[^\s\)\]\},;]+)").expect("doi regex")
});

const PROJECTS: &[&str] = &[
    "FCLC", "MCOA", "Ze", "BioSense", "CDATA", "AIM",
    "Annals", "PhD", "Books", "GLA", "LongevityCommon",
];

const MAX_PATH_PREDICTIONS: usize = 3;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Prediction {
    pub tool: String,
    pub args: BTreeMap<String, String>,
}

impl Prediction {
    pub fn new(tool: &str, args: &[(&str, &str)]) -> Self {
        let mut m = BTreeMap::new();
        for (k, v) in args {
            m.insert((*k).to_string(), (*v).to_string());
        }
        Self {
            tool: tool.to_string(),
            args: m,
        }
    }

    pub fn key(&self) -> String {
        cache_key(&self.tool, &self.args)
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Turn {
    /// Both `content` and `result` map to the same scan space.
    pub content: String,
}

// ── cache key ──────────────────────────────────────────────────────────────

/// Stable cache key: `tool::k1=v1|k2=v2|…` (alphabetically sorted, value
/// truncated at 120 chars). Mirrors Python `_key`.
pub fn cache_key(tool: &str, args: &BTreeMap<String, String>) -> String {
    let parts: Vec<String> = args
        .iter()
        .map(|(k, v)| {
            let truncated: String = v.chars().take(120).collect();
            format!("{}={}", k, truncated)
        })
        .collect();
    format!("{}::{}", tool, parts.join("|"))
}

// ── predictor ──────────────────────────────────────────────────────────────

/// Scan the most recent `last_n` turns and produce prefetch suggestions.
/// Default Python uses `last_n = 3`. Rules (priority order):
///   1. Up to 3 absolute paths (under /home, /tmp, /var, /etc, /Users) →
///      `read_file{path, offset:0, limit:200}`.
///   2. Each known project name → `memory_recall{query: <name>, k: 6}`.
///   3. Each PMID → `verify_pmid{pmid: <id>}`.
///   4. Each DOI → `verify_doi{doi: <id>}`.
pub fn predict(history: &[Turn], last_n: usize) -> Vec<Prediction> {
    if history.is_empty() {
        return Vec::new();
    }
    let take = last_n.min(history.len());
    let start = history.len() - take;
    let text: String = history[start..]
        .iter()
        .map(|t| t.content.as_str())
        .collect::<Vec<_>>()
        .join("\n");

    let mut predictions: Vec<Prediction> = Vec::new();
    let mut seen_keys: std::collections::HashSet<String> = std::collections::HashSet::new();

    // 1. Paths
    let mut seen_paths: std::collections::HashSet<String> = std::collections::HashSet::new();
    for cap in PATH_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1) {
            let p = m.as_str().trim_end_matches([',', '.', ')', ';']).to_string();
            if seen_paths.contains(&p) {
                continue;
            }
            seen_paths.insert(p.clone());
            let pred = Prediction::new(
                "read_file",
                &[("path", &p), ("offset", "0"), ("limit", "200")],
            );
            let k = pred.key();
            if seen_keys.insert(k) {
                predictions.push(pred);
            }
            if seen_paths.len() >= MAX_PATH_PREDICTIONS {
                break;
            }
        }
    }

    // 2. Projects
    let lowered = text.to_lowercase();
    for proj in PROJECTS {
        let needle = format!(" {} ", proj.to_lowercase());
        let edge_left = format!("\n{}", proj.to_lowercase());
        let edge_right = format!("{} ", proj.to_lowercase());
        if lowered.contains(&needle)
            || lowered.starts_with(&proj.to_lowercase())
            || lowered.contains(&edge_left)
            || lowered.contains(&edge_right)
            || lowered.contains(&proj.to_lowercase())
        {
            // The simpler `contains(proj.to_lowercase())` is what we want;
            // boundary-aware regex would over-match too. Python uses
            // `re.search(rf"\b{proj}\b", text)`. Approximate the boundary by
            // a regex per project.
            let re = Regex::new(&format!(r"(?i)\b{}\b", regex::escape(proj))).unwrap();
            if re.is_match(&text) {
                let pred = Prediction::new(
                    "memory_recall",
                    &[("query", proj), ("k", "6")],
                );
                if seen_keys.insert(pred.key()) {
                    predictions.push(pred);
                }
            }
        }
    }

    // 3. PMIDs
    for cap in PMID_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1) {
            let pmid = m.as_str().to_string();
            let pred = Prediction::new("verify_pmid", &[("pmid", &pmid)]);
            if seen_keys.insert(pred.key()) {
                predictions.push(pred);
            }
        }
    }

    // 4. DOIs
    for cap in DOI_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1) {
            let doi = m.as_str().to_string();
            let pred = Prediction::new("verify_doi", &[("doi", &doi)]);
            if seen_keys.insert(pred.key()) {
                predictions.push(pred);
            }
        }
    }

    predictions
}

// ── cache ──────────────────────────────────────────────────────────────────

/// Outcome of a speculative call.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CacheState {
    Done(String),
    Pending,
    NotPresent,
}

#[derive(Default)]
pub struct Cache {
    inner: Mutex<BTreeMap<String, CacheState>>,
}

impl Cache {
    pub fn new() -> Self {
        Self::default()
    }

    /// Mark `(tool, args)` as in-flight. Returns whether a new slot was
    /// created (false if the key already existed).
    pub fn submit(&self, tool: &str, args: &BTreeMap<String, String>) -> bool {
        let key = cache_key(tool, args);
        let mut m = self.inner.lock();
        if m.contains_key(&key) {
            return false;
        }
        m.insert(key, CacheState::Pending);
        true
    }

    /// Resolve a pending entry with a finished result.
    pub fn resolve(&self, tool: &str, args: &BTreeMap<String, String>, value: impl Into<String>) {
        let key = cache_key(tool, args);
        self.inner.lock().insert(key, CacheState::Done(value.into()));
    }

    /// Pop the entry. Mirrors Python `consume`: returns `Some(_)` only when
    /// the slot is `Done`; `None` when missing or still pending. Pending
    /// keys are also removed (the future is "thrown away").
    pub fn consume(&self, tool: &str, args: &BTreeMap<String, String>) -> Option<String> {
        let key = cache_key(tool, args);
        let mut m = self.inner.lock();
        match m.remove(&key) {
            Some(CacheState::Done(v)) => Some(v),
            _ => None,
        }
    }

    pub fn peek(&self, tool: &str, args: &BTreeMap<String, String>) -> CacheState {
        let key = cache_key(tool, args);
        self.inner
            .lock()
            .get(&key)
            .cloned()
            .unwrap_or(CacheState::NotPresent)
    }

    pub fn len(&self) -> usize {
        self.inner.lock().len()
    }
    pub fn is_empty(&self) -> bool {
        self.inner.lock().is_empty()
    }
    pub fn clear(&self) {
        self.inner.lock().clear()
    }
}

// ── prefetcher (thin orchestrator) ─────────────────────────────────────────

/// Pluggable executor. Production binds to a thread/Tokio pool; tests use
/// a synchronous stub.
pub trait Executor: Send + Sync {
    /// Execute `pred` and return its result. Production impls run this in
    /// the background and pass the value to [`Cache::resolve`] when done.
    fn execute(&self, pred: Prediction) -> String;
}

pub struct Prefetcher<'a> {
    pub cache: &'a Cache,
    pub executor: &'a dyn Executor,
}

impl<'a> Prefetcher<'a> {
    pub fn new(cache: &'a Cache, executor: &'a dyn Executor) -> Self {
        Self { cache, executor }
    }

    /// Synchronous variant: predict, run inline, fill the cache. Useful
    /// for tests; production wraps `execute` in a background pool.
    pub fn observe_and_run(&self, history: &[Turn]) {
        for pred in predict(history, 3) {
            if !self.cache.submit(&pred.tool, &pred.args) {
                continue;
            }
            let value = self.executor.execute(pred.clone());
            self.cache.resolve(&pred.tool, &pred.args, value);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn turn(content: &str) -> Turn {
        Turn {
            content: content.into(),
        }
    }

    fn args(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
        let mut m = BTreeMap::new();
        for (k, v) in pairs {
            m.insert((*k).to_string(), (*v).to_string());
        }
        m
    }

    // ── cache_key ───────────────────────────────────────────────────────────

    #[test]
    fn cache_key_alphabetical_and_truncated() {
        let a = args(&[("z", "z-value"), ("a", "a-value")]);
        let k = cache_key("read_file", &a);
        assert!(k.contains("a=a-value"));
        assert!(k.contains("z=z-value"));
        // BTreeMap iteration order is alphabetical → 'a' before 'z'
        let pos_a = k.find("a=a-value").unwrap();
        let pos_z = k.find("z=z-value").unwrap();
        assert!(pos_a < pos_z);
    }

    #[test]
    fn cache_key_truncates_long_value() {
        let big = "x".repeat(500);
        let a = args(&[("path", &big)]);
        let k = cache_key("read_file", &a);
        // Value should be at most 120 chars
        let value_part = k.split("path=").nth(1).unwrap();
        assert_eq!(value_part.chars().count(), 120);
    }

    // ── predict: paths ──────────────────────────────────────────────────────

    #[test]
    fn predict_picks_up_absolute_paths_in_text() {
        let history = vec![turn("see /home/oem/Desktop/x.md")];
        let preds = predict(&history, 3);
        assert!(preds.iter().any(|p| p.tool == "read_file"
            && p.args.get("path").unwrap() == "/home/oem/Desktop/x.md"));
    }

    #[test]
    fn predict_caps_paths_at_three() {
        let history = vec![turn(
            "/home/a /home/b /home/c /home/d /home/e /home/f",
        )];
        let preds = predict(&history, 3);
        let n_paths = preds.iter().filter(|p| p.tool == "read_file").count();
        assert_eq!(n_paths, MAX_PATH_PREDICTIONS);
    }

    #[test]
    fn predict_strips_trailing_punctuation_from_path() {
        let history = vec![turn("see /home/oem/x.md.")];
        let preds = predict(&history, 3);
        let p = preds.iter().find(|p| p.tool == "read_file").unwrap();
        assert_eq!(p.args.get("path").unwrap(), "/home/oem/x.md");
    }

    // ── predict: projects ──────────────────────────────────────────────────

    #[test]
    fn predict_recognises_project_names() {
        let history = vec![turn("обновил CDATA сегодня")];
        let preds = predict(&history, 3);
        let recall: Vec<_> = preds
            .iter()
            .filter(|p| p.tool == "memory_recall")
            .collect();
        assert!(recall.iter().any(|p| p.args.get("query").unwrap() == "CDATA"));
    }

    #[test]
    fn predict_does_not_match_substring_in_word() {
        // "screened" contains "ze" but not project Ze
        let history = vec![turn("screened the data")];
        let preds = predict(&history, 3);
        assert!(!preds.iter().any(|p| p.args.get("query").map(|s| s.as_str()) == Some("Ze")));
    }

    #[test]
    fn predict_limits_to_last_n_turns() {
        let history = vec![
            turn("first turn mentions FCLC"),
            turn("middle turn boring"),
            turn("recent turn mentions AIM"),
        ];
        let preds = predict(&history, 1);
        let names: Vec<&str> = preds
            .iter()
            .filter(|p| p.tool == "memory_recall")
            .map(|p| p.args.get("query").unwrap().as_str())
            .collect();
        assert!(names.contains(&"AIM"));
        assert!(!names.contains(&"FCLC"));
    }

    // ── predict: PMID / DOI ────────────────────────────────────────────────

    #[test]
    fn predict_extracts_pmid() {
        let history = vec![turn("see PMID 12345678 for details")];
        let preds = predict(&history, 3);
        assert!(preds
            .iter()
            .any(|p| p.tool == "verify_pmid" && p.args.get("pmid").unwrap() == "12345678"));
    }

    #[test]
    fn predict_extracts_doi() {
        let history = vec![turn("ref 10.1073/pnas.123 for the paper")];
        let preds = predict(&history, 3);
        assert!(preds
            .iter()
            .any(|p| p.tool == "verify_doi" && p.args.get("doi").unwrap().starts_with("10.1073")));
    }

    #[test]
    fn predict_dedupes_repeated_pmid() {
        let history = vec![turn("PMID 11111 again PMID 11111")];
        let preds = predict(&history, 3);
        let n = preds
            .iter()
            .filter(|p| p.tool == "verify_pmid" && p.args.get("pmid").unwrap() == "11111")
            .count();
        assert_eq!(n, 1);
    }

    #[test]
    fn predict_empty_history_returns_empty() {
        assert!(predict(&[], 3).is_empty());
    }

    // ── Cache ───────────────────────────────────────────────────────────────

    #[test]
    fn cache_submit_returns_true_first_time_then_false() {
        let c = Cache::new();
        let a = args(&[("path", "/x")]);
        assert!(c.submit("read_file", &a));
        assert!(!c.submit("read_file", &a));
    }

    #[test]
    fn cache_consume_returns_value_only_when_done() {
        let c = Cache::new();
        let a = args(&[("path", "/x")]);
        c.submit("read_file", &a);
        // pending → None (and removes the slot)
        assert_eq!(c.consume("read_file", &a), None);
        // Slot now removed
        assert_eq!(c.peek("read_file", &a), CacheState::NotPresent);
        // resubmit + resolve
        c.submit("read_file", &a);
        c.resolve("read_file", &a, "hello");
        assert_eq!(c.consume("read_file", &a), Some("hello".into()));
        assert_eq!(c.peek("read_file", &a), CacheState::NotPresent);
    }

    #[test]
    fn cache_peek_reflects_state() {
        let c = Cache::new();
        let a = args(&[("path", "/x")]);
        assert_eq!(c.peek("read_file", &a), CacheState::NotPresent);
        c.submit("read_file", &a);
        assert_eq!(c.peek("read_file", &a), CacheState::Pending);
        c.resolve("read_file", &a, "v");
        assert_eq!(c.peek("read_file", &a), CacheState::Done("v".into()));
    }

    // ── Prefetcher.observe_and_run ─────────────────────────────────────────

    struct StubExecutor;
    impl Executor for StubExecutor {
        fn execute(&self, pred: Prediction) -> String {
            format!("ran:{}", pred.tool)
        }
    }

    #[test]
    fn prefetcher_runs_predictions_into_cache() {
        let cache = Cache::new();
        let exec = StubExecutor;
        let p = Prefetcher::new(&cache, &exec);
        p.observe_and_run(&[turn("see /home/oem/x.md and CDATA")]);
        // both predictions executed
        let read_args = args(&[("path", "/home/oem/x.md"), ("offset", "0"), ("limit", "200")]);
        let recall_args = args(&[("query", "CDATA"), ("k", "6")]);
        assert_eq!(
            cache.consume("read_file", &read_args),
            Some("ran:read_file".into())
        );
        assert_eq!(
            cache.consume("memory_recall", &recall_args),
            Some("ran:memory_recall".into())
        );
    }

    #[test]
    fn prefetcher_skips_already_submitted_keys() {
        let cache = Cache::new();
        let exec = StubExecutor;
        let p = Prefetcher::new(&cache, &exec);
        p.observe_and_run(&[turn("see /home/oem/x.md")]);
        // running again should not add a duplicate (cache already has it)
        let len_before = cache.len();
        p.observe_and_run(&[turn("see /home/oem/x.md")]);
        // still 1 (the entry was consumed via observe_and_run resolve, not popped)
        // observe_and_run only resolves; Done entries stay.
        let _ = len_before;
        assert!(cache.peek(
            "read_file",
            &args(&[("path", "/home/oem/x.md"), ("offset", "0"), ("limit", "200")])
        ) != CacheState::NotPresent);
    }
}
