//! aim-cost-monitor — token-cost tracking with daily/monthly caps + alerts.
//!
//! Port of `agents/cost_monitor.py`. Records every successful LLM call,
//! persists to SQLite (`~/.claude/cost_monitor.db`), raises an alert when
//! daily or monthly caps are exceeded. Alerts go to:
//!
//! - in-memory audit log (always)
//! - one or more [`Notifier`]s — production wires Telegram/webhook,
//!   tests use [`MemoryNotifier`]
//!
//! ## Public API
//! - [`Monitor::record`] — log one call; auto-fires alerts; returns
//!   [`RecordResult`] with cost breakdown + running daily/monthly totals
//! - [`Monitor::daily_cost`] / [`Monitor::monthly_cost`] / [`Monitor::stats`]
//! - [`Monitor::alerts`] / [`Monitor::acknowledge`]
//! - [`Pricing::default()`] — DeepSeek V4 + Groq prices as of 2026-04

use async_trait::async_trait;
use chrono::{DateTime, Datelike, NaiveDate, Utc};
use parking_lot::Mutex;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CostError {
    #[error("hard-stop: {0}")]
    LimitExceeded(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelPrice {
    /// USD per 1M input tokens
    pub input: f64,
    /// USD per 1M output tokens
    pub output: f64,
    /// USD per 1M cache-hit input tokens (None → same as `input`)
    #[serde(default)]
    pub cache_hit: Option<f64>,
}

#[derive(Debug, Clone, Default)]
pub struct Pricing {
    pub map: HashMap<String, ModelPrice>,
}

impl Pricing {
    /// Default DeepSeek V4 + Groq pricing (matches Python module 2026-04).
    pub fn default() -> Self {
        let mut m = HashMap::new();
        let dsf = ModelPrice {
            input: 0.14,
            output: 0.28,
            cache_hit: Some(0.0028),
        };
        let dsp = ModelPrice {
            input: 0.435,
            output: 0.87,
            cache_hit: Some(0.003625),
        };
        m.insert("deepseek-v4-flash".into(), dsf.clone());
        m.insert("deepseek-chat".into(), dsf.clone());
        m.insert("deepseek-v4-pro".into(), dsp.clone());
        m.insert("deepseek-reasoner".into(), dsp);
        m.insert(
            "llama-3.3-70b-versatile".into(),
            ModelPrice {
                input: 0.59,
                output: 0.79,
                cache_hit: None,
            },
        );
        m.insert(
            "llama-3.1-8b-instant".into(),
            ModelPrice {
                input: 0.05,
                output: 0.08,
                cache_hit: None,
            },
        );
        m.insert(
            "mixtral-8x7b-32768".into(),
            ModelPrice {
                input: 0.24,
                output: 0.24,
                cache_hit: None,
            },
        );
        Self { map: m }
    }

    /// Look up a model price; falls back to fuzzy substring match, then a
    /// generic $1.00/$2.00 (matches Python module's behaviour).
    pub fn for_model(&self, model: &str) -> ModelPrice {
        if let Some(p) = self.map.get(model) {
            return p.clone();
        }
        for (k, v) in &self.map {
            if k.contains(model) || model.contains(k) {
                return v.clone();
            }
        }
        ModelPrice {
            input: 1.0,
            output: 2.0,
            cache_hit: None,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Limits {
    pub daily_usd: f64,
    pub monthly_usd: f64,
    pub hard_stop: bool,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            daily_usd: 5.0,
            monthly_usd: 50.0,
            hard_stop: false,
        }
    }
}

impl Limits {
    pub fn from_env() -> Self {
        let daily = std::env::var("AIM_COST_LIMIT_DAILY")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(5.0);
        let monthly = std::env::var("AIM_COST_LIMIT_MONTHLY")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(50.0);
        let hard_stop = std::env::var("AIM_COST_HARD_STOP")
            .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);
        Self {
            daily_usd: daily,
            monthly_usd: monthly,
            hard_stop,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RecordResult {
    pub input_cost: f64,
    pub output_cost: f64,
    pub total_cost: f64,
    pub daily: f64,
    pub monthly: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertRecord {
    pub id: i64,
    pub ts: String,
    pub kind: String,
    pub message: String,
    pub acknowledged: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stats {
    pub daily_cost: f64,
    pub monthly_cost: f64,
    pub total_calls: u64,
    pub total_cost: f64,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub cost_by_model_7d: HashMap<String, f64>,
    pub daily_limit: f64,
    pub monthly_limit: f64,
    pub remaining_daily: f64,
    pub remaining_monthly: f64,
    pub hard_stop: bool,
}

/// Pluggable external notification channel. Production wires Telegram /
/// webhook; tests use [`MemoryNotifier`].
#[async_trait]
pub trait Notifier: Send + Sync {
    async fn notify(&self, kind: &str, message: &str) -> Result<(), CostError>;
}

#[derive(Debug, Default)]
pub struct MemoryNotifier {
    pub events: Mutex<Vec<(String, String)>>,
}

impl MemoryNotifier {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn snapshot(&self) -> Vec<(String, String)> {
        self.events.lock().clone()
    }
}

#[async_trait]
impl Notifier for MemoryNotifier {
    async fn notify(&self, kind: &str, message: &str) -> Result<(), CostError> {
        self.events
            .lock()
            .push((kind.to_string(), message.to_string()));
        Ok(())
    }
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

#[derive(Debug)]
pub struct ManualClock {
    state: Mutex<DateTime<Utc>>,
}

impl ManualClock {
    pub fn new(t: DateTime<Utc>) -> Self {
        Self {
            state: Mutex::new(t),
        }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.state.lock() = t;
    }
    pub fn advance(&self, days: i64) {
        let mut g = self.state.lock();
        *g = *g + chrono::Duration::days(days);
    }
}

impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.state.lock()
    }
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, model TEXT, provider TEXT,
    input_tokens INTEGER, output_tokens INTEGER,
    input_cost REAL, output_cost REAL, total_cost REAL,
    task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_costs_ts ON costs(ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, kind TEXT, message TEXT, acknowledged INTEGER DEFAULT 0
);
";

pub struct Monitor {
    conn: Arc<Mutex<Connection>>,
    pricing: Pricing,
    limits: Limits,
    notifiers: Vec<Arc<dyn Notifier>>,
    clock: Arc<dyn Clock>,
}

pub fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude").join("cost_monitor.db")
}

impl Monitor {
    pub fn open(
        db: impl AsRef<Path>,
        pricing: Pricing,
        limits: Limits,
    ) -> Result<Self, CostError> {
        Self::open_with(db, pricing, limits, vec![], Arc::new(SystemClock))
    }

    pub fn open_with(
        db: impl AsRef<Path>,
        pricing: Pricing,
        limits: Limits,
        notifiers: Vec<Arc<dyn Notifier>>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, CostError> {
        let p = db.as_ref();
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let conn = Connection::open(p)?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
            pricing,
            limits,
            notifiers,
            clock,
        })
    }

    fn ts(&self) -> String {
        self.clock.now().format("%Y-%m-%dT%H:%M:%S").to_string()
    }

    /// Record one LLM call. Returns cost breakdown and current daily/monthly
    /// totals. Fires alerts when caps are exceeded; raises
    /// `CostError::LimitExceeded` if `hard_stop` is on.
    pub async fn record(
        &self,
        model: &str,
        input_tokens: u64,
        output_tokens: u64,
        provider: &str,
        task_id: Option<&str>,
    ) -> Result<RecordResult, CostError> {
        let p = self.pricing.for_model(model);
        let icost = (input_tokens as f64) * p.input / 1_000_000.0;
        let ocost = (output_tokens as f64) * p.output / 1_000_000.0;
        let total = icost + ocost;
        let ts = self.ts();
        {
            let con = self.conn.lock();
            con.execute(
                "INSERT INTO costs(ts, model, provider, input_tokens, output_tokens, \
                 input_cost, output_cost, total_cost, task_id) VALUES (?,?,?,?,?,?,?,?,?)",
                params![
                    ts,
                    model,
                    provider,
                    input_tokens as i64,
                    output_tokens as i64,
                    round6(icost),
                    round6(ocost),
                    round6(total),
                    task_id,
                ],
            )?;
        }

        let now = self.clock.now();
        let daily = self.cost_for_prefix(&now.format("%Y-%m-%d").to_string())?;
        let monthly = self.cost_for_prefix(&now.format("%Y-%m").to_string())?;

        if daily > self.limits.daily_usd {
            self.alert(
                "DAILY_CAP",
                &format!(
                    "daily ${:.2} > limit ${:.2}",
                    daily, self.limits.daily_usd
                ),
            )
            .await?;
            if self.limits.hard_stop {
                return Err(CostError::LimitExceeded(format!(
                    "daily cap exceeded: ${:.2}",
                    daily
                )));
            }
        }
        if monthly > self.limits.monthly_usd {
            self.alert(
                "MONTHLY_CAP",
                &format!(
                    "monthly ${:.2} > limit ${:.2}",
                    monthly, self.limits.monthly_usd
                ),
            )
            .await?;
            if self.limits.hard_stop {
                return Err(CostError::LimitExceeded(format!(
                    "monthly cap exceeded: ${:.2}",
                    monthly
                )));
            }
        }

        Ok(RecordResult {
            input_cost: icost,
            output_cost: ocost,
            total_cost: total,
            daily,
            monthly,
        })
    }

    fn cost_for_prefix(&self, prefix: &str) -> Result<f64, CostError> {
        let con = self.conn.lock();
        let v: f64 = con
            .query_row(
                "SELECT COALESCE(SUM(total_cost),0) FROM costs WHERE ts LIKE ?",
                params![format!("{prefix}%")],
                |r| r.get(0),
            )
            .unwrap_or(0.0);
        Ok(v)
    }

    pub fn daily_cost(&self, date: NaiveDate) -> Result<f64, CostError> {
        self.cost_for_prefix(&date.format("%Y-%m-%d").to_string())
    }

    pub fn monthly_cost(&self, date: NaiveDate) -> Result<f64, CostError> {
        self.cost_for_prefix(&format!("{:04}-{:02}", date.year(), date.month()))
    }

    pub fn stats(&self) -> Result<Stats, CostError> {
        let now = self.clock.now();
        let daily = self.daily_cost(now.date_naive())?;
        let monthly = self.monthly_cost(now.date_naive())?;
        let con = self.conn.lock();
        let (total_calls, total_cost, in_tok, out_tok): (u64, f64, u64, u64) = con
            .query_row(
                "SELECT COUNT(*), COALESCE(SUM(total_cost),0), \
                 COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM costs",
                [],
                |r| {
                    Ok((
                        r.get::<_, i64>(0)? as u64,
                        r.get::<_, f64>(1)?,
                        r.get::<_, i64>(2)? as u64,
                        r.get::<_, i64>(3)? as u64,
                    ))
                },
            )
            .unwrap_or((0, 0.0, 0, 0));
        let week_ago = (now - chrono::Duration::days(7))
            .format("%Y-%m-%dT%H:%M:%S")
            .to_string();
        let mut by_model = HashMap::new();
        {
            let mut stmt = con.prepare(
                "SELECT model, SUM(total_cost) FROM costs WHERE ts >= ? \
                 GROUP BY model ORDER BY 2 DESC",
            )?;
            let rows = stmt.query_map(params![week_ago], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?))
            })?;
            for row in rows.flatten() {
                by_model.insert(row.0, round4(row.1));
            }
        }
        Ok(Stats {
            daily_cost: round4(daily),
            monthly_cost: round4(monthly),
            total_calls,
            total_cost: round4(total_cost),
            total_input_tokens: in_tok,
            total_output_tokens: out_tok,
            cost_by_model_7d: by_model,
            daily_limit: self.limits.daily_usd,
            monthly_limit: self.limits.monthly_usd,
            remaining_daily: round4((self.limits.daily_usd - daily).max(0.0)),
            remaining_monthly: round4((self.limits.monthly_usd - monthly).max(0.0)),
            hard_stop: self.limits.hard_stop,
        })
    }

    async fn alert(&self, kind: &str, message: &str) -> Result<(), CostError> {
        let ts = self.ts();
        {
            let con = self.conn.lock();
            con.execute(
                "INSERT INTO alerts(ts, kind, message) VALUES (?,?,?)",
                params![ts, kind, message],
            )?;
        }
        for n in &self.notifiers {
            if let Err(e) = n.notify(kind, message).await {
                tracing::warn!("notifier error: {e}");
            }
        }
        Ok(())
    }

    pub fn alerts(&self, limit: u32, only_unacked: bool) -> Result<Vec<AlertRecord>, CostError> {
        let con = self.conn.lock();
        let sql = if only_unacked {
            "SELECT id, ts, kind, message, acknowledged FROM alerts WHERE acknowledged=0 ORDER BY ts DESC LIMIT ?"
        } else {
            "SELECT id, ts, kind, message, acknowledged FROM alerts ORDER BY ts DESC LIMIT ?"
        };
        let mut stmt = con.prepare(sql)?;
        let v: Vec<AlertRecord> = stmt
            .query_map(params![limit as i64], |r| {
                Ok(AlertRecord {
                    id: r.get(0)?,
                    ts: r.get(1)?,
                    kind: r.get(2)?,
                    message: r.get(3)?,
                    acknowledged: r.get::<_, i64>(4)? != 0,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn acknowledge(&self, alert_id: i64) -> Result<bool, CostError> {
        let con = self.conn.lock();
        let n = con.execute(
            "UPDATE alerts SET acknowledged=1 WHERE id=?",
            params![alert_id],
        )?;
        Ok(n > 0)
    }

    pub fn reset(&self) -> Result<(), CostError> {
        let con = self.conn.lock();
        con.execute("DELETE FROM costs", [])?;
        con.execute("DELETE FROM alerts", [])?;
        Ok(())
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
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn make(
        limits: Limits,
    ) -> (TempDir, Monitor, Arc<MemoryNotifier>, Arc<ManualClock>) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("c.db");
        let notifier = Arc::new(MemoryNotifier::new());
        let clock = Arc::new(ManualClock::new(Utc.with_ymd_and_hms(2026, 5, 4, 12, 0, 0).unwrap()));
        let mon = Monitor::open_with(
            &db,
            Pricing::default(),
            limits,
            vec![notifier.clone()],
            clock.clone(),
        )
        .unwrap();
        (dir, mon, notifier, clock)
    }

    #[test]
    fn pricing_default_resolves_known_model() {
        let p = Pricing::default();
        let v4f = p.for_model("deepseek-v4-flash");
        assert!((v4f.input - 0.14).abs() < 1e-9);
        let v4p = p.for_model("deepseek-v4-pro");
        assert!((v4p.output - 0.87).abs() < 1e-9);
    }

    #[test]
    fn pricing_fuzzy_match() {
        let p = Pricing::default();
        // Unknown exact match → falls through to substring (deepseek-v4-flash matches)
        let r = p.for_model("deepseek-chat");
        assert_eq!(r.input, 0.14);
    }

    #[test]
    fn pricing_unknown_returns_generic() {
        let p = Pricing::default();
        let r = p.for_model("totally-bogus-model-xyz");
        assert_eq!(r.input, 1.0);
        assert_eq!(r.output, 2.0);
    }

    #[tokio::test]
    async fn record_computes_cost() {
        let (_d, mon, _n, _c) = make(Limits::default());
        let r = mon
            .record("deepseek-v4-flash", 1_000_000, 500_000, "deepseek", None)
            .await
            .unwrap();
        // input: 1M * 0.14/1M = 0.14
        // output: 0.5M * 0.28/1M = 0.14
        // total: 0.28
        assert!((r.input_cost - 0.14).abs() < 1e-9);
        assert!((r.output_cost - 0.14).abs() < 1e-9);
        assert!((r.total_cost - 0.28).abs() < 1e-9);
    }

    #[tokio::test]
    async fn daily_cost_aggregates_today() {
        let (_d, mon, _n, clock) = make(Limits::default());
        for _ in 0..3 {
            mon.record("deepseek-v4-flash", 1_000_000, 0, "deepseek", None)
                .await
                .unwrap();
        }
        let today = clock.now().date_naive();
        let dc = mon.daily_cost(today).unwrap();
        assert!((dc - 0.42).abs() < 1e-6, "got {}", dc);
    }

    #[tokio::test]
    async fn monthly_cost_includes_other_days() {
        let (_d, mon, _n, clock) = make(Limits::default());
        // record on May 4
        mon.record("deepseek-v4-flash", 1_000_000, 0, "", None).await.unwrap();
        // shift clock to May 5 in same month
        clock.advance(1);
        mon.record("deepseek-v4-flash", 2_000_000, 0, "", None).await.unwrap();
        let m = mon.monthly_cost(clock.now().date_naive()).unwrap();
        assert!((m - 0.42).abs() < 1e-6, "got {}", m);
        // daily on May 5 only
        let d = mon.daily_cost(clock.now().date_naive()).unwrap();
        assert!((d - 0.28).abs() < 1e-6, "got {}", d);
    }

    #[tokio::test]
    async fn alert_fires_when_daily_cap_exceeded() {
        let (_d, mon, notif, _c) = make(Limits {
            daily_usd: 0.1,
            monthly_usd: 100.0,
            hard_stop: false,
        });
        let _ = mon
            .record("deepseek-v4-flash", 1_000_000, 0, "", None)
            .await
            .unwrap(); // 0.14 > 0.1
        assert_eq!(notif.snapshot().len(), 1);
        let (k, m) = &notif.snapshot()[0];
        assert_eq!(k, "DAILY_CAP");
        assert!(m.contains("daily"));
        let alerts = mon.alerts(10, true).unwrap();
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].kind, "DAILY_CAP");
    }

    #[tokio::test]
    async fn hard_stop_raises_after_alert() {
        let (_d, mon, _n, _c) = make(Limits {
            daily_usd: 0.05,
            monthly_usd: 100.0,
            hard_stop: true,
        });
        let err = mon
            .record("deepseek-v4-flash", 1_000_000, 0, "", None)
            .await
            .unwrap_err();
        assert!(matches!(err, CostError::LimitExceeded(_)));
    }

    #[tokio::test]
    async fn no_alert_below_caps() {
        let (_d, mon, notif, _c) = make(Limits {
            daily_usd: 100.0,
            monthly_usd: 1000.0,
            hard_stop: true,
        });
        mon.record("deepseek-v4-flash", 100_000, 50_000, "", None)
            .await
            .unwrap();
        assert!(notif.snapshot().is_empty());
        assert!(mon.alerts(10, true).unwrap().is_empty());
    }

    #[tokio::test]
    async fn acknowledge_marks_alert() {
        let (_d, mon, _n, _c) = make(Limits {
            daily_usd: 0.01,
            monthly_usd: 100.0,
            hard_stop: false,
        });
        mon.record("deepseek-v4-flash", 1_000_000, 0, "", None)
            .await
            .unwrap();
        let unacked = mon.alerts(10, true).unwrap();
        assert_eq!(unacked.len(), 1);
        let id = unacked[0].id;
        assert!(mon.acknowledge(id).unwrap());
        assert!(mon.alerts(10, true).unwrap().is_empty());
        assert_eq!(mon.alerts(10, false).unwrap().len(), 1);
    }

    #[tokio::test]
    async fn stats_reports_totals() {
        let (_d, mon, _n, _c) = make(Limits::default());
        mon.record("deepseek-v4-flash", 100_000, 100_000, "", None)
            .await
            .unwrap();
        mon.record("deepseek-v4-pro", 100_000, 100_000, "", None)
            .await
            .unwrap();
        let s = mon.stats().unwrap();
        assert_eq!(s.total_calls, 2);
        assert_eq!(s.total_input_tokens, 200_000);
        assert_eq!(s.total_output_tokens, 200_000);
        assert!(s.total_cost > 0.0);
        assert_eq!(s.cost_by_model_7d.len(), 2);
    }

    #[tokio::test]
    async fn reset_drops_everything() {
        let (_d, mon, _n, _c) = make(Limits {
            daily_usd: 0.01,
            monthly_usd: 1.0,
            hard_stop: false,
        });
        mon.record("deepseek-v4-flash", 1_000_000, 0, "", None)
            .await
            .unwrap();
        mon.reset().unwrap();
        let s = mon.stats().unwrap();
        assert_eq!(s.total_calls, 0);
        assert!(mon.alerts(10, false).unwrap().is_empty());
    }

    #[test]
    fn limits_from_env_defaults_when_unset() {
        let l = Limits::from_env();
        assert!(l.daily_usd > 0.0);
        assert!(l.monthly_usd > 0.0);
    }
}
