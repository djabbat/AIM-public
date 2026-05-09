//! Local SQLite state for sync_log + L_CONSENT opt-outs.
//! Schema parity with `hive_consumer.py::_connect`.

use rusqlite::{params, Connection, OpenFlags};
use std::path::PathBuf;
use std::sync::Mutex;

use crate::{ConsumerError, Update};

pub struct ConsumerState {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SyncState {
    pub last_pull_ts: Option<String>,
    pub last_seen_id: Option<String>,
    pub n_installed: u32,
    pub n_skipped: u32,
}

impl ConsumerState {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, ConsumerError> {
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
            CREATE TABLE IF NOT EXISTS sync_log (
                update_id      TEXT PRIMARY KEY,
                update_ts      TEXT NOT NULL,
                kind           TEXT NOT NULL,
                installed      INTEGER NOT NULL DEFAULT 0,
                skipped        INTEGER NOT NULL DEFAULT 0,
                skipped_reason TEXT,
                seen_at        TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS opt_outs (
                kind     TEXT NOT NULL,
                pattern  TEXT NOT NULL,
                PRIMARY KEY (kind, pattern)
            );
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn default_path() -> PathBuf {
        if let Ok(p) = std::env::var("AIM_HIVE_STATE_DB") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("hive_state.db");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".cache").join("aim").join("hive_state.db")
    }

    pub fn open_default() -> Result<Self, ConsumerError> {
        Self::open(Self::default_path())
    }

    // ── L_CONSENT ────────────────────────────────────────────

    pub fn opt_out(&self, kind: &str, pattern: &str) -> Result<(), ConsumerError> {
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR REPLACE INTO opt_outs(kind, pattern) VALUES (?1, ?2)",
            params![kind, pattern],
        )?;
        Ok(())
    }

    pub fn opt_in(&self, kind: &str, pattern: &str) -> Result<bool, ConsumerError> {
        let c = self.conn.lock().unwrap();
        let n = c.execute(
            "DELETE FROM opt_outs WHERE kind = ?1 AND pattern = ?2",
            params![kind, pattern],
        )?;
        Ok(n > 0)
    }

    pub fn is_opted_out(
        &self,
        kind: &str,
        body: &serde_json::Value,
    ) -> Result<bool, ConsumerError> {
        let c = self.conn.lock().unwrap();
        let mut stmt =
            c.prepare("SELECT pattern FROM opt_outs WHERE kind = ?1")?;
        let rows: Vec<String> = stmt
            .query_map(params![kind], |r| r.get::<_, String>(0))?
            .filter_map(Result::ok)
            .collect();
        if rows.is_empty() {
            return Ok(false);
        }
        for pattern in rows {
            if pattern == "*" {
                return Ok(true);
            }
            // Match against any string value in body.
            if matches_any_string(body, &pattern) {
                return Ok(true);
            }
        }
        Ok(false)
    }

    // ── sync_log ─────────────────────────────────────────────

    pub fn record_decision(
        &self,
        update: &Update,
        installed: bool,
        skipped: bool,
        skipped_reason: Option<&str>,
        seen_at: &str,
    ) -> Result<(), ConsumerError> {
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR REPLACE INTO sync_log\
             (update_id, update_ts, kind, installed, skipped, skipped_reason, seen_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                update.id,
                update.ts,
                update.kind,
                installed as i64,
                skipped as i64,
                skipped_reason,
                seen_at
            ],
        )?;
        Ok(())
    }

    pub fn last_seen_ts(&self) -> Result<Option<String>, ConsumerError> {
        let c = self.conn.lock().unwrap();
        let v: Option<String> = c
            .query_row("SELECT MAX(update_ts) FROM sync_log", [], |r| r.get(0))
            .ok()
            .flatten();
        Ok(v)
    }

    pub fn sync_state(&self) -> Result<SyncState, ConsumerError> {
        let c = self.conn.lock().unwrap();
        let row = c.query_row(
            "SELECT MAX(seen_at), MAX(update_id), \
                COALESCE(SUM(installed),0), COALESCE(SUM(skipped),0) \
                FROM sync_log",
            [],
            |r| {
                let seen_at: Option<String> = r.get(0).ok();
                let last_id: Option<String> = r.get(1).ok();
                let installed: i64 = r.get(2)?;
                let skipped: i64 = r.get(3)?;
                Ok((seen_at, last_id, installed, skipped))
            },
        )?;
        Ok(SyncState {
            last_pull_ts: row.0,
            last_seen_id: row.1,
            n_installed: row.2 as u32,
            n_skipped: row.3 as u32,
        })
    }
}

fn matches_any_string(v: &serde_json::Value, pattern: &str) -> bool {
    match v {
        serde_json::Value::String(s) => glob_match(pattern, s),
        serde_json::Value::Array(arr) => arr.iter().any(|x| matches_any_string(x, pattern)),
        serde_json::Value::Object(map) => {
            map.values().any(|x| matches_any_string(x, pattern))
        }
        _ => false,
    }
}

/// Tiny `*`-glob matcher, matching `fnmatch.fnmatch` in the Python
/// reference for the patterns we actually emit (`*`, `prefix-*`,
/// `*-suffix`). We use the `glob` crate's `Pattern` for full glob
/// semantics.
fn glob_match(pattern: &str, s: &str) -> bool {
    glob::Pattern::new(pattern)
        .map(|p| p.matches(s))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn s() -> (tempfile::TempDir, ConsumerState) {
        let d = tempdir().unwrap();
        let st = ConsumerState::open(d.path().join("s.db")).unwrap();
        (d, st)
    }

    #[test]
    fn opt_out_star_matches_anything() {
        let (_d, st) = s();
        st.opt_out("skill", "*").unwrap();
        assert!(st.is_opted_out("skill", &serde_json::json!({})).unwrap());
        assert!(st
            .is_opted_out("skill", &serde_json::json!({"skill_id":"x"}))
            .unwrap());
    }

    #[test]
    fn opt_out_glob_matches_string_field() {
        let (_d, st) = s();
        st.opt_out("skill", "auto-*").unwrap();
        assert!(st
            .is_opted_out("skill", &serde_json::json!({"skill_id":"auto-12345"}))
            .unwrap());
        assert!(!st
            .is_opted_out("skill", &serde_json::json!({"skill_id":"manual-1"}))
            .unwrap());
    }

    #[test]
    fn opt_in_removes_opt_out() {
        let (_d, st) = s();
        st.opt_out("skill", "*").unwrap();
        let removed = st.opt_in("skill", "*").unwrap();
        assert!(removed);
        assert!(!st.is_opted_out("skill", &serde_json::json!({})).unwrap());
    }

    #[test]
    fn sync_state_counts() {
        let (_d, st) = s();
        let u = Update {
            id: "u1".into(),
            ts: "2026-05-04T00:00:00Z".into(),
            kind: "skill".into(),
            body: serde_json::json!({}),
            source_n: 3,
            eval_delta: None,
            signature: "abcdef0123".into(),
        };
        st.record_decision(&u, true, false, None, "2026-05-04T01:00:00Z").unwrap();
        let s = st.sync_state().unwrap();
        assert_eq!(s.n_installed, 1);
        assert_eq!(s.n_skipped, 0);
        assert_eq!(s.last_seen_id.as_deref(), Some("u1"));
    }
}
