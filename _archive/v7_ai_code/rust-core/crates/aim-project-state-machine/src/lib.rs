//! aim-project-state-machine — phase transitions (P5).
//!
//! Port of `agents/project_state_machine.py`. Each project YAML carries a
//! `phase`. This crate formalises the legal transitions, suggests next
//! concrete actions for the current phase, and logs every transition into
//! a JSONL audit so we can replay the project's life-cycle later.
//!
//! ## Phases
//! - `DRAFT` — initial conception / writing
//! - `REVIEW` — internal peer review (FCLC v10-style)
//! - `SUBMITTED` — awaiting external decision (eLife / Nature / EIC)
//! - `ACCEPTED` — accepted but not yet public
//! - `PUBLISHED` — public / DOI minted / funded
//! - `REJECTED` — terminal failure; can fork into a new DRAFT
//! - `ARCHIVED` — no longer active
//!
//! ## Allowed graph
//!
//! ```text
//! DRAFT     → REVIEW, SUBMITTED, ARCHIVED
//! REVIEW    → DRAFT, SUBMITTED, ARCHIVED
//! SUBMITTED → ACCEPTED, REJECTED, REVIEW (revisions), ARCHIVED
//! ACCEPTED  → PUBLISHED, ARCHIVED
//! PUBLISHED → ARCHIVED
//! REJECTED  → DRAFT, ARCHIVED
//! ARCHIVED  → (terminal)
//! ```
//!
//! ## Public API
//! - [`Phase`] enum + parse/as_str
//! - [`is_legal`] / [`legal_moves`]
//! - [`next_actions`]
//! - [`phase_advisory`]
//! - [`StateMachine::transition`] + [`StateMachine::history`]

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
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
    #[error("project YAML missing for {0:?}")]
    NoProject(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("project owner: {0}")]
    Owner(#[from] aim_project_owner::ProjectError),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Phase {
    Draft,
    Review,
    Submitted,
    Accepted,
    Published,
    Rejected,
    Archived,
}

impl Phase {
    pub fn as_str(self) -> &'static str {
        match self {
            Phase::Draft => "DRAFT",
            Phase::Review => "REVIEW",
            Phase::Submitted => "SUBMITTED",
            Phase::Accepted => "ACCEPTED",
            Phase::Published => "PUBLISHED",
            Phase::Rejected => "REJECTED",
            Phase::Archived => "ARCHIVED",
        }
    }

    pub fn parse(s: &str) -> Result<Self, StateError> {
        match s.to_uppercase().as_str() {
            "DRAFT" => Ok(Phase::Draft),
            "REVIEW" => Ok(Phase::Review),
            "SUBMITTED" => Ok(Phase::Submitted),
            "ACCEPTED" => Ok(Phase::Accepted),
            "PUBLISHED" => Ok(Phase::Published),
            "REJECTED" => Ok(Phase::Rejected),
            "ARCHIVED" => Ok(Phase::Archived),
            _ => Err(StateError::UnknownPhase(s.to_string())),
        }
    }

    pub fn all() -> &'static [Phase] {
        &[
            Phase::Draft,
            Phase::Review,
            Phase::Submitted,
            Phase::Accepted,
            Phase::Published,
            Phase::Rejected,
            Phase::Archived,
        ]
    }
}

/// Sorted vector of legal destination phases for `src`.
pub fn legal_moves(src: Phase) -> Vec<Phase> {
    let mut out: Vec<Phase> = match src {
        Phase::Draft => vec![Phase::Review, Phase::Submitted, Phase::Archived],
        Phase::Review => vec![Phase::Draft, Phase::Submitted, Phase::Archived],
        Phase::Submitted => vec![
            Phase::Accepted,
            Phase::Rejected,
            Phase::Review,
            Phase::Archived,
        ],
        Phase::Accepted => vec![Phase::Published, Phase::Archived],
        Phase::Published => vec![Phase::Archived],
        Phase::Rejected => vec![Phase::Draft, Phase::Archived],
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
        Phase::Draft => vec![
            "Lock the scope: which milestone makes this submittable?",
            "Identify the target venue / call (deadline, scope match)",
            "Draft the core outline before filling sections",
        ],
        Phase::Review => vec![
            "Run the peer-review rubric — note every blocker as a milestone",
            "Triage blockers into Fix / Defer / Cut",
            "Decide: back to DRAFT for revision, or push to SUBMITTED?",
        ],
        Phase::Submitted => vec![
            "Track expected decision date; set it as a stakeholder follow-up",
            "Prep response-to-reviewers template in advance",
            "Don't start downstream work that assumes acceptance",
        ],
        Phase::Accepted => vec![
            "Confirm DOI / contract terms in writing",
            "Schedule announcement (memory NEEDTOWRITE entry)",
            "Update STATE.md with acceptance date",
        ],
        Phase::Published => vec![
            "Add to publications list (memory: publications.md)",
            "Announce to stakeholders + Telegram + GLA news",
            "Move project to maintenance / new follow-up",
        ],
        Phase::Rejected => vec![
            "Capture reviewer feedback as DRAFT memory",
            "Decide within 7 days: re-target venue or shelve",
            "If re-target: open new DRAFT phase with the salvageable parts",
        ],
        Phase::Archived => vec!["(no actions — project closed)"],
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditRecord {
    pub ts: String,
    pub project: String,
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
    base.join("phase_history.jsonl")
}

pub struct StateMachine {
    projects_dir: PathBuf,
    audit_path: PathBuf,
}

impl StateMachine {
    pub fn new(projects_dir: impl Into<PathBuf>, audit_path: impl Into<PathBuf>) -> Self {
        Self {
            projects_dir: projects_dir.into(),
            audit_path: audit_path.into(),
        }
    }

    pub fn from_env() -> Self {
        Self::new(aim_project_owner::projects_dir(), default_audit_path())
    }

    pub fn projects_dir(&self) -> &Path {
        &self.projects_dir
    }

    pub fn audit_path(&self) -> &Path {
        &self.audit_path
    }

    pub fn current_phase(&self, project: &str) -> Result<Phase, StateError> {
        let state = aim_project_owner::load(&self.projects_dir, project)?;
        Phase::parse(&state.phase)
    }

    /// Move `project` to phase `dst`. Persists the YAML (round-trip preserves
    /// sibling keys via Mapping mutation) and appends an audit row.
    pub fn transition(
        &self,
        project: &str,
        dst: Phase,
        reason: &str,
        actor: &str,
    ) -> Result<AuditRecord, StateError> {
        let state = aim_project_owner::load(&self.projects_dir, project)?;
        let src = Phase::parse(&state.phase)?;
        if !is_legal(src, dst) {
            return Err(StateError::IllegalTransition {
                src,
                dst,
                legal: legal_moves(src),
            });
        }

        let yaml_path = self.projects_dir.join(format!("{project}.yaml"));
        if !yaml_path.exists() {
            return Err(StateError::NoProject(project.to_string()));
        }
        let raw = std::fs::read_to_string(&yaml_path)?;
        let mut parsed: serde_yaml::Value = serde_yaml::from_str(&raw)?;
        if let Some(map) = parsed.as_mapping_mut() {
            map.insert(
                serde_yaml::Value::String("phase".into()),
                serde_yaml::Value::String(dst.as_str().into()),
            );
        }
        std::fs::write(&yaml_path, serde_yaml::to_string(&parsed)?)?;

        let record = AuditRecord {
            ts: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            project: state.name.clone(),
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

    pub fn history(&self, project: Option<&str>) -> Result<Vec<AuditRecord>, StateError> {
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
            if let Some(p) = project {
                if row.project != p {
                    continue;
                }
            }
            out.push(row);
        }
        Ok(out)
    }

    pub fn phase_advisory(&self, project: &str) -> Result<String, StateError> {
        let state = aim_project_owner::load(&self.projects_dir, project)?;
        let phase = Phase::parse(&state.phase)?;
        let actions = next_actions(phase);
        if actions.is_empty() {
            return Ok(format!("phase: {} — no actions", phase.as_str()));
        }
        let mut out = vec![format!("📐 phase {} — next actions:", phase.as_str())];
        for a in actions {
            out.push(format!("  • {a}"));
        }
        Ok(out.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make() -> (TempDir, StateMachine) {
        let dir = TempDir::new().unwrap();
        let projects = dir.path().join("projects");
        std::fs::create_dir_all(&projects).unwrap();
        let audit = dir.path().join("phase.jsonl");
        let sm = StateMachine::new(projects, audit);
        (dir, sm)
    }

    fn write_proj(sm: &StateMachine, name: &str, phase: &str) {
        let body = format!(
            "name: {name}\ncanonical: /tmp\nphase: {phase}\n"
        );
        std::fs::write(sm.projects_dir().join(format!("{name}.yaml")), body).unwrap();
    }

    #[test]
    fn phase_parse_roundtrip() {
        for &p in Phase::all() {
            let s = p.as_str();
            assert_eq!(Phase::parse(s).unwrap(), p);
            assert_eq!(Phase::parse(&s.to_lowercase()).unwrap(), p);
        }
    }

    #[test]
    fn phase_parse_unknown_errors() {
        let err = Phase::parse("PURGATORY").unwrap_err();
        assert!(matches!(err, StateError::UnknownPhase(_)));
    }

    #[test]
    fn legal_moves_match_python_graph() {
        assert_eq!(
            legal_moves(Phase::Draft),
            vec![Phase::Archived, Phase::Review, Phase::Submitted]
        );
        assert_eq!(legal_moves(Phase::Archived), vec![]);
        let sub = legal_moves(Phase::Submitted);
        assert!(sub.contains(&Phase::Accepted));
        assert!(sub.contains(&Phase::Rejected));
        assert!(sub.contains(&Phase::Review));
        assert!(sub.contains(&Phase::Archived));
        assert_eq!(sub.len(), 4);
    }

    #[test]
    fn is_legal_basic() {
        assert!(is_legal(Phase::Draft, Phase::Review));
        assert!(is_legal(Phase::Submitted, Phase::Accepted));
        assert!(!is_legal(Phase::Draft, Phase::Accepted));
        assert!(!is_legal(Phase::Archived, Phase::Draft));
    }

    #[test]
    fn next_actions_per_phase() {
        assert!(next_actions(Phase::Draft).len() >= 3);
        assert_eq!(next_actions(Phase::Archived).len(), 1);
        assert!(next_actions(Phase::Submitted)
            .iter()
            .any(|a| a.contains("decision date")));
    }

    #[test]
    fn transition_writes_yaml_and_audit() {
        let (_d, sm) = make();
        write_proj(&sm, "FCLC", "DRAFT");
        let rec = sm
            .transition("FCLC", Phase::Submitted, "ready to submit", "human")
            .unwrap();
        assert_eq!(rec.from, "DRAFT");
        assert_eq!(rec.to, "SUBMITTED");
        // YAML now reflects the new phase
        let yaml = std::fs::read_to_string(sm.projects_dir().join("FCLC.yaml")).unwrap();
        assert!(yaml.contains("phase: SUBMITTED"));
        // Audit log has the row
        let h = sm.history(Some("FCLC")).unwrap();
        assert_eq!(h.len(), 1);
        assert_eq!(h[0].reason, "ready to submit");
    }

    #[test]
    fn transition_preserves_sibling_keys() {
        let (_d, sm) = make();
        let body = "name: FCLC\nphase: DRAFT\ngoals:\n  - Win EIC\nstakeholders:\n  - name: Geiger\n    role: co-PI\n";
        std::fs::write(sm.projects_dir().join("FCLC.yaml"), body).unwrap();
        sm.transition("FCLC", Phase::Submitted, "", "test").unwrap();
        let raw = std::fs::read_to_string(sm.projects_dir().join("FCLC.yaml")).unwrap();
        assert!(raw.contains("Win EIC"));
        assert!(raw.contains("Geiger"));
        assert!(raw.contains("phase: SUBMITTED"));
    }

    #[test]
    fn transition_rejects_illegal() {
        let (_d, sm) = make();
        write_proj(&sm, "X", "DRAFT");
        let err = sm
            .transition("X", Phase::Accepted, "", "test")
            .unwrap_err();
        assert!(matches!(err, StateError::IllegalTransition { .. }));
    }

    #[test]
    fn transition_chain_through_lifecycle() {
        let (_d, sm) = make();
        write_proj(&sm, "X", "DRAFT");
        sm.transition("X", Phase::Review, "", "test").unwrap();
        sm.transition("X", Phase::Submitted, "", "test").unwrap();
        sm.transition("X", Phase::Accepted, "", "test").unwrap();
        sm.transition("X", Phase::Published, "", "test").unwrap();
        sm.transition("X", Phase::Archived, "", "test").unwrap();
        let h = sm.history(Some("X")).unwrap();
        assert_eq!(h.len(), 5);
        assert_eq!(h.first().unwrap().to, "REVIEW");
        assert_eq!(h.last().unwrap().to, "ARCHIVED");
    }

    #[test]
    fn history_filters_by_project() {
        let (_d, sm) = make();
        write_proj(&sm, "A", "DRAFT");
        write_proj(&sm, "B", "DRAFT");
        sm.transition("A", Phase::Review, "", "test").unwrap();
        sm.transition("B", Phase::Submitted, "", "test").unwrap();
        let a = sm.history(Some("A")).unwrap();
        let b = sm.history(Some("B")).unwrap();
        let all = sm.history(None).unwrap();
        assert_eq!(a.len(), 1);
        assert_eq!(b.len(), 1);
        assert_eq!(all.len(), 2);
    }

    #[test]
    fn history_empty_when_no_audit() {
        let (_d, sm) = make();
        assert!(sm.history(None).unwrap().is_empty());
    }

    #[test]
    fn current_phase_reads_yaml() {
        let (_d, sm) = make();
        write_proj(&sm, "X", "submitted");
        assert_eq!(sm.current_phase("X").unwrap(), Phase::Submitted);
    }

    #[test]
    fn current_phase_unknown_errors() {
        let (_d, sm) = make();
        let body = "name: X\nphase: WEIRD\n";
        std::fs::write(sm.projects_dir().join("X.yaml"), body).unwrap();
        let err = sm.current_phase("X").unwrap_err();
        assert!(matches!(err, StateError::UnknownPhase(_)));
    }

    #[test]
    fn phase_advisory_renders_actions() {
        let (_d, sm) = make();
        write_proj(&sm, "X", "DRAFT");
        let s = sm.phase_advisory("X").unwrap();
        assert!(s.contains("📐 phase DRAFT — next actions:"));
        assert!(s.contains("•"));
    }

    #[test]
    fn phase_advisory_archived_no_actions() {
        let (_d, sm) = make();
        write_proj(&sm, "X", "ARCHIVED");
        let s = sm.phase_advisory("X").unwrap();
        // Even ARCHIVED has the placeholder action ("(no actions — project closed)")
        assert!(s.contains("ARCHIVED"));
    }

    #[test]
    fn audit_record_serialises_with_from_field() {
        let r = AuditRecord {
            ts: "2026-05-04T10:00:00".into(),
            project: "X".into(),
            from: "DRAFT".into(),
            to: "REVIEW".into(),
            reason: "".into(),
            actor: "human".into(),
        };
        let s = serde_json::to_string(&r).unwrap();
        assert!(s.contains("\"from\":\"DRAFT\""));
        assert!(s.contains("\"to\":\"REVIEW\""));
    }
}
