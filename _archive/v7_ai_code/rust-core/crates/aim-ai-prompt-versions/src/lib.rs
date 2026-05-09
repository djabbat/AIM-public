//! aim-ai-prompt-versions — PV1.
//!
//! Track sha256 / size of `AI/docs/SELF_DIAGNOSTIC_PROMPT.md` across
//! revisions so we can correlate prompt edits with diagnostic-quality
//! changes in the ledger. Stored in a sidecar table on the same DB
//! as the ledger, schema parity with `AI/ai/prompt_versions.py`.

use rusqlite::{params, Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PromptError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("prompt file not found: {0}")]
    PromptNotFound(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Fingerprint {
    pub sha256: String,
    pub byte_count: u64,
    pub line_count: u64,
    pub ts: Option<String>,
}

/// Resolve the prompt path: `AI_DIAGNOSTIC_PROMPT` env →
/// `AI/docs/SELF_DIAGNOSTIC_PROMPT.md` relative to the current AIM root
/// (the env-overridable `AIM_ROOT`, falling back to CWD).
pub fn default_prompt_path() -> PathBuf {
    if let Ok(p) = std::env::var("AI_DIAGNOSTIC_PROMPT") {
        return PathBuf::from(p);
    }
    let root = std::env::var("AIM_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    root.join("AI").join("docs").join("SELF_DIAGNOSTIC_PROMPT.md")
}

/// Hash + size of `path`'s current contents.
pub fn fingerprint_of(path: &std::path::Path) -> Result<Fingerprint, PromptError> {
    if !path.exists() {
        return Err(PromptError::PromptNotFound(path.display().to_string()));
    }
    use sha2::Digest;
    let blob = std::fs::read(path)?;
    let mut h = sha2::Sha256::new();
    h.update(&blob);
    let digest = hex::encode(h.finalize());
    let byte_count = blob.len() as u64;
    let line_count = {
        let lf = blob.iter().filter(|b| **b == b'\n').count() as u64;
        if blob.last().copied() == Some(b'\n') || blob.is_empty() {
            lf
        } else {
            lf + 1
        }
    };
    Ok(Fingerprint {
        sha256: digest,
        byte_count,
        line_count,
        ts: None,
    })
}

/// Drift summary against the most recent stored fingerprint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Drift {
    pub have_baseline: bool,
    pub prompt_present: bool,
    pub changed: bool,
    pub last_sha: Option<String>,
    pub current_sha: Option<String>,
    pub delta_bytes: i64,
    pub delta_lines: i64,
    pub last_ts: Option<String>,
}

/// Sidecar handle on the diagnostic-ledger DB.
pub struct PromptStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl PromptStore {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, PromptError> {
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
            CREATE TABLE IF NOT EXISTS prompt_versions (
                ts          TEXT NOT NULL,
                sha256      TEXT NOT NULL,
                byte_count  INTEGER NOT NULL,
                line_count  INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_sha
                ON prompt_versions(sha256);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn open_default() -> Result<Self, PromptError> {
        Self::open(aim_ai_ledger::Ledger::default_path())
    }

    /// Record the current prompt's fingerprint. Idempotent on sha
    /// (same content twice ⇒ no duplicate row).
    pub fn record_current(
        &self,
        path: Option<&std::path::Path>,
        ts: Option<&str>,
    ) -> Result<Fingerprint, PromptError> {
        let owned;
        let p = match path {
            Some(p) => p,
            None => {
                owned = default_prompt_path();
                owned.as_path()
            }
        };
        let mut fp = fingerprint_of(p)?;
        let ts_owned = ts
            .map(|s| s.to_string())
            .unwrap_or_else(|| chrono::Utc::now().to_rfc3339());
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR IGNORE INTO prompt_versions(ts, sha256, byte_count, line_count) \
             VALUES (?1, ?2, ?3, ?4)",
            params![ts_owned, fp.sha256, fp.byte_count as i64, fp.line_count as i64],
        )?;
        fp.ts = Some(ts_owned);
        Ok(fp)
    }

    /// All fingerprints, oldest first.
    pub fn history(&self) -> Result<Vec<Fingerprint>, PromptError> {
        let c = self.conn.lock().unwrap();
        let mut stmt = c.prepare(
            "SELECT ts, sha256, byte_count, line_count \
             FROM prompt_versions ORDER BY ts ASC",
        )?;
        let rows = stmt
            .query_map([], |r| {
                Ok(Fingerprint {
                    ts: Some(r.get::<_, String>(0)?),
                    sha256: r.get(1)?,
                    byte_count: r.get::<_, i64>(2)? as u64,
                    line_count: r.get::<_, i64>(3)? as u64,
                })
            })?
            .filter_map(Result::ok)
            .collect();
        Ok(rows)
    }

    /// Compare current prompt to the most recent stored fingerprint.
    pub fn drift_since_last(&self, path: Option<&std::path::Path>) -> Result<Drift, PromptError> {
        let owned;
        let p = match path {
            Some(p) => p,
            None => {
                owned = default_prompt_path();
                owned.as_path()
            }
        };
        if !p.exists() {
            return Ok(Drift {
                have_baseline: false,
                prompt_present: false,
                changed: false,
                last_sha: None,
                current_sha: None,
                delta_bytes: 0,
                delta_lines: 0,
                last_ts: None,
            });
        }
        let cur = fingerprint_of(p)?;
        let h = self.history()?;
        if h.is_empty() {
            return Ok(Drift {
                have_baseline: false,
                prompt_present: true,
                changed: false,
                last_sha: None,
                current_sha: Some(cur.sha256),
                delta_bytes: 0,
                delta_lines: 0,
                last_ts: None,
            });
        }
        let last = h.last().unwrap();
        Ok(Drift {
            have_baseline: true,
            prompt_present: true,
            changed: cur.sha256 != last.sha256,
            last_sha: Some(last.sha256.clone()),
            current_sha: Some(cur.sha256.clone()),
            delta_bytes: cur.byte_count as i64 - last.byte_count as i64,
            delta_lines: cur.line_count as i64 - last.line_count as i64,
            last_ts: last.ts.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, PromptStore, PathBuf) {
        let d = tempdir().unwrap();
        let store = PromptStore::open(d.path().join("ledger.db")).unwrap();
        let prompt = d.path().join("prompt.md");
        (d, store, prompt)
    }

    #[test]
    fn fingerprint_known_bytes() {
        let d = tempdir().unwrap();
        let p = d.path().join("p.md");
        std::fs::write(&p, "hello\nworld\n").unwrap();
        let f = fingerprint_of(&p).unwrap();
        assert_eq!(f.byte_count, 12);
        assert_eq!(f.line_count, 2);
        assert_eq!(f.sha256.len(), 64);
    }

    #[test]
    fn fingerprint_no_trailing_newline_counts_last_line() {
        let d = tempdir().unwrap();
        let p = d.path().join("p.md");
        std::fs::write(&p, "ab\ncd").unwrap();
        let f = fingerprint_of(&p).unwrap();
        assert_eq!(f.line_count, 2);
    }

    #[test]
    fn fingerprint_missing_file_errors() {
        let d = tempdir().unwrap();
        let p = d.path().join("absent.md");
        assert!(matches!(fingerprint_of(&p), Err(PromptError::PromptNotFound(_))));
    }

    #[test]
    fn record_current_is_idempotent_on_sha() {
        let (_d, store, prompt) = fresh();
        std::fs::write(&prompt, "abc\n").unwrap();
        store.record_current(Some(&prompt), Some("t1")).unwrap();
        store.record_current(Some(&prompt), Some("t2")).unwrap();
        let h = store.history().unwrap();
        assert_eq!(h.len(), 1, "duplicate sha must not insert second row");
    }

    #[test]
    fn record_after_change_appends_row() {
        let (_d, store, prompt) = fresh();
        std::fs::write(&prompt, "abc\n").unwrap();
        store.record_current(Some(&prompt), Some("t1")).unwrap();
        std::fs::write(&prompt, "abcd\n").unwrap();
        store.record_current(Some(&prompt), Some("t2")).unwrap();
        assert_eq!(store.history().unwrap().len(), 2);
    }

    #[test]
    fn drift_no_baseline_when_no_history() {
        let (_d, store, prompt) = fresh();
        std::fs::write(&prompt, "x").unwrap();
        let d = store.drift_since_last(Some(&prompt)).unwrap();
        assert!(!d.have_baseline);
        assert!(d.prompt_present);
        assert!(d.current_sha.is_some());
    }

    #[test]
    fn drift_no_prompt_when_file_missing() {
        let (_d, store, prompt) = fresh();
        // prompt path does not exist
        let d = store.drift_since_last(Some(&prompt)).unwrap();
        assert!(!d.prompt_present);
    }

    #[test]
    fn drift_unchanged_when_sha_matches() {
        let (_d, store, prompt) = fresh();
        std::fs::write(&prompt, "stable\n").unwrap();
        store.record_current(Some(&prompt), Some("t1")).unwrap();
        let d = store.drift_since_last(Some(&prompt)).unwrap();
        assert!(d.have_baseline);
        assert!(!d.changed);
        assert_eq!(d.delta_bytes, 0);
    }

    #[test]
    fn drift_changed_with_deltas() {
        let (_d, store, prompt) = fresh();
        std::fs::write(&prompt, "ab\n").unwrap();
        store.record_current(Some(&prompt), Some("t1")).unwrap();
        std::fs::write(&prompt, "abcd\nef\n").unwrap();
        let d = store.drift_since_last(Some(&prompt)).unwrap();
        assert!(d.changed);
        assert_eq!(d.delta_bytes, 5); // 8 - 3
        assert_eq!(d.delta_lines, 1);
    }
}
