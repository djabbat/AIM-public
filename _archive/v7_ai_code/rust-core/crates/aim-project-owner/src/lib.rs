//! aim-project-owner — Project Owner Agent (P1).
//!
//! Port of `agents/project_owner.py`. Loads a YAML state file per project
//! (`USER/projects/<name>.yaml`), exposes `goals` / `milestones` /
//! `stakeholders` / `daily_checks` as typed structs, and renders the
//! morning brief that lists what's hot today.
//!
//! ## Schema
//!
//! ```yaml
//! name:        FCLC
//! canonical:   /home/oem/Desktop/LongevityCommon/FCLC
//! phase:       SUBMITTED            # DRAFT|REVIEW|SUBMITTED|ACCEPTED|PUBLISHED
//! goals:
//!   - Get EIC Pathfinder Challenges 2026 funded (€3M, 36 mo)
//! milestones:
//!   - id: eic-submit
//!     deadline: 2026-10-28T17:00:00+02:00
//!     status: pending
//!     criticality: high
//!     blockers: ["Need ≥2 EU-MS Co-PI LoIs"]
//! stakeholders:
//!   - name: Hartmut Geiger
//!     role: Co-PI Phase B
//!     last_contact: 2026-04-23
//!     awaiting_reply: false
//!     expected_response_by: ~
//!     notes: LoS signed
//! daily_checks: ["EIC submission deadline countdown"]
//! ```
//!
//! ## Public API
//! - [`projects_dir`] — `$AIM_PROJECTS_DIR` override → `USER/projects/`
//! - [`list_projects`] — sorted YAML stems
//! - [`load`] — typed [`ProjectState`]
//! - [`morning_brief`] — one-screen Telegram-ready brief
//! - [`overdue_followups`] — strings ready for the daily-brief assembly
//! - [`hot_milestones`] — filter helper

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ProjectError {
    #[error("project YAML not found: {0}")]
    NotFound(PathBuf),
    #[error("{path}: top-level must be a mapping")]
    NotMapping { path: PathBuf },
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Stakeholder {
    pub name: String,
    #[serde(default)]
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_contact: Option<NaiveDate>,
    #[serde(default)]
    pub awaiting_reply: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_response_by: Option<NaiveDate>,
    #[serde(default)]
    pub notes: String,
}

impl Stakeholder {
    pub fn days_silent(&self, today: NaiveDate) -> Option<i64> {
        let lc = self.last_contact?;
        Some((today - lc).num_days())
    }

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

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Milestone {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deadline: Option<DateTime<Utc>>,
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
        let d = self.deadline?;
        Some((d.date_naive() - today).num_days())
    }

    pub fn is_hot(&self, today: NaiveDate) -> bool {
        if self.status != "pending" {
            return false;
        }
        let Some(d) = self.days_to_deadline(today) else {
            return false;
        };
        d <= 7 || (self.criticality == "high" && d <= 14)
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectState {
    pub name: String,
    #[serde(default)]
    pub canonical: String,
    #[serde(default = "default_phase")]
    pub phase: String,
    #[serde(default)]
    pub goals: Vec<String>,
    #[serde(default)]
    pub milestones: Vec<Milestone>,
    #[serde(default)]
    pub stakeholders: Vec<Stakeholder>,
    #[serde(default)]
    pub daily_checks: Vec<String>,
}

fn default_phase() -> String {
    "DRAFT".into()
}

// ── Path resolution ────────────────────────────────────────────────────

pub fn projects_dir() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_PROJECTS_DIR") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
        }
    }
    PathBuf::from("USER/projects")
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

pub fn list_projects(dir: &Path) -> Vec<String> {
    if !dir.exists() {
        return Vec::new();
    }
    let mut out: Vec<String> = std::fs::read_dir(dir)
        .ok()
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("yaml"))
        .filter_map(|e| {
            e.path()
                .file_stem()
                .and_then(|s| s.to_str())
                .map(String::from)
        })
        .collect();
    out.sort();
    out
}

// ── YAML loading (lenient — matches Python) ────────────────────────────

fn parse_date_value(v: &serde_yaml::Value) -> Option<NaiveDate> {
    match v {
        serde_yaml::Value::Null => None,
        serde_yaml::Value::String(s) => {
            let s = s.trim();
            if s.is_empty() || s == "~" {
                return None;
            }
            let prefix = s.split('T').next().unwrap_or("");
            NaiveDate::parse_from_str(&prefix[..prefix.len().min(10)], "%Y-%m-%d").ok()
        }
        _ => None,
    }
}

fn parse_datetime_value(v: &serde_yaml::Value) -> Option<DateTime<Utc>> {
    match v {
        serde_yaml::Value::Null => None,
        serde_yaml::Value::String(s) => {
            let s = s.trim();
            if s.is_empty() || s == "~" {
                return None;
            }
            // Try full RFC3339 first (handles +02:00, Z)
            if let Ok(dt) = DateTime::parse_from_rfc3339(&s.replace(' ', "T")) {
                return Some(dt.with_timezone(&Utc));
            }
            // Naive datetime → assume UTC
            if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S") {
                return Some(naive.and_utc());
            }
            // Date-only → 00:00 UTC
            if let Ok(d) = NaiveDate::parse_from_str(&s[..s.len().min(10)], "%Y-%m-%d") {
                return Some(d.and_hms_opt(0, 0, 0)?.and_utc());
            }
            None
        }
        _ => None,
    }
}

fn parse_milestone(m: &serde_yaml::Value) -> Milestone {
    let map = match m.as_mapping() {
        Some(m) => m,
        None => return Milestone::default(),
    };
    let id = map
        .get("id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let deadline = map.get("deadline").and_then(parse_datetime_value);
    let status = map
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("pending")
        .to_string();
    let blockers: Vec<String> = map
        .get("blockers")
        .and_then(|v| v.as_sequence())
        .map(|s| {
            s.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let criticality = map
        .get("criticality")
        .and_then(|v| v.as_str())
        .unwrap_or("medium")
        .to_string();
    Milestone {
        id,
        deadline,
        status,
        blockers,
        criticality,
    }
}

fn parse_stakeholder(s: &serde_yaml::Value) -> Stakeholder {
    let map = match s.as_mapping() {
        Some(m) => m,
        None => return Stakeholder::default(),
    };
    Stakeholder {
        name: map
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        role: map
            .get("role")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        last_contact: map.get("last_contact").and_then(parse_date_value),
        awaiting_reply: map
            .get("awaiting_reply")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        expected_response_by: map.get("expected_response_by").and_then(parse_date_value),
        notes: map
            .get("notes")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
    }
}

fn parse_state(name_fallback: &str, raw: &serde_yaml::Value) -> ProjectState {
    let map = raw.as_mapping().expect("checked by load()");
    let name = map
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or(name_fallback)
        .to_string();
    let canonical = map
        .get("canonical")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let phase = map
        .get("phase")
        .and_then(|v| v.as_str())
        .unwrap_or("DRAFT")
        .to_string();
    let goals: Vec<String> = map
        .get("goals")
        .and_then(|v| v.as_sequence())
        .map(|s| {
            s.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let milestones: Vec<Milestone> = map
        .get("milestones")
        .and_then(|v| v.as_sequence())
        .map(|s| s.iter().map(parse_milestone).collect())
        .unwrap_or_default();
    let stakeholders: Vec<Stakeholder> = map
        .get("stakeholders")
        .and_then(|v| v.as_sequence())
        .map(|s| s.iter().map(parse_stakeholder).collect())
        .unwrap_or_default();
    let daily_checks: Vec<String> = map
        .get("daily_checks")
        .and_then(|v| v.as_sequence())
        .map(|s| {
            s.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    ProjectState {
        name,
        canonical,
        phase,
        goals,
        milestones,
        stakeholders,
        daily_checks,
    }
}

pub fn load(dir: &Path, project: &str) -> Result<ProjectState, ProjectError> {
    let path = dir.join(format!("{project}.yaml"));
    if !path.exists() {
        return Err(ProjectError::NotFound(path));
    }
    let raw = std::fs::read_to_string(&path)?;
    let parsed: serde_yaml::Value = serde_yaml::from_str(&raw)?;
    if !parsed.is_mapping() {
        return Err(ProjectError::NotMapping { path });
    }
    Ok(parse_state(project, &parsed))
}

// ── Brief generation ──────────────────────────────────────────────────

pub fn overdue_followups(state: &ProjectState, today: NaiveDate) -> Vec<String> {
    let mut out = Vec::new();
    for s in &state.stakeholders {
        if s.overdue(today) {
            let days = match s.expected_response_by {
                Some(d) => (today - d).num_days(),
                None => 0,
            };
            out.push(format!("{} ({}) — overdue by {}d", s.name, s.role, days));
        }
    }
    out
}

pub fn hot_milestones<'a>(state: &'a ProjectState, today: NaiveDate) -> Vec<&'a Milestone> {
    state.milestones.iter().filter(|m| m.is_hot(today)).collect()
}

/// Optional inputs threaded in from sibling crates (kpi, project_state_machine).
#[derive(Debug, Clone, Default)]
pub struct BriefExtras {
    pub phase_actions: Vec<String>,
    pub kpi_block: String,
}

/// Render the morning brief. Plain text, ≤ 30 lines so it actually gets
/// read. `extras` lets the caller inject phase-aware actions (P5) and the
/// KPI dashboard (K1) from sibling crates without this crate depending on
/// them.
pub fn morning_brief(state: &ProjectState, today: NaiveDate, extras: &BriefExtras) -> String {
    let mut lines = Vec::new();
    lines.push(format!("📌 {} — {}", state.name, today));
    lines.push(format!("phase: {}", state.phase));
    if let Some(g) = state.goals.first() {
        lines.push(format!("goal: {g}"));
    }

    let mut hot = hot_milestones(state, today);
    if !hot.is_empty() {
        hot.sort_by_key(|m| m.days_to_deadline(today).unwrap_or(9999));
        lines.push(String::new());
        lines.push(format!("🔥 hot milestones ({}):", hot.len()));
        for m in &hot {
            let d = m.days_to_deadline(today).unwrap_or(9999);
            let tag = if d == 0 {
                "TODAY".to_string()
            } else if d > 0 {
                format!("in {d}d")
            } else {
                format!("OVERDUE {}d", -d)
            };
            let mut line = format!("  • {} — {} [{}]", m.id, tag, m.criticality);
            if !m.blockers.is_empty() {
                let pick: Vec<&str> = m.blockers.iter().take(2).map(|s| s.as_str()).collect();
                line.push_str(&format!("  blockers: {}", pick.join(", ")));
            }
            lines.push(line);
        }
    }

    let overdue: Vec<&Stakeholder> = state
        .stakeholders
        .iter()
        .filter(|s| s.overdue(today))
        .collect();
    if !overdue.is_empty() {
        lines.push(String::new());
        lines.push(format!("📮 overdue follow-ups ({}):", overdue.len()));
        for s in &overdue {
            let d = match s.expected_response_by {
                Some(d) => (today - d).num_days(),
                None => 0,
            };
            lines.push(format!(
                "  • {} ({}) — {}d past expected reply",
                s.name, s.role, d
            ));
        }
    }

    let awaiting: Vec<&Stakeholder> = state
        .stakeholders
        .iter()
        .filter(|s| s.awaiting_reply && !s.overdue(today))
        .collect();
    if !awaiting.is_empty() {
        lines.push(String::new());
        lines.push(format!("⏳ awaiting reply ({}):", awaiting.len()));
        for s in awaiting.iter().take(5) {
            let silent_s = match s.days_silent(today) {
                Some(n) => format!(", {n}d silent"),
                None => String::new(),
            };
            lines.push(format!("  • {} ({}{})", s.name, s.role, silent_s));
        }
    }

    if !state.daily_checks.is_empty() {
        lines.push(String::new());
        lines.push("✅ daily checks:".to_string());
        for c in &state.daily_checks {
            lines.push(format!("  • {c}"));
        }
    }

    if !extras.phase_actions.is_empty() {
        lines.push(String::new());
        lines.push(format!("📐 phase {} — next actions:", state.phase));
        for a in &extras.phase_actions {
            lines.push(format!("  • {a}"));
        }
    }

    if !extras.kpi_block.is_empty() {
        lines.push(String::new());
        lines.push(extras.kpi_block.clone());
    }

    let any = !hot.is_empty() || !overdue.is_empty() || !awaiting.is_empty();
    if !any {
        lines.push(String::new());
        lines.push("✨ nothing on fire today.".to_string());
    }

    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }

    fn write(dir: &TempDir, name: &str, body: &str) -> PathBuf {
        let p = dir.path().join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn list_projects_sorted_stems() {
        let dir = TempDir::new().unwrap();
        write(&dir, "Ze.yaml", "name: Ze");
        write(&dir, "FCLC.yaml", "name: FCLC");
        write(&dir, "skip.txt", "ignored");
        let v = list_projects(dir.path());
        assert_eq!(v, vec!["FCLC", "Ze"]);
    }

    #[test]
    fn list_projects_missing_dir_returns_empty() {
        let dir = TempDir::new().unwrap();
        let v = list_projects(&dir.path().join("does-not-exist"));
        assert!(v.is_empty());
    }

    #[test]
    fn load_basic_state() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "FCLC.yaml",
            r#"name: FCLC
canonical: /path
phase: SUBMITTED
goals:
  - Goal A
milestones:
  - id: eic-submit
    deadline: 2026-10-28T17:00:00+02:00
    status: pending
    criticality: high
    blockers: ["Need ≥2 EU-MS Co-PI LoIs"]
stakeholders:
  - name: Geiger
    role: Co-PI
    last_contact: 2026-04-23
    awaiting_reply: false
daily_checks: ["countdown"]
"#,
        );
        let state = load(dir.path(), "FCLC").unwrap();
        assert_eq!(state.name, "FCLC");
        assert_eq!(state.phase, "SUBMITTED");
        assert_eq!(state.goals, vec!["Goal A"]);
        assert_eq!(state.milestones.len(), 1);
        assert_eq!(state.milestones[0].id, "eic-submit");
        assert_eq!(state.milestones[0].criticality, "high");
        assert_eq!(state.stakeholders[0].name, "Geiger");
    }

    #[test]
    fn load_missing_file_returns_not_found() {
        let dir = TempDir::new().unwrap();
        let err = load(dir.path(), "ghost").unwrap_err();
        assert!(matches!(err, ProjectError::NotFound(_)));
    }

    #[test]
    fn load_non_mapping_errors() {
        let dir = TempDir::new().unwrap();
        write(&dir, "x.yaml", "- list\n- of\n- items");
        let err = load(dir.path(), "x").unwrap_err();
        assert!(matches!(err, ProjectError::NotMapping { .. }));
    }

    #[test]
    fn load_uses_filename_as_default_name() {
        let dir = TempDir::new().unwrap();
        write(&dir, "X.yaml", "phase: DRAFT");
        let state = load(dir.path(), "X").unwrap();
        assert_eq!(state.name, "X");
    }

    #[test]
    fn load_uses_default_status_when_missing() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "X.yaml",
            r#"name: X
milestones:
  - id: m1
    deadline: 2026-10-28
"#,
        );
        let state = load(dir.path(), "X").unwrap();
        assert_eq!(state.milestones[0].status, "pending");
        assert_eq!(state.milestones[0].criticality, "medium");
    }

    #[test]
    fn parse_date_handles_tilde_and_empty() {
        assert!(parse_date_value(&serde_yaml::Value::String("~".into())).is_none());
        assert!(parse_date_value(&serde_yaml::Value::String("".into())).is_none());
        assert_eq!(
            parse_date_value(&serde_yaml::Value::String("2026-04-23".into())),
            Some(d(2026, 4, 23))
        );
    }

    #[test]
    fn milestone_days_to_deadline_and_is_hot() {
        let m = Milestone {
            id: "eic".into(),
            deadline: Some(Utc.with_ymd_and_hms(2026, 5, 11, 17, 0, 0).unwrap()),
            status: "pending".into(),
            blockers: vec![],
            criticality: "high".into(),
        };
        let today = d(2026, 5, 4);
        assert_eq!(m.days_to_deadline(today), Some(7));
        assert!(m.is_hot(today));
    }

    #[test]
    fn milestone_not_hot_when_status_done() {
        let m = Milestone {
            id: "eic".into(),
            deadline: Some(Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap()),
            status: "done".into(),
            blockers: vec![],
            criticality: "high".into(),
        };
        assert!(!m.is_hot(d(2026, 5, 4)));
    }

    #[test]
    fn milestone_high_crit_hot_window_is_14d() {
        let m = Milestone {
            id: "x".into(),
            deadline: Some(Utc.with_ymd_and_hms(2026, 5, 18, 0, 0, 0).unwrap()),
            status: "pending".into(),
            blockers: vec![],
            criticality: "high".into(),
        };
        assert!(m.is_hot(d(2026, 5, 4)));
    }

    #[test]
    fn milestone_medium_crit_hot_window_is_7d_only() {
        let m = Milestone {
            id: "x".into(),
            deadline: Some(Utc.with_ymd_and_hms(2026, 5, 18, 0, 0, 0).unwrap()),
            status: "pending".into(),
            blockers: vec![],
            criticality: "medium".into(),
        };
        assert!(!m.is_hot(d(2026, 5, 4)));
    }

    #[test]
    fn stakeholder_overdue_helper() {
        let s = Stakeholder {
            name: "X".into(),
            role: "".into(),
            last_contact: None,
            awaiting_reply: true,
            expected_response_by: Some(d(2026, 5, 1)),
            notes: "".into(),
        };
        assert!(s.overdue(d(2026, 5, 4)));
        assert!(!s.overdue(d(2026, 4, 30)));
    }

    #[test]
    fn stakeholder_not_overdue_when_not_awaiting() {
        let s = Stakeholder {
            name: "X".into(),
            role: "".into(),
            last_contact: None,
            awaiting_reply: false,
            expected_response_by: Some(d(2026, 4, 1)),
            notes: "".into(),
        };
        assert!(!s.overdue(d(2026, 5, 4)));
    }

    #[test]
    fn overdue_followups_strings() {
        let state = ProjectState {
            name: "FCLC".into(),
            stakeholders: vec![Stakeholder {
                name: "Janke".into(),
                role: "Curie co-PI".into(),
                awaiting_reply: true,
                expected_response_by: Some(d(2026, 4, 24)),
                ..Default::default()
            }],
            ..Default::default()
        };
        let today = d(2026, 5, 4);
        let v = overdue_followups(&state, today);
        assert_eq!(v.len(), 1);
        assert!(v[0].contains("Janke"));
        assert!(v[0].contains("10d"));
    }

    #[test]
    fn brief_renders_hot_overdue_awaiting() {
        let state = ProjectState {
            name: "FCLC".into(),
            phase: "SUBMITTED".into(),
            goals: vec!["Win EIC".into()],
            milestones: vec![Milestone {
                id: "submit".into(),
                deadline: Some(Utc.with_ymd_and_hms(2026, 5, 11, 0, 0, 0).unwrap()),
                status: "pending".into(),
                criticality: "high".into(),
                blockers: vec!["Need LoIs".into()],
            }],
            stakeholders: vec![
                Stakeholder {
                    name: "Janke".into(),
                    role: "co-PI".into(),
                    awaiting_reply: true,
                    expected_response_by: Some(d(2026, 5, 1)),
                    last_contact: Some(d(2026, 4, 28)),
                    ..Default::default()
                },
                Stakeholder {
                    name: "Geiger".into(),
                    role: "co-PI".into(),
                    awaiting_reply: true,
                    expected_response_by: Some(d(2026, 5, 9)),
                    last_contact: Some(d(2026, 5, 1)),
                    ..Default::default()
                },
            ],
            daily_checks: vec!["countdown".into()],
            ..Default::default()
        };
        let brief = morning_brief(&state, d(2026, 5, 4), &BriefExtras::default());
        assert!(brief.contains("📌 FCLC"));
        assert!(brief.contains("phase: SUBMITTED"));
        assert!(brief.contains("🔥 hot milestones"));
        assert!(brief.contains("submit"));
        assert!(brief.contains("Need LoIs"));
        assert!(brief.contains("📮 overdue follow-ups"));
        assert!(brief.contains("Janke"));
        assert!(brief.contains("⏳ awaiting reply"));
        assert!(brief.contains("Geiger"));
        assert!(brief.contains("✅ daily checks"));
    }

    #[test]
    fn brief_emits_nothing_on_fire_when_quiet() {
        let state = ProjectState {
            name: "Idle".into(),
            phase: "DRAFT".into(),
            ..Default::default()
        };
        let brief = morning_brief(&state, d(2026, 5, 4), &BriefExtras::default());
        assert!(brief.contains("✨ nothing on fire today."));
    }

    #[test]
    fn brief_includes_extras_when_provided() {
        let state = ProjectState {
            name: "FCLC".into(),
            phase: "DRAFT".into(),
            ..Default::default()
        };
        let extras = BriefExtras {
            phase_actions: vec!["Lock concept note".into()],
            kpi_block: "📈 KPIs — FCLC\n  • pubmed: 7/8".into(),
        };
        let brief = morning_brief(&state, d(2026, 5, 4), &extras);
        assert!(brief.contains("📐 phase DRAFT — next actions:"));
        assert!(brief.contains("Lock concept note"));
        assert!(brief.contains("📈 KPIs — FCLC"));
    }

    #[test]
    fn brief_sorts_hot_milestones_by_days() {
        let state = ProjectState {
            name: "X".into(),
            phase: "DRAFT".into(),
            milestones: vec![
                Milestone {
                    id: "later".into(),
                    deadline: Some(Utc.with_ymd_and_hms(2026, 5, 10, 0, 0, 0).unwrap()),
                    status: "pending".into(),
                    criticality: "high".into(),
                    blockers: vec![],
                },
                Milestone {
                    id: "sooner".into(),
                    deadline: Some(Utc.with_ymd_and_hms(2026, 5, 6, 0, 0, 0).unwrap()),
                    status: "pending".into(),
                    criticality: "high".into(),
                    blockers: vec![],
                },
            ],
            ..Default::default()
        };
        let brief = morning_brief(&state, d(2026, 5, 4), &BriefExtras::default());
        let pos_sooner = brief.find("sooner").unwrap();
        let pos_later = brief.find("later").unwrap();
        assert!(pos_sooner < pos_later);
    }
}
