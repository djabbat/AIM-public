//! aim-stakeholder-tracker — contacts DB + email hooks (P3).
//!
//! Port of `agents/stakeholder_tracker.py`. SQLite-backed cross-project,
//! cross-session tracker for project YAML stakeholder lists. Pluggable
//! [`Clock`] keeps tests deterministic (no `std::time` reads inside the
//! crate's logic).
//!
//! ## Hook surface (call from email_agent / git push / Telegram)
//! - [`Tracker::on_email_sent`] — mark just-emailed, awaiting reply
//! - [`Tracker::on_email_received`] — clear awaiting_reply
//! - [`Tracker::on_meeting`] — bump last_contact_at without changing
//!   awaiting_reply
//!
//! ## Queries
//! - [`Tracker::overdue_followups`]
//! - [`Tracker::silent_for`]
//! - [`Tracker::awaiting_reply`]
//! - [`Tracker::by_project`]
//! - [`Tracker::all_contacts`] / [`Tracker::get_by_email`] / [`Tracker::get_by_name`]
//!
//! Default DB lives at `$AIM_HOME/contacts.db` (else
//! `~/.cache/aim/contacts.db`); env override `AIM_CONTACTS_DB`.

use chrono::{DateTime, NaiveDate, Utc};
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TrackerError {
    #[error("name is required")]
    EmptyName,
    #[error("need name or email")]
    NoIdentifier,
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Contact {
    pub id: i64,
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_contact_at: Option<String>,
    #[serde(default)]
    pub awaiting_reply: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_response_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

impl Contact {
    pub fn days_silent(&self, today: NaiveDate) -> Option<i64> {
        let raw = self.last_contact_at.as_deref()?;
        let prefix: String = raw.chars().take(10).collect();
        let d = NaiveDate::parse_from_str(&prefix, "%Y-%m-%d").ok()?;
        Some((today - d).num_days())
    }

    pub fn overdue(&self, today: NaiveDate) -> bool {
        if !self.awaiting_reply {
            return false;
        }
        let raw = match &self.expected_response_by {
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

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

#[derive(Debug)]
pub struct ManualClock {
    state: Mutex<DateTime<Utc>>,
}

impl ManualClock {
    pub fn new(t: DateTime<Utc>) -> Self {
        Self {
            state: Mutex::new(t),
        }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.state.lock() = t;
    }
}

impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.state.lock()
    }
}

pub fn default_db_path() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_CONTACTS_DB") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
        }
    }
    if let Ok(p) = std::env::var("AIM_HOME") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p).join("contacts.db");
        }
    }
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".cache").join("aim").join("contacts.db")
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

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    role TEXT,
    project TEXT,
    last_contact_at TEXT,
    awaiting_reply INTEGER NOT NULL DEFAULT 0,
    expected_response_by TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_name_email ON contacts(name, IFNULL(email, ''));
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email) WHERE email IS NOT NULL;
";

pub struct Tracker {
    conn: Arc<Mutex<Connection>>,
    clock: Arc<dyn Clock>,
}

impl Tracker {
    pub fn open(db: impl AsRef<Path>) -> Result<Self, TrackerError> {
        Self::open_with_clock(db, Arc::new(SystemClock))
    }

    pub fn open_with_clock(
        db: impl AsRef<Path>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, TrackerError> {
        let p = db.as_ref();
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let conn = Connection::open(p)?;
        conn.execute_batch("PRAGMA foreign_keys=ON;")?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
            clock,
        })
    }

    fn now_iso(&self) -> String {
        self.clock.now().format("%Y-%m-%dT%H:%M:%S").to_string()
    }

    fn map_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Contact> {
        Ok(Contact {
            id: row.get("id")?,
            name: row.get("name")?,
            email: row.get("email")?,
            role: row.get("role")?,
            project: row.get("project")?,
            last_contact_at: row.get("last_contact_at")?,
            awaiting_reply: row.get::<_, i64>("awaiting_reply")? != 0,
            expected_response_by: row.get("expected_response_by")?,
            notes: row.get("notes")?,
        })
    }

    fn normalise_email(email: Option<&str>) -> Option<String> {
        email
            .map(|s| s.trim().to_lowercase())
            .filter(|s| !s.is_empty())
    }

    /// Create-or-update a contact by `(name, email)`. Returns row id.
    pub fn upsert(
        &self,
        name: &str,
        email: Option<&str>,
        role: Option<&str>,
        project: Option<&str>,
        notes: Option<&str>,
    ) -> Result<i64, TrackerError> {
        let name = name.trim();
        if name.is_empty() {
            return Err(TrackerError::EmptyName);
        }
        let email_norm = Self::normalise_email(email);
        let now = self.now_iso();
        let con = self.conn.lock();

        let existing: Option<i64> = con
            .query_row(
                "SELECT id FROM contacts WHERE name=? AND IFNULL(email,'')=?",
                params![name, email_norm.clone().unwrap_or_default()],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(id) = existing {
            con.execute(
                "UPDATE contacts SET role=COALESCE(?, role), \
                                     project=COALESCE(?, project), \
                                     notes=COALESCE(?, notes), \
                                     updated_at=? \
                 WHERE id=?",
                params![role, project, notes, now, id],
            )?;
            Ok(id)
        } else {
            con.execute(
                "INSERT INTO contacts(name, email, role, project, notes, created_at, updated_at) \
                 VALUES (?,?,?,?,?,?,?)",
                params![name, email_norm, role, project, notes, now, now],
            )?;
            Ok(con.last_insert_rowid())
        }
    }

    pub fn get_by_email(&self, email: &str) -> Result<Option<Contact>, TrackerError> {
        let em = email.trim().to_lowercase();
        if em.is_empty() {
            return Ok(None);
        }
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM contacts WHERE email=?")?;
        let r = stmt.query_row(params![em], Self::map_row).optional()?;
        Ok(r)
    }

    pub fn get_by_name(&self, name: &str) -> Result<Vec<Contact>, TrackerError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM contacts WHERE name=?")?;
        let v: Vec<Contact> = stmt
            .query_map(params![name], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn by_project(&self, project: &str) -> Result<Vec<Contact>, TrackerError> {
        let con = self.conn.lock();
        let mut stmt =
            con.prepare("SELECT * FROM contacts WHERE project LIKE ? ORDER BY name")?;
        let v: Vec<Contact> = stmt
            .query_map(params![format!("%{project}%")], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn all_contacts(&self) -> Result<Vec<Contact>, TrackerError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM contacts ORDER BY name")?;
        let v: Vec<Contact> = stmt
            .query_map([], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn on_email_sent(
        &self,
        name: Option<&str>,
        email: Option<&str>,
        project: Option<&str>,
        expected_response_by: Option<&str>,
        role: Option<&str>,
    ) -> Result<i64, TrackerError> {
        if name.is_none() && email.is_none() {
            return Err(TrackerError::NoIdentifier);
        }
        let resolved_name: String = match name {
            Some(n) if !n.trim().is_empty() => n.trim().to_string(),
            _ => email
                .unwrap_or("")
                .split('@')
                .next()
                .unwrap_or("")
                .to_string(),
        };
        let id = self.upsert(&resolved_name, email, role, project, None)?;
        let now = self.now_iso();
        let con = self.conn.lock();
        con.execute(
            "UPDATE contacts SET last_contact_at=?, awaiting_reply=1, \
             expected_response_by=?, updated_at=? WHERE id=?",
            params![now, expected_response_by, now, id],
        )?;
        Ok(id)
    }

    pub fn on_email_received(&self, email: &str) -> Result<bool, TrackerError> {
        let em = email.trim().to_lowercase();
        if em.is_empty() {
            return Ok(false);
        }
        let now = self.now_iso();
        let con = self.conn.lock();
        let n = con.execute(
            "UPDATE contacts SET awaiting_reply=0, last_contact_at=?, \
             expected_response_by=NULL, updated_at=? WHERE email=?",
            params![now, now, em],
        )?;
        Ok(n > 0)
    }

    pub fn on_meeting(
        &self,
        name: Option<&str>,
        email: Option<&str>,
    ) -> Result<i64, TrackerError> {
        if name.is_none() && email.is_none() {
            return Err(TrackerError::NoIdentifier);
        }
        let resolved_name: String = match name {
            Some(n) if !n.trim().is_empty() => n.trim().to_string(),
            _ => email
                .unwrap_or("")
                .split('@')
                .next()
                .unwrap_or("")
                .to_string(),
        };
        let id = self.upsert(&resolved_name, email, None, None, None)?;
        let now = self.now_iso();
        let con = self.conn.lock();
        con.execute(
            "UPDATE contacts SET last_contact_at=?, updated_at=? WHERE id=?",
            params![now, now, id],
        )?;
        Ok(id)
    }

    pub fn overdue_followups(&self, today: NaiveDate) -> Result<Vec<Contact>, TrackerError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT * FROM contacts \
             WHERE awaiting_reply=1 AND expected_response_by IS NOT NULL \
               AND date(expected_response_by) < date(?) \
             ORDER BY expected_response_by",
        )?;
        let v: Vec<Contact> = stmt
            .query_map(params![today.to_string()], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn silent_for(
        &self,
        days: i64,
        today: NaiveDate,
    ) -> Result<Vec<Contact>, TrackerError> {
        let cutoff = (today - chrono::Duration::days(days)).to_string();
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT * FROM contacts \
             WHERE last_contact_at IS NOT NULL \
               AND date(last_contact_at) < date(?) \
             ORDER BY last_contact_at",
        )?;
        let v: Vec<Contact> = stmt
            .query_map(params![cutoff], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }

    pub fn awaiting_reply(&self) -> Result<Vec<Contact>, TrackerError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare(
            "SELECT * FROM contacts WHERE awaiting_reply=1 ORDER BY expected_response_by",
        )?;
        let v: Vec<Contact> = stmt
            .query_map([], Self::map_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(v)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn at(y: i32, m: u32, d: u32, h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, 0, 0).unwrap()
    }

    fn fresh() -> (TempDir, Tracker, Arc<ManualClock>) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("contacts.db");
        let clock = Arc::new(ManualClock::new(at(2026, 5, 4, 12)));
        let t = Tracker::open_with_clock(&db, clock.clone()).unwrap();
        (dir, t, clock)
    }

    #[test]
    fn upsert_creates_then_updates() {
        let (_d, t, _c) = fresh();
        let id1 = t
            .upsert("Geiger", Some("geiger@example.com"), Some("Co-PI"), Some("FCLC"), None)
            .unwrap();
        let id2 = t
            .upsert("Geiger", Some("geiger@example.com"), None, Some("FCLC,Ze"), Some("note"))
            .unwrap();
        assert_eq!(id1, id2, "same (name,email) → upsert");
        let c = t.get_by_email("geiger@example.com").unwrap().unwrap();
        // Role should not have been overwritten by None (COALESCE)
        assert_eq!(c.role.as_deref(), Some("Co-PI"));
        assert_eq!(c.project.as_deref(), Some("FCLC,Ze"));
        assert_eq!(c.notes.as_deref(), Some("note"));
    }

    #[test]
    fn upsert_email_normalised() {
        let (_d, t, _c) = fresh();
        t.upsert("Geiger", Some("Geiger@Example.COM"), None, None, None).unwrap();
        let c = t.get_by_email("geiger@example.com").unwrap().unwrap();
        assert_eq!(c.email.as_deref(), Some("geiger@example.com"));
    }

    #[test]
    fn upsert_empty_name_errors() {
        let (_d, t, _c) = fresh();
        let err = t.upsert("   ", None, None, None, None).unwrap_err();
        assert!(matches!(err, TrackerError::EmptyName));
    }

    #[test]
    fn on_email_sent_marks_awaiting() {
        let (_d, t, _c) = fresh();
        let id = t
            .on_email_sent(
                Some("Geiger"),
                Some("geiger@example.com"),
                Some("FCLC"),
                Some("2026-05-11"),
                Some("Co-PI"),
            )
            .unwrap();
        let c = t.get_by_email("geiger@example.com").unwrap().unwrap();
        assert_eq!(c.id, id);
        assert!(c.awaiting_reply);
        assert_eq!(c.expected_response_by.as_deref(), Some("2026-05-11"));
        assert!(c.last_contact_at.is_some());
    }

    #[test]
    fn on_email_sent_uses_email_localpart_when_no_name() {
        let (_d, t, _c) = fresh();
        let id = t
            .on_email_sent(None, Some("alice@example.com"), None, None, None)
            .unwrap();
        let c = t.get_by_email("alice@example.com").unwrap().unwrap();
        assert_eq!(c.id, id);
        assert_eq!(c.name, "alice");
    }

    #[test]
    fn on_email_received_clears_awaiting() {
        let (_d, t, _c) = fresh();
        t.on_email_sent(
            Some("Geiger"),
            Some("geiger@example.com"),
            None,
            Some("2026-05-11"),
            None,
        )
        .unwrap();
        assert!(t.on_email_received("geiger@example.com").unwrap());
        let c = t.get_by_email("geiger@example.com").unwrap().unwrap();
        assert!(!c.awaiting_reply);
        assert!(c.expected_response_by.is_none());
    }

    #[test]
    fn on_email_received_returns_false_when_no_match() {
        let (_d, t, _c) = fresh();
        assert!(!t.on_email_received("nobody@example.com").unwrap());
    }

    #[test]
    fn on_meeting_bumps_last_contact() {
        let (_d, t, clock) = fresh();
        clock.set(at(2026, 5, 4, 9));
        t.on_email_sent(
            Some("Geiger"),
            Some("geiger@example.com"),
            None,
            Some("2026-05-11"),
            None,
        )
        .unwrap();
        let before = t.get_by_email("geiger@example.com").unwrap().unwrap();
        clock.set(at(2026, 5, 5, 14));
        t.on_meeting(Some("Geiger"), Some("geiger@example.com")).unwrap();
        let after = t.get_by_email("geiger@example.com").unwrap().unwrap();
        // last_contact_at moved forward; awaiting_reply still true
        assert_ne!(after.last_contact_at, before.last_contact_at);
        assert!(after.awaiting_reply);
    }

    #[test]
    fn no_identifier_errors() {
        let (_d, t, _c) = fresh();
        let err = t.on_email_sent(None, None, None, None, None).unwrap_err();
        assert!(matches!(err, TrackerError::NoIdentifier));
    }

    #[test]
    fn overdue_followups_filters() {
        let (_d, t, _c) = fresh();
        t.on_email_sent(
            Some("A"),
            Some("a@x.com"),
            None,
            Some("2026-04-01"), // past
            None,
        )
        .unwrap();
        t.on_email_sent(
            Some("B"),
            Some("b@x.com"),
            None,
            Some("2026-06-01"), // future
            None,
        )
        .unwrap();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let v = t.overdue_followups(today).unwrap();
        let names: Vec<&str> = v.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["A"]);
    }

    #[test]
    fn silent_for_window() {
        let (_d, t, clock) = fresh();
        clock.set(at(2026, 4, 1, 12));
        t.upsert("Old", Some("old@x.com"), None, None, None).unwrap();
        t.on_meeting(Some("Old"), Some("old@x.com")).unwrap();
        clock.set(at(2026, 5, 3, 12));
        t.upsert("Recent", Some("rec@x.com"), None, None, None).unwrap();
        t.on_meeting(Some("Recent"), Some("rec@x.com")).unwrap();
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let v = t.silent_for(14, today).unwrap();
        let names: Vec<&str> = v.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["Old"]);
    }

    #[test]
    fn awaiting_reply_lists_only_awaiting() {
        let (_d, t, _c) = fresh();
        t.on_email_sent(Some("X"), Some("x@x.com"), None, None, None).unwrap();
        t.upsert("Y", Some("y@y.com"), None, None, None).unwrap();
        let v = t.awaiting_reply().unwrap();
        let names: Vec<&str> = v.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["X"]);
    }

    #[test]
    fn by_project_substring_match() {
        let (_d, t, _c) = fresh();
        t.upsert("A", Some("a@x.com"), None, Some("FCLC"), None).unwrap();
        t.upsert("B", Some("b@x.com"), None, Some("FCLC,Ze"), None).unwrap();
        t.upsert("C", Some("c@x.com"), None, Some("MCOA"), None).unwrap();
        let v = t.by_project("FCLC").unwrap();
        let names: Vec<&str> = v.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, vec!["A", "B"]);
    }

    #[test]
    fn contact_overdue_helper() {
        let c = Contact {
            id: 1,
            name: "X".into(),
            email: None,
            role: None,
            project: None,
            last_contact_at: None,
            awaiting_reply: true,
            expected_response_by: Some("2026-04-01".into()),
            notes: None,
        };
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        assert!(c.overdue(today));
        let mut not_awaiting = c.clone();
        not_awaiting.awaiting_reply = false;
        assert!(!not_awaiting.overdue(today));
    }

    #[test]
    fn days_silent_helper() {
        let c = Contact {
            id: 1,
            name: "X".into(),
            email: None,
            role: None,
            project: None,
            last_contact_at: Some("2026-04-20T09:00:00".into()),
            awaiting_reply: false,
            expected_response_by: None,
            notes: None,
        };
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        assert_eq!(c.days_silent(today), Some(14));
    }

    #[test]
    fn get_by_name_returns_all_matches() {
        let (_d, t, _c) = fresh();
        t.upsert("Geiger", Some("a@x.com"), None, None, None).unwrap();
        t.upsert("Geiger", Some("b@x.com"), None, None, None).unwrap();
        let v = t.get_by_name("Geiger").unwrap();
        assert_eq!(v.len(), 2);
    }
}
