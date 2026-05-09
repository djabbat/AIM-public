//! aim-patient-owner — patient as a managed entity (Phase A, 2026-05-06).
//!
//! Mirror to `aim-project-owner`. Loads `Patients/<id>/MEMORY.md` via
//! `aim-patient-memory`, exposes `morning_brief` + hot milestones +
//! overdue follow-ups, and implements the [`Lifecycle`] trait so the
//! daily brief can iterate projects + patients + experiments uniformly.
//!
//! ## Schema
//!
//! Extended `MEMORY.md` (see `aim-patient-memory` for full list of
//! sections). Phase A added:
//!
//! ```markdown
//! ## Phase
//! ACTIVE_TREATMENT
//!
//! ## Milestones
//! - thyroid-recheck (2026-08-15, medium): pending — TSH result
//!
//! ## Awaiting
//! - repeat lab K+ (since 2026-05-06, expected 2026-05-13)
//! ```
//!
//! ## Public API
//! - [`patients_dir`] — `$AIM_PATIENTS_DIR` override → `Patients/`
//! - [`PatientOwner::new`] — bind to a directory
//! - [`PatientOwner::list_patients`] — sorted folder names with MEMORY.md
//! - [`PatientOwner::load`] — typed `PatientMemory`
//! - [`PatientOwner::morning_brief`] — Telegram-ready brief
//! - implements [`aim_lifecycle::Lifecycle`] (object-safe trait)

use std::path::{Path, PathBuf};

use aim_lifecycle::{EntityKind, HotItem, Lifecycle, LifecycleError};
use aim_patient_memory::{
    read_memory, Awaiting, Milestone, NoopIndex, PatientIndex, PatientMemory,
};
use aim_patient_state_machine as sm;
use chrono::NaiveDate;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OwnerError {
    #[error("patients root does not exist: {0}")]
    RootMissing(PathBuf),
    #[error("patient not found: {0}")]
    NotFound(String),
    #[error("patient memory error: {0}")]
    Memory(#[from] aim_patient_memory::PatientError),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

impl From<OwnerError> for LifecycleError {
    fn from(e: OwnerError) -> Self {
        match e {
            OwnerError::NotFound(s) => LifecycleError::NotFound(s),
            OwnerError::RootMissing(p) => {
                LifecycleError::Other(format!("patients root missing: {}", p.display()))
            }
            OwnerError::Memory(m) => LifecycleError::Other(m.to_string()),
            OwnerError::Io(e) => LifecycleError::Io(e),
        }
    }
}

// ── path resolution ────────────────────────────────────────────────────────

pub fn patients_dir() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_PATIENTS_DIR") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
        }
    }
    PathBuf::from("Patients")
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

/// Holds a binding to a patients root directory and an index. Ports
/// the surface of `agents/project_owner.py` to the patient domain.
pub struct PatientOwner {
    patients_root: PathBuf,
    index: Box<dyn PatientIndex>,
}

impl PatientOwner {
    pub fn new(patients_root: impl Into<PathBuf>) -> Self {
        Self {
            patients_root: patients_root.into(),
            index: Box::new(NoopIndex),
        }
    }

    pub fn from_env() -> Self {
        Self::new(patients_dir())
    }

    pub fn with_index(mut self, index: Box<dyn PatientIndex>) -> Self {
        self.index = index;
        self
    }

    pub fn patients_root(&self) -> &Path {
        &self.patients_root
    }

    /// Sorted patient ids that have a `MEMORY.md`. Folders without
    /// MEMORY.md are skipped (could be stale / WIP intake folders).
    pub fn list_patients(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        let dir = match std::fs::read_dir(&self.patients_root) {
            Ok(d) => d,
            Err(_) => return out,
        };
        for entry in dir.flatten() {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            // Skip the INBOX special folder
            if path.file_name().and_then(|s| s.to_str()) == Some("INBOX") {
                continue;
            }
            let mem = path.join("MEMORY.md");
            if !mem.exists() {
                continue;
            }
            if let Some(name) = path.file_name().and_then(|s| s.to_str()) {
                out.push(name.to_string());
            }
        }
        out.sort();
        out
    }

    pub fn load(&self, patient_id: &str) -> Result<PatientMemory, OwnerError> {
        match read_memory(&self.patients_root, patient_id, self.index.as_ref())? {
            Some(m) => Ok(m),
            None => Err(OwnerError::NotFound(patient_id.to_string())),
        }
    }

    /// Hot milestones for a patient (pending, deadline ≤ 7d, or high
    /// criticality and ≤ 14d).
    pub fn hot_milestones(
        &self,
        patient_id: &str,
        today: NaiveDate,
    ) -> Result<Vec<Milestone>, OwnerError> {
        let m = self.load(patient_id)?;
        Ok(m.milestones
            .iter()
            .filter(|x| x.is_hot(today))
            .cloned()
            .collect())
    }

    /// Awaiting items past their `expected_by`.
    pub fn overdue_followups(
        &self,
        patient_id: &str,
        today: NaiveDate,
    ) -> Result<Vec<Awaiting>, OwnerError> {
        let m = self.load(patient_id)?;
        Ok(m.awaiting
            .iter()
            .filter(|a| a.overdue(today))
            .cloned()
            .collect())
    }

    /// One-screen status brief. Mirror to `project_owner.morning_brief`,
    /// adapted for the patient domain.
    pub fn morning_brief(
        &self,
        patient_id: &str,
        today: NaiveDate,
    ) -> Result<String, OwnerError> {
        let mem = self.load(patient_id)?;
        let mut lines: Vec<String> = Vec::new();
        lines.push(format!("🏥 {} — {}", mem.id, today.format("%Y-%m-%d")));
        lines.push(format!("phase: {}", mem.phase));

        if !mem.conditions.is_empty() {
            let dxs: Vec<String> = mem
                .conditions
                .iter()
                .map(|c| c.dx.clone())
                .filter(|s| !s.is_empty())
                .collect();
            if !dxs.is_empty() {
                lines.push(format!("dx: {}", dxs.join(", ")));
            }
        }

        let hot: Vec<&Milestone> = mem
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
                let mut line = format!("  • {} — {} [{}]", m.id, tag, m.criticality);
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

        let overdue: Vec<&Awaiting> = mem
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

        let pending_awaiting: Vec<&Awaiting> = mem
            .awaiting
            .iter()
            .filter(|a| !a.overdue(today))
            .collect();
        if !pending_awaiting.is_empty() {
            lines.push(String::new());
            lines.push(format!("⏳ awaiting ({}):", pending_awaiting.len()));
            for a in pending_awaiting.iter().take(5) {
                let silent_s = a
                    .days_silent(today)
                    .map(|n| format!(", {n}d silent"))
                    .unwrap_or_default();
                lines.push(format!("  • {}{}", a.topic, silent_s));
            }
        }

        // Phase-aware next actions
        if let Ok(phase) = sm::Phase::parse(&mem.phase) {
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

        if hot.is_empty() && overdue.is_empty() && pending_awaiting.is_empty() {
            lines.push(String::new());
            lines.push("✨ nothing on fire today.".into());
        }
        Ok(lines.join("\n"))
    }

    /// Concatenate `morning_brief` for every patient. Useful for the
    /// daily-brief assembly.
    pub fn all_briefs(&self, today: NaiveDate) -> String {
        let names = self.list_patients();
        if names.is_empty() {
            return "(no patients with MEMORY.md)".into();
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

// ── Lifecycle trait impl ───────────────────────────────────────────────────

impl Lifecycle for PatientOwner {
    fn kind(&self) -> EntityKind {
        EntityKind::Patient
    }

    fn list_entities(&self) -> Vec<String> {
        self.list_patients()
    }

    fn current_phase(&self, id: &str) -> Result<String, LifecycleError> {
        let m = self.load(id)?;
        Ok(m.phase)
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
        let ms = self.hot_milestones(id, today)?;
        let mut out: Vec<HotItem> = ms
            .into_iter()
            .map(|m| HotItem {
                days_to: m.days_to_deadline(today).unwrap_or(9999),
                id: m.id,
                label: String::new(),
                criticality: m.criticality,
                blockers: m.blockers,
            })
            .collect();
        // Also surface awaiting that's not yet overdue but expected
        // within 7d as "hot" — caller can use this to render upcoming
        // follow-ups as a single "hot" set.
        let mem = self.load(id)?;
        for a in &mem.awaiting {
            if let Some(exp) = a.expected_by {
                let days = (exp - today).num_days();
                if days >= 0 && days <= 7 {
                    out.push(HotItem {
                        id: format!("await:{}", a.topic),
                        label: a.topic.clone(),
                        days_to: days,
                        criticality: "medium".into(),
                        blockers: Vec::new(),
                    });
                }
            }
        }
        Ok(out)
    }

    fn overdue_items(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<Vec<HotItem>, LifecycleError> {
        let aws = self.overdue_followups(id, today)?;
        let out: Vec<HotItem> = aws
            .into_iter()
            .map(|a| {
                let days_to = a
                    .expected_by
                    .map(|d| (d - today).num_days())
                    .unwrap_or(0);
                HotItem {
                    id: format!("await:{}", a.topic),
                    label: a.topic,
                    days_to,
                    criticality: "high".into(),
                    blockers: Vec::new(),
                }
            })
            .collect();
        Ok(out)
    }

    fn morning_brief(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<String, LifecycleError> {
        Ok(self.morning_brief(id, today)?)
    }
}

// ── tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use aim_patient_memory::{
        write_memory, Awaiting, Demographics, Milestone, NoopIndex, PatientMemory,
        SystemClock,
    };
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn ts() -> chrono::DateTime<chrono::Utc> {
        chrono::Utc.with_ymd_and_hms(2026, 5, 6, 0, 0, 0).unwrap()
    }

    fn today_2026_05_06() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 6).unwrap()
    }

    fn write_test_patient(root: &Path, id: &str, build: impl FnOnce(&mut PatientMemory)) {
        let mut mem = PatientMemory::new(id);
        build(&mut mem);
        let clk = aim_patient_memory::FixedClock(ts());
        let idx = NoopIndex;
        write_memory(root, &mem, &clk, &idx).unwrap();
    }

    #[test]
    fn list_patients_finds_dirs_with_memory_md() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "Smith_John_1980_05_15", |_m| {});
        write_test_patient(tmp.path(), "Doe_Jane_1990_01_01", |_m| {});
        // Empty dir should be skipped
        std::fs::create_dir_all(tmp.path().join("Empty_X")).unwrap();
        // INBOX always skipped
        std::fs::create_dir_all(tmp.path().join("INBOX")).unwrap();
        let owner = PatientOwner::new(tmp.path());
        let list = owner.list_patients();
        assert_eq!(
            list,
            vec![
                "Doe_Jane_1990_01_01".to_string(),
                "Smith_John_1980_05_15".to_string()
            ]
        );
    }

    #[test]
    fn list_patients_empty_when_root_missing() {
        let tmp = TempDir::new().unwrap();
        let nonexistent = tmp.path().join("ghost");
        let owner = PatientOwner::new(&nonexistent);
        assert!(owner.list_patients().is_empty());
    }

    #[test]
    fn load_returns_not_found_for_unknown() {
        let tmp = TempDir::new().unwrap();
        let owner = PatientOwner::new(tmp.path());
        let err = owner.load("ghost").unwrap_err();
        assert!(matches!(err, OwnerError::NotFound(_)));
    }

    #[test]
    fn morning_brief_renders_phase_and_milestones() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "Feradze_Maia_1981_12_20", |m| {
            m.demographics = Demographics {
                age: Some(44),
                sex: Some("F".into()),
                country: Some("GE".into()),
            };
            m.phase = "ACTIVE_TREATMENT".into();
            m.milestones.push(Milestone {
                id: "thyroid-recheck".into(),
                deadline: NaiveDate::from_ymd_opt(2026, 5, 13),
                status: "pending".into(),
                blockers: vec!["TSH result".into()],
                criticality: "medium".into(),
            });
            m.awaiting.push(Awaiting {
                topic: "repeat lab K+".into(),
                since: NaiveDate::from_ymd_opt(2026, 4, 20),
                expected_by: NaiveDate::from_ymd_opt(2026, 5, 1),
            });
        });

        let owner = PatientOwner::new(tmp.path());
        let brief = owner
            .morning_brief("Feradze_Maia_1981_12_20", today_2026_05_06())
            .unwrap();
        assert!(brief.contains("🏥 Feradze_Maia_1981_12_20"));
        assert!(brief.contains("phase: ACTIVE_TREATMENT"));
        assert!(brief.contains("hot milestones"));
        assert!(brief.contains("thyroid-recheck"));
        assert!(brief.contains("in 7d"));
        assert!(brief.contains("overdue follow-ups"));
        assert!(brief.contains("repeat lab K+"));
        assert!(brief.contains("📐 phase ACTIVE_TREATMENT"));
    }

    #[test]
    fn morning_brief_says_nothing_on_fire_when_clean() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "Stable_X_2000_01_01", |m| {
            m.phase = "STABLE".into();
        });
        let owner = PatientOwner::new(tmp.path());
        let brief = owner
            .morning_brief("Stable_X_2000_01_01", today_2026_05_06())
            .unwrap();
        assert!(brief.contains("✨ nothing on fire today."));
    }

    #[test]
    fn lifecycle_trait_object_safe() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "X_Y_2000_01_01", |m| {
            m.phase = "INTAKE".into();
        });
        let owner: Box<dyn Lifecycle> = Box::new(PatientOwner::new(tmp.path()));
        assert_eq!(owner.kind(), EntityKind::Patient);
        assert_eq!(
            owner.list_entities(),
            vec!["X_Y_2000_01_01".to_string()]
        );
        assert_eq!(
            owner.current_phase("X_Y_2000_01_01").unwrap(),
            "INTAKE"
        );
        let legal = owner.legal_phases("INTAKE");
        assert!(legal.contains(&"DIAGNOSTIC_WORKUP".to_string()));
    }

    #[test]
    fn hot_items_includes_awaiting_within_7d() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "P_2000_01_01", |m| {
            m.awaiting.push(Awaiting {
                topic: "repeat creatinine".into(),
                since: NaiveDate::from_ymd_opt(2026, 5, 1),
                expected_by: NaiveDate::from_ymd_opt(2026, 5, 10),
            });
        });
        let owner = PatientOwner::new(tmp.path());
        let hot = owner
            .hot_items("P_2000_01_01", today_2026_05_06())
            .unwrap();
        assert!(hot.iter().any(|h| h.id.starts_with("await:")));
    }

    #[test]
    fn overdue_items_returns_past_awaiting() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "P_2000_01_01", |m| {
            m.awaiting.push(Awaiting {
                topic: "MRI consult".into(),
                since: NaiveDate::from_ymd_opt(2026, 4, 20),
                expected_by: NaiveDate::from_ymd_opt(2026, 5, 1),
            });
        });
        let owner = PatientOwner::new(tmp.path());
        let overdue = owner
            .overdue_items("P_2000_01_01", today_2026_05_06())
            .unwrap();
        assert_eq!(overdue.len(), 1);
        assert!(overdue[0].label.contains("MRI consult"));
    }

    #[test]
    fn all_briefs_concatenates_with_separator() {
        let tmp = TempDir::new().unwrap();
        write_test_patient(tmp.path(), "A_2000_01_01", |m| {
            m.phase = "INTAKE".into();
        });
        write_test_patient(tmp.path(), "B_1990_01_01", |m| {
            m.phase = "STABLE".into();
        });
        let owner = PatientOwner::new(tmp.path());
        let all = owner.all_briefs(today_2026_05_06());
        assert!(all.contains("A_2000_01_01"));
        assert!(all.contains("B_1990_01_01"));
        assert!(all.contains("———"));
    }

    #[test]
    fn all_briefs_empty_when_no_patients() {
        let tmp = TempDir::new().unwrap();
        let owner = PatientOwner::new(tmp.path());
        let all = owner.all_briefs(today_2026_05_06());
        assert!(all.contains("no patients"));
    }

    /// Force the unused-import diagnostic to silence:
    #[test]
    fn _unused_keep_systemclock_in_scope() {
        let _c: SystemClock = SystemClock;
    }
}
