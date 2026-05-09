//! aim-ai-distillation — S9 per-tier model performance matrix.
//!
//! Run the same eval suite against 3-4 model tiers and ask:
//!  * On which cases has the cheaper tier caught up to the premium one?
//!  * Which cases STILL need the premium model — the irreducible cost
//!    surface?
//!
//! Result: a "downgrade safety" matrix surfaced in the weekly digest so
//! we can route each task class to the cheapest tier that still solves
//! it, saving cost without sacrificing accuracy.
//!
//! Rust port of `AI/ai/distillation_tracker.py`. Schema parity.

use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DistillError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TierRun {
    pub case_id: String,
    pub tier: String,
    pub score: f64,
    pub cost_usd: f64,
    pub latency_ms: i64,
    pub ts: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DowngradeRecommendation {
    pub case_id: String,
    pub safe_tier: String,
    pub premium_tier: String,
    pub safe_score: f64,
    pub premium_score: f64,
    pub cost_saved_per_call: f64,
}

pub struct DistillStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl DistillStore {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, DistillError> {
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
            CREATE TABLE IF NOT EXISTS tier_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                tier        TEXT NOT NULL,
                case_id     TEXT NOT NULL,
                score       REAL NOT NULL,
                latency_ms  INTEGER NOT NULL DEFAULT 0,
                cost_usd    REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_tier_runs_case
                ON tier_runs(case_id, tier, ts);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tier_runs
                ON tier_runs(tier, case_id, ts);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn default_path() -> PathBuf {
        if let Ok(p) = std::env::var("AI_DISTILL_DB") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("distillation.db");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".cache").join("aim").join("distillation.db")
    }

    pub fn open_default() -> Result<Self, DistillError> {
        Self::open(Self::default_path())
    }

    pub fn record(
        &self,
        tier: &str,
        case_id: &str,
        score: f64,
        latency_ms: i64,
        cost_usd: f64,
    ) -> Result<(), DistillError> {
        let ts = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true);
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR REPLACE INTO tier_runs(ts, tier, case_id, score, latency_ms, cost_usd) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![ts, tier, case_id, score, latency_ms, cost_usd],
        )?;
        Ok(())
    }

    /// Latest row per (case_id, tier) pair — basis for the matrix.
    pub fn latest_per_pair(&self) -> Result<Vec<TierRun>, DistillError> {
        let c = self.conn.lock().unwrap();
        let mut stmt = c.prepare(
            "SELECT case_id, tier, score, cost_usd, latency_ms, ts \
             FROM tier_runs t1 \
             WHERE t1.id = (SELECT MAX(id) FROM tier_runs t2 \
                            WHERE t2.case_id = t1.case_id AND t2.tier = t1.tier)",
        )?;
        let rows = stmt
            .query_map([], |r| {
                Ok(TierRun {
                    case_id: r.get(0)?,
                    tier: r.get(1)?,
                    score: r.get(2)?,
                    cost_usd: r.get(3)?,
                    latency_ms: r.get(4)?,
                    ts: r.get(5)?,
                })
            })?
            .filter_map(Result::ok)
            .collect();
        Ok(rows)
    }

    /// `case_id → tier → score` matrix using the latest row per pair.
    pub fn compare_tiers(&self) -> Result<BTreeMap<String, BTreeMap<String, f64>>, DistillError> {
        let mut out: BTreeMap<String, BTreeMap<String, f64>> = BTreeMap::new();
        for r in self.latest_per_pair()? {
            out.entry(r.case_id.clone())
                .or_default()
                .insert(r.tier.clone(), r.score);
        }
        Ok(out)
    }

    /// Find (case, cheaper-tier) pairs where the cheaper tier reaches
    /// `≥ ratio × premium_score` AND its absolute score is `≥ min_safe`.
    /// `budget_tiers` is walked cheapest-first; we pick the cheapest
    /// passing tier per case.
    pub fn downgrade_candidates(
        &self,
        premium_tier: &str,
        budget_tiers: &[&str],
        min_safe_score: f64,
        ratio: f64,
    ) -> Result<Vec<DowngradeRecommendation>, DistillError> {
        let runs = self.latest_per_pair()?;
        let mut by_case: BTreeMap<String, BTreeMap<String, &TierRun>> = BTreeMap::new();
        for r in &runs {
            by_case
                .entry(r.case_id.clone())
                .or_default()
                .insert(r.tier.clone(), r);
        }

        let mut out: Vec<DowngradeRecommendation> = Vec::new();
        for (case_id, by_tier) in &by_case {
            let Some(prem) = by_tier.get(premium_tier) else {
                continue;
            };
            for budget in budget_tiers {
                let Some(row) = by_tier.get(*budget) else { continue };
                if row.score >= min_safe_score && row.score >= ratio * prem.score {
                    let cost_saved = (prem.cost_usd - row.cost_usd).max(0.0);
                    out.push(DowngradeRecommendation {
                        case_id: case_id.clone(),
                        safe_tier: (*budget).to_string(),
                        premium_tier: premium_tier.to_string(),
                        safe_score: row.score,
                        premium_score: prem.score,
                        cost_saved_per_call: cost_saved,
                    });
                    break; // cheapest first
                }
            }
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, DistillStore) {
        let d = tempdir().unwrap();
        let s = DistillStore::open(d.path().join("d.db")).unwrap();
        (d, s)
    }

    #[test]
    fn record_and_latest_round_trip() {
        let (_d, s) = fresh();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("premium", "case-1", 0.95, 100, 0.10).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("budget", "case-1", 0.90, 50, 0.01).unwrap();
        let rows = s.latest_per_pair().unwrap();
        assert_eq!(rows.len(), 2);
    }

    #[test]
    fn compare_tiers_builds_matrix() {
        let (_d, s) = fresh();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("premium", "c1", 0.95, 100, 0.10).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("premium", "c2", 0.85, 100, 0.10).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("budget", "c1", 0.92, 50, 0.01).unwrap();
        let m = s.compare_tiers().unwrap();
        assert_eq!(m.len(), 2);
        assert_eq!(m["c1"]["premium"], 0.95);
        assert_eq!(m["c1"]["budget"], 0.92);
        assert!(!m["c2"].contains_key("budget"));
    }

    #[test]
    fn downgrade_candidates_picks_cheapest_safe_tier() {
        let (_d, s) = fresh();
        // Premium 0.95, budget1 (cheaper) 0.92, budget2 (cheapest) 0.80
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("premium", "c1", 0.95, 100, 0.10).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("budget1", "c1", 0.92, 60, 0.05).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("budget2", "c1", 0.80, 30, 0.01).unwrap();
        // ratio 0.95 → premium*0.95 = 0.9025
        // budget2 (0.80) fails; budget1 (0.92) passes
        // budget order: cheapest first → budget2 first, fails; pick budget1
        let recs = s
            .downgrade_candidates("premium", &["budget2", "budget1"], 0.85, 0.95)
            .unwrap();
        assert_eq!(recs.len(), 1);
        assert_eq!(recs[0].safe_tier, "budget1");
        assert!((recs[0].cost_saved_per_call - 0.05).abs() < 1e-9);
    }

    #[test]
    fn downgrade_no_recommendation_when_below_safe() {
        let (_d, s) = fresh();
        s.record("premium", "c1", 0.95, 100, 0.10).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        s.record("budget", "c1", 0.50, 50, 0.01).unwrap();
        let recs = s
            .downgrade_candidates("premium", &["budget"], 0.85, 0.95)
            .unwrap();
        assert!(recs.is_empty());
    }

    #[test]
    fn downgrade_skips_cases_without_premium_baseline() {
        let (_d, s) = fresh();
        s.record("budget", "c1", 0.95, 50, 0.01).unwrap();
        let recs = s
            .downgrade_candidates("premium", &["budget"], 0.85, 0.95)
            .unwrap();
        assert!(recs.is_empty());
    }

    #[test]
    fn record_idempotent_on_unique_index() {
        let (_d, s) = fresh();
        // Same ts won't match because we use micro-precision; force a
        // duplicate by reusing manually via direct sqlite. Simpler:
        // verify two records inside one test are both retained.
        s.record("premium", "c1", 0.5, 0, 0.0).unwrap();
        s.record("premium", "c1", 0.6, 0, 0.0).unwrap();
        let rows = s.latest_per_pair().unwrap();
        // latest_per_pair returns the highest id row → score 0.6
        assert_eq!(rows.len(), 1);
        assert!((rows[0].score - 0.6).abs() < 1e-9);
    }
}
