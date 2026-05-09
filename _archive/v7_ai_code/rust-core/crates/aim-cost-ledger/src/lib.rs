//! aim-cost-ledger — daily/weekly/monthly $ tracking + budget alerts.
//!
//! Combines the SQL backend of `agents/cost_monitor.py` (which records
//! every LLM call) and the budget logic of `agents/cost_ledger.py`
//! (which surfaces 80%/100% threshold breaches).
//!
//! Schema: `calls(ts TEXT, model TEXT, provider TEXT, input_tokens
//! INT, output_tokens INT, cost_usd REAL, task_id TEXT)`. Schema parity
//! with the Python cost_monitor.
//!
//! Public API:
//! - [`CostStore::open`] — open or create the SQLite log
//! - [`CostStore::record`] — persist one call
//! - [`CostStore::daily_cost`] / `weekly_cost` / `monthly_cost` for a
//!   given date (defaults to today)
//! - [`check_budgets`] — return a list of [`BudgetAlert`] for any
//!   threshold the current spend has crossed
//!
//! Budgets resolve from env (or library default):
//!     AIM_BUDGET_DAILY_USD   (5.0)
//!     AIM_BUDGET_WEEKLY_USD  (25.0)
//!     AIM_BUDGET_MONTHLY_USD (80.0)

use chrono::NaiveDate;
use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CostError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Copy)]
pub enum Window {
    Day,
    Week,
    Month,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AlertLevel {
    Warn,
    Critical,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetAlert {
    pub level: AlertLevel,
    pub window: String,
    pub spent_usd: f64,
    pub budget_usd: f64,
    pub fraction: f64,
}

pub struct CostStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl CostStore {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, CostError> {
        let path = path.into();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open_with_flags(
            &path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_CREATE,
        )?;
        conn.execute_batch(
            r#"
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE IF NOT EXISTS calls (
                ts            TEXT NOT NULL,
                model         TEXT NOT NULL,
                provider      TEXT,
                input_tokens  INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd      REAL NOT NULL DEFAULT 0,
                task_id       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_calls_ts ON calls(ts);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn default_path() -> PathBuf {
        if let Ok(p) = std::env::var("AIM_COST_DB") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("cost.db");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".cache").join("aim").join("cost.db")
    }

    pub fn open_default() -> Result<Self, CostError> {
        Self::open(Self::default_path())
    }

    /// Record one LLM call. `cost_usd` is computed by the caller (we
    /// don't bake provider price tables into this crate).
    #[allow(clippy::too_many_arguments)]
    pub fn record(
        &self,
        model: &str,
        provider: Option<&str>,
        input_tokens: i64,
        output_tokens: i64,
        cost_usd: f64,
        task_id: Option<&str>,
        ts: Option<&str>,
    ) -> Result<(), CostError> {
        let ts_owned = ts
            .map(|s| s.to_string())
            .unwrap_or_else(|| chrono::Utc::now().to_rfc3339());
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT INTO calls(ts, model, provider, input_tokens, output_tokens, cost_usd, task_id) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![ts_owned, model, provider, input_tokens, output_tokens, cost_usd, task_id],
        )?;
        Ok(())
    }

    fn sum_cost(&self, start: NaiveDate, end: NaiveDate) -> Result<f64, CostError> {
        let c = self.conn.lock().unwrap();
        let total: f64 = c
            .query_row(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM calls \
                 WHERE date(ts) BETWEEN date(?1) AND date(?2)",
                params![start.to_string(), end.to_string()],
                |r| r.get(0),
            )
            .unwrap_or(0.0);
        Ok(total)
    }

    pub fn daily_cost(&self, today: NaiveDate) -> Result<f64, CostError> {
        self.sum_cost(today, today)
    }

    pub fn weekly_cost(&self, today: NaiveDate) -> Result<f64, CostError> {
        let start = today - chrono::Duration::days(6);
        self.sum_cost(start, today)
    }

    pub fn monthly_cost(&self, today: NaiveDate) -> Result<f64, CostError> {
        let start = today - chrono::Duration::days(29);
        self.sum_cost(start, today)
    }

    pub fn cost_for(&self, w: Window, today: NaiveDate) -> Result<f64, CostError> {
        match w {
            Window::Day => self.daily_cost(today),
            Window::Week => self.weekly_cost(today),
            Window::Month => self.monthly_cost(today),
        }
    }
}

// ── budget config ───────────────────────────────────────────────

fn env_f(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(default)
}

pub fn daily_budget() -> f64 {
    env_f("AIM_BUDGET_DAILY_USD", 5.0)
}
pub fn weekly_budget() -> f64 {
    env_f("AIM_BUDGET_WEEKLY_USD", 25.0)
}
pub fn monthly_budget() -> f64 {
    env_f("AIM_BUDGET_MONTHLY_USD", 80.0)
}

/// 80% = warn; 100% = critical.
fn classify(spent: f64, budget: f64) -> Option<AlertLevel> {
    if budget <= 0.0 {
        return None;
    }
    let frac = spent / budget;
    if frac >= 1.0 {
        Some(AlertLevel::Critical)
    } else if frac >= 0.8 {
        Some(AlertLevel::Warn)
    } else {
        None
    }
}

pub fn check_budgets(store: &CostStore, today: NaiveDate) -> Result<Vec<BudgetAlert>, CostError> {
    check_budgets_with(store, today, daily_budget(), weekly_budget(), monthly_budget())
}

/// Test-friendly variant that takes budgets explicitly so parallel
/// tests don't fight over env vars.
pub fn check_budgets_with(
    store: &CostStore,
    today: NaiveDate,
    daily: f64,
    weekly: f64,
    monthly: f64,
) -> Result<Vec<BudgetAlert>, CostError> {
    let mut alerts: Vec<BudgetAlert> = Vec::new();
    let pairs = [
        (Window::Day, "day", daily),
        (Window::Week, "week", weekly),
        (Window::Month, "month", monthly),
    ];
    for (w, label, budget) in pairs {
        let spent = store.cost_for(w, today)?;
        if let Some(level) = classify(spent, budget) {
            alerts.push(BudgetAlert {
                level,
                window: label.to_string(),
                spent_usd: spent,
                budget_usd: budget,
                fraction: if budget > 0.0 { spent / budget } else { 0.0 },
            });
        }
    }
    Ok(alerts)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, CostStore) {
        let d = tempdir().unwrap();
        let s = CostStore::open(d.path().join("cost.db")).unwrap();
        (d, s)
    }

    #[test]
    fn empty_store_zero_spend() {
        let (_d, s) = fresh();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        assert_eq!(s.daily_cost(today).unwrap(), 0.0);
        assert_eq!(s.weekly_cost(today).unwrap(), 0.0);
        assert_eq!(s.monthly_cost(today).unwrap(), 0.0);
    }

    #[test]
    fn record_and_daily_round_trip() {
        let (_d, s) = fresh();
        s.record(
            "deepseek-chat",
            Some("deepseek"),
            100,
            200,
            0.0125,
            Some("task-1"),
            Some("2026-05-04T10:00:00Z"),
        )
        .unwrap();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        assert!((s.daily_cost(today).unwrap() - 0.0125).abs() < 1e-9);
    }

    #[test]
    fn weekly_window_aggregates_seven_days() {
        let (_d, s) = fresh();
        for i in 0..7 {
            let d = NaiveDate::from_ymd_opt(2026, 5, 1 + i as u32).unwrap();
            s.record("m", None, 0, 0, 1.0, None, Some(&format!("{d}T10:00:00Z")))
                .unwrap();
        }
        // today = May 7 → window May 1..May 7 = 7 days, all in
        let today = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        assert!((s.weekly_cost(today).unwrap() - 7.0).abs() < 1e-9);
    }

    #[test]
    fn classify_thresholds() {
        assert_eq!(classify(0.5, 1.0), None);
        assert_eq!(classify(0.79, 1.0), None);
        assert_eq!(classify(0.85, 1.0), Some(AlertLevel::Warn));
        assert_eq!(classify(1.05, 1.0), Some(AlertLevel::Critical));
        assert_eq!(classify(5.0, 0.0), None); // unlimited
    }

    #[test]
    fn check_budgets_emits_warn_at_85_percent() {
        let (_d, s) = fresh();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        s.record("m", None, 0, 0, 8.5, None, Some("2026-05-04T10:00:00Z")).unwrap();
        // daily 8.5/10 = 85% → Warn; week 8.5/100 = 8.5%; month 8.5/1000
        let alerts = check_budgets_with(&s, today, 10.0, 100.0, 1000.0).unwrap();
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].level, AlertLevel::Warn);
        assert_eq!(alerts[0].window, "day");
    }

    #[test]
    fn check_budgets_critical_at_over_100() {
        let (_d, s) = fresh();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        s.record("m", None, 0, 0, 6.0, None, Some("2026-05-04T10:00:00Z")).unwrap();
        let alerts = check_budgets_with(&s, today, 5.0, 1000.0, 1000.0).unwrap();
        let day = alerts.iter().find(|a| a.window == "day").unwrap();
        assert_eq!(day.level, AlertLevel::Critical);
    }

    #[test]
    fn classify_zero_budget_treated_as_unlimited() {
        // Mirror the safety_gate convention: 0 budget = no alert ever
        assert_eq!(classify(100.0, 0.0), None);
    }
}
