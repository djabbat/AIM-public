//! aim-experiment-owner — experiment as a managed entity (Phase B, 2026-05-06).
//!
//! Sister to `aim-project-owner` and `aim-patient-owner`. Loads
//! `USER/experiments/<name>.yaml` and exposes `morning_brief` + hot
//! milestones + overdue follow-ups + Lifecycle trait impl.
//!
//! ## YAML schema
//!
//! ```yaml
//! name: E0
//! canonical: /home/oem/Desktop/PhD/E0
//! phase: COMMISSIONING
//! goals:
//!   - Stabilise rig for 6-month autonomous CDATA imaging
//! milestones:
//!   - id: hardware-ordering-phase1
//!     deadline: 2026-05-03
//!     status: blocked
//!     blockers: ["Tsomaia phase 1 component selection"]
//!     criticality: high
//! awaiting:
//!   - topic: Tsomaia ordering decision
//!     since: 2026-04-27
//!     expected_by: 2026-05-03
//! journal_paths:
//!   - "~/.cache/aim/microscopy/sessions/"
//! kpis:
//!   - id: rig-uptime-pct
//!     target: 95
//!     unit: "%"
//! ```

use std::path::{Path, PathBuf};

use aim_experiment_state_machine as sm;
use aim_lifecycle::{EntityKind, HotItem, Lifecycle, LifecycleError};
use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OwnerError {
    #[error("experiments root does not exist: {0}")]
    RootMissing(PathBuf),
    #[error("experiment not found: {0}")]
    NotFound(String),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

impl From<OwnerError> for LifecycleError {
    fn from(e: OwnerError) -> Self {
        match e {
            OwnerError::NotFound(s) => LifecycleError::NotFound(s),
            OwnerError::RootMissing(p) => LifecycleError::Other(format!(
                "experiments root missing: {}",
                p.display()
            )),
            OwnerError::Yaml(e) => LifecycleError::Other(format!("yaml: {e}")),
            OwnerError::Io(e) => LifecycleError::Io(e),
        }
    }
}

// ── data ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Milestone {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deadline: Option<NaiveDate>,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub blockers: Vec<String>,
    #[serde(default = "default_criticality")]
    pub criticality: String,
}

fn default_status() -> String {
    "pending".into()
}
fn default_criticality() -> String {
    "medium".into()
}

impl Milestone {
    pub fn days_to_deadline(&self, today: NaiveDate) -> Option<i64> {
        self.deadline.map(|d| (d - today).num_days())
    }

    pub fn is_hot(&self, today: NaiveDate) -> bool {
        if self.status != "pending" && self.status != "blocked" {
            return false;
        }
        let Some(d) = self.days_to_deadline(today) else {
            return false;
        };
        d <= 7 || (self.criticality == "high" && d <= 14)
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Awaiting {
    pub topic: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub since: Option<NaiveDate>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_by: Option<NaiveDate>,
}

impl Awaiting {
    pub fn overdue(&self, today: NaiveDate) -> bool {
        match self.expected_by {
            Some(d) => today > d,
            None => false,
        }
    }
    pub fn days_silent(&self, today: NaiveDate) -> Option<i64> {
        self.since.map(|d| (today - d).num_days())
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ExperimentState {
    pub name: String,
    #[serde(default)]
    pub canonical: String,
    #[serde(default = "default_phase_str")]
    pub phase: String,
    #[serde(default)]
    pub goals: Vec<String>,
    #[serde(default)]
    pub milestones: Vec<Milestone>,
    #[serde(default)]
    pub awaiting: Vec<Awaiting>,
    #[serde(default)]
    pub journal_paths: Vec<String>,
    #[serde(default)]
    pub daily_checks: Vec<String>,
}

fn default_phase_str() -> String {
    "COMMISSIONING".into()
}

// ── path resolution ────────────────────────────────────────────────────────

pub fn experiments_dir() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_EXPERIMENTS_DIR") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
        }
    }
    PathBuf::from("USER/experiments")
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

// ── owner ──────────────────────────────────────────────────────────────────

pub struct ExperimentOwner {
    root: PathBuf,
}

impl ExperimentOwner {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn from_env() -> Self {
        Self::new(experiments_dir())
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn list_experiments(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        let dir = match std::fs::read_dir(&self.root) {
            Ok(d) => d,
            Err(_) => return out,
        };
        for entry in dir.flatten() {
            let p = entry.path();
            if p.is_file() && p.extension().and_then(|s| s.to_str()) == Some("yaml") {
                if let Some(s) = p.file_stem().and_then(|s| s.to_str()) {
                    out.push(s.to_string());
                }
            }
        }
        out.sort();
        out
    }

    pub fn load(&self, name: &str) -> Result<ExperimentState, OwnerError> {
        let p = self.root.join(format!("{name}.yaml"));
        if !p.exists() {
            return Err(OwnerError::NotFound(name.to_string()));
        }
        let raw = std::fs::read_to_string(&p)?;
        let state: ExperimentState = serde_yaml::from_str(&raw)?;
        Ok(state)
    }

    pub fn morning_brief(
        &self,
        name: &str,
        today: NaiveDate,
    ) -> Result<String, OwnerError> {
        let state = self.load(name)?;
        let mut lines: Vec<String> = Vec::new();
        lines.push(format!("🔬 {} — {}", state.name, today.format("%Y-%m-%d")));
        lines.push(format!("phase: {}", state.phase));
        if let Some(g) = state.goals.first() {
            lines.push(format!("goal: {g}"));
        }

        let hot: Vec<&Milestone> = state
            .milestones
            .iter()
            .filter(|m| m.is_hot(today))
            .collect();
        if !hot.is_empty() {
            lines.push(String::new());
            lines.push(format!("🔥 hot milestones ({}):", hot.len()));
            for m in &hot {
                let d = m.days_to_deadline(today);
                let tag = match d {
                    Some(0) => "TODAY".to_string(),
                    Some(n) if n > 0 => format!("in {n}d"),
                    Some(n) => format!("OVERDUE {}d", -n),
                    None => "no deadline".to_string(),
                };
                let mut line =
                    format!("  • {} — {} [{}, {}]", m.id, tag, m.criticality, m.status);
                if !m.blockers.is_empty() {
                    line.push_str(&format!(
                        "  blockers: {}",
                        m.blockers
                            .iter()
                            .take(2)
                            .cloned()
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
                lines.push(line);
            }
        }

        let overdue: Vec<&Awaiting> = state
            .awaiting
            .iter()
            .filter(|a| a.overdue(today))
            .collect();
        if !overdue.is_empty() {
            lines.push(String::new());
            lines.push(format!("📮 overdue follow-ups ({}):", overdue.len()));
            for a in &overdue {
                let d = a
                    .expected_by
                    .map(|d| (today - d).num_days())
                    .unwrap_or(0);
                lines.push(format!("  • {} — {}d past expected", a.topic, d));
            }
        }

        if let Ok(phase) = sm::Phase::parse(&state.phase) {
            let acts = sm::next_actions(phase);
            if !acts.is_empty() {
                lines.push(String::new());
                lines.push(format!(
                    "📐 phase {} — next actions:",
                    phase.as_str()
                ));
                for a in acts {
                    lines.push(format!("  • {a}"));
                }
            }
        }

        if !state.daily_checks.is_empty() {
            lines.push(String::new());
            lines.push("✅ daily checks:".into());
            for c in &state.daily_checks {
                lines.push(format!("  • {c}"));
            }
        }

        if hot.is_empty() && overdue.is_empty() {
            lines.push(String::new());
            lines.push("✨ nothing on fire today.".into());
        }
        Ok(lines.join("\n"))
    }

    pub fn all_briefs(&self, today: NaiveDate) -> String {
        let names = self.list_experiments();
        if names.is_empty() {
            return "(no experiments configured)".into();
        }
        let mut parts: Vec<String> = Vec::new();
        for n in names {
            match self.morning_brief(&n, today) {
                Ok(b) => parts.push(b),
                Err(e) => parts.push(format!("❌ {n}: {e}")),
            }
        }
        parts.join("\n\n———\n\n")
    }
}

impl Lifecycle for ExperimentOwner {
    fn kind(&self) -> EntityKind {
        EntityKind::Experiment
    }

    fn list_entities(&self) -> Vec<String> {
        self.list_experiments()
    }

    fn current_phase(&self, id: &str) -> Result<String, LifecycleError> {
        let s = self.load(id)?;
        Ok(s.phase)
    }

    fn legal_phases(&self, src: &str) -> Vec<String> {
        match sm::Phase::parse(src) {
            Ok(p) => sm::legal_moves(p)
                .into_iter()
                .map(|p| p.as_str().to_string())
                .collect(),
            Err(_) => Vec::new(),
        }
    }

    fn next_actions(&self, phase: &str) -> Vec<&'static str> {
        match sm::Phase::parse(phase) {
            Ok(p) => sm::next_actions(p),
            Err(_) => Vec::new(),
        }
    }

    fn hot_items(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<Vec<HotItem>, LifecycleError> {
        let s = self.load(id)?;
        Ok(s.milestones
            .iter()
            .filter(|m| m.is_hot(today))
            .map(|m| HotItem {
                days_to: m.days_to_deadline(today).unwrap_or(9999),
                id: m.id.clone(),
                label: String::new(),
                criticality: m.criticality.clone(),
                blockers: m.blockers.clone(),
            })
            .collect())
    }

    fn overdue_items(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<Vec<HotItem>, LifecycleError> {
        let s = self.load(id)?;
        Ok(s.awaiting
            .iter()
            .filter(|a| a.overdue(today))
            .map(|a| HotItem {
                days_to: a
                    .expected_by
                    .map(|d| (d - today).num_days())
                    .unwrap_or(0),
                id: format!("await:{}", a.topic),
                label: a.topic.clone(),
                criticality: "high".into(),
                blockers: Vec::new(),
            })
            .collect())
    }

    fn morning_brief(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<String, LifecycleError> {
        Ok(self.morning_brief(id, today)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn today() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 6).unwrap()
    }

    fn write_yaml(dir: &Path, name: &str, body: &str) {
        std::fs::write(dir.join(format!("{name}.yaml")), body).unwrap();
    }

    #[test]
    fn list_finds_yaml_files() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0", "name: E0\nphase: COMMISSIONING\n");
        write_yaml(tmp.path(), "AutomatedMicroscopy", "name: AutomatedMicroscopy\nphase: COMMISSIONING\n");
        let o = ExperimentOwner::new(tmp.path());
        assert_eq!(o.list_experiments(), vec!["AutomatedMicroscopy", "E0"]);
    }

    #[test]
    fn load_returns_state() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0",
            "name: E0\ncanonical: /home/oem/Desktop/PhD/E0\nphase: CALIBRATING\n");
        let o = ExperimentOwner::new(tmp.path());
        let s = o.load("E0").unwrap();
        assert_eq!(s.phase, "CALIBRATING");
        assert_eq!(s.canonical, "/home/oem/Desktop/PhD/E0");
    }

    #[test]
    fn morning_brief_renders_phase_and_milestones() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0", r#"
name: E0
phase: COMMISSIONING
goals:
  - Stabilise rig
milestones:
  - id: hw-order
    deadline: 2026-05-03
    status: blocked
    blockers: ["Tsomaia phase 1 component selection"]
    criticality: high
awaiting:
  - topic: Tsomaia ordering decision
    since: 2026-04-27
    expected_by: 2026-05-03
"#);
        let o = ExperimentOwner::new(tmp.path());
        let b = o.morning_brief("E0", today()).unwrap();
        assert!(b.contains("🔬 E0"));
        assert!(b.contains("phase: COMMISSIONING"));
        assert!(b.contains("hw-order"));
        assert!(b.contains("OVERDUE 3d"));
        assert!(b.contains("blockers: Tsomaia"));
        assert!(b.contains("Tsomaia ordering decision"));
        assert!(b.contains("📐 phase COMMISSIONING"));
    }

    #[test]
    fn lifecycle_object_safe() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0", "name: E0\nphase: RUNNING\n");
        let o: Box<dyn Lifecycle> = Box::new(ExperimentOwner::new(tmp.path()));
        assert_eq!(o.kind(), EntityKind::Experiment);
        assert_eq!(o.list_entities(), vec!["E0"]);
        assert_eq!(o.current_phase("E0").unwrap(), "RUNNING");
        let legal = o.legal_phases("RUNNING");
        assert!(legal.contains(&"DATA_PROCESSING".to_string()));
    }

    #[test]
    fn nothing_on_fire_when_clean() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0", "name: E0\nphase: RUNNING\n");
        let o = ExperimentOwner::new(tmp.path());
        let b = o.morning_brief("E0", today()).unwrap();
        assert!(b.contains("✨ nothing on fire today."));
    }

    #[test]
    fn all_briefs_concatenates() {
        let tmp = TempDir::new().unwrap();
        write_yaml(tmp.path(), "E0", "name: E0\nphase: COMMISSIONING\n");
        write_yaml(tmp.path(), "AM", "name: AM\nphase: RUNNING\n");
        let o = ExperimentOwner::new(tmp.path());
        let s = o.all_briefs(today());
        assert!(s.contains("E0"));
        assert!(s.contains("AM"));
        assert!(s.contains("———"));
    }

    #[test]
    fn missing_experiment_returns_not_found() {
        let tmp = TempDir::new().unwrap();
        let o = ExperimentOwner::new(tmp.path());
        let err = o.load("ghost").unwrap_err();
        assert!(matches!(err, OwnerError::NotFound(_)));
    }
}
