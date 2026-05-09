//! aim-ab-router — automated A/B routing tournament (S5).
//!
//! Port of `agents/ab_router.py`. Schedules a tournament between two
//! routing strategies (challenger vs baseline), records eval-suite runs,
//! and emits a verdict via Welch's t-test (with Welch–Satterthwaite df)
//! gated by a cost guard.
//!
//! ## Workflow
//! 1. [`AbRouter::start_round`] — register a round (challenger, baseline,
//!    repeats, tag).
//! 2. [`AbRouter::record_run`] — append a run for either strategy. Each
//!    record: score, cost_usd, latency_ms, n_cases.
//! 3. [`AbRouter::decide`] — compare baselines, write decision row, mark
//!    round `decided`.
//! 4. [`AbRouter::current_baseline`] — most-recent winner across history.
//! 5. [`AbRouter::history`] — recent decisions joined with their rounds.
//!
//! ## Verdict semantics
//! `promote_challenger` requires:
//! - `mean_challenger - mean_baseline ≥ min_delta`
//! - p-value ≤ min_p
//! - cost increase ≤ `cost_tolerance × baseline_cost` (skipped if base = 0)
//!
//! Welch's t-test p-value uses a normal approximation
//! (erfc(|t|/√2)) — matches the Python fallback when scipy isn't available
//! and is reasonable for df ≥ 30.

use chrono::Utc;
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AbError {
    #[error("challenger required")]
    NoChallenger,
    #[error("unknown round {0}")]
    UnknownRound(i64),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    PromoteChallenger,
    KeepBaseline,
    Neutral,
    Insufficient,
}

impl Verdict {
    pub fn as_str(self) -> &'static str {
        match self {
            Verdict::PromoteChallenger => "promote_challenger",
            Verdict::KeepBaseline => "keep_baseline",
            Verdict::Neutral => "neutral",
            Verdict::Insufficient => "insufficient",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Decision {
    pub round_id: i64,
    pub decided_at: String,
    pub winner: String,
    pub verdict: Verdict,
    pub p_value: Option<f64>,
    pub delta: f64,
    pub cost_delta: f64,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub round_id: i64,
    pub decided_at: String,
    pub winner: String,
    pub verdict: Verdict,
    pub p_value: Option<f64>,
    pub delta: f64,
    pub cost_delta: f64,
    pub note: String,
    pub challenger: String,
    pub baseline: Option<String>,
}

#[derive(Debug, Clone, Copy)]
pub struct DecideOpts {
    pub min_p: f64,
    pub min_delta: f64,
    pub cost_tolerance: f64,
}

impl Default for DecideOpts {
    fn default() -> Self {
        Self {
            min_p: 0.05,
            min_delta: 0.01,
            cost_tolerance: 0.20,
        }
    }
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    challenger TEXT NOT NULL,
    baseline TEXT,
    repeats INTEGER NOT NULL DEFAULT 3,
    tag TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);
CREATE TABLE IF NOT EXISTS round_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    score REAL NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    n_cases INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (round_id) REFERENCES rounds(id)
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    decided_at TEXT NOT NULL,
    winner TEXT NOT NULL,
    verdict TEXT NOT NULL,
    p_value REAL,
    delta REAL NOT NULL,
    cost_delta REAL NOT NULL DEFAULT 0,
    note TEXT
);
";

pub struct AbRouter {
    conn: Arc<Mutex<Connection>>,
}

pub fn default_db_path() -> PathBuf {
    if let Ok(v) = std::env::var("AIM_AB_ROUTER_DB") {
        let v = v.trim();
        if !v.is_empty() {
            return expand_tilde(v);
        }
    }
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(|s| expand_tilde(&s))
        .unwrap_or_else(|| {
            std::env::var("HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(".cache")
                .join("aim")
        });
    base.join("ab_router.db")
}

fn expand_tilde(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix("~/") {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        home.join(rest)
    } else if p == "~" {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    } else {
        PathBuf::from(p)
    }
}

impl AbRouter {
    pub fn open(db: impl AsRef<Path>) -> Result<Self, AbError> {
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
        })
    }

    fn now() -> String {
        Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string()
    }

    pub fn start_round(
        &self,
        challenger: &str,
        baseline: Option<&str>,
        repeats: u32,
        tag: Option<&str>,
    ) -> Result<i64, AbError> {
        if challenger.is_empty() {
            return Err(AbError::NoChallenger);
        }
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO rounds(started_at, challenger, baseline, repeats, tag) VALUES (?,?,?,?,?)",
            params![Self::now(), challenger, baseline, repeats as i64, tag],
        )?;
        Ok(con.last_insert_rowid())
    }

    pub fn record_run(
        &self,
        round_id: i64,
        strategy: &str,
        score: f64,
        cost_usd: f64,
        latency_ms: i64,
        n_cases: u32,
    ) -> Result<i64, AbError> {
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO round_runs(round_id, strategy, score, cost_usd, latency_ms, n_cases, recorded_at) \
             VALUES (?,?,?,?,?,?,?)",
            params![round_id, strategy, score, cost_usd, latency_ms, n_cases as i64, Self::now()],
        )?;
        Ok(con.last_insert_rowid())
    }

    fn round_meta(&self, round_id: i64) -> Result<(String, Option<String>), AbError> {
        let con = self.conn.lock();
        let r: Option<(String, Option<String>)> = con
            .query_row(
                "SELECT challenger, baseline FROM rounds WHERE id=?",
                params![round_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        r.ok_or(AbError::UnknownRound(round_id))
    }

    fn runs_for(&self, round_id: i64, strategy: &str) -> Result<Vec<RunRow>, AbError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT score, cost_usd, latency_ms, n_cases FROM round_runs \
             WHERE round_id=? AND strategy=? ORDER BY id",
        )?;
        let v: Vec<RunRow> = stmt
            .query_map(params![round_id, strategy], |r| {
                Ok(RunRow {
                    score: r.get(0)?,
                    cost_usd: r.get(1)?,
                    latency_ms: r.get(2)?,
                    n_cases: r.get::<_, i64>(3)? as u32,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn decide(&self, round_id: i64, opts: &DecideOpts) -> Result<Decision, AbError> {
        let (challenger, baseline_opt) = self.round_meta(round_id)?;
        let challenger_runs = self.runs_for(round_id, &challenger)?;
        let baseline_runs = match &baseline_opt {
            Some(b) => self.runs_for(round_id, b)?,
            None => Vec::new(),
        };
        let baseline_name = baseline_opt.clone().unwrap_or_else(|| challenger.clone());

        if challenger_runs.len() < 2 || baseline_runs.len() < 2 {
            let d = Decision {
                round_id,
                decided_at: Self::now(),
                winner: baseline_name.clone(),
                verdict: Verdict::Insufficient,
                p_value: None,
                delta: 0.0,
                cost_delta: 0.0,
                note: "need ≥2 runs per strategy".into(),
            };
            self.persist_decision(&d)?;
            return Ok(d);
        }

        let cs: Vec<f64> = challenger_runs.iter().map(|r| r.score).collect();
        let bs: Vec<f64> = baseline_runs.iter().map(|r| r.score).collect();
        let mc = mean(&cs);
        let mb = mean(&bs);
        let delta = mc - mb;
        let p = welch_t_p(&bs, &cs);

        let cost_c = mean(&challenger_runs.iter().map(|r| r.cost_usd).collect::<Vec<_>>());
        let cost_b = mean(&baseline_runs.iter().map(|r| r.cost_usd).collect::<Vec<_>>());
        let cost_delta = cost_c - cost_b;
        let cost_ok = cost_b == 0.0 || cost_delta <= opts.cost_tolerance * cost_b;

        let (verdict, winner, note) = if delta >= opts.min_delta
            && p.map(|pv| pv <= opts.min_p).unwrap_or(false)
            && cost_ok
        {
            (
                Verdict::PromoteChallenger,
                challenger.clone(),
                format!(
                    "Δ={:.3} p={:.3} cost_Δ=${:.4} OK",
                    delta,
                    p.unwrap_or(0.0),
                    cost_delta
                ),
            )
        } else if delta < -opts.min_delta && p.map(|pv| pv <= opts.min_p).unwrap_or(false) {
            (
                Verdict::KeepBaseline,
                baseline_name.clone(),
                format!("challenger worse Δ={:.3} p={:.3}", delta, p.unwrap_or(0.0)),
            )
        } else if p.is_none() || p.unwrap() > opts.min_p {
            let pstr = p
                .map(|v| format!("{:.3}", v))
                .unwrap_or_else(|| "n/a".to_string());
            (
                Verdict::Neutral,
                baseline_name.clone(),
                format!("Δ={:.3} p={}", delta, pstr),
            )
        } else {
            (
                Verdict::KeepBaseline,
                baseline_name.clone(),
                format!("cost guard: Δ${:.4} > tolerance", cost_delta),
            )
        };

        let d = Decision {
            round_id,
            decided_at: Self::now(),
            winner,
            verdict,
            p_value: p,
            delta,
            cost_delta,
            note,
        };
        self.persist_decision(&d)?;
        Ok(d)
    }

    fn persist_decision(&self, d: &Decision) -> Result<(), AbError> {
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO decisions(round_id, decided_at, winner, verdict, p_value, delta, cost_delta, note) \
             VALUES (?,?,?,?,?,?,?,?)",
            params![
                d.round_id,
                d.decided_at,
                d.winner,
                d.verdict.as_str(),
                d.p_value,
                d.delta,
                d.cost_delta,
                d.note
            ],
        )?;
        con.execute(
            "UPDATE rounds SET status='decided' WHERE id=?",
            params![d.round_id],
        )?;
        Ok(())
    }

    pub fn current_baseline(&self) -> Result<Option<String>, AbError> {
        let con = self.conn.lock();
        let r: Option<String> = con
            .query_row(
                "SELECT winner FROM decisions \
                 WHERE verdict IN ('promote_challenger','keep_baseline') \
                 ORDER BY id DESC LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()?;
        Ok(r)
    }

    pub fn history(&self, limit: u32) -> Result<Vec<HistoryEntry>, AbError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT d.round_id, d.decided_at, d.winner, d.verdict, d.p_value, d.delta, d.cost_delta, d.note, \
                    r.challenger, r.baseline \
             FROM decisions d JOIN rounds r ON r.id = d.round_id \
             ORDER BY d.id DESC LIMIT ?",
        )?;
        let v: Vec<HistoryEntry> = stmt
            .query_map(params![limit as i64], |row| {
                let verdict_str: String = row.get(3)?;
                let verdict = match verdict_str.as_str() {
                    "promote_challenger" => Verdict::PromoteChallenger,
                    "keep_baseline" => Verdict::KeepBaseline,
                    "neutral" => Verdict::Neutral,
                    _ => Verdict::Insufficient,
                };
                Ok(HistoryEntry {
                    round_id: row.get(0)?,
                    decided_at: row.get(1)?,
                    winner: row.get(2)?,
                    verdict,
                    p_value: row.get(4)?,
                    delta: row.get(5)?,
                    cost_delta: row.get(6)?,
                    note: row.get(7)?,
                    challenger: row.get(8)?,
                    baseline: row.get(9)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }
}

#[derive(Debug, Clone)]
struct RunRow {
    score: f64,
    cost_usd: f64,
    #[allow(dead_code)]
    latency_ms: i64,
    #[allow(dead_code)]
    n_cases: u32,
}

// ── statistics ──────────────────────────────────────────────────────────

fn mean(xs: &[f64]) -> f64 {
    if xs.is_empty() {
        0.0
    } else {
        xs.iter().sum::<f64>() / xs.len() as f64
    }
}

fn var(xs: &[f64], m: f64) -> f64 {
    if xs.len() < 2 {
        return 0.0;
    }
    xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (xs.len() - 1) as f64
}

/// Two-tailed Welch t-test p-value via normal approximation:
/// `erfc(|t| / √2)`. Matches `agents/ab_router.py`'s scipy-less fallback.
pub fn welch_t_p(a: &[f64], b: &[f64]) -> Option<f64> {
    if a.len() < 2 || b.len() < 2 {
        return None;
    }
    let ma = mean(a);
    let mb = mean(b);
    let va = var(a, ma);
    let vb = var(b, mb);
    if va == 0.0 && vb == 0.0 {
        return Some(if (ma - mb).abs() > f64::EPSILON { 0.0 } else { 1.0 });
    }
    let se = (va / a.len() as f64 + vb / b.len() as f64).sqrt();
    if se == 0.0 {
        return Some(1.0);
    }
    let t = (mb - ma) / se;
    Some(libm::erfc(t.abs() / std::f64::consts::SQRT_2))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fresh() -> (TempDir, AbRouter) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("ab.db");
        let r = AbRouter::open(&db).unwrap();
        (dir, r)
    }

    #[test]
    fn welch_zero_variance() {
        let p = welch_t_p(&[1.0, 1.0, 1.0], &[1.0, 1.0, 1.0]).unwrap();
        assert_eq!(p, 1.0);
        let p2 = welch_t_p(&[1.0, 1.0], &[2.0, 2.0]).unwrap();
        assert_eq!(p2, 0.0);
    }

    #[test]
    fn welch_insufficient_samples() {
        assert!(welch_t_p(&[1.0], &[2.0, 3.0]).is_none());
    }

    #[test]
    fn welch_significant_difference() {
        let a = vec![0.1, 0.12, 0.09, 0.11, 0.10];
        let b = vec![0.95, 0.92, 0.96, 0.94, 0.93];
        let p = welch_t_p(&a, &b).unwrap();
        assert!(p < 0.001, "got p={p}");
    }

    #[test]
    fn welch_no_difference() {
        let a = vec![0.5, 0.55, 0.45, 0.5, 0.52];
        let b = vec![0.5, 0.45, 0.55, 0.51, 0.49];
        let p = welch_t_p(&a, &b).unwrap();
        assert!(p > 0.10, "got p={p}");
    }

    #[test]
    fn start_round_requires_challenger() {
        let (_d, r) = fresh();
        let err = r.start_round("", None, 3, None).unwrap_err();
        assert!(matches!(err, AbError::NoChallenger));
    }

    #[test]
    fn round_round_trip() {
        let (_d, r) = fresh();
        let rid = r.start_round("router_v2", Some("router_v1"), 3, Some("nightly")).unwrap();
        assert!(rid > 0);
        r.record_run(rid, "router_v2", 0.85, 0.01, 100, 30).unwrap();
        r.record_run(rid, "router_v1", 0.80, 0.01, 100, 30).unwrap();
        let runs_v2 = r.runs_for(rid, "router_v2").unwrap();
        let runs_v1 = r.runs_for(rid, "router_v1").unwrap();
        assert_eq!(runs_v2.len(), 1);
        assert_eq!(runs_v1.len(), 1);
    }

    #[test]
    fn decide_insufficient_runs() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        r.record_run(rid, "v2", 0.9, 0.0, 0, 0).unwrap();
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(d.verdict, Verdict::Insufficient);
        assert_eq!(d.winner, "v1");
    }

    #[test]
    fn decide_promotes_when_significant_and_cost_ok() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        // Big spread, identical cost
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid, "v2", s, 0.01, 0, 30).unwrap();
        }
        for s in [0.80, 0.79, 0.81, 0.78, 0.80] {
            r.record_run(rid, "v1", s, 0.01, 0, 30).unwrap();
        }
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(d.verdict, Verdict::PromoteChallenger);
        assert_eq!(d.winner, "v2");
        assert!(d.delta > 0.10);
        assert!(d.p_value.unwrap() < 0.05);
    }

    #[test]
    fn decide_keeps_baseline_when_challenger_worse() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        for s in [0.50, 0.52, 0.49, 0.51, 0.50] {
            r.record_run(rid, "v2", s, 0.01, 0, 30).unwrap();
        }
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid, "v1", s, 0.01, 0, 30).unwrap();
        }
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(d.verdict, Verdict::KeepBaseline);
        assert_eq!(d.winner, "v1");
    }

    #[test]
    fn decide_neutral_when_overlap() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        for s in [0.80, 0.82, 0.78, 0.81, 0.80] {
            r.record_run(rid, "v2", s, 0.01, 0, 30).unwrap();
        }
        for s in [0.79, 0.80, 0.82, 0.78, 0.81] {
            r.record_run(rid, "v1", s, 0.01, 0, 30).unwrap();
        }
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(d.verdict, Verdict::Neutral);
        assert_eq!(d.winner, "v1");
    }

    #[test]
    fn decide_blocks_promotion_on_cost_blowout() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        // v2 wins on score…
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid, "v2", s, 0.10, 0, 30).unwrap(); // 10× cost!
        }
        for s in [0.80, 0.79, 0.81, 0.78, 0.80] {
            r.record_run(rid, "v1", s, 0.01, 0, 30).unwrap();
        }
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        // …but cost guard rejects it. Verdict falls to keep_baseline because
        // cost gate fires (cost_ok=false → no promote, score is better → no
        // "challenger worse", and p<0.05 → not neutral).
        assert_ne!(d.verdict, Verdict::PromoteChallenger);
        assert!(d.cost_delta > 0.0);
    }

    #[test]
    fn decide_promotes_when_baseline_cost_zero() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid, "v2", s, 0.005, 0, 30).unwrap();
        }
        for s in [0.80, 0.79, 0.81, 0.78, 0.80] {
            r.record_run(rid, "v1", s, 0.0, 0, 30).unwrap();
        }
        let d = r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(d.verdict, Verdict::PromoteChallenger);
    }

    #[test]
    fn current_baseline_returns_latest_winner() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid, "v2", s, 0.0, 0, 30).unwrap();
        }
        for s in [0.80, 0.79, 0.81, 0.78, 0.80] {
            r.record_run(rid, "v1", s, 0.0, 0, 30).unwrap();
        }
        r.decide(rid, &DecideOpts::default()).unwrap();
        assert_eq!(r.current_baseline().unwrap().as_deref(), Some("v2"));
    }

    #[test]
    fn current_baseline_skips_insufficient_decisions() {
        let (_d, r) = fresh();
        let rid = r.start_round("v2", Some("v1"), 3, None).unwrap();
        r.record_run(rid, "v2", 0.9, 0.0, 0, 0).unwrap();
        r.decide(rid, &DecideOpts::default()).unwrap();
        // Insufficient never enters current_baseline view
        assert!(r.current_baseline().unwrap().is_none());
    }

    #[test]
    fn history_orders_newest_first_and_joins_round() {
        let (_d, r) = fresh();
        let rid1 = r.start_round("v2", Some("v1"), 3, None).unwrap();
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid1, "v2", s, 0.0, 0, 30).unwrap();
        }
        for s in [0.80, 0.79, 0.81, 0.78, 0.80] {
            r.record_run(rid1, "v1", s, 0.0, 0, 30).unwrap();
        }
        r.decide(rid1, &DecideOpts::default()).unwrap();

        let rid2 = r.start_round("v3", Some("v2"), 3, None).unwrap();
        for s in [0.50, 0.52, 0.49, 0.51, 0.50] {
            r.record_run(rid2, "v3", s, 0.0, 0, 30).unwrap();
        }
        for s in [0.92, 0.93, 0.91, 0.94, 0.92] {
            r.record_run(rid2, "v2", s, 0.0, 0, 30).unwrap();
        }
        r.decide(rid2, &DecideOpts::default()).unwrap();

        let h = r.history(20).unwrap();
        assert_eq!(h.len(), 2);
        assert_eq!(h[0].challenger, "v3");
        assert_eq!(h[0].verdict, Verdict::KeepBaseline);
        assert_eq!(h[1].challenger, "v2");
        assert_eq!(h[1].verdict, Verdict::PromoteChallenger);
    }

    #[test]
    fn unknown_round_returns_error() {
        let (_d, r) = fresh();
        let err = r.decide(9999, &DecideOpts::default()).unwrap_err();
        assert!(matches!(err, AbError::UnknownRound(9999)));
    }
}
