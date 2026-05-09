//! aim-ai-ledger — DG1 diagnostic ledger.
//!
//! Append-only SQLite log of every self-diagnostic run. One row per
//! saved report; no PII (only metric counts + grade).
//!
//! Why this matters: with auto-retry on `run_self_diagnostic`, we want
//! to know whether the corrective suffix is actually pulling compliance
//! up over time, AND whether prompt-tightening is moving the average
//! grade.
//!
//! Schema parity with `AI/ai/diagnostic_ledger.py::_connect`, so the
//! same DB is readable by either implementation during the migration.
//!
//! Public API:
//! - [`Ledger::open`] / [`Ledger::open_default`]
//! - [`Ledger::record`] — append a new row from explicit metrics
//! - [`Ledger::all_rows`] — every row, oldest-first
//! - [`Ledger::recent`] — last N rows
//! - [`Ledger::trend`] — aggregate trend stats
//! - [`Ledger::prune_phantom`] — remove rows whose `report_path` no
//!   longer exists on disk (test-fixture leftovers)

use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LedgerError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid input: {0}")]
    Invalid(String),
}

/// One ledger row. Mirrors the Python `Row` dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Row {
    pub ts: String,
    pub model: String,
    pub grade: Option<String>,
    pub n_refs: i64,
    pub n_with_line: i64,
    pub compliance: f64,
    pub crit: Option<i64>,
    pub high: Option<i64>,
    pub med: Option<i64>,
    pub low: Option<i64>,
    pub retry_used: bool,
    pub report_path: Option<String>,
}

/// Aggregate trend stats across all rows.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trend {
    pub n_runs: u64,
    pub avg_compliance: f64,
    pub avg_crit: f64,
    pub grade_dist: BTreeMap<String, u64>,
    pub retry_share: f64,
    pub first_ts: Option<String>,
    pub last_ts: Option<String>,
}

/// Append-only ledger backed by SQLite.
pub struct Ledger {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl Ledger {
    /// Open or create the ledger DB at the given path. Sets WAL mode
    /// and applies the schema on first open.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, LedgerError> {
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
            CREATE TABLE IF NOT EXISTS runs (
                ts          TEXT NOT NULL,
                model       TEXT NOT NULL,
                grade       TEXT,
                n_refs      INTEGER NOT NULL,
                n_with_line INTEGER NOT NULL,
                compliance  REAL NOT NULL,
                crit        INTEGER,
                high        INTEGER,
                med         INTEGER,
                low         INTEGER,
                retry_used  INTEGER NOT NULL DEFAULT 0,
                report_path TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    /// Resolve the canonical ledger path:
    /// `AI_DIAGNOSTIC_DB` env → `~/.cache/aim/diagnostic_ledger.db`.
    pub fn default_path() -> PathBuf {
        if let Ok(p) = std::env::var("AI_DIAGNOSTIC_DB") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("diagnostic_ledger.db");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home)
            .join(".cache")
            .join("aim")
            .join("diagnostic_ledger.db")
    }

    pub fn open_default() -> Result<Self, LedgerError> {
        Self::open(Self::default_path())
    }

    /// Append a new row. `compliance` is computed from `n_refs +
    /// n_with_line` and stored alongside.
    #[allow(clippy::too_many_arguments)]
    pub fn record(
        &self,
        model: &str,
        grade: Option<&str>,
        n_refs: i64,
        n_with_line: i64,
        crit: Option<i64>,
        high: Option<i64>,
        med: Option<i64>,
        low: Option<i64>,
        retry_used: bool,
        report_path: Option<&str>,
        ts: Option<&str>,
    ) -> Result<(), LedgerError> {
        if n_refs < 0 || n_with_line < 0 {
            return Err(LedgerError::Invalid("counts must be non-negative".to_string()));
        }
        if n_with_line > n_refs {
            return Err(LedgerError::Invalid(
                "n_with_line cannot exceed n_refs".to_string(),
            ));
        }
        let compliance = if n_refs > 0 {
            n_with_line as f64 / n_refs as f64
        } else {
            0.0
        };
        let ts_owned = ts
            .map(|s| s.to_string())
            .unwrap_or_else(|| chrono::Utc::now().to_rfc3339());
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT INTO runs(ts, model, grade, n_refs, n_with_line, compliance, \
                crit, high, med, low, retry_used, report_path) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                ts_owned,
                model,
                grade,
                n_refs,
                n_with_line,
                compliance,
                crit,
                high,
                med,
                low,
                retry_used as i64,
                report_path
            ],
        )?;
        Ok(())
    }

    /// All rows, oldest first.
    pub fn all_rows(&self) -> Result<Vec<Row>, LedgerError> {
        let c = self.conn.lock().unwrap();
        let mut stmt = c.prepare(
            "SELECT ts, model, grade, n_refs, n_with_line, compliance, \
                crit, high, med, low, retry_used, report_path \
             FROM runs ORDER BY ts ASC",
        )?;
        let rows = stmt
            .query_map([], row_from_db)?
            .filter_map(Result::ok)
            .collect();
        Ok(rows)
    }

    /// Last `n` rows by ts.
    pub fn recent(&self, n: usize) -> Result<Vec<Row>, LedgerError> {
        let mut all = self.all_rows()?;
        let len = all.len();
        if n >= len {
            return Ok(all);
        }
        Ok(all.split_off(len - n))
    }

    /// Aggregate trend across all rows.
    pub fn trend(&self) -> Result<Trend, LedgerError> {
        let rows = self.all_rows()?;
        if rows.is_empty() {
            return Ok(Trend {
                n_runs: 0,
                avg_compliance: 0.0,
                avg_crit: 0.0,
                grade_dist: BTreeMap::new(),
                retry_share: 0.0,
                first_ts: None,
                last_ts: None,
            });
        }
        let n = rows.len() as u64;
        let avg_compliance = rows.iter().map(|r| r.compliance).sum::<f64>() / n as f64;
        let crit_rows: Vec<i64> = rows.iter().filter_map(|r| r.crit).collect();
        let avg_crit = if crit_rows.is_empty() {
            0.0
        } else {
            crit_rows.iter().sum::<i64>() as f64 / crit_rows.len() as f64
        };
        let mut grade_dist: BTreeMap<String, u64> = BTreeMap::new();
        for r in &rows {
            if let Some(g) = r.grade.as_ref() {
                *grade_dist.entry(g.clone()).or_insert(0) += 1;
            }
        }
        let retry_share = rows.iter().filter(|r| r.retry_used).count() as f64 / n as f64;
        Ok(Trend {
            n_runs: n,
            avg_compliance,
            avg_crit,
            grade_dist,
            retry_share,
            first_ts: rows.first().map(|r| r.ts.clone()),
            last_ts: rows.last().map(|r| r.ts.clone()),
        })
    }

    /// Remove rows whose `report_path` was set but the file no longer
    /// exists on disk (almost certainly test-fixture leftovers).
    /// Returns counts. Safe by default (`dry_run: true`).
    pub fn prune_phantom(&self, dry_run: bool) -> Result<PruneResult, LedgerError> {
        let rows = self.all_rows()?;
        let mut phantom: Vec<String> = Vec::new();
        let mut kept: u64 = 0;
        for r in &rows {
            match r.report_path.as_ref() {
                Some(p) if !Path::new(p).exists() => phantom.push(r.ts.clone()),
                _ => kept += 1,
            }
        }
        if dry_run || phantom.is_empty() {
            return Ok(PruneResult {
                removed: 0,
                would_remove: phantom.len() as u64,
                kept,
                dry_run,
            });
        }
        // Real removal — chunk by 500 to stay under SQL parameter limits.
        let c = self.conn.lock().unwrap();
        for chunk in phantom.chunks(500) {
            let placeholders = std::iter::repeat("?")
                .take(chunk.len())
                .collect::<Vec<_>>()
                .join(",");
            let sql = format!("DELETE FROM runs WHERE ts IN ({placeholders})");
            let mut stmt = c.prepare(&sql)?;
            let params_iter: Vec<&dyn rusqlite::ToSql> =
                chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
            stmt.execute(params_iter.as_slice())?;
        }
        Ok(PruneResult {
            removed: phantom.len() as u64,
            would_remove: 0,
            kept,
            dry_run: false,
        })
    }

    #[allow(dead_code)]
    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PruneResult {
    pub removed: u64,
    pub would_remove: u64,
    pub kept: u64,
    pub dry_run: bool,
}

fn row_from_db(r: &rusqlite::Row<'_>) -> rusqlite::Result<Row> {
    Ok(Row {
        ts: r.get(0)?,
        model: r.get(1)?,
        grade: r.get(2)?,
        n_refs: r.get(3)?,
        n_with_line: r.get(4)?,
        compliance: r.get(5)?,
        crit: r.get(6)?,
        high: r.get(7)?,
        med: r.get(8)?,
        low: r.get(9)?,
        retry_used: r.get::<_, i64>(10)? != 0,
        report_path: r.get(11)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, Ledger) {
        let d = tempdir().unwrap();
        let l = Ledger::open(d.path().join("ledger.db")).unwrap();
        (d, l)
    }

    #[test]
    fn empty_trend_is_zero() {
        let (_d, l) = fresh();
        let t = l.trend().unwrap();
        assert_eq!(t.n_runs, 0);
        assert!(t.first_ts.is_none());
    }

    #[test]
    fn record_basic_compliance() {
        let (_d, l) = fresh();
        l.record(
            "deepseek-v4-flash",
            Some("B"),
            10,
            7,
            Some(1),
            Some(2),
            Some(3),
            Some(4),
            false,
            None,
            Some("2026-05-04T00:00:00Z"),
        )
        .unwrap();
        let rows = l.all_rows().unwrap();
        assert_eq!(rows.len(), 1);
        let r = &rows[0];
        assert!((r.compliance - 0.7).abs() < 1e-9);
        assert_eq!(r.grade.as_deref(), Some("B"));
        assert_eq!(r.crit, Some(1));
        assert!(!r.retry_used);
    }

    #[test]
    fn record_rejects_negative_counts() {
        let (_d, l) = fresh();
        let e = l.record("m", None, -1, 0, None, None, None, None, false, None, None);
        assert!(matches!(e, Err(LedgerError::Invalid(_))));
    }

    #[test]
    fn record_rejects_with_line_exceeds_refs() {
        let (_d, l) = fresh();
        let e = l.record("m", None, 3, 5, None, None, None, None, false, None, None);
        assert!(matches!(e, Err(LedgerError::Invalid(_))));
    }

    #[test]
    fn record_zero_refs_yields_zero_compliance() {
        let (_d, l) = fresh();
        l.record("m", None, 0, 0, None, None, None, None, false, None, None)
            .unwrap();
        assert_eq!(l.all_rows().unwrap()[0].compliance, 0.0);
    }

    #[test]
    fn trend_aggregates_correctly() {
        let (_d, l) = fresh();
        l.record("m1", Some("A"), 10, 8, Some(0), None, None, None, false, None, Some("2026-05-01T00:00:00Z")).unwrap();
        l.record("m1", Some("B"), 10, 6, Some(2), None, None, None, true, None, Some("2026-05-02T00:00:00Z")).unwrap();
        l.record("m2", Some("A"), 10, 9, Some(0), None, None, None, false, None, Some("2026-05-03T00:00:00Z")).unwrap();
        let t = l.trend().unwrap();
        assert_eq!(t.n_runs, 3);
        assert!((t.avg_compliance - (0.8 + 0.6 + 0.9) / 3.0).abs() < 1e-9);
        assert!((t.avg_crit - (0.0 + 2.0 + 0.0) / 3.0).abs() < 1e-9);
        assert_eq!(t.grade_dist.get("A").copied(), Some(2));
        assert_eq!(t.grade_dist.get("B").copied(), Some(1));
        assert!((t.retry_share - 1.0 / 3.0).abs() < 1e-9);
        assert_eq!(t.first_ts.as_deref(), Some("2026-05-01T00:00:00Z"));
        assert_eq!(t.last_ts.as_deref(), Some("2026-05-03T00:00:00Z"));
    }

    #[test]
    fn recent_returns_tail() {
        let (_d, l) = fresh();
        for i in 0..5 {
            l.record(
                "m",
                None,
                10,
                i + 1,
                None,
                None,
                None,
                None,
                false,
                None,
                Some(&format!("2026-05-04T0{}:00:00Z", i)),
            )
            .unwrap();
        }
        let r = l.recent(2).unwrap();
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].n_with_line, 4);
        assert_eq!(r[1].n_with_line, 5);
    }

    #[test]
    fn recent_more_than_total_returns_all() {
        let (_d, l) = fresh();
        l.record("m", None, 10, 8, None, None, None, None, false, None, None).unwrap();
        let r = l.recent(50).unwrap();
        assert_eq!(r.len(), 1);
    }

    #[test]
    fn prune_phantom_dry_run_does_not_delete() {
        let (_d, l) = fresh();
        l.record("m", None, 10, 8, None, None, None, None, false,
                 Some("/nonexistent/path/report.md"), None).unwrap();
        l.record("m", None, 10, 9, None, None, None, None, false, None, None).unwrap();
        let r = l.prune_phantom(true).unwrap();
        assert_eq!(r.dry_run, true);
        assert_eq!(r.removed, 0);
        assert_eq!(r.would_remove, 1);
        assert_eq!(l.all_rows().unwrap().len(), 2);
    }

    #[test]
    fn prune_phantom_removes_when_real() {
        let (_d, l) = fresh();
        l.record("m", None, 10, 8, None, None, None, None, false,
                 Some("/nonexistent/path/report.md"), Some("2026-05-04T01:00:00Z")).unwrap();
        l.record("m", None, 10, 9, None, None, None, None, false, None,
                 Some("2026-05-04T02:00:00Z")).unwrap();
        let r = l.prune_phantom(false).unwrap();
        assert_eq!(r.dry_run, false);
        assert_eq!(r.removed, 1);
        assert_eq!(r.kept, 1);
        let remaining = l.all_rows().unwrap();
        assert_eq!(remaining.len(), 1);
        assert!(remaining[0].report_path.is_none());
    }

    #[test]
    fn persistence_round_trip() {
        let d = tempdir().unwrap();
        let p = d.path().join("ledger.db");
        {
            let l = Ledger::open(&p).unwrap();
            l.record("m", Some("A"), 10, 9, None, None, None, None, false, None,
                     Some("2026-05-04T00:00:00Z")).unwrap();
        }
        let l2 = Ledger::open(&p).unwrap();
        assert_eq!(l2.all_rows().unwrap().len(), 1);
    }
}
