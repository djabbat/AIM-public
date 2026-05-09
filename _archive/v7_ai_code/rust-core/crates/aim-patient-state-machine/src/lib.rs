//! aim-patient-state-machine — patient phase transitions (Phase A, 2026-05-06).
//!
//! Mirror to `aim-project-state-machine`, with clinical phase vocabulary:
//!
//! ```text
//! INTAKE              — first contact, demographics + chief complaint
//! DIAGNOSTIC_WORKUP   — labs / imaging / examinations being collected
//! ACTIVE_TREATMENT    — intervention in progress (drugs / procedure)
//! MONITORING          — post-intervention observation, periodic checks
//! STABLE              — no active intervention, periodic surveillance
//! CLOSED              — episode ended (discharged / transfer / loss)
//! ```
//!
//! ## Allowed graph
//!
//! ```text
//! INTAKE             → DIAGNOSTIC_WORKUP, MONITORING, CLOSED
//! DIAGNOSTIC_WORKUP  → ACTIVE_TREATMENT, MONITORING, CLOSED
//! ACTIVE_TREATMENT   → MONITORING, CLOSED
//! MONITORING         → ACTIVE_TREATMENT, STABLE, CLOSED
//! STABLE             → MONITORING (relapse), CLOSED
//! CLOSED             → INTAKE (re-engagement / new episode)
//! ```
//!
//! Re-engagement: `CLOSED → INTAKE` is legal so the same patient folder
//! can host a new episode without losing history. The previous episode
//! lives in `AI_LOG.md`; phase audit accumulates in
//! `~/.cache/aim/patient_phase_history.jsonl`.

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

// ── phase enum ──────────────────────────────────────────────────────────────

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
    Intake,
    DiagnosticWorkup,
    ActiveTreatment,
    Monitoring,
    Stable,
    Closed,
}

impl Phase {
    pub fn as_str(self) -> &'static str {
        match self {
            Phase::Intake => "INTAKE",
            Phase::DiagnosticWorkup => "DIAGNOSTIC_WORKUP",
            Phase::ActiveTreatment => "ACTIVE_TREATMENT",
            Phase::Monitoring => "MONITORING",
            Phase::Stable => "STABLE",
            Phase::Closed => "CLOSED",
        }
    }

    pub fn parse(s: &str) -> Result<Self, StateError> {
        match s.trim().to_uppercase().as_str() {
            "INTAKE" => Ok(Phase::Intake),
            "DIAGNOSTIC_WORKUP" | "DIAGNOSTICWORKUP" => Ok(Phase::DiagnosticWorkup),
            "ACTIVE_TREATMENT" | "ACTIVETREATMENT" => Ok(Phase::ActiveTreatment),
            "MONITORING" => Ok(Phase::Monitoring),
            "STABLE" => Ok(Phase::Stable),
            "CLOSED" => Ok(Phase::Closed),
            _ => Err(StateError::UnknownPhase(s.to_string())),
        }
    }

    pub fn all() -> &'static [Phase] {
        &[
            Phase::Intake,
            Phase::DiagnosticWorkup,
            Phase::ActiveTreatment,
            Phase::Monitoring,
            Phase::Stable,
            Phase::Closed,
        ]
    }
}

/// Sorted vector of legal destination phases for `src`.
pub fn legal_moves(src: Phase) -> Vec<Phase> {
    let mut out: Vec<Phase> = match src {
        Phase::Intake => vec![Phase::DiagnosticWorkup, Phase::Monitoring, Phase::Closed],
        Phase::DiagnosticWorkup => {
            vec![Phase::ActiveTreatment, Phase::Monitoring, Phase::Closed]
        }
        Phase::ActiveTreatment => vec![Phase::Monitoring, Phase::Closed],
        Phase::Monitoring => vec![Phase::ActiveTreatment, Phase::Stable, Phase::Closed],
        Phase::Stable => vec![Phase::Monitoring, Phase::Closed],
        // Re-engagement: closed episode can re-open with new INTAKE
        Phase::Closed => vec![Phase::Intake],
    };
    out.sort_by_key(|p| p.as_str());
    out
}

pub fn is_legal(src: Phase, dst: Phase) -> bool {
    legal_moves(src).contains(&dst)
}

/// Per-phase next-action advice. Surfaced in `morning_brief()` as
/// "what should I do for this patient today".
pub fn next_actions(phase: Phase) -> Vec<&'static str> {
    match phase {
        Phase::Intake => vec![
            "Записать demographics + DOB + chief complaint",
            "Запросить outside records (если есть)",
            "Назначить базовую панель labs / imaging",
        ],
        Phase::DiagnosticWorkup => vec![
            "Собрать пропущенные labs / images по checklist",
            "Кросс-проверить интерпретации через kernel scoring",
            "При уточнении dx — переход в ACTIVE_TREATMENT или MONITORING",
        ],
        Phase::ActiveTreatment => vec![
            "Сверить regimen через regimen_validator (interactions, contraindications)",
            "Запланировать follow-up визит / repeat labs",
            "При завершении курса — переход в MONITORING",
        ],
        Phase::Monitoring => vec![
            "Регулярные follow-up labs по интервалу dx-specific",
            "Проверить compliance + side effects",
            "Если параметры стабильны N циклов — переход в STABLE",
        ],
        Phase::Stable => vec![
            "Annual или semi-annual surveillance labs",
            "При появлении новых симптомов / labs out of range — MONITORING (relapse)",
        ],
        Phase::Closed => vec![
            "Episode завершён. При новом обращении — переход в INTAKE.",
        ],
    }
}

// ── audit ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditRecord {
    pub ts: String,
    pub patient_id: String,
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

/// Default audit log path: `$AIM_HOME/patient_phase_history.jsonl` or
/// `~/.cache/aim/patient_phase_history.jsonl`.
pub fn default_audit_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let base = std::env::var("AIM_HOME")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".cache").join("aim"));
    base.join("patient_phase_history.jsonl")
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

    /// Record a transition. Caller is expected to update the patient
    /// MEMORY.md `## Phase` section themselves (parser lives in
    /// `aim-patient-memory`); this crate only validates + audits.
    pub fn transition(
        &self,
        patient_id: &str,
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
            patient_id: patient_id.to_string(),
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
        patient_id: Option<&str>,
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
            if let Some(p) = patient_id {
                if row.patient_id != p {
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
        let audit = dir.path().join("patient_phase.jsonl");
        let sm = StateMachine::new(audit);
        (dir, sm)
    }

    // ── parsing ────────────────────────────────────────────────────────────

    #[test]
    fn phase_parse_roundtrip() {
        for &p in Phase::all() {
            let s = p.as_str();
            assert_eq!(Phase::parse(s).unwrap(), p);
            assert_eq!(Phase::parse(&s.to_lowercase()).unwrap(), p);
        }
    }

    #[test]
    fn phase_parse_aliases() {
        assert_eq!(
            Phase::parse("DiagnosticWorkup").unwrap(),
            Phase::DiagnosticWorkup
        );
        assert_eq!(
            Phase::parse("ACTIVETREATMENT").unwrap(),
            Phase::ActiveTreatment
        );
    }

    #[test]
    fn phase_parse_unknown_errors() {
        let err = Phase::parse("ZOMBIE").unwrap_err();
        assert!(matches!(err, StateError::UnknownPhase(_)));
    }

    // ── transition graph ──────────────────────────────────────────────────

    #[test]
    fn intake_legal_destinations() {
        let m = legal_moves(Phase::Intake);
        assert!(m.contains(&Phase::DiagnosticWorkup));
        assert!(m.contains(&Phase::Monitoring));
        assert!(m.contains(&Phase::Closed));
        assert_eq!(m.len(), 3);
    }

    #[test]
    fn closed_only_to_intake() {
        let m = legal_moves(Phase::Closed);
        assert_eq!(m, vec![Phase::Intake]);
    }

    #[test]
    fn stable_to_monitoring_relapse() {
        assert!(is_legal(Phase::Stable, Phase::Monitoring));
        // STABLE cannot leap directly to ACTIVE_TREATMENT
        assert!(!is_legal(Phase::Stable, Phase::ActiveTreatment));
    }

    #[test]
    fn intake_cannot_jump_to_active_treatment() {
        // Must go through diagnostic workup
        assert!(!is_legal(Phase::Intake, Phase::ActiveTreatment));
    }

    #[test]
    fn next_actions_per_phase_nonempty() {
        for &p in Phase::all() {
            assert!(
                !next_actions(p).is_empty(),
                "phase {:?} has no actions",
                p
            );
        }
    }

    #[test]
    fn intake_actions_mention_dob() {
        let acts = next_actions(Phase::Intake);
        assert!(acts.iter().any(|a| a.contains("DOB")));
    }

    // ── transition audit ──────────────────────────────────────────────────

    #[test]
    fn transition_writes_audit() {
        let (_d, sm) = make();
        let rec = sm
            .transition(
                "Feradze_Maia_1981_12_20",
                Phase::Intake,
                Phase::DiagnosticWorkup,
                "lab panel ordered",
                "human",
            )
            .unwrap();
        assert_eq!(rec.from, "INTAKE");
        assert_eq!(rec.to, "DIAGNOSTIC_WORKUP");
        let h = sm.history(Some("Feradze_Maia_1981_12_20")).unwrap();
        assert_eq!(h.len(), 1);
        assert_eq!(h[0].reason, "lab panel ordered");
    }

    #[test]
    fn transition_rejects_illegal() {
        let (_d, sm) = make();
        let err = sm
            .transition("X", Phase::Intake, Phase::Stable, "", "test")
            .unwrap_err();
        assert!(matches!(err, StateError::IllegalTransition { .. }));
    }

    #[test]
    fn transition_lifecycle_then_reengage() {
        let (_d, sm) = make();
        let pid = "X";
        sm.transition(pid, Phase::Intake, Phase::DiagnosticWorkup, "", "t").unwrap();
        sm.transition(pid, Phase::DiagnosticWorkup, Phase::ActiveTreatment, "", "t").unwrap();
        sm.transition(pid, Phase::ActiveTreatment, Phase::Monitoring, "", "t").unwrap();
        sm.transition(pid, Phase::Monitoring, Phase::Stable, "", "t").unwrap();
        sm.transition(pid, Phase::Stable, Phase::Closed, "", "t").unwrap();
        // Re-engagement
        sm.transition(pid, Phase::Closed, Phase::Intake, "new episode", "t").unwrap();

        let h = sm.history(Some(pid)).unwrap();
        assert_eq!(h.len(), 6);
        assert_eq!(h.last().unwrap().to, "INTAKE");
    }

    #[test]
    fn history_filters_by_patient() {
        let (_d, sm) = make();
        sm.transition("A", Phase::Intake, Phase::DiagnosticWorkup, "", "t").unwrap();
        sm.transition("B", Phase::Intake, Phase::Monitoring, "", "t").unwrap();
        let a = sm.history(Some("A")).unwrap();
        let b = sm.history(Some("B")).unwrap();
        let all = sm.history(None).unwrap();
        assert_eq!(a.len(), 1);
        assert_eq!(b.len(), 1);
        assert_eq!(all.len(), 2);
    }

    // ── advisory ──────────────────────────────────────────────────────────

    #[test]
    fn phase_advisory_renders_actions() {
        let (_d, sm) = make();
        let s = sm.phase_advisory(Phase::DiagnosticWorkup);
        assert!(s.contains("DIAGNOSTIC_WORKUP"));
        assert!(s.contains("•"));
    }
}
