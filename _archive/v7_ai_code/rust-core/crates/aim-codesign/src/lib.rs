//! aim-codesign — patient co-design event log (Fix #2, 2026-05-07).
//!
//! Records discrete co-design events per the "Patient as a Project"
//! cornerstone: the patient was consulted, agreed, modified, refused, or
//! suggested an alternative. Persisted as JSONL in
//! `Patients/<id>/_codesign.jsonl` so it survives across sessions and is
//! human-greppable.
//!
//! `mark_codesigned(patient_id, decision_id)` is the sentinel the kernel
//! reads: returns `true` iff there is at least one `agreed` or `modified`
//! event for that decision id. Wire that into the `L_AGENCY` caller as:
//!     context.patient_codesigned = mark_codesigned(...)

use chrono::{DateTime, Local};
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CodesignError {
    #[error("unknown event kind {0:?}; expected consulted | agreed | modified | refused | alternative")]
    UnknownKind(String),
    #[error("`by` must be 'patient' or 'caregiver', got {0:?}")]
    InvalidBy(String),
    #[error("patient directory missing: {0}")]
    PatientDirMissing(PathBuf),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Consulted,
    Agreed,
    Modified,
    Refused,
    Alternative,
}

impl Kind {
    pub fn parse(s: &str) -> Result<Self, CodesignError> {
        Ok(match s {
            "consulted" => Kind::Consulted,
            "agreed" => Kind::Agreed,
            "modified" => Kind::Modified,
            "refused" => Kind::Refused,
            "alternative" => Kind::Alternative,
            _ => return Err(CodesignError::UnknownKind(s.into())),
        })
    }

    pub fn is_codesigned(&self) -> bool {
        matches!(self, Kind::Agreed | Kind::Modified)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum By {
    Patient,
    Caregiver,
}

impl By {
    pub fn parse(s: &str) -> Result<Self, CodesignError> {
        Ok(match s {
            "patient" => By::Patient,
            "caregiver" => By::Caregiver,
            _ => return Err(CodesignError::InvalidBy(s.into())),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Event {
    pub ts: DateTime<Local>,
    pub kind: Kind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decision_id: Option<String>,
    pub topic: String,
    pub by: By,
    #[serde(default)]
    pub notes: String,
}

fn log_path(patients_dir: &Path, patient_id: &str) -> PathBuf {
    patients_dir.join(patient_id).join("_codesign.jsonl")
}

pub fn record(
    patients_dir: &Path,
    patient_id: &str,
    kind: Kind,
    topic: &str,
    decision_id: Option<&str>,
    by: By,
    notes: &str,
) -> Result<Event, CodesignError> {
    let pdir = patients_dir.join(patient_id);
    if !pdir.exists() {
        return Err(CodesignError::PatientDirMissing(pdir));
    }
    let event = Event {
        ts: Local::now(),
        kind,
        decision_id: decision_id.map(String::from),
        topic: topic.into(),
        by,
        notes: notes.into(),
    };
    let p = log_path(patients_dir, patient_id);
    let mut f = OpenOptions::new().create(true).append(true).open(&p)?;
    writeln!(f, "{}", serde_json::to_string(&event)?)?;
    Ok(event)
}

pub fn events(patients_dir: &Path, patient_id: &str) -> Result<Vec<Event>, CodesignError> {
    let p = log_path(patients_dir, patient_id);
    if !p.exists() {
        return Ok(Vec::new());
    }
    let f = std::fs::File::open(&p)?;
    let mut out = Vec::new();
    for line in BufReader::new(f).lines() {
        let line = line?;
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if let Ok(e) = serde_json::from_str::<Event>(line) {
            out.push(e);
        }
    }
    Ok(out)
}

pub fn mark_codesigned(
    patients_dir: &Path,
    patient_id: &str,
    decision_id: &str,
) -> Result<bool, CodesignError> {
    Ok(events(patients_dir, patient_id)?.iter().any(|e| {
        e.decision_id.as_deref() == Some(decision_id) && e.kind.is_codesigned()
    }))
}

pub fn filter_by_kind(
    patients_dir: &Path,
    patient_id: &str,
    kinds: &[Kind],
) -> Result<Vec<Event>, CodesignError> {
    Ok(events(patients_dir, patient_id)?
        .into_iter()
        .filter(|e| kinds.contains(&e.kind))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn setup() -> (TempDir, PathBuf) {
        let tmp = TempDir::new().unwrap();
        let pid = "TEST_Smith_2000_01_01";
        let pdir = tmp.path().join(pid);
        std::fs::create_dir_all(&pdir).unwrap();
        (tmp, pdir)
    }

    #[test]
    fn record_appends_jsonl() {
        let (tmp, _) = setup();
        let pid = "TEST_Smith_2000_01_01";
        let e = record(tmp.path(), pid, Kind::Agreed, "ACEi for HTN",
                       Some("rx-001"), By::Patient, "").unwrap();
        assert_eq!(e.kind, Kind::Agreed);
        let log_p = tmp.path().join(pid).join("_codesign.jsonl");
        let content = std::fs::read_to_string(log_p).unwrap();
        assert!(content.contains("\"agreed\""));
        assert!(content.contains("rx-001"));
    }

    #[test]
    fn rejects_missing_patient_dir() {
        let tmp = TempDir::new().unwrap();
        let err = record(tmp.path(), "MISSING", Kind::Consulted, "x",
                         None, By::Patient, "").unwrap_err();
        assert!(matches!(err, CodesignError::PatientDirMissing(_)));
    }

    #[test]
    fn mark_codesigned_only_for_agreed_modified() {
        let (tmp, _) = setup();
        let pid = "TEST_Smith_2000_01_01";
        record(tmp.path(), pid, Kind::Consulted, "review", Some("d1"),
               By::Patient, "").unwrap();
        record(tmp.path(), pid, Kind::Modified, "halve dose", Some("d1"),
               By::Patient, "").unwrap();
        record(tmp.path(), pid, Kind::Refused, "second-line", Some("d2"),
               By::Patient, "").unwrap();
        assert!(mark_codesigned(tmp.path(), pid, "d1").unwrap());
        assert!(!mark_codesigned(tmp.path(), pid, "d2").unwrap());
        assert!(!mark_codesigned(tmp.path(), pid, "d3").unwrap());
    }

    #[test]
    fn filter_by_kind_works() {
        let (tmp, _) = setup();
        let pid = "TEST_Smith_2000_01_01";
        record(tmp.path(), pid, Kind::Consulted, "a", None, By::Patient, "").unwrap();
        record(tmp.path(), pid, Kind::Refused, "b", None, By::Patient, "").unwrap();
        record(tmp.path(), pid, Kind::Refused, "c", None, By::Patient, "").unwrap();
        let r = filter_by_kind(tmp.path(), pid, &[Kind::Refused]).unwrap();
        assert_eq!(r.len(), 2);
    }

    #[test]
    fn empty_log_returns_empty_events() {
        let (tmp, _) = setup();
        let r = events(tmp.path(), "TEST_Smith_2000_01_01").unwrap();
        assert!(r.is_empty());
    }

    #[test]
    fn unknown_kind_rejected() {
        let err = Kind::parse("hugged").unwrap_err();
        assert!(matches!(err, CodesignError::UnknownKind(_)));
    }
}
