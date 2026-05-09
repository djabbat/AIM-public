//! aim-ai-suppressions — FS1.
//!
//! Some diagnostic findings are persistent false-positives or
//! intentional code (a TODO that's part of the design, a known
//! limitation that has a roadmap entry). RA1 alerts must not fire on
//! those forever.
//!
//! Sidecar table on the ledger DB. A suppression has an optional
//! `until_ts` — `is_active()` is true when `until_ts is None or
//! until_ts > now`. Expiry frees the finding back to alerting.
//!
//! Rust port of `AI/ai/finding_suppressions.py`.

use aim_ai_ledger::Ledger;
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SuppressError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid input: {0}")]
    Invalid(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Suppression {
    pub r#ref: String,
    pub reason: String,
    pub created_ts: String,
    pub until_ts: Option<String>,
}

impl Suppression {
    /// True if `until_ts` is None OR parseable & > now.
    pub fn is_active(&self) -> bool {
        match &self.until_ts {
            None => true,
            Some(s) => match DateTime::parse_from_rfc3339(s) {
                Ok(dt) => Utc::now() < dt.with_timezone(&Utc),
                Err(_) => true, // unparseable → leave active (matches Python)
            },
        }
    }
}

pub struct SuppressionStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl SuppressionStore {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, SuppressError> {
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
            CREATE TABLE IF NOT EXISTS finding_suppressions (
                ref         TEXT PRIMARY KEY,
                reason      TEXT NOT NULL DEFAULT '',
                created_ts  TEXT NOT NULL,
                until_ts    TEXT
            );
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn open_default() -> Result<Self, SuppressError> {
        Self::open(Ledger::default_path())
    }

    /// Add or replace a suppression. `until` is optional RFC3339 time.
    pub fn suppress(
        &self,
        r#ref: &str,
        reason: &str,
        until: Option<DateTime<Utc>>,
    ) -> Result<Suppression, SuppressError> {
        let trimmed = r#ref.trim();
        if trimmed.is_empty() {
            return Err(SuppressError::Invalid("ref must be non-empty".into()));
        }
        let created = Utc::now().to_rfc3339();
        let until_ts = until.map(|d| d.to_rfc3339());
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR REPLACE INTO finding_suppressions(ref, reason, created_ts, until_ts) \
             VALUES (?1, ?2, ?3, ?4)",
            params![trimmed, reason, created, until_ts],
        )?;
        Ok(Suppression {
            r#ref: trimmed.to_string(),
            reason: reason.to_string(),
            created_ts: created,
            until_ts,
        })
    }

    /// Remove a suppression. Returns true if a row was deleted.
    pub fn unsuppress(&self, r#ref: &str) -> Result<bool, SuppressError> {
        let c = self.conn.lock().unwrap();
        let n = c.execute(
            "DELETE FROM finding_suppressions WHERE ref = ?1",
            params![r#ref],
        )?;
        Ok(n > 0)
    }

    /// All suppressions, oldest first.
    pub fn all_rows(&self) -> Result<Vec<Suppression>, SuppressError> {
        let c = self.conn.lock().unwrap();
        let mut stmt = c.prepare(
            "SELECT ref, reason, created_ts, until_ts FROM finding_suppressions \
             ORDER BY created_ts ASC",
        )?;
        let rows = stmt
            .query_map([], |r| {
                Ok(Suppression {
                    r#ref: r.get(0)?,
                    reason: r.get(1)?,
                    created_ts: r.get(2)?,
                    until_ts: r.get(3)?,
                })
            })?
            .filter_map(Result::ok)
            .collect();
        Ok(rows)
    }

    /// Currently-active suppressions only.
    pub fn active(&self) -> Result<Vec<Suppression>, SuppressError> {
        Ok(self.all_rows()?.into_iter().filter(|s| s.is_active()).collect())
    }

    pub fn is_suppressed(&self, r#ref: &str) -> Result<bool, SuppressError> {
        Ok(self.active()?.iter().any(|s| s.r#ref == r#ref))
    }

    /// Return refs minus any currently-suppressed.
    pub fn filter_findings<'a, I>(&self, refs: I) -> Result<Vec<String>, SuppressError>
    where
        I: IntoIterator<Item = &'a str>,
    {
        let blocked: BTreeSet<String> = self
            .active()?
            .into_iter()
            .map(|s| s.r#ref)
            .collect();
        Ok(refs
            .into_iter()
            .filter(|r| !blocked.contains(*r))
            .map(|s| s.to_string())
            .collect())
    }

    /// Delete rows whose `until_ts` has passed. Returns count removed.
    pub fn prune_expired(&self) -> Result<u64, SuppressError> {
        let rows = self.all_rows()?;
        let expired: Vec<String> = rows
            .iter()
            .filter(|s| !s.is_active())
            .map(|s| s.r#ref.clone())
            .collect();
        if expired.is_empty() {
            return Ok(0);
        }
        let c = self.conn.lock().unwrap();
        for chunk in expired.chunks(500) {
            let placeholders = std::iter::repeat("?")
                .take(chunk.len())
                .collect::<Vec<_>>()
                .join(",");
            let sql =
                format!("DELETE FROM finding_suppressions WHERE ref IN ({placeholders})");
            let mut stmt = c.prepare(&sql)?;
            let p: Vec<&dyn rusqlite::ToSql> =
                chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
            stmt.execute(p.as_slice())?;
        }
        Ok(expired.len() as u64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, SuppressionStore) {
        let d = tempdir().unwrap();
        let s = SuppressionStore::open(d.path().join("ledger.db")).unwrap();
        (d, s)
    }

    #[test]
    fn suppress_then_check() {
        let (_d, s) = fresh();
        s.suppress("agents/foo.py:42", "intentional TODO", None).unwrap();
        assert!(s.is_suppressed("agents/foo.py:42").unwrap());
        assert!(!s.is_suppressed("other.py:1").unwrap());
    }

    #[test]
    fn empty_ref_rejected() {
        let (_d, s) = fresh();
        assert!(matches!(
            s.suppress("", "", None),
            Err(SuppressError::Invalid(_))
        ));
        assert!(matches!(
            s.suppress("   ", "", None),
            Err(SuppressError::Invalid(_))
        ));
    }

    #[test]
    fn unsuppress_removes() {
        let (_d, s) = fresh();
        s.suppress("a.py:1", "x", None).unwrap();
        assert!(s.unsuppress("a.py:1").unwrap());
        assert!(!s.is_suppressed("a.py:1").unwrap());
    }

    #[test]
    fn unsuppress_unknown_returns_false() {
        let (_d, s) = fresh();
        assert!(!s.unsuppress("nope.py:99").unwrap());
    }

    #[test]
    fn until_in_future_is_active() {
        let (_d, s) = fresh();
        let until = Utc::now() + Duration::days(1);
        s.suppress("a.py:1", "", Some(until)).unwrap();
        assert!(s.is_suppressed("a.py:1").unwrap());
    }

    #[test]
    fn until_in_past_is_inactive() {
        let (_d, s) = fresh();
        let until = Utc::now() - Duration::days(1);
        s.suppress("a.py:1", "", Some(until)).unwrap();
        assert!(!s.is_suppressed("a.py:1").unwrap());
        // But the row remains in all_rows()
        assert_eq!(s.all_rows().unwrap().len(), 1);
    }

    #[test]
    fn filter_findings_drops_active_suppressions() {
        let (_d, s) = fresh();
        s.suppress("a.py:1", "", None).unwrap();
        let kept = s
            .filter_findings(["a.py:1", "b.py:2", "c.py:3"])
            .unwrap();
        assert_eq!(kept, vec!["b.py:2".to_string(), "c.py:3".to_string()]);
    }

    #[test]
    fn prune_expired_removes_only_expired() {
        let (_d, s) = fresh();
        s.suppress("a.py:1", "", None).unwrap();
        s.suppress("b.py:2", "", Some(Utc::now() - Duration::hours(1))).unwrap();
        s.suppress("c.py:3", "", Some(Utc::now() + Duration::days(7))).unwrap();
        let n = s.prune_expired().unwrap();
        assert_eq!(n, 1);
        let remaining: Vec<String> = s
            .all_rows()
            .unwrap()
            .into_iter()
            .map(|s| s.r#ref)
            .collect();
        assert!(remaining.contains(&"a.py:1".to_string()));
        assert!(remaining.contains(&"c.py:3".to_string()));
        assert!(!remaining.contains(&"b.py:2".to_string()));
    }
}
