//! aim-smart-routing — pick the cheapest adequate model based on prompt
//! complexity + estimated cost.
//!
//! Port of `agents/smart_routing.py`. Three tiers:
//! - **fast** — Groq llama-3.1-8b-instant (cheapest, ≤200 chars or
//!   simple-Q pattern)
//! - **standard** — DeepSeek chat (default)
//! - **reasoning** — DeepSeek-reasoner (only when reasoning markers
//!   detected OR caller forces it)
//!
//! Backwards-compatible: callers opt in via `AIM_SMART_ROUTING=1`. Routes
//! get logged to SQLite (`~/.claude/smart_routing.db`) for cost-savings
//! analysis.

use chrono::Utc;
use parking_lot::Mutex;
use regex::Regex;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RouteError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Tier {
    Fast,
    Standard,
    Reasoning,
    Forced,
}

impl Tier {
    pub fn as_str(self) -> &'static str {
        match self {
            Tier::Fast => "fast",
            Tier::Standard => "standard",
            Tier::Reasoning => "reasoning",
            Tier::Forced => "forced",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelPrice {
    pub input: f64,
    pub output: f64,
}

/// Default DeepSeek V4 + Groq pricing (mirrors Python module 2026-04).
pub fn default_prices() -> HashMap<String, ModelPrice> {
    let mut m = HashMap::new();
    m.insert(
        "deepseek-v4-flash".into(),
        ModelPrice {
            input: 0.14,
            output: 0.28,
        },
    );
    m.insert(
        "deepseek-v4-pro".into(),
        ModelPrice {
            input: 0.435,
            output: 0.87,
        },
    );
    m.insert(
        "deepseek-chat".into(),
        ModelPrice {
            input: 0.14,
            output: 0.28,
        },
    );
    m.insert(
        "deepseek-reasoner".into(),
        ModelPrice {
            input: 0.435,
            output: 0.87,
        },
    );
    m.insert(
        "llama-3.1-8b-instant".into(),
        ModelPrice {
            input: 0.05,
            output: 0.08,
        },
    );
    m.insert(
        "llama-3.3-70b-versatile".into(),
        ModelPrice {
            input: 0.59,
            output: 0.79,
        },
    );
    m
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RouteInfo {
    pub model: String,
    pub tier: Tier,
    pub reason: String,
    pub est_in_tokens: u64,
    pub est_cost: f64,
}

static REASONING_RE: OnceLock<Regex> = OnceLock::new();
static FAST_RE: OnceLock<Regex> = OnceLock::new();

fn reasoning_re() -> &'static Regex {
    REASONING_RE.get_or_init(|| {
        Regex::new(
            r"(?i)\b(?:почему|объясни|обоснуй|проанализируй|сравни|оцени|why|explain|analyse|analyze|compare|reason|prove|justify|докажи|выведи|разложи|обсуди)\b",
        )
        .expect("reasoning regex")
    })
}

fn fast_re() -> &'static Regex {
    FAST_RE.get_or_init(|| {
        Regex::new(
            r"(?i)^(?:что|кто|когда|где|сколько|when|who|where|how many|what is|какой|какая|какое)\s",
        )
        .expect("fast regex")
    })
}

/// Pure classification — no DB write, no env. Test seam.
pub fn classify(prompt: &str, force_model: Option<&str>) -> RouteInfo {
    if let Some(m) = force_model {
        return RouteInfo {
            model: m.to_string(),
            tier: Tier::Forced,
            reason: "caller forced model".into(),
            est_in_tokens: (prompt.len() / 4).max(1) as u64,
            est_cost: 0.0,
        };
    }
    let n = prompt.chars().count();
    let est_tokens = (prompt.len() / 4).max(1) as u64;

    if reasoning_re().is_match(prompt) {
        return RouteInfo {
            model: "deepseek-reasoner".into(),
            tier: Tier::Reasoning,
            reason: "reasoning marker matched".into(),
            est_in_tokens: est_tokens,
            est_cost: 0.0,
        };
    }
    if n < 200 || fast_re().is_match(prompt) {
        return RouteInfo {
            model: "llama-3.1-8b-instant".into(),
            tier: Tier::Fast,
            reason: "short or simple-Q pattern".into(),
            est_in_tokens: est_tokens,
            est_cost: 0.0,
        };
    }
    RouteInfo {
        model: "deepseek-chat".into(),
        tier: Tier::Standard,
        reason: "default".into(),
        est_in_tokens: est_tokens,
        est_cost: 0.0,
    }
}

pub fn estimate_cost(prices: &HashMap<String, ModelPrice>, model: &str, in_tok: u64, out_tok: u64) -> f64 {
    let p = prices.get(model).cloned().unwrap_or(ModelPrice {
        input: 1.0,
        output: 2.0,
    });
    ((in_tok as f64) * p.input + (out_tok as f64) * p.output) / 1_000_000.0
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RouteStats {
    pub enabled: bool,
    pub rows: u64,
    pub estimated_cost: f64,
    pub by_tier: HashMap<String, u64>,
    pub by_model: HashMap<String, u64>,
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS routes (
    ts TEXT, model TEXT, tier TEXT,
    prompt_chars INTEGER, est_in_tokens INTEGER,
    est_cost REAL
);
CREATE INDEX IF NOT EXISTS idx_routes_ts ON routes(ts);
";

pub fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude").join("smart_routing.db")
}

pub struct Router {
    prices: HashMap<String, ModelPrice>,
    /// Default 500 tokens for output cost estimate.
    pub assume_output_tokens: u64,
    /// Whether to log to the DB.
    pub enabled: bool,
    conn: Option<Arc<Mutex<Connection>>>,
}

impl Router {
    pub fn new(
        prices: HashMap<String, ModelPrice>,
        enabled: bool,
        db: Option<&Path>,
    ) -> Result<Self, RouteError> {
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
        Ok(Self {
            prices,
            assume_output_tokens: 500,
            enabled,
            conn,
        })
    }

    pub fn from_env() -> Result<Self, RouteError> {
        let enabled = std::env::var("AIM_SMART_ROUTING")
            .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);
        let db = default_db_path();
        Self::new(default_prices(), enabled, Some(&db))
    }

    /// Public API: returns `RouteInfo` with cost filled in. Logs the
    /// decision to the DB iff `enabled`.
    pub fn route(&self, prompt: &str, force_model: Option<&str>) -> Result<RouteInfo, RouteError> {
        let mut info = classify(prompt, force_model);
        info.est_cost = round6(estimate_cost(
            &self.prices,
            &info.model,
            info.est_in_tokens,
            self.assume_output_tokens,
        ));
        if self.enabled {
            if let Some(conn) = &self.conn {
                let con = conn.lock();
                let _ = con.execute(
                    "INSERT INTO routes(ts, model, tier, prompt_chars, est_in_tokens, est_cost) VALUES (?,?,?,?,?,?)",
                    params![
                        Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
                        info.model,
                        info.tier.as_str(),
                        prompt.chars().count() as i64,
                        info.est_in_tokens as i64,
                        info.est_cost,
                    ],
                );
            }
        }
        Ok(info)
    }

    pub fn stats(&self) -> Result<RouteStats, RouteError> {
        let Some(conn) = &self.conn else {
            return Ok(RouteStats {
                enabled: self.enabled,
                ..Default::default()
            });
        };
        let con = conn.lock();
        let (n, cost): (u64, f64) = con
            .query_row(
                "SELECT COUNT(*), COALESCE(SUM(est_cost),0) FROM routes",
                [],
                |r| Ok((r.get::<_, i64>(0)? as u64, r.get::<_, f64>(1)?)),
            )
            .unwrap_or((0, 0.0));
        let mut by_tier = HashMap::new();
        let mut by_model = HashMap::new();
        {
            let mut stmt = con.prepare("SELECT tier, COUNT(*) FROM routes GROUP BY tier")?;
            let rows = stmt.query_map([], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)? as u64))
            })?;
            for row in rows.flatten() {
                by_tier.insert(row.0, row.1);
            }
        }
        {
            let mut stmt = con.prepare("SELECT model, COUNT(*) FROM routes GROUP BY model")?;
            let rows = stmt.query_map([], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)? as u64))
            })?;
            for row in rows.flatten() {
                by_model.insert(row.0, row.1);
            }
        }
        Ok(RouteStats {
            enabled: self.enabled,
            rows: n,
            estimated_cost: round4(cost),
            by_tier,
            by_model,
        })
    }
}

fn round6(x: f64) -> f64 {
    (x * 1_000_000.0).round() / 1_000_000.0
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn classify_short_prompt_routes_fast() {
        let r = classify("hi there", None);
        assert_eq!(r.tier, Tier::Fast);
        assert_eq!(r.model, "llama-3.1-8b-instant");
    }

    #[test]
    fn classify_long_prompt_routes_standard() {
        let r = classify(&"x".repeat(300), None);
        assert_eq!(r.tier, Tier::Standard);
        assert_eq!(r.model, "deepseek-chat");
    }

    #[test]
    fn classify_reasoning_marker_routes_reasoner() {
        let r = classify("сравни препарат A и препарат B", None);
        assert_eq!(r.tier, Tier::Reasoning);
        assert_eq!(r.model, "deepseek-reasoner");
    }

    #[test]
    fn classify_simple_question_routes_fast_even_when_long() {
        let prompt = format!("что такое {}", "x".repeat(500));
        let r = classify(&prompt, None);
        // Starts with "что …" — fast pattern wins despite length
        assert_eq!(r.tier, Tier::Fast);
    }

    #[test]
    fn classify_force_model_overrides_heuristic() {
        let r = classify(
            "compare these two studies in depth",
            Some("deepseek-v4-pro"),
        );
        assert_eq!(r.tier, Tier::Forced);
        assert_eq!(r.model, "deepseek-v4-pro");
    }

    #[test]
    fn estimate_cost_known_model() {
        let prices = default_prices();
        // 1M input tokens × 0.14/M = $0.14
        let c = estimate_cost(&prices, "deepseek-chat", 1_000_000, 0);
        assert!((c - 0.14).abs() < 1e-9);
    }

    #[test]
    fn estimate_cost_unknown_model_uses_generic() {
        let prices = default_prices();
        let c = estimate_cost(&prices, "totally-bogus", 1_000_000, 1_000_000);
        // 1M × 1 + 1M × 2 = 3.0
        assert!((c - 3.0).abs() < 1e-9);
    }

    #[test]
    fn route_logs_to_db_when_enabled() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("r.db");
        let r = Router::new(default_prices(), true, Some(&db)).unwrap();
        r.route("hi", None).unwrap();
        r.route("hello world", None).unwrap();
        let s = r.stats().unwrap();
        assert_eq!(s.rows, 2);
        assert!(s.by_tier.contains_key("fast"));
    }

    #[test]
    fn route_skips_log_when_disabled() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("r.db");
        let r = Router::new(default_prices(), false, Some(&db)).unwrap();
        r.route("hi", None).unwrap();
        let s = r.stats().unwrap();
        assert_eq!(s.rows, 0);
    }

    #[test]
    fn route_fills_est_cost() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("r.db");
        let r = Router::new(default_prices(), false, Some(&db)).unwrap();
        let info = r.route(&"x".repeat(400), None).unwrap();
        assert!(info.est_cost > 0.0);
    }

    #[test]
    fn stats_empty_when_no_data() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("r.db");
        let r = Router::new(default_prices(), true, Some(&db)).unwrap();
        let s = r.stats().unwrap();
        assert_eq!(s.rows, 0);
        assert_eq!(s.estimated_cost, 0.0);
    }

    #[test]
    fn stats_groups_by_tier_and_model() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("r.db");
        let r = Router::new(default_prices(), true, Some(&db)).unwrap();
        // 3× fast, 1× reasoning
        r.route("hi", None).unwrap();
        r.route("сколько лет", None).unwrap();
        r.route("hello?", None).unwrap();
        r.route("проанализируй данные подробно ", None).unwrap();
        let s = r.stats().unwrap();
        assert_eq!(s.rows, 4);
        assert_eq!(s.by_tier.get("fast"), Some(&3));
        assert_eq!(s.by_tier.get("reasoning"), Some(&1));
    }

    #[test]
    fn tier_serde_lowercase() {
        let s = serde_json::to_string(&Tier::Reasoning).unwrap();
        assert_eq!(s, "\"reasoning\"");
    }
}
