//! aim-ai-health — HS1 health score.
//!
//! Compose a 0-100 score from five weighted components:
//!
//! | component        | weight | source                                              |
//! |------------------|--------|-----------------------------------------------------|
//! | wiring           |    30  | (TODO) doctor smoke-test wiring; stub: full credit  |
//! | regression       |    25  | aim-ai-regression — not regressed = full credit     |
//! | compliance       |    15  | aim-ai-ledger trend.avg_compliance                  |
//! | cases            |    20  | (TODO) eval-case validator; stub: full credit       |
//! | prompt_drift     |    10  | (TODO) aim-ai-prompt-versions; stub: full credit    |
//!
//! Weights match `AI/ai/health_score.py`. The components marked TODO
//! are reserved-credit stubs returning full points until the upstream
//! Rust crate exists. As each upstream port lands, replace the stub
//! with the real check; behaviour matches the Python predecessor's
//! conservative "no signal ⇒ trust" policy.
//!
//! Persistence: scores are recorded into the same DB as the diagnostic
//! ledger (`health_scores` table, schema parity with the Python
//! version), so a single backup covers both.

use aim_ai_cases::validate_dir as validate_cases_dir;
use aim_ai_ledger::Ledger;
use aim_ai_prompt_versions::PromptStore;
use aim_ai_regression::detect as detect_regression;
use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

const W_WIRING: i64 = 30;
const W_REGRESSION: i64 = 25;
const W_COMPLIANCE: i64 = 15;
const W_CASES: i64 = 20;
const W_PROMPT_DRIFT: i64 = 10;

#[derive(Debug, Error)]
pub enum HealthError {
    #[error("ledger: {0}")]
    Ledger(#[from] aim_ai_ledger::LedgerError),
    #[error("regression: {0}")]
    Regression(#[from] aim_ai_regression::RegressionError),
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Score {
    pub total: i64,
    pub grade: String,
    pub components: BTreeMap<String, i64>,
    pub notes: Vec<String>,
}

impl Score {
    fn grade_from_total(total: i64) -> String {
        let s = match total {
            90..=100 => "A",
            80..=89 => "B",
            70..=79 => "C",
            60..=69 => "D",
            _ => "F",
        };
        s.to_string()
    }
}

/// Compose all components and produce a fresh score (read-only).
pub fn compute(ledger: &Ledger) -> Result<Score, HealthError> {
    let mut components: BTreeMap<String, i64> = BTreeMap::new();
    let mut notes: Vec<String> = Vec::new();

    let (w, mut wn) = wiring_component();
    components.insert("wiring".to_string(), w);
    notes.append(&mut wn);

    let (r, mut rn) = regression_component(ledger)?;
    components.insert("regression".to_string(), r);
    notes.append(&mut rn);

    let (c, mut cn) = compliance_component(ledger)?;
    components.insert("compliance".to_string(), c);
    notes.append(&mut cn);

    let (cs, mut csn) = cases_component();
    components.insert("cases".to_string(), cs);
    notes.append(&mut csn);

    let (pd, mut pdn) = prompt_drift_component();
    components.insert("prompt_drift".to_string(), pd);
    notes.append(&mut pdn);

    let total: i64 = components.values().sum::<i64>().clamp(0, 100);
    Ok(Score {
        total,
        grade: Score::grade_from_total(total),
        components,
        notes,
    })
}

/// One-line cron summary.
///
/// Format matches Python `info_line`:
/// `AIM/AI: 80/100 B  wir=30 reg=25 comp=0 cases=15 pd=10`
pub fn info_line(s: &Score) -> String {
    format!(
        "AIM/AI: {}/100 {}  wir={}  reg={}  comp={}  cases={}  pd={}",
        s.total,
        s.grade,
        s.components.get("wiring").copied().unwrap_or(0),
        s.components.get("regression").copied().unwrap_or(0),
        s.components.get("compliance").copied().unwrap_or(0),
        s.components.get("cases").copied().unwrap_or(0),
        s.components.get("prompt_drift").copied().unwrap_or(0),
    )
}

// ── components ──────────────────────────────────────────────────

fn wiring_component() -> (i64, Vec<String>) {
    // TODO: integrate aim-doctor smoke test once that crate exists.
    // Until then, give full credit (Python policy when component fails).
    (W_WIRING, vec![])
}

fn regression_component(ledger: &Ledger) -> Result<(i64, Vec<String>), HealthError> {
    let r = detect_regression(ledger)?;
    if !r.have_baseline {
        return Ok((W_REGRESSION / 2, vec!["regression: no baseline yet".into()]));
    }
    if r.regressed() {
        let n = r.new_findings.len();
        return Ok((0, vec![format!("regression: {} new finding(s)", n)]));
    }
    if r.improved() {
        return Ok((W_REGRESSION, vec!["regression: improved".into()]));
    }
    Ok((W_REGRESSION, vec![]))
}

fn compliance_component(ledger: &Ledger) -> Result<(i64, Vec<String>), HealthError> {
    let t = ledger.trend()?;
    if t.n_runs == 0 {
        return Ok((W_COMPLIANCE / 2, vec!["compliance: no runs yet".into()]));
    }
    // Linear scale: 0% → 0 pts, 100% → W_COMPLIANCE pts.
    let pts = (t.avg_compliance.clamp(0.0, 1.0) * W_COMPLIANCE as f64).round() as i64;
    let mut notes = Vec::new();
    if t.avg_compliance < 0.6 {
        notes.push(format!(
            "compliance: avg {:.0}% under 60%",
            t.avg_compliance * 100.0
        ));
    }
    Ok((pts, notes))
}

fn cases_component() -> (i64, Vec<String>) {
    let report = validate_cases_dir(None);
    if report.n_cases == 0 {
        // No cases yet — full credit (matches Python policy).
        return (W_CASES, vec![]);
    }
    if report.n_failed == 0 {
        return (W_CASES, vec![]);
    }
    let ratio = report.n_ok as f64 / report.n_cases as f64;
    let pts = (W_CASES as f64 * ratio).round() as i64;
    (
        pts,
        vec![format!(
            "cases: {} invalid eval case(s) out of {}",
            report.n_failed, report.n_cases
        )],
    )
}

fn prompt_drift_component() -> (i64, Vec<String>) {
    // Prompt-drift component opens the same DB as the ledger, since
    // PromptStore lives alongside it.
    let store = match PromptStore::open_default() {
        Ok(s) => s,
        Err(e) => {
            return (
                0,
                vec![format!("prompt versions: open failed: {e}")],
            )
        }
    };
    let drift = match store.drift_since_last(None) {
        Ok(d) => d,
        Err(e) => {
            return (
                0,
                vec![format!("prompt versions: drift failed: {e}")],
            )
        }
    };
    if !drift.prompt_present {
        return (
            W_PROMPT_DRIFT / 2,
            vec!["prompt drift: SELF_DIAGNOSTIC_PROMPT.md missing".to_string()],
        );
    }
    if !drift.have_baseline {
        return (
            W_PROMPT_DRIFT / 2,
            vec!["prompt drift: never fingerprinted yet".to_string()],
        );
    }
    if drift.changed {
        return (
            W_PROMPT_DRIFT / 2,
            vec!["prompt drift: prompt changed since last record".to_string()],
        );
    }
    (W_PROMPT_DRIFT, vec![])
}

// ── persistence ─────────────────────────────────────────────────

/// Sidecar handle on the diagnostic ledger DB. Creates a
/// `health_scores` table if missing, schema-compatible with Python.
pub struct HealthStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl HealthStore {
    /// Open / create the sidecar table on the same path as the
    /// diagnostic ledger DB.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, HealthError> {
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
            CREATE TABLE IF NOT EXISTS health_scores (
                ts           TEXT NOT NULL,
                total        INTEGER NOT NULL,
                grade        TEXT NOT NULL,
                wiring       INTEGER NOT NULL,
                regression   INTEGER NOT NULL,
                compliance   INTEGER NOT NULL,
                cases        INTEGER NOT NULL,
                prompt_drift INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_health_ts ON health_scores(ts);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn open_default() -> Result<Self, HealthError> {
        Self::open(Ledger::default_path())
    }

    /// Persist a score row.
    pub fn record(&self, score: &Score, ts: Option<&str>) -> Result<(), HealthError> {
        let ts_owned = ts
            .map(|s| s.to_string())
            .unwrap_or_else(|| chrono::Utc::now().to_rfc3339());
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT INTO health_scores(ts, total, grade, wiring, regression, \
                compliance, cases, prompt_drift) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                ts_owned,
                score.total,
                score.grade,
                score.components.get("wiring").copied().unwrap_or(0),
                score.components.get("regression").copied().unwrap_or(0),
                score.components.get("compliance").copied().unwrap_or(0),
                score.components.get("cases").copied().unwrap_or(0),
                score.components.get("prompt_drift").copied().unwrap_or(0),
            ],
        )?;
        Ok(())
    }

    /// Last `limit` recorded scores, oldest first (matches Python).
    pub fn history(&self, limit: i64) -> Result<Vec<HealthRow>, HealthError> {
        let c = self.conn.lock().unwrap();
        let mut stmt = c.prepare(
            "SELECT ts, total, grade, wiring, regression, compliance, cases, prompt_drift \
             FROM health_scores ORDER BY ts DESC LIMIT ?1",
        )?;
        let mut rows: Vec<HealthRow> = stmt
            .query_map(params![limit], |r| {
                Ok(HealthRow {
                    ts: r.get(0)?,
                    total: r.get(1)?,
                    grade: r.get(2)?,
                    wiring: r.get(3)?,
                    regression: r.get(4)?,
                    compliance: r.get(5)?,
                    cases: r.get(6)?,
                    prompt_drift: r.get(7)?,
                })
            })?
            .filter_map(Result::ok)
            .collect();
        rows.reverse();
        Ok(rows)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthRow {
    pub ts: String,
    pub total: i64,
    pub grade: String,
    pub wiring: i64,
    pub regression: i64,
    pub compliance: i64,
    pub cases: i64,
    pub prompt_drift: i64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger, HealthStore) {
        let d = tempdir().unwrap();
        let p = d.path().join("ledger.db");
        let l = Ledger::open(&p).unwrap();
        let h = HealthStore::open(&p).unwrap();
        (d, l, h)
    }

    #[test]
    fn empty_state_full_credit_for_stub_components() {
        let (_d, l, _h) = fresh();
        let s = compute(&l).unwrap();
        // wiring + cases + prompt_drift = 30+20+10 = 60 (stubs full credit)
        // regression with no baseline = W_REGRESSION/2 = 12 (12.5 rounded)
        // compliance with no runs = W_COMPLIANCE/2 = 7 (7.5 rounded)
        // total ≈ 79
        assert!(s.total >= 70 && s.total <= 80, "got {}", s.total);
        assert!(s.notes.iter().any(|n| n.contains("no baseline")));
    }

    #[test]
    fn full_compliance_full_credit() {
        let (_d, l, _h) = fresh();
        l.record("m", Some("A"), 10, 10, Some(0), None, None, None, false, None,
                 Some("2026-05-04T00:00:00Z")).unwrap();
        let (pts, _) = compliance_component(&l).unwrap();
        assert_eq!(pts, W_COMPLIANCE);
    }

    #[test]
    fn zero_compliance_zero_credit() {
        let (_d, l, _h) = fresh();
        l.record("m", Some("F"), 10, 0, Some(5), None, None, None, false, None,
                 Some("2026-05-04T00:00:00Z")).unwrap();
        let (pts, notes) = compliance_component(&l).unwrap();
        assert_eq!(pts, 0);
        assert!(notes.iter().any(|n| n.contains("under 60%")));
    }

    #[test]
    fn regression_zero_when_regressed() {
        let d = tempdir().unwrap();
        let p = d.path().join("ledger.db");
        let l = Ledger::open(&p).unwrap();
        // Two runs with new finding via a real report file
        let r1 = d.path().join("r1.md");
        let r2 = d.path().join("r2.md");
        std::fs::write(&r1, "clean").unwrap();
        std::fs::write(&r2, "issue at lib.rs:42").unwrap();
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(r1.to_str().unwrap()), Some("2026-05-04T00:00:00Z")).unwrap();
        l.record("m", Some("A"), 0, 0, Some(0), None, None, None, false,
                 Some(r2.to_str().unwrap()), Some("2026-05-04T01:00:00Z")).unwrap();
        let (pts, notes) = regression_component(&l).unwrap();
        assert_eq!(pts, 0);
        assert!(notes.iter().any(|n| n.contains("new finding")));
    }

    #[test]
    fn grade_from_total() {
        assert_eq!(Score::grade_from_total(95), "A");
        assert_eq!(Score::grade_from_total(85), "B");
        assert_eq!(Score::grade_from_total(75), "C");
        assert_eq!(Score::grade_from_total(65), "D");
        assert_eq!(Score::grade_from_total(50), "F");
    }

    #[test]
    fn record_persists_and_history_round_trip() {
        let (_d, _l, h) = fresh();
        let s = Score {
            total: 80,
            grade: "B".to_string(),
            components: [
                ("wiring".to_string(), 30),
                ("regression".to_string(), 25),
                ("compliance".to_string(), 15),
                ("cases".to_string(), 0),
                ("prompt_drift".to_string(), 10),
            ]
            .into_iter()
            .collect(),
            notes: vec![],
        };
        h.record(&s, Some("2026-05-04T00:00:00Z")).unwrap();
        let hist = h.history(10).unwrap();
        assert_eq!(hist.len(), 1);
        assert_eq!(hist[0].total, 80);
        assert_eq!(hist[0].grade, "B");
        assert_eq!(hist[0].wiring, 30);
    }

    #[test]
    fn info_line_format() {
        let s = Score {
            total: 80,
            grade: "B".to_string(),
            components: [
                ("wiring".to_string(), 30),
                ("regression".to_string(), 25),
                ("compliance".to_string(), 0),
                ("cases".to_string(), 15),
                ("prompt_drift".to_string(), 10),
            ]
            .into_iter()
            .collect(),
            notes: vec![],
        };
        let line = info_line(&s);
        assert!(line.starts_with("AIM/AI: 80/100 B"));
        assert!(line.contains("wir=30"));
        assert!(line.contains("reg=25"));
        assert!(line.contains("comp=0"));
        assert!(line.contains("cases=15"));
        assert!(line.contains("pd=10"));
    }
}
