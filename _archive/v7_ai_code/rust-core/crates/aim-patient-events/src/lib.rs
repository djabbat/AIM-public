//! aim-patient-events — append-only timeline log per patient.
//!
//! Per "patient-as-project" rule (`feedback_project_core`): each patient
//! folder gets a `_events.jsonl` file alongside MEMORY.md. Each line is
//! one JSON-encoded `Event`. Strict append-only — entries are never
//! mutated; corrections add a new entry of `kind: correction` referring
//! to the original by `id`.
//!
//! Event kinds: complaint, diagnosis, lab, treatment, allergy_reported,
//! visit, note, correction. Custom kinds can be passed as free-text;
//! the `EventKind` enum has a `Custom` variant for extensibility.
//!
//! Usage from a Phoenix LiveView (or any caller): subprocess to the
//! `aim-patient-events` CLI binary. No HTTP; the file is the source of
//! truth.

use std::path::PathBuf;

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum EventsError {
    #[error("patient root does not exist: {0}")]
    RootMissing(PathBuf),
    #[error("patient folder not found: {0}")]
    PatientNotFound(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    Complaint,
    Diagnosis,
    Lab,
    Treatment,
    AllergyReported,
    Visit,
    Note,
    Correction,
    #[serde(untagged)]
    Custom(String),
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventSource {
    Manual,
    Ocr,
    Agent,
    Pam,
    Doctor,
    Codesign,
    Kernel,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    /// Stable identifier, generated as `<event_date>_<idx>` on first append.
    pub id: String,
    /// Logical date this event refers to (might be in the past — historic
    /// complaint, prior diagnosis). ISO-8601 (YYYY-MM-DD).
    pub event_date: NaiveDate,
    /// Wall-clock timestamp of the append (audit; never edited).
    pub recorded_at: DateTime<Utc>,
    pub kind: EventKind,
    /// Free-text description (clinician note, parsed lab summary, etc.).
    pub description: String,
    /// Where the entry came from. Default `manual` for clinician input.
    pub source: EventSource,
    /// Optional structured payload (e.g. `{"drug":"ibuprofen","dose":"200mg"}`
    /// for `treatment`; `{"icd10":"F41.1"}` for `diagnosis`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payload: Option<serde_json::Value>,
    /// For `correction` kind: id of the event being corrected.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub corrects_id: Option<String>,
}

impl Event {
    pub fn new(
        event_date: NaiveDate,
        kind: EventKind,
        description: impl Into<String>,
        source: EventSource,
    ) -> Self {
        Self {
            id: String::new(), // populated on append
            event_date,
            recorded_at: Utc::now(),
            kind,
            description: description.into(),
            source,
            payload: None,
            corrects_id: None,
        }
    }

    pub fn with_payload(mut self, payload: serde_json::Value) -> Self {
        self.payload = Some(payload);
        self
    }

    pub fn correcting(mut self, original_id: impl Into<String>) -> Self {
        self.kind = EventKind::Correction;
        self.corrects_id = Some(original_id.into());
        self
    }
}

// ── store ────────────────────────────────────────────────────────────────

pub struct EventStore {
    patients_root: PathBuf,
}

impl EventStore {
    pub fn new(patients_root: impl Into<PathBuf>) -> Self {
        Self {
            patients_root: patients_root.into(),
        }
    }

    pub fn from_env() -> Self {
        let root = std::env::var("AIM_PATIENTS_DIR")
            .ok()
            .map(|s| {
                let s = s.trim();
                if let Some(rest) = s.strip_prefix("~/") {
                    let home =
                        std::env::var("HOME").unwrap_or_else(|_| ".".into());
                    PathBuf::from(home).join(rest)
                } else {
                    PathBuf::from(s)
                }
            })
            .unwrap_or_else(|| PathBuf::from("Patients"));
        Self::new(root)
    }

    pub fn patient_dir(&self, id: &str) -> PathBuf {
        self.patients_root.join(id)
    }

    pub fn events_path(&self, id: &str) -> PathBuf {
        self.patient_dir(id).join("_events.jsonl")
    }

    /// Read all events. Empty if the file doesn't exist yet (new patient).
    pub fn read_all(&self, id: &str) -> Result<Vec<Event>, EventsError> {
        if !self.patient_dir(id).is_dir() {
            return Err(EventsError::PatientNotFound(id.into()));
        }
        let path = self.events_path(id);
        if !path.exists() {
            return Ok(Vec::new());
        }
        let text = std::fs::read_to_string(&path)?;
        let mut out = Vec::new();
        for (n, line) in text.lines().enumerate() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            match serde_json::from_str::<Event>(trimmed) {
                Ok(e) => out.push(e),
                Err(e) => {
                    eprintln!(
                        "warning: events.jsonl line {} of {}: {}",
                        n + 1,
                        path.display(),
                        e
                    );
                }
            }
        }
        Ok(out)
    }

    /// Append one event. Generates `id` from `<event_date>_<seq>` where
    /// `seq` is the count of events with the same `event_date` already
    /// in the file (so id is stable across replays).
    pub fn append(&self, id: &str, mut event: Event) -> Result<Event, EventsError> {
        if !self.patient_dir(id).is_dir() {
            return Err(EventsError::PatientNotFound(id.into()));
        }

        let existing = self.read_all(id)?;
        let same_day_count = existing
            .iter()
            .filter(|e| e.event_date == event.event_date)
            .count();
        event.id = format!("{}_{}", event.event_date, same_day_count);

        if event.recorded_at.timestamp() == 0 {
            event.recorded_at = Utc::now();
        }

        let path = self.events_path(id);
        let line = format!("{}\n", serde_json::to_string(&event)?);

        use std::io::Write;
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)?;
        f.write_all(line.as_bytes())?;
        f.sync_data()?;
        Ok(event)
    }

    /// Read events filtered by kind (returns full event records).
    pub fn read_kind(
        &self,
        id: &str,
        kind: &EventKind,
    ) -> Result<Vec<Event>, EventsError> {
        Ok(self
            .read_all(id)?
            .into_iter()
            .filter(|e| event_kind_matches(&e.kind, kind))
            .collect())
    }

    /// Read events sorted by `event_date` desc (newest first); returns
    /// up to `limit` items.
    pub fn timeline(&self, id: &str, limit: usize) -> Result<Vec<Event>, EventsError> {
        let mut all = self.read_all(id)?;
        all.sort_by(|a, b| {
            b.event_date
                .cmp(&a.event_date)
                .then(b.recorded_at.cmp(&a.recorded_at))
        });
        all.truncate(limit.max(0));
        Ok(all)
    }

    pub fn count(&self, id: &str) -> Result<usize, EventsError> {
        Ok(self.read_all(id)?.len())
    }
}

fn event_kind_matches(a: &EventKind, b: &EventKind) -> bool {
    match (a, b) {
        (EventKind::Custom(x), EventKind::Custom(y)) => x == y,
        (x, y) => std::mem::discriminant(x) == std::mem::discriminant(y),
    }
}

// ── tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn setup() -> (TempDir, EventStore, String) {
        let tmp = TempDir::new().unwrap();
        let pid = "Smith_John_1980_05_15".to_string();
        let pdir = tmp.path().join(&pid);
        std::fs::create_dir_all(&pdir).unwrap();
        // Place a fake MEMORY.md so EventStore is happy.
        std::fs::write(pdir.join("MEMORY.md"), "# memory\n").unwrap();
        let store = EventStore::new(tmp.path());
        (tmp, store, pid)
    }

    #[test]
    fn append_and_read_one() {
        let (_tmp, store, pid) = setup();
        let e = Event::new(
            NaiveDate::from_ymd_opt(2026, 5, 7).unwrap(),
            EventKind::Complaint,
            "Headache 3 days",
            EventSource::Manual,
        );
        let saved = store.append(&pid, e).unwrap();
        assert_eq!(saved.id, "2026-05-07_0");

        let all = store.read_all(&pid).unwrap();
        assert_eq!(all.len(), 1);
        assert_eq!(all[0].description, "Headache 3 days");
    }

    #[test]
    fn id_increments_within_same_day() {
        let (_tmp, store, pid) = setup();
        let date = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let a = store
            .append(
                &pid,
                Event::new(date, EventKind::Complaint, "first", EventSource::Manual),
            )
            .unwrap();
        let b = store
            .append(
                &pid,
                Event::new(date, EventKind::Note, "second", EventSource::Manual),
            )
            .unwrap();
        assert_eq!(a.id, "2026-05-07_0");
        assert_eq!(b.id, "2026-05-07_1");
    }

    #[test]
    fn timeline_sorts_desc() {
        let (_tmp, store, pid) = setup();
        let e1 = Event::new(
            NaiveDate::from_ymd_opt(2024, 1, 15).unwrap(),
            EventKind::Diagnosis,
            "old",
            EventSource::Doctor,
        );
        let e2 = Event::new(
            NaiveDate::from_ymd_opt(2026, 5, 7).unwrap(),
            EventKind::Visit,
            "new",
            EventSource::Manual,
        );
        store.append(&pid, e1).unwrap();
        store.append(&pid, e2).unwrap();
        let line = store.timeline(&pid, 10).unwrap();
        assert_eq!(line[0].description, "new");
        assert_eq!(line[1].description, "old");
    }

    #[test]
    fn read_kind_filters() {
        let (_tmp, store, pid) = setup();
        let date = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        store
            .append(
                &pid,
                Event::new(date, EventKind::Complaint, "a", EventSource::Manual),
            )
            .unwrap();
        store
            .append(
                &pid,
                Event::new(date, EventKind::Lab, "b", EventSource::Ocr),
            )
            .unwrap();
        store
            .append(
                &pid,
                Event::new(date, EventKind::Lab, "c", EventSource::Ocr),
            )
            .unwrap();

        let labs = store.read_kind(&pid, &EventKind::Lab).unwrap();
        assert_eq!(labs.len(), 2);
        let comp = store.read_kind(&pid, &EventKind::Complaint).unwrap();
        assert_eq!(comp.len(), 1);
    }

    #[test]
    fn correction_carries_corrects_id() {
        let (_tmp, store, pid) = setup();
        let date = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let original = store
            .append(
                &pid,
                Event::new(date, EventKind::Complaint, "wrong", EventSource::Manual),
            )
            .unwrap();
        let correction = Event::new(
            date,
            EventKind::Correction,
            "right",
            EventSource::Manual,
        )
        .correcting(original.id.clone());
        let saved = store.append(&pid, correction).unwrap();
        assert_eq!(saved.corrects_id.as_deref(), Some(original.id.as_str()));
    }

    #[test]
    fn payload_round_trips() {
        let (_tmp, store, pid) = setup();
        let date = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let e = Event::new(date, EventKind::Treatment, "ibu started", EventSource::Doctor)
            .with_payload(serde_json::json!({"drug":"ibuprofen","dose":"200mg"}));
        store.append(&pid, e).unwrap();
        let all = store.read_all(&pid).unwrap();
        assert_eq!(
            all[0]
                .payload
                .as_ref()
                .and_then(|v| v.get("drug"))
                .and_then(|v| v.as_str()),
            Some("ibuprofen")
        );
    }

    #[test]
    fn read_all_empty_when_no_file() {
        let (_tmp, store, pid) = setup();
        let all = store.read_all(&pid).unwrap();
        assert!(all.is_empty());
        assert_eq!(store.count(&pid).unwrap(), 0);
    }

    #[test]
    fn read_all_ignores_blank_lines() {
        let (_tmp, store, pid) = setup();
        let path = store.events_path(&pid);
        std::fs::write(
            &path,
            "{\"id\":\"x\",\"event_date\":\"2026-01-01\",\"recorded_at\":\"2026-01-01T00:00:00Z\",\"kind\":\"note\",\"description\":\"a\",\"source\":\"manual\"}\n\n   \n{\"id\":\"y\",\"event_date\":\"2026-02-01\",\"recorded_at\":\"2026-02-01T00:00:00Z\",\"kind\":\"note\",\"description\":\"b\",\"source\":\"manual\"}\n",
        )
        .unwrap();
        let all = store.read_all(&pid).unwrap();
        assert_eq!(all.len(), 2);
    }

    #[test]
    fn append_to_unknown_patient_errors() {
        let tmp = TempDir::new().unwrap();
        let store = EventStore::new(tmp.path());
        let r = store.append(
            "ghost",
            Event::new(
                NaiveDate::from_ymd_opt(2026, 5, 7).unwrap(),
                EventKind::Note,
                "oops",
                EventSource::Manual,
            ),
        );
        assert!(matches!(r, Err(EventsError::PatientNotFound(_))));
    }
}
