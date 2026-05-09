//! aim-smart-fallback — multi-tier fallback chain across LLM providers.
//!
//! Port of `agents/smart_fallback.py`. Last line of defence after
//! circuit-breaker / rate-limiter / resilient-llm have already exhausted
//! retries on the primary path. Walks through a configurable provider
//! chain, returns the first successful response, records every attempt
//! to SQLite for analytics.
//!
//! ## Default chain (top → bottom)
//! 1. `deepseek/deepseek-chat` (primary)
//! 2. `deepseek/deepseek-reasoner` (better quality, more expensive)
//! 3. `groq/llama-3.3-70b-versatile` (different network)
//! 4. `groq/llama-3.1-8b-instant` (cheapest, last resort)
//!
//! Override via env:
//! - `AIM_FALLBACK_CHAIN=deepseek-chat,groq-llama-70b,groq-llama-8b`
//! - `AIM_FALLBACK_DISABLED=1` (skip fallback entirely)
//!
//! ## Pluggable callers
//! [`Caller`] is the trait the host wires to actual `_deepseek()` /
//! `_groq()` clients. Tests inject [`StubCaller`] with a per-tier success/
//! failure script.

use async_trait::async_trait;
use chrono::Utc;
use parking_lot::Mutex;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;
use std::time::Instant;

#[derive(Debug, Error)]
pub enum FallbackError {
    #[error("all fallback tiers exhausted; last error: {0}")]
    AllExhausted(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Tier {
    pub provider: String,
    pub model: String,
}

impl Tier {
    pub fn new(provider: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            provider: provider.into(),
            model: model.into(),
        }
    }

    pub fn label(&self) -> String {
        format!("{}/{}", self.provider, self.model)
    }
}

pub fn default_chain() -> Vec<Tier> {
    vec![
        Tier::new("deepseek", "deepseek-chat"),
        Tier::new("deepseek", "deepseek-reasoner"),
        Tier::new("groq", "llama-3.3-70b-versatile"),
        Tier::new("groq", "llama-3.1-8b-instant"),
    ]
}

/// Read `AIM_FALLBACK_CHAIN` (comma-separated) into a [`Tier`] vec.
/// Bare names beginning with `groq-` or `llama` resolve to the `groq`
/// provider; everything else routes to `deepseek`. Mirrors Python.
pub fn load_chain_from_env() -> Vec<Tier> {
    let raw = std::env::var("AIM_FALLBACK_CHAIN").unwrap_or_default();
    if raw.trim().is_empty() {
        return default_chain();
    }
    let mut out = Vec::new();
    for entry in raw.split(',') {
        let e = entry.trim();
        if e.is_empty() {
            continue;
        }
        if e.starts_with("groq-") || e.starts_with("llama") {
            out.push(Tier::new("groq", e.trim_start_matches("groq-")));
        } else {
            out.push(Tier::new("deepseek", e));
        }
    }
    if out.is_empty() {
        default_chain()
    } else {
        out
    }
}

pub fn fallback_disabled() -> bool {
    std::env::var("AIM_FALLBACK_DISABLED")
        .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(false)
}

#[derive(Debug, Clone, Copy, Default)]
pub struct CallOpts {
    pub temperature: f32,
    pub max_tokens: u32,
}

impl CallOpts {
    pub fn new() -> Self {
        Self {
            temperature: 0.3,
            max_tokens: 4096,
        }
    }
}

#[async_trait]
pub trait Caller: Send + Sync {
    /// Invoke a specific provider/model pair. Return `Ok(text)` on
    /// success or `Err(message)` on any failure.
    async fn call(
        &self,
        tier: &Tier,
        prompt: &str,
        system: &str,
        opts: CallOpts,
    ) -> Result<String, String>;
}

/// Test-friendly caller: a tier-keyed map of either canned responses or
/// errors, popped one at a time.
pub struct StubCaller {
    pub responses: Mutex<HashMap<String, Vec<Result<String, String>>>>,
    pub call_log: Mutex<Vec<String>>,
}

impl StubCaller {
    pub fn new() -> Self {
        Self {
            responses: Mutex::new(HashMap::new()),
            call_log: Mutex::new(Vec::new()),
        }
    }

    pub fn with_response(self, label: &str, response: Result<&str, &str>) -> Self {
        let mut q = self.responses.lock();
        let entry = q.entry(label.to_string()).or_default();
        entry.push(match response {
            Ok(s) => Ok(s.to_string()),
            Err(e) => Err(e.to_string()),
        });
        drop(q);
        self
    }

    pub fn calls(&self) -> Vec<String> {
        self.call_log.lock().clone()
    }
}

impl Default for StubCaller {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Caller for StubCaller {
    async fn call(
        &self,
        tier: &Tier,
        _prompt: &str,
        _system: &str,
        _opts: CallOpts,
    ) -> Result<String, String> {
        let label = tier.label();
        self.call_log.lock().push(label.clone());
        let mut q = self.responses.lock();
        let entry = q.get_mut(&label);
        match entry {
            Some(v) if !v.is_empty() => v.remove(0),
            _ => Err(format!("stub: no response for {label}")),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AttemptStats {
    pub attempts: u64,
    pub successes: u64,
    pub fail_rate: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FallbackStats {
    pub chain: Vec<Tier>,
    pub rows: u64,
    pub by_model: HashMap<String, AttemptStats>,
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, provider TEXT, model TEXT,
    ok INTEGER, error TEXT, latency_s REAL
);
";

pub fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude").join("smart_fallback.db")
}

pub struct Fallback {
    chain: Vec<Tier>,
    caller: Arc<dyn Caller>,
    conn: Option<Arc<Mutex<Connection>>>,
}

impl Fallback {
    pub fn new(
        chain: Vec<Tier>,
        caller: Arc<dyn Caller>,
        db: Option<&Path>,
    ) -> Result<Self, FallbackError> {
        let conn = match db {
            Some(p) => {
                if let Some(parent) = p.parent() {
                    if !parent.as_os_str().is_empty() {
                        std::fs::create_dir_all(parent)?;
                    }
                }
                let c = Connection::open(p)?;
                c.execute_batch(SCHEMA)?;
                Some(Arc::new(Mutex::new(c)))
            }
            None => None,
        };
        Ok(Self { chain, caller, conn })
    }

    pub fn chain(&self) -> &[Tier] {
        &self.chain
    }

    fn record(&self, tier: &Tier, ok: bool, error: &str, latency_s: f64) {
        let Some(conn) = &self.conn else {
            return;
        };
        let con = conn.lock();
        let trimmed: String = error.chars().take(300).collect();
        let _ = con.execute(
            "INSERT INTO attempts(ts, provider, model, ok, error, latency_s) VALUES (?,?,?,?,?,?)",
            params![
                Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
                tier.provider,
                tier.model,
                if ok { 1 } else { 0 },
                trimmed,
                round3(latency_s),
            ],
        );
    }

    /// Try each tier in the chain; return the first successful response.
    /// All-tier failure surfaces as `FallbackError::AllExhausted`.
    pub async fn call(
        &self,
        prompt: &str,
        system: &str,
        opts: CallOpts,
    ) -> Result<String, FallbackError> {
        let mut last_err = String::new();
        for (i, tier) in self.chain.iter().enumerate() {
            let t0 = Instant::now();
            match self.caller.call(tier, prompt, system, opts).await {
                Ok(text) => {
                    let dt = t0.elapsed().as_secs_f64();
                    self.record(tier, true, "", dt);
                    if i > 0 {
                        tracing::warn!(
                            "fallback succeeded at tier {} ({})",
                            i + 1,
                            tier.label()
                        );
                    }
                    return Ok(text);
                }
                Err(e) => {
                    let dt = t0.elapsed().as_secs_f64();
                    self.record(tier, false, &e, dt);
                    tracing::warn!(
                        "fallback tier {} ({}) failed: {}",
                        i + 1,
                        tier.label(),
                        e
                    );
                    last_err = e;
                }
            }
        }
        Err(FallbackError::AllExhausted(last_err))
    }

    pub fn stats(&self) -> Result<FallbackStats, FallbackError> {
        let chain = self.chain.clone();
        let Some(conn) = &self.conn else {
            return Ok(FallbackStats {
                chain,
                rows: 0,
                by_model: HashMap::new(),
            });
        };
        let con = conn.lock();
        let rows: u64 = con
            .query_row("SELECT COUNT(*) FROM attempts", [], |r| {
                r.get::<_, i64>(0).map(|n| n as u64)
            })
            .unwrap_or(0);
        let mut by_model = HashMap::new();
        {
            let mut stmt = con.prepare(
                "SELECT provider, model, COUNT(*), COALESCE(SUM(ok),0) FROM attempts GROUP BY provider, model",
            )?;
            let q = stmt.query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, i64>(2)? as u64,
                    r.get::<_, i64>(3)? as u64,
                ))
            })?;
            for row in q.flatten() {
                let label = format!("{}/{}", row.0, row.1);
                if row.2 == 0 {
                    continue;
                }
                let fail_rate = round3(1.0 - (row.3 as f64) / (row.2 as f64));
                by_model.insert(
                    label,
                    AttemptStats {
                        attempts: row.2,
                        successes: row.3,
                        fail_rate,
                    },
                );
            }
        }
        Ok(FallbackStats {
            chain,
            rows,
            by_model,
        })
    }
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make(stub: Arc<StubCaller>) -> (TempDir, Fallback) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("fb.db");
        let f = Fallback::new(default_chain(), stub, Some(&db)).unwrap();
        (dir, f)
    }

    #[test]
    fn default_chain_has_four_tiers() {
        let c = default_chain();
        assert_eq!(c.len(), 4);
        assert_eq!(c[0].label(), "deepseek/deepseek-chat");
        assert_eq!(c[3].label(), "groq/llama-3.1-8b-instant");
    }

    #[test]
    fn load_chain_default_when_env_empty() {
        std::env::remove_var("AIM_FALLBACK_CHAIN");
        assert_eq!(load_chain_from_env(), default_chain());
    }

    #[test]
    fn load_chain_parses_csv_and_routes_groq_prefix() {
        std::env::set_var(
            "AIM_FALLBACK_CHAIN",
            "deepseek-chat,groq-llama-3.3-70b-versatile,llama-3.1-8b-instant",
        );
        let chain = load_chain_from_env();
        assert_eq!(chain.len(), 3);
        assert_eq!(chain[0].provider, "deepseek");
        assert_eq!(chain[1].provider, "groq");
        assert_eq!(chain[1].model, "llama-3.3-70b-versatile");
        assert_eq!(chain[2].provider, "groq");
        std::env::remove_var("AIM_FALLBACK_CHAIN");
    }

    #[test]
    fn fallback_disabled_env_check() {
        std::env::remove_var("AIM_FALLBACK_DISABLED");
        assert!(!fallback_disabled());
        std::env::set_var("AIM_FALLBACK_DISABLED", "1");
        assert!(fallback_disabled());
        std::env::set_var("AIM_FALLBACK_DISABLED", "yes");
        assert!(fallback_disabled());
        std::env::set_var("AIM_FALLBACK_DISABLED", "no");
        assert!(!fallback_disabled());
        std::env::remove_var("AIM_FALLBACK_DISABLED");
    }

    #[tokio::test]
    async fn first_tier_success_short_circuits() {
        let stub = Arc::new(
            StubCaller::new().with_response("deepseek/deepseek-chat", Ok("hello")),
        );
        let (_d, fb) = make(stub.clone());
        let r = fb.call("Q?", "", CallOpts::new()).await.unwrap();
        assert_eq!(r, "hello");
        assert_eq!(stub.calls(), vec!["deepseek/deepseek-chat"]);
    }

    #[tokio::test]
    async fn falls_through_on_failure() {
        let stub = Arc::new(
            StubCaller::new()
                .with_response("deepseek/deepseek-chat", Err("rate limited"))
                .with_response("deepseek/deepseek-reasoner", Err("503"))
                .with_response("groq/llama-3.3-70b-versatile", Ok("from llama 70b")),
        );
        let (_d, fb) = make(stub.clone());
        let r = fb.call("Q?", "", CallOpts::new()).await.unwrap();
        assert_eq!(r, "from llama 70b");
        // All three earlier tiers were tried
        let log = stub.calls();
        assert_eq!(log.len(), 3);
        assert_eq!(log[2], "groq/llama-3.3-70b-versatile");
    }

    #[tokio::test]
    async fn all_exhausted_surfaces_last_error() {
        let stub = Arc::new(
            StubCaller::new()
                .with_response("deepseek/deepseek-chat", Err("e1"))
                .with_response("deepseek/deepseek-reasoner", Err("e2"))
                .with_response("groq/llama-3.3-70b-versatile", Err("e3"))
                .with_response("groq/llama-3.1-8b-instant", Err("LAST")),
        );
        let (_d, fb) = make(stub.clone());
        let err = fb.call("Q?", "", CallOpts::new()).await.unwrap_err();
        match err {
            FallbackError::AllExhausted(msg) => assert_eq!(msg, "LAST"),
            _ => panic!("wrong err"),
        }
        assert_eq!(stub.calls().len(), 4);
    }

    #[tokio::test]
    async fn stats_records_every_attempt() {
        let stub = Arc::new(
            StubCaller::new()
                .with_response("deepseek/deepseek-chat", Err("nope"))
                .with_response("deepseek/deepseek-reasoner", Ok("ok")),
        );
        let (_d, fb) = make(stub);
        fb.call("Q", "", CallOpts::new()).await.unwrap();
        let s = fb.stats().unwrap();
        assert_eq!(s.rows, 2);
        let chat = s.by_model.get("deepseek/deepseek-chat").unwrap();
        assert_eq!(chat.attempts, 1);
        assert_eq!(chat.successes, 0);
        assert!((chat.fail_rate - 1.0).abs() < 1e-9);
        let reasoner = s.by_model.get("deepseek/deepseek-reasoner").unwrap();
        assert_eq!(reasoner.successes, 1);
        assert_eq!(reasoner.fail_rate, 0.0);
    }

    #[tokio::test]
    async fn stats_empty_when_no_attempts() {
        let stub = Arc::new(StubCaller::new());
        let (_d, fb) = make(stub);
        let s = fb.stats().unwrap();
        assert_eq!(s.rows, 0);
        assert!(s.by_model.is_empty());
        assert_eq!(s.chain.len(), 4);
    }

    #[tokio::test]
    async fn fallback_without_db_skips_recording() {
        let stub = Arc::new(StubCaller::new().with_response("deepseek/deepseek-chat", Ok("ok")));
        let fb = Fallback::new(default_chain(), stub.clone(), None).unwrap();
        let r = fb.call("Q", "", CallOpts::new()).await.unwrap();
        assert_eq!(r, "ok");
        let s = fb.stats().unwrap();
        assert_eq!(s.rows, 0);
    }

    #[tokio::test]
    async fn custom_chain_is_walked_in_order() {
        let stub = Arc::new(
            StubCaller::new()
                .with_response("deepseek/x1", Err("fail"))
                .with_response("groq/x2", Ok("hit")),
        );
        let chain = vec![Tier::new("deepseek", "x1"), Tier::new("groq", "x2")];
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("fb.db");
        let fb = Fallback::new(chain, stub.clone(), Some(&db)).unwrap();
        let r = fb.call("Q", "", CallOpts::new()).await.unwrap();
        assert_eq!(r, "hit");
        assert_eq!(stub.calls(), vec!["deepseek/x1", "groq/x2"]);
    }
}
