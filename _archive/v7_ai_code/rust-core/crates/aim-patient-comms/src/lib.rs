//! aim-patient-comms — patient communication tracker (Phase D, 2026-05-06).
//!
//! Sister to `aim-stakeholder-tracker` (which serves Co-PI / external
//! collaborators). This crate is for *patient*-side communications:
//! WhatsApp messages, SMS, email, clinic visits. Different schema and
//! different privacy posture (PII redaction at egress).
//!
//! ```text
//! patient_messages   — raw inbound/outbound message log
//! patient_followups  — open follow-up items per (patient_id, topic)
//! ```
//!
//! Storage: `$AIM_HOME/patient_comms.db` (defaults to
//! `~/.cache/aim/patient_comms.db`). Bundled SQLite — no system dep.

use chrono::{DateTime, NaiveDate, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CommsError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid: {0}")]
    Invalid(String),
}

pub type Result<T> = std::result::Result<T, CommsError>;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Message {
    pub id: i64,
    pub patient_id: String,
    pub channel: String,    // whatsapp | sms | email | clinic | telegram
    pub direction: String,  // in | out
    pub body: String,
    pub ts: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Followup {
    pub patient_id: String,
    pub topic: String,
    pub awaiting_reply: bool,
    pub expected_response_by: Option<NaiveDate>,
    pub last_contact_at: Option<DateTime<Utc>>,
}

impl Followup {
    pub fn overdue(&self, today: NaiveDate) -> bool {
        if !self.awaiting_reply {
            return false;
        }
        match self.expected_response_by {
            Some(d) => today > d,
            None => false,
        }
    }
}

// ── store ──────────────────────────────────────────────────────────────────

pub struct CommsStore {
    db_path: PathBuf,
}

impl CommsStore {
    pub fn new(db_path: impl Into<PathBuf>) -> Result<Self> {
        let p = db_path.into();
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let store = Self { db_path: p };
        store.init_schema()?;
        Ok(store)
    }

    pub fn from_env() -> Result<Self> {
        Self::new(default_db_path())
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    fn conn(&self) -> Result<Connection> {
        Ok(Connection::open(&self.db_path)?)
    }

    fn init_schema(&self) -> Result<()> {
        let c = self.conn()?;
        c.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS patient_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                direction TEXT NOT NULL,
                body TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_patient_msg_pid_ts
                ON patient_messages(patient_id, ts DESC);
            CREATE TABLE IF NOT EXISTS patient_followups (
                patient_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                awaiting_reply INTEGER NOT NULL DEFAULT 1,
                expected_response_by TEXT,
                last_contact_at TEXT,
                PRIMARY KEY(patient_id, topic)
            );
            "#,
        )?;
        Ok(())
    }

    // ── messages ──────────────────────────────────────────────────────────

    pub fn record_message(
        &self,
        patient_id: &str,
        channel: &str,
        direction: &str,
        body: &str,
        ts: DateTime<Utc>,
    ) -> Result<i64> {
        if direction != "in" && direction != "out" {
            return Err(CommsError::Invalid(format!(
                "direction must be 'in' or 'out', got {direction:?}"
            )));
        }
        let c = self.conn()?;
        c.execute(
            "INSERT INTO patient_messages(patient_id, channel, direction, body, ts) \
             VALUES(?, ?, ?, ?, ?)",
            params![patient_id, channel, direction, body, ts.to_rfc3339()],
        )?;
        Ok(c.last_insert_rowid())
    }

    pub fn last_messages(&self, patient_id: &str, limit: i64) -> Result<Vec<Message>> {
        let c = self.conn()?;
        let mut stmt = c.prepare(
            "SELECT id, patient_id, channel, direction, body, ts \
             FROM patient_messages WHERE patient_id=? ORDER BY ts DESC LIMIT ?",
        )?;
        let rows = stmt
            .query_map(params![patient_id, limit], |r| {
                let ts_s: String = r.get(5)?;
                let ts = DateTime::parse_from_rfc3339(&ts_s)
                    .map_err(|_| {
                        rusqlite::Error::FromSqlConversionFailure(
                            5,
                            rusqlite::types::Type::Text,
                            "rfc3339".into(),
                        )
                    })?
                    .with_timezone(&Utc);
                Ok(Message {
                    id: r.get(0)?,
                    patient_id: r.get(1)?,
                    channel: r.get(2)?,
                    direction: r.get(3)?,
                    body: r.get(4)?,
                    ts,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn last_contact(
        &self,
        patient_id: &str,
    ) -> Result<Option<DateTime<Utc>>> {
        let c = self.conn()?;
        let row: Option<String> = c
            .query_row(
                "SELECT ts FROM patient_messages WHERE patient_id=? ORDER BY ts DESC LIMIT 1",
                params![patient_id],
                |r| r.get(0),
            )
            .optional()?;
        match row {
            Some(s) => Ok(Some(
                DateTime::parse_from_rfc3339(&s)
                    .map_err(|e| CommsError::Invalid(e.to_string()))?
                    .with_timezone(&Utc),
            )),
            None => Ok(None),
        }
    }

    // ── follow-ups ────────────────────────────────────────────────────────

    pub fn upsert_followup(
        &self,
        patient_id: &str,
        topic: &str,
        expected_response_by: Option<NaiveDate>,
    ) -> Result<()> {
        let c = self.conn()?;
        let exp_s = expected_response_by.map(|d| d.format("%Y-%m-%d").to_string());
        c.execute(
            "INSERT INTO patient_followups(patient_id, topic, awaiting_reply, expected_response_by) \
             VALUES(?, ?, 1, ?) \
             ON CONFLICT(patient_id, topic) DO UPDATE SET \
                awaiting_reply=1, expected_response_by=excluded.expected_response_by",
            params![patient_id, topic, exp_s],
        )?;
        Ok(())
    }

    pub fn close_followup(&self, patient_id: &str, topic: &str) -> Result<()> {
        let c = self.conn()?;
        c.execute(
            "UPDATE patient_followups SET awaiting_reply=0 WHERE patient_id=? AND topic=?",
            params![patient_id, topic],
        )?;
        Ok(())
    }

    pub fn list_followups(&self, patient_id: Option<&str>) -> Result<Vec<Followup>> {
        let c = self.conn()?;
        let (sql, args): (&str, Vec<String>) = match patient_id {
            Some(pid) => (
                "SELECT patient_id, topic, awaiting_reply, expected_response_by, last_contact_at \
                 FROM patient_followups WHERE patient_id=? ORDER BY topic",
                vec![pid.to_string()],
            ),
            None => (
                "SELECT patient_id, topic, awaiting_reply, expected_response_by, last_contact_at \
                 FROM patient_followups ORDER BY patient_id, topic",
                vec![],
            ),
        };
        let mut stmt = c.prepare(sql)?;
        let rows = stmt
            .query_map(rusqlite::params_from_iter(args.iter()), |r| {
                let exp: Option<String> = r.get(3)?;
                let last: Option<String> = r.get(4)?;
                let exp_d = exp.and_then(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok());
                let last_dt = last.and_then(|s| {
                    DateTime::parse_from_rfc3339(&s)
                        .ok()
                        .map(|d| d.with_timezone(&Utc))
                });
                Ok(Followup {
                    patient_id: r.get(0)?,
                    topic: r.get(1)?,
                    awaiting_reply: r.get::<_, i64>(2)? != 0,
                    expected_response_by: exp_d,
                    last_contact_at: last_dt,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn overdue_followups(&self, today: NaiveDate) -> Result<Vec<Followup>> {
        let all = self.list_followups(None)?;
        Ok(all.into_iter().filter(|f| f.overdue(today)).collect())
    }
}

pub fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("patient_comms.db")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make() -> (TempDir, CommsStore) {
        let tmp = TempDir::new().unwrap();
        let store = CommsStore::new(tmp.path().join("test.db")).unwrap();
        (tmp, store)
    }

    #[test]
    fn record_and_read_message() {
        let (_d, s) = make();
        let id = s
            .record_message("Feradze_Maia_1981_12_20", "whatsapp", "in", "когда повтор анализа?",
                            Utc::now())
            .unwrap();
        assert!(id > 0);
        let msgs = s.last_messages("Feradze_Maia_1981_12_20", 10).unwrap();
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0].body, "когда повтор анализа?");
        assert_eq!(msgs[0].direction, "in");
    }

    #[test]
    fn invalid_direction_rejected() {
        let (_d, s) = make();
        let err = s
            .record_message("X", "whatsapp", "sideways", "...", Utc::now())
            .unwrap_err();
        assert!(matches!(err, CommsError::Invalid(_)));
    }

    #[test]
    fn last_contact_returns_latest() {
        let (_d, s) = make();
        let early = Utc::now() - chrono::Duration::days(3);
        let late = Utc::now() - chrono::Duration::hours(1);
        s.record_message("X", "sms", "in", "ping1", early).unwrap();
        s.record_message("X", "sms", "in", "ping2", late).unwrap();
        let lc = s.last_contact("X").unwrap().unwrap();
        // Allow some tolerance for serialization round-trip
        assert!((lc - late).num_seconds().abs() <= 1);
    }

    #[test]
    fn upsert_and_close_followup() {
        let (_d, s) = make();
        s.upsert_followup("X", "lab K+", Some(NaiveDate::from_ymd_opt(2026, 5, 13).unwrap()))
            .unwrap();
        let list = s.list_followups(Some("X")).unwrap();
        assert_eq!(list.len(), 1);
        assert!(list[0].awaiting_reply);

        s.close_followup("X", "lab K+").unwrap();
        let list = s.list_followups(Some("X")).unwrap();
        assert!(!list[0].awaiting_reply);
    }

    #[test]
    fn upsert_idempotent() {
        let (_d, s) = make();
        s.upsert_followup("X", "lab K+", Some(NaiveDate::from_ymd_opt(2026, 5, 13).unwrap()))
            .unwrap();
        s.upsert_followup("X", "lab K+", Some(NaiveDate::from_ymd_opt(2026, 5, 20).unwrap()))
            .unwrap();
        let list = s.list_followups(Some("X")).unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(
            list[0].expected_response_by,
            NaiveDate::from_ymd_opt(2026, 5, 20)
        );
    }

    #[test]
    fn overdue_filter() {
        let (_d, s) = make();
        let today = NaiveDate::from_ymd_opt(2026, 5, 6).unwrap();
        s.upsert_followup("X", "old", Some(NaiveDate::from_ymd_opt(2026, 4, 1).unwrap()))
            .unwrap();
        s.upsert_followup("X", "future", Some(NaiveDate::from_ymd_opt(2026, 6, 1).unwrap()))
            .unwrap();
        let overdue = s.overdue_followups(today).unwrap();
        assert_eq!(overdue.len(), 1);
        assert_eq!(overdue[0].topic, "old");
    }

    #[test]
    fn list_followups_all_no_filter() {
        let (_d, s) = make();
        s.upsert_followup("A", "x", None).unwrap();
        s.upsert_followup("B", "y", None).unwrap();
        let all = s.list_followups(None).unwrap();
        assert_eq!(all.len(), 2);
    }

    #[test]
    fn last_contact_none_for_unknown() {
        let (_d, s) = make();
        assert!(s.last_contact("ghost").unwrap().is_none());
    }

    #[test]
    fn message_count_pagination() {
        let (_d, s) = make();
        for i in 0..5 {
            s.record_message("X", "sms", "in", &format!("msg{i}"),
                             Utc::now() + chrono::Duration::seconds(i)).unwrap();
        }
        let limited = s.last_messages("X", 3).unwrap();
        assert_eq!(limited.len(), 3);
    }

    #[test]
    fn isolated_per_patient_id() {
        let (_d, s) = make();
        s.record_message("A", "sms", "in", "for A", Utc::now()).unwrap();
        s.record_message("B", "sms", "in", "for B", Utc::now()).unwrap();
        let a = s.last_messages("A", 10).unwrap();
        assert_eq!(a.len(), 1);
        assert_eq!(a[0].patient_id, "A");
    }
}
