//! aim-experiment-state-machine — robotic / instrumented experiment phases (Phase B, 2026-05-06).
//!
//! Sister crate to `aim-project-state-machine` and
//! `aim-patient-state-machine`. Models the lifecycle of a hardware-on-loop
//! experiment (AutomatedMicroscopy, PhD/E0, etc.) where AIM is
//! mission-control and Claude Code (or another agent) drives the rig.
//!
//! ## Phases
//!
//! ```text
//! COMMISSIONING    — hardware assembly, firmware install, integration
//! CALIBRATING      — pre-run calibration cycles, sensor zero, alignment
//! RUNNING          — live data collection, AI making routine decisions
//! DATA_PROCESSING  — run finished; analysis / QA / dataset packaging
//! REPORTED         — preprint / paper / dataset published
//! ARCHIVED         — closed; rig may be reused for next experiment
//! ```
//!
//! ## Allowed graph
//!
//! ```text
//! COMMISSIONING   → CALIBRATING, ARCHIVED
//! CALIBRATING     → COMMISSIONING (regression), RUNNING, ARCHIVED
//! RUNNING         → DATA_PROCESSING, CALIBRATING (recalibrate), ARCHIVED
//! DATA_PROCESSING → REPORTED, RUNNING (more data needed), ARCHIVED
//! REPORTED        → ARCHIVED
//! ARCHIVED        → (terminal)
//! ```

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum StateError {
    #[error("unknown phase: {0:?}")]
    UnknownPhase(String),
    #[error("illegal transition {src:?} → {dst:?}; legal: {legal:?}")]
    IllegalTransition {
        src: Phase,
        dst: Phase,
        legal: Vec<Phase>,
    },
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Hash)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Phase {
    Commissioning,
    Calibrating,
    Running,
    DataProcessing,
    Reported,
    Archived,
}

impl Phase {
    pub fn as_str(self) -> &'static str {
        match self {
            Phase::Commissioning => "COMMISSIONING",
            Phase::Calibrating => "CALIBRATING",
            Phase::Running => "RUNNING",
            Phase::DataProcessing => "DATA_PROCESSING",
            Phase::Reported => "REPORTED",
            Phase::Archived => "ARCHIVED",
        }
    }

    pub fn parse(s: &str) -> Result<Self, StateError> {
        match s.trim().to_uppercase().as_str() {
            "COMMISSIONING" => Ok(Phase::Commissioning),
            "CALIBRATING" => Ok(Phase::Calibrating),
            "RUNNING" => Ok(Phase::Running),
            "DATA_PROCESSING" | "DATAPROCESSING" => Ok(Phase::DataProcessing),
            "REPORTED" => Ok(Phase::Reported),
            "ARCHIVED" => Ok(Phase::Archived),
            _ => Err(StateError::UnknownPhase(s.to_string())),
        }
    }

    pub fn all() -> &'static [Phase] {
        &[
            Phase::Commissioning,
            Phase::Calibrating,
            Phase::Running,
            Phase::DataProcessing,
            Phase::Reported,
            Phase::Archived,
        ]
    }
}

pub fn legal_moves(src: Phase) -> Vec<Phase> {
    let mut out: Vec<Phase> = match src {
        Phase::Commissioning => vec![Phase::Calibrating, Phase::Archived],
        Phase::Calibrating => vec![Phase::Commissioning, Phase::Running, Phase::Archived],
        Phase::Running => vec![Phase::DataProcessing, Phase::Calibrating, Phase::Archived],
        Phase::DataProcessing => vec![Phase::Reported, Phase::Running, Phase::Archived],
        Phase::Reported => vec![Phase::Archived],
        Phase::Archived => vec![],
    };
    out.sort_by_key(|p| p.as_str());
    out
}

pub fn is_legal(src: Phase, dst: Phase) -> bool {
    legal_moves(src).contains(&dst)
}

pub fn next_actions(phase: Phase) -> Vec<&'static str> {
    match phase {
        Phase::Commissioning => vec![
            "Hardware ordering / receipt checklist",
            "Firmware flash + bench tests (interlock, sensors)",
            "When integration smoke tests pass — переход в CALIBRATING",
        ],
        Phase::Calibrating => vec![
            "Запустить calibration cycles (alignment, sensor zero, ROI)",
            "Verify reproducibility ≥ N циклов одинаковых",
            "При успехе — RUNNING; при regression — обратно в COMMISSIONING",
        ],
        Phase::Running => vec![
            "Контролировать journal NDJSON: uptime, decisions/h, contamination",
            "Эскалейтить human при out-of-policy decision требованиях",
            "При завершении планируемого периода — DATA_PROCESSING",
        ],
        Phase::DataProcessing => vec![
            "Архивирование raw data (NAS / S3)",
            "QA + аналитический pipeline (figures, stats)",
            "При готовности к публикации — REPORTED; иначе RUNNING для дополнительных данных",
        ],
        Phase::Reported => vec![
            "Депозит preprint / dataset (Zenodo / OSF)",
            "Notify co-PI + community",
            "Перевести в ARCHIVED после завершения follow-up",
        ],
        Phase::Archived => vec![
            "(experiment closed — rig может быть переиспользован для нового эксперимента)",
        ],
    }
}

// ── audit ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditRecord {
    pub ts: String,
    pub experiment: String,
    pub from: String,
    pub to: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default = "default_actor")]
    pub actor: String,
}

fn default_actor() -> String {
    "human".into()
}

pub fn default_audit_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("experiment_phase_history.jsonl")
}

pub struct StateMachine {
    audit_path: PathBuf,
}

impl StateMachine {
    pub fn new(audit_path: impl Into<PathBuf>) -> Self {
        Self {
            audit_path: audit_path.into(),
        }
    }

    pub fn from_env() -> Self {
        Self::new(default_audit_path())
    }

    pub fn audit_path(&self) -> &std::path::Path {
        &self.audit_path
    }

    pub fn transition(
        &self,
        experiment: &str,
        src: Phase,
        dst: Phase,
        reason: &str,
        actor: &str,
    ) -> Result<AuditRecord, StateError> {
        if !is_legal(src, dst) {
            return Err(StateError::IllegalTransition {
                src,
                dst,
                legal: legal_moves(src),
            });
        }
        let record = AuditRecord {
            ts: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            experiment: experiment.to_string(),
            from: src.as_str().into(),
            to: dst.as_str().into(),
            reason: reason.to_string(),
            actor: actor.to_string(),
        };
        self.audit_append(&record)?;
        Ok(record)
    }

    fn audit_append(&self, record: &AuditRecord) -> Result<(), StateError> {
        if let Some(parent) = self.audit_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let line = serde_json::to_string(record)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.audit_path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    pub fn history(
        &self,
        experiment: Option<&str>,
    ) -> Result<Vec<AuditRecord>, StateError> {
        if !self.audit_path.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(&self.audit_path)?;
        let mut out = Vec::new();
        for line in raw.lines() {
            if line.trim().is_empty() {
                continue;
            }
            let row: AuditRecord = match serde_json::from_str(line) {
                Ok(r) => r,
                Err(_) => continue,
            };
            if let Some(p) = experiment {
                if row.experiment != p {
                    continue;
                }
            }
            out.push(row);
        }
        Ok(out)
    }

    pub fn phase_advisory(&self, phase: Phase) -> String {
        let actions = next_actions(phase);
        if actions.is_empty() {
            return format!("phase: {} — no actions", phase.as_str());
        }
        let mut out = vec![format!("📐 phase {} — next actions:", phase.as_str())];
        for a in actions {
            out.push(format!("  • {a}"));
        }
        out.join("\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make() -> (TempDir, StateMachine) {
        let dir = TempDir::new().unwrap();
        let audit = dir.path().join("exp_phase.jsonl");
        let sm = StateMachine::new(audit);
        (dir, sm)
    }

    #[test]
    fn phase_parse_roundtrip() {
        for &p in Phase::all() {
            let s = p.as_str();
            assert_eq!(Phase::parse(s).unwrap(), p);
        }
    }

    #[test]
    fn data_processing_alias() {
        assert_eq!(Phase::parse("DataProcessing").unwrap(), Phase::DataProcessing);
        assert_eq!(Phase::parse("DATA_PROCESSING").unwrap(), Phase::DataProcessing);
    }

    #[test]
    fn commissioning_to_running_blocked() {
        // Must go via CALIBRATING
        assert!(!is_legal(Phase::Commissioning, Phase::Running));
        assert!(is_legal(Phase::Commissioning, Phase::Calibrating));
        assert!(is_legal(Phase::Calibrating, Phase::Running));
    }

    #[test]
    fn running_can_recalibrate() {
        assert!(is_legal(Phase::Running, Phase::Calibrating));
    }

    #[test]
    fn data_processing_can_run_again_for_more_data() {
        assert!(is_legal(Phase::DataProcessing, Phase::Running));
    }

    #[test]
    fn archived_terminal() {
        assert!(legal_moves(Phase::Archived).is_empty());
    }

    #[test]
    fn next_actions_per_phase_nonempty() {
        for &p in Phase::all() {
            assert!(!next_actions(p).is_empty());
        }
    }

    #[test]
    fn lifecycle_from_commissioning_to_reported() {
        let (_d, sm) = make();
        let n = "E0";
        sm.transition(n, Phase::Commissioning, Phase::Calibrating, "", "t").unwrap();
        sm.transition(n, Phase::Calibrating, Phase::Running, "", "t").unwrap();
        sm.transition(n, Phase::Running, Phase::DataProcessing, "", "t").unwrap();
        sm.transition(n, Phase::DataProcessing, Phase::Reported, "", "t").unwrap();
        sm.transition(n, Phase::Reported, Phase::Archived, "", "t").unwrap();
        let h = sm.history(Some(n)).unwrap();
        assert_eq!(h.len(), 5);
        assert_eq!(h.last().unwrap().to, "ARCHIVED");
    }

    #[test]
    fn transition_rejects_illegal() {
        let (_d, sm) = make();
        let err = sm
            .transition("X", Phase::Commissioning, Phase::Running, "", "t")
            .unwrap_err();
        assert!(matches!(err, StateError::IllegalTransition { .. }));
    }

    #[test]
    fn phase_advisory_renders() {
        let (_d, sm) = make();
        let s = sm.phase_advisory(Phase::Running);
        assert!(s.contains("RUNNING"));
        assert!(s.contains("•"));
    }
}
