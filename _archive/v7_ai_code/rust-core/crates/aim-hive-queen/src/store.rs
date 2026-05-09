//! SQLite-backed queen store. Schema parity with `hive_queen.py::_connect`
//! so a single DB is readable by either implementation during migration.

use rusqlite::{params, Connection, OpenFlags};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use thiserror::Error;

use crate::{Contribution, Update};

#[derive(Debug, Error)]
pub enum QueenError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

pub struct QueenStore {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    path: PathBuf,
}

impl QueenStore {
    /// Open or create the queen DB at the given path. Sets WAL mode
    /// and creates schema on first open.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, QueenError> {
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
            CREATE TABLE IF NOT EXISTS contributions (
                id          TEXT PRIMARY KEY,
                ts          TEXT NOT NULL,
                worker_id   TEXT NOT NULL,
                payload     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_contrib_worker
                ON contributions(worker_id, ts);
            CREATE TABLE IF NOT EXISTS updates (
                id          TEXT PRIMARY KEY,
                ts          TEXT NOT NULL,
                kind        TEXT NOT NULL,
                body        TEXT NOT NULL,
                source_n    INTEGER NOT NULL,
                eval_delta  REAL,
                signature   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_updates_ts ON updates(ts);
            "#,
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    /// Resolve the canonical queen DB path: `AIM_HIVE_QUEEN_DB` env →
    /// `~/.cache/aim/hive_queen.db` (or XDG cache).
    pub fn default_path() -> PathBuf {
        if let Ok(p) = std::env::var("AIM_HIVE_QUEEN_DB") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("hive_queen.db");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".cache").join("aim").join("hive_queen.db")
    }

    pub fn open_default() -> Result<Self, QueenError> {
        Self::open(Self::default_path())
    }

    pub fn insert_contribution(
        &self,
        id: &str,
        ts: &str,
        worker_id: &str,
        payload_blob: &str,
    ) -> Result<(), QueenError> {
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT OR REPLACE INTO contributions(id, ts, worker_id, payload) \
             VALUES (?1, ?2, ?3, ?4)",
            params![id, ts, worker_id, payload_blob],
        )?;
        Ok(())
    }

    pub fn list_contributions(
        &self,
        limit: i64,
        worker_id: Option<&str>,
    ) -> Result<Vec<Contribution>, QueenError> {
        let c = self.conn.lock().unwrap();
        let mut stmt;
        let rows: Vec<Contribution> = if let Some(wid) = worker_id {
            stmt = c.prepare(
                "SELECT id, ts, worker_id, payload FROM contributions \
                 WHERE worker_id = ?1 ORDER BY ts DESC LIMIT ?2",
            )?;
            stmt.query_map(params![wid, limit], row_to_contribution)?
                .filter_map(Result::ok)
                .collect()
        } else {
            stmt = c.prepare(
                "SELECT id, ts, worker_id, payload FROM contributions \
                 ORDER BY ts DESC LIMIT ?1",
            )?;
            stmt.query_map(params![limit], row_to_contribution)?
                .filter_map(Result::ok)
                .collect()
        };
        Ok(rows)
    }

    pub fn count_contributions(&self) -> Result<u64, QueenError> {
        let c = self.conn.lock().unwrap();
        let n: i64 = c.query_row("SELECT COUNT(*) FROM contributions", [], |r| r.get(0))?;
        Ok(n as u64)
    }

    pub fn insert_update(
        &self,
        id: &str,
        ts: &str,
        kind: &str,
        body_blob: &str,
        source_n: u32,
        eval_delta: Option<f64>,
        signature: &str,
    ) -> Result<(), QueenError> {
        let c = self.conn.lock().unwrap();
        c.execute(
            "INSERT INTO updates(id, ts, kind, body, source_n, eval_delta, signature) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![id, ts, kind, body_blob, source_n, eval_delta, signature],
        )?;
        Ok(())
    }

    pub fn list_updates(&self, since: Option<&str>) -> Result<Vec<Update>, QueenError> {
        let c = self.conn.lock().unwrap();
        let mut stmt;
        let rows: Vec<Update> = if let Some(s) = since {
            stmt = c.prepare(
                "SELECT id, ts, kind, body, source_n, eval_delta, signature \
                 FROM updates WHERE ts > ?1 ORDER BY ts ASC",
            )?;
            stmt.query_map(params![s], row_to_update)?
                .filter_map(Result::ok)
                .collect()
        } else {
            stmt = c.prepare(
                "SELECT id, ts, kind, body, source_n, eval_delta, signature \
                 FROM updates ORDER BY ts ASC",
            )?;
            stmt.query_map([], row_to_update)?
                .filter_map(Result::ok)
                .collect()
        };
        Ok(rows)
    }

    #[allow(dead_code)]
    pub fn path(&self) -> &Path {
        &self.path
    }
}

fn row_to_contribution(r: &rusqlite::Row<'_>) -> rusqlite::Result<Contribution> {
    let blob: String = r.get(3)?;
    let payload = serde_json::from_str(&blob).unwrap_or(serde_json::Value::Null);
    Ok(Contribution {
        id: r.get(0)?,
        ts: r.get(1)?,
        worker_id: r.get(2)?,
        payload,
    })
}

fn row_to_update(r: &rusqlite::Row<'_>) -> rusqlite::Result<Update> {
    let blob: String = r.get(3)?;
    let body = serde_json::from_str(&blob).unwrap_or(serde_json::Value::Null);
    Ok(Update {
        id: r.get(0)?,
        ts: r.get(1)?,
        kind: r.get(2)?,
        body,
        source_n: r.get::<_, i64>(4)? as u32,
        eval_delta: r.get(5)?,
        signature: r.get(6)?,
    })
}
