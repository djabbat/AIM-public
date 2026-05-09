//! aim-feature-flags — in-flight flag/experiment tracker (FX1).
//!
//! Port of `agents/feature_flags.py`. A small SQLite registry for the kind
//! of "remove-once-X" tags that otherwise rot quietly: feature flags,
//! staged rollouts, A/B experiments, on-call workarounds.
//!
//! ## Schema
//! Each flag has `id` · `project` · `owner` · `status` (active/ramping/
//! ready_to_remove/retired) · `cleanup_by` (ISO date) · `notes` · created_at /
//! updated_at.
//!
//! ## Public API
//! - [`Registry::add`] — upsert a flag by id
//! - [`Registry::update`] — partial update by named fields
//! - [`Registry::list_flags`] — filter by status/project
//! - [`Registry::overdue`] — flags whose `cleanup_by` ≤ today + horizon
//! - [`Registry::summary`] — human-readable digest

use chrono::NaiveDate;
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum FlagError {
    #[error("flag id required")]
    EmptyId,
    #[error("status must be one of: active, ramping, ready_to_remove, retired")]
    InvalidStatus,
    #[error("invalid cleanup_by date '{0}'")]
    InvalidDate(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Active,
    Ramping,
    ReadyToRemove,
    Retired,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Active => "active",
            Status::Ramping => "ramping",
            Status::ReadyToRemove => "ready_to_remove",
            Status::Retired => "retired",
        }
    }

    pub fn parse(s: &str) -> Result<Self, FlagError> {
        match s {
            "active" => Ok(Status::Active),
            "ramping" => Ok(Status::Ramping),
            "ready_to_remove" => Ok(Status::ReadyToRemove),
            "retired" => Ok(Status::Retired),
            _ => Err(FlagError::InvalidStatus),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Flag {
    pub id: String,
    #[serde(default)]
    pub project: Option<String>,
    #[serde(default)]
    pub owner: Option<String>,
    pub status: Status,
    #[serde(default)]
    pub cleanup_by: Option<String>,
    #[serde(default)]
    pub notes: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

impl Flag {
    pub fn is_overdue(&self, today: NaiveDate) -> bool {
        if self.status == Status::Retired {
            return false;
        }
        let raw = match &self.cleanup_by {
            Some(s) if !s.is_empty() => s,
            _ => return false,
        };
        let prefix: String = raw.chars().take(10).collect();
        match NaiveDate::parse_from_str(&prefix, "%Y-%m-%d") {
            Ok(d) => today > d,
            Err(_) => false,
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct UpdateFields {
    pub project: Option<String>,
    pub owner: Option<String>,
    pub status: Option<Status>,
    pub cleanup_by: Option<String>,
    pub notes: Option<String>,
}

impl UpdateFields {
    pub fn is_empty(&self) -> bool {
        self.project.is_none()
            && self.owner.is_none()
            && self.status.is_none()
            && self.cleanup_by.is_none()
            && self.notes.is_none()
    }
}

pub fn default_db_path() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_FLAGS_DB") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
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
    base.join("feature_flags.db")
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

pub struct Registry {
    conn: Arc<Mutex<Connection>>,
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS flags (
    id TEXT PRIMARY KEY,
    project TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    cleanup_by TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flags_status  ON flags(status);
CREATE INDEX IF NOT EXISTS idx_flags_cleanup ON flags(cleanup_by);
";

impl Registry {
    pub fn open(db: impl AsRef<Path>) -> Result<Self, FlagError> {
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
        chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string()
    }

    /// Upsert a flag by id (matches Python's `add` which is upsert).
    pub fn add(
        &self,
        id: &str,
        project: Option<&str>,
        owner: Option<&str>,
        status: Status,
        cleanup_by: Option<&str>,
        notes: Option<&str>,
    ) -> Result<String, FlagError> {
        let id = id.trim();
        if id.is_empty() {
            return Err(FlagError::EmptyId);
        }
        if let Some(d) = cleanup_by {
            if !d.is_empty() {
                let prefix: String = d.chars().take(10).collect();
                if NaiveDate::parse_from_str(&prefix, "%Y-%m-%d").is_err() {
                    return Err(FlagError::InvalidDate(d.to_string()));
                }
            }
        }
        let now = Self::now();
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO flags(id, project, owner, status, cleanup_by, notes, created_at, updated_at) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?) \
             ON CONFLICT(id) DO UPDATE SET \
                 project    = excluded.project, \
                 owner      = excluded.owner, \
                 status     = excluded.status, \
                 cleanup_by = excluded.cleanup_by, \
                 notes      = excluded.notes, \
                 updated_at = excluded.updated_at",
            params![id, project, owner, status.as_str(), cleanup_by, notes, now, now],
        )?;
        Ok(id.to_string())
    }

    pub fn update(&self, id: &str, fields: &UpdateFields) -> Result<bool, FlagError> {
        if fields.is_empty() {
            return Ok(false);
        }
        let mut clauses = Vec::new();
        let mut binds: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
        if let Some(v) = &fields.project {
            clauses.push("project=?");
            binds.push(Box::new(v.clone()));
        }
        if let Some(v) = &fields.owner {
            clauses.push("owner=?");
            binds.push(Box::new(v.clone()));
        }
        if let Some(s) = fields.status {
            clauses.push("status=?");
            binds.push(Box::new(s.as_str().to_string()));
        }
        if let Some(v) = &fields.cleanup_by {
            if !v.is_empty() {
                let prefix: String = v.chars().take(10).collect();
                if NaiveDate::parse_from_str(&prefix, "%Y-%m-%d").is_err() {
                    return Err(FlagError::InvalidDate(v.clone()));
                }
            }
            clauses.push("cleanup_by=?");
            binds.push(Box::new(v.clone()));
        }
        if let Some(v) = &fields.notes {
            clauses.push("notes=?");
            binds.push(Box::new(v.clone()));
        }
        clauses.push("updated_at=?");
        binds.push(Box::new(Self::now()));
        binds.push(Box::new(id.to_string()));

        let sql = format!(
            "UPDATE flags SET {} WHERE id=?",
            clauses.join(", "),
        );
        let con = self.conn.lock();
        let bind_refs: Vec<&dyn rusqlite::ToSql> = binds.iter().map(|b| b.as_ref()).collect();
        let n = con.execute(&sql, bind_refs.as_slice())?;
        Ok(n > 0)
    }

    pub fn get(&self, id: &str) -> Result<Option<Flag>, FlagError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM flags WHERE id=?")?;
        let f = stmt.query_row(params![id], row_to_flag).optional()?;
        Ok(f)
    }

    pub fn list_flags(
        &self,
        status: Option<Status>,
        project: Option<&str>,
    ) -> Result<Vec<Flag>, FlagError> {
        let mut sql = String::from("SELECT * FROM flags WHERE 1=1");
        let mut binds: Vec<String> = Vec::new();
        if let Some(s) = status {
            sql.push_str(" AND status=?");
            binds.push(s.as_str().to_string());
        }
        if let Some(p) = project {
            sql.push_str(" AND project=?");
            binds.push(p.to_string());
        }
        sql.push_str(" ORDER BY id");
        let con = self.conn.lock();
        let mut stmt = con.prepare(&sql)?;
        let bind_refs: Vec<&dyn rusqlite::ToSql> =
            binds.iter().map(|b| b as &dyn rusqlite::ToSql).collect();
        let v: Vec<Flag> = stmt
            .query_map(bind_refs.as_slice(), row_to_flag)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn remove(&self, id: &str) -> Result<bool, FlagError> {
        let con = self.conn.lock();
        let n = con.execute("DELETE FROM flags WHERE id=?", params![id])?;
        Ok(n > 0)
    }

    /// Flags whose `cleanup_by ≤ today + horizon_days` AND status != retired.
    pub fn overdue(&self, today: NaiveDate, horizon_days: i64) -> Result<Vec<Flag>, FlagError> {
        let cutoff = (today + chrono::Duration::days(horizon_days)).format("%Y-%m-%d").to_string();
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT * FROM flags \
             WHERE status != 'retired' \
               AND cleanup_by IS NOT NULL \
               AND cleanup_by != '' \
               AND date(cleanup_by) <= date(?) \
             ORDER BY cleanup_by ASC",
        )?;
        let v: Vec<Flag> = stmt
            .query_map(params![cutoff], row_to_flag)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn summary(&self, today: NaiveDate) -> Result<String, FlagError> {
        let flags = self.list_flags(None, None)?;
        if flags.is_empty() {
            return Ok("(no feature flags tracked)".into());
        }
        let mut by_status: std::collections::BTreeMap<&str, u32> = Default::default();
        for f in &flags {
            *by_status.entry(f.status.as_str()).or_insert(0) += 1;
        }
        let mut lines = vec!["🚩 Feature flags:".to_string()];
        for (s, n) in &by_status {
            lines.push(format!("  • {}: {}", s, n));
        }
        let over = self.overdue(today, 14)?;
        if !over.is_empty() {
            lines.push(format!("  ⚠ overdue/cleanup-soon ({}):", over.len()));
            for f in over.iter().take(8) {
                let cb: String = f
                    .cleanup_by
                    .as_deref()
                    .unwrap_or("")
                    .chars()
                    .take(10)
                    .collect();
                lines.push(format!(
                    "    - {}  (cleanup_by={}, owner={}, project={})",
                    f.id,
                    cb,
                    f.owner.as_deref().unwrap_or("?"),
                    f.project.as_deref().unwrap_or("?")
                ));
            }
        }
        Ok(lines.join("\n"))
    }
}

fn row_to_flag(row: &rusqlite::Row<'_>) -> rusqlite::Result<Flag> {
    let status_str: String = row.get("status")?;
    let status = Status::parse(&status_str).unwrap_or(Status::Active);
    Ok(Flag {
        id: row.get("id")?,
        project: row.get("project")?,
        owner: row.get("owner")?,
        status,
        cleanup_by: row.get("cleanup_by")?,
        notes: row.get("notes")?,
        created_at: row.get("created_at")?,
        updated_at: row.get("updated_at")?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fresh() -> (TempDir, Registry) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("flags.db");
        let r = Registry::open(&db).unwrap();
        (dir, r)
    }

    fn date(y: i32, m: u32, d: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, d).unwrap()
    }

    #[test]
    fn add_then_get() {
        let (_d, r) = fresh();
        r.add("kill_legacy", Some("aim"), Some("jaba"), Status::Active, Some("2026-06-01"), None)
            .unwrap();
        let f = r.get("kill_legacy").unwrap().unwrap();
        assert_eq!(f.id, "kill_legacy");
        assert_eq!(f.project.as_deref(), Some("aim"));
        assert_eq!(f.status, Status::Active);
        assert_eq!(f.cleanup_by.as_deref(), Some("2026-06-01"));
    }

    #[test]
    fn add_rejects_empty_id() {
        let (_d, r) = fresh();
        let e = r.add("   ", None, None, Status::Active, None, None).unwrap_err();
        assert!(matches!(e, FlagError::EmptyId));
    }

    #[test]
    fn add_rejects_bad_date() {
        let (_d, r) = fresh();
        let e = r
            .add("x", None, None, Status::Active, Some("not-a-date"), None)
            .unwrap_err();
        assert!(matches!(e, FlagError::InvalidDate(_)));
    }

    #[test]
    fn add_upserts_existing() {
        let (_d, r) = fresh();
        r.add("a", Some("p1"), None, Status::Active, None, None).unwrap();
        r.add("a", Some("p2"), None, Status::Ramping, None, None).unwrap();
        let f = r.get("a").unwrap().unwrap();
        assert_eq!(f.project.as_deref(), Some("p2"));
        assert_eq!(f.status, Status::Ramping);
    }

    #[test]
    fn update_partial_fields() {
        let (_d, r) = fresh();
        r.add("a", None, None, Status::Active, None, None).unwrap();
        let mut fields = UpdateFields::default();
        fields.status = Some(Status::ReadyToRemove);
        fields.notes = Some("ready next sprint".into());
        let changed = r.update("a", &fields).unwrap();
        assert!(changed);
        let f = r.get("a").unwrap().unwrap();
        assert_eq!(f.status, Status::ReadyToRemove);
        assert_eq!(f.notes.as_deref(), Some("ready next sprint"));
    }

    #[test]
    fn update_empty_returns_false() {
        let (_d, r) = fresh();
        r.add("a", None, None, Status::Active, None, None).unwrap();
        assert!(!r.update("a", &UpdateFields::default()).unwrap());
    }

    #[test]
    fn list_filters_by_status_and_project() {
        let (_d, r) = fresh();
        r.add("a", Some("p1"), None, Status::Active, None, None).unwrap();
        r.add("b", Some("p1"), None, Status::Retired, None, None).unwrap();
        r.add("c", Some("p2"), None, Status::Active, None, None).unwrap();
        let active = r.list_flags(Some(Status::Active), None).unwrap();
        assert_eq!(active.len(), 2);
        let p1 = r.list_flags(None, Some("p1")).unwrap();
        assert_eq!(p1.len(), 2);
        let active_p1 = r.list_flags(Some(Status::Active), Some("p1")).unwrap();
        assert_eq!(active_p1.len(), 1);
        assert_eq!(active_p1[0].id, "a");
    }

    #[test]
    fn remove_returns_true_only_when_existed() {
        let (_d, r) = fresh();
        r.add("a", None, None, Status::Active, None, None).unwrap();
        assert!(r.remove("a").unwrap());
        assert!(!r.remove("a").unwrap());
    }

    #[test]
    fn overdue_includes_within_horizon() {
        let (_d, r) = fresh();
        let today = date(2026, 5, 4);
        r.add("past", None, None, Status::Active, Some("2026-05-01"), None).unwrap();
        r.add("soon", None, None, Status::Active, Some("2026-05-10"), None).unwrap();
        r.add("future", None, None, Status::Active, Some("2026-09-01"), None).unwrap();
        r.add("retired", None, None, Status::Retired, Some("2026-05-01"), None).unwrap();
        let v = r.overdue(today, 14).unwrap();
        let ids: Vec<&str> = v.iter().map(|f| f.id.as_str()).collect();
        assert!(ids.contains(&"past"));
        assert!(ids.contains(&"soon"));
        assert!(!ids.contains(&"future"));
        assert!(!ids.contains(&"retired"));
    }

    #[test]
    fn flag_is_overdue_helper() {
        let f = Flag {
            id: "x".into(),
            project: None,
            owner: None,
            status: Status::Active,
            cleanup_by: Some("2026-04-01".into()),
            notes: None,
            created_at: "x".into(),
            updated_at: "x".into(),
        };
        assert!(f.is_overdue(date(2026, 5, 4)));
        assert!(!f.is_overdue(date(2026, 1, 1)));
        let mut retired = f.clone();
        retired.status = Status::Retired;
        assert!(!retired.is_overdue(date(2026, 5, 4)));
    }

    #[test]
    fn summary_empty_registry() {
        let (_d, r) = fresh();
        let s = r.summary(date(2026, 5, 4)).unwrap();
        assert!(s.contains("no feature flags"));
    }

    #[test]
    fn summary_groups_by_status_and_lists_overdue() {
        let (_d, r) = fresh();
        let today = date(2026, 5, 4);
        r.add("a", Some("p1"), Some("jaba"), Status::Active, Some("2026-04-01"), None).unwrap();
        r.add("b", None, None, Status::Retired, None, None).unwrap();
        let s = r.summary(today).unwrap();
        assert!(s.contains("🚩 Feature flags:"));
        assert!(s.contains("active: 1"));
        assert!(s.contains("retired: 1"));
        assert!(s.contains("overdue/cleanup-soon"));
        assert!(s.contains("- a"));
    }

    #[test]
    fn status_serde_round_trip() {
        let raw = serde_json::to_string(&Status::ReadyToRemove).unwrap();
        assert_eq!(raw, "\"ready_to_remove\"");
        let back: Status = serde_json::from_str("\"ramping\"").unwrap();
        assert_eq!(back, Status::Ramping);
    }
}
