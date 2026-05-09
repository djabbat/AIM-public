//! aim-weekly-project-digest — outward-facing weekly digest (Phase E port, 2026-05-06).
//!
//! Sister to existing `aim-weekly-digest` (which covers AIM-self
//! quality: pattern miner / ab router / prompt evolver). This digest
//! is *outward-facing*: project velocity, patient follow-up drift,
//! experiment uptime, stakeholder silence.
//!
//! Pure Rust port of `scripts/weekly_project_digest.py`. Eliminates
//! Python subprocess overhead and respects the Stack rule.

use chrono::{Datelike, NaiveDate};
use serde::Serialize;
use std::path::PathBuf;

use aim_experiment_owner::ExperimentOwner;
use aim_patient_comms::CommsStore;
use aim_stakeholder_tracker::Tracker;

#[derive(Debug, Clone, Default, Serialize)]
pub struct DigestSections {
    pub projects: String,
    pub stakeholder_silence: String,
    pub experiments: String,
    pub patient_drift: String,
}

/// Resolve a path that may be relative ("USER/projects") to a sensible
/// absolute one. Same logic as aim-daily-brief.
pub fn resolve_relative(p: PathBuf) -> PathBuf {
    if p.is_absolute() {
        return p;
    }
    if let Ok(c) = std::env::current_dir() {
        let cand = c.join(&p);
        if cand.exists() {
            return cand;
        }
    }
    if let Ok(root) = std::env::var("AIM_ROOT") {
        let cand = PathBuf::from(root).join(&p);
        if cand.exists() {
            return cand;
        }
    }
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home)
        .join("Desktop/LongevityCommon/AIM")
        .join(&p)
}

pub fn render_projects_section(today: NaiveDate) -> String {
    let proj_root = resolve_relative(aim_project_owner::projects_dir());
    let names = aim_project_owner::list_projects(&proj_root);
    if names.is_empty() {
        return "_(no projects configured)_".into();
    }
    let mut lines: Vec<String> = Vec::new();
    for name in names {
        let state = match aim_project_owner::load(&proj_root, &name) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let hot = aim_project_owner::hot_milestones(&state, today);
        let overdue: Vec<&aim_project_owner::Stakeholder> = state
            .stakeholders
            .iter()
            .filter(|s| s.overdue(today))
            .collect();
        if hot.is_empty() && overdue.is_empty() {
            continue;
        }
        let mut bits: Vec<String> = Vec::new();
        if !hot.is_empty() {
            bits.push(format!("{} hot", hot.len()));
        }
        if !overdue.is_empty() {
            bits.push(format!("{} overdue stakeholder", overdue.len()));
        }
        lines.push(format!(
            "**{}** ({}) — {}",
            state.name,
            state.phase,
            bits.join(", ")
        ));
    }
    if lines.is_empty() {
        "_(no projects with hot/overdue this week)_".into()
    } else {
        lines.join("\n")
    }
}

pub fn render_stakeholder_silence_section(min_days: i64, today: NaiveDate) -> String {
    // Reads the same SQLite DB Python `agents/stakeholder_tracker.py`
    // writes (`~/.cache/aim/contacts.db`). The Rust port lives in
    // `aim-stakeholder-tracker` and shares the schema.
    let db_path = stakeholder_db_path();
    if !db_path.exists() {
        return "_(no stakeholder DB found)_".into();
    }
    let tracker = match Tracker::open(&db_path) {
        Ok(t) => t,
        Err(e) => return format!("_(could not open stakeholder DB: {e})_"),
    };
    let silent = match tracker.silent_for(min_days, today) {
        Ok(v) => v,
        Err(e) => return format!("_(could not query silence: {e})_"),
    };
    if silent.is_empty() {
        return "_(no stakeholder silence patterns detected)_".into();
    }
    silent
        .iter()
        .map(|c| {
            let days = c.days_silent(today).unwrap_or(0);
            format!(
                "- {} ({}) — {}d silent",
                c.name,
                c.role.as_deref().unwrap_or("?"),
                days
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn stakeholder_db_path() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_CONTACTS_DB") {
        return PathBuf::from(p);
    }
    if let Ok(home) = std::env::var("AIM_HOME") {
        return PathBuf::from(home).join("contacts.db");
    }
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home)
        .join(".cache")
        .join("aim")
        .join("contacts.db")
}

pub fn render_experiments_section(today: NaiveDate) -> String {
    let exp_root = resolve_relative(aim_experiment_owner::experiments_dir());
    let owner = ExperimentOwner::new(exp_root);
    let body = owner.all_briefs(today);
    if body.contains("(no experiments") {
        "_(no experiments configured)_".into()
    } else {
        body
    }
}

pub fn render_patient_drift_section(today: NaiveDate) -> String {
    let store = match CommsStore::from_env() {
        Ok(s) => s,
        Err(_) => return "_(patient_comms DB unavailable)_".into(),
    };
    let overdue = match store.overdue_followups(today) {
        Ok(v) => v,
        Err(_) => return "_(could not query patient_comms)_".into(),
    };
    if overdue.is_empty() {
        return "_(no overdue patient follow-ups)_".into();
    }
    overdue
        .iter()
        .map(|f| {
            let d = f
                .expected_response_by
                .map(|d| (today - d).num_days())
                .unwrap_or(0);
            format!("- {} | {} | {}d past expected", f.patient_id, f.topic, d)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn compose(today: NaiveDate) -> DigestSections {
    DigestSections {
        projects: render_projects_section(today),
        stakeholder_silence: render_stakeholder_silence_section(14, today),
        experiments: render_experiments_section(today),
        patient_drift: render_patient_drift_section(today),
    }
}

pub fn render(today: NaiveDate, sections: &DigestSections) -> String {
    let iso = today.iso_week();
    let week = iso.week();
    let year = iso.year();
    let mut parts: Vec<String> = Vec::new();
    parts.push(format!(
        "# 📅 Weekly project digest — {} (W{:02}/{})",
        today.format("%Y-%m-%d"),
        week,
        year
    ));
    parts.push(String::new());
    parts.push(section("Projects (hot + overdue)", &sections.projects));
    parts.push(section("Stakeholder silence (≥14d)", &sections.stakeholder_silence));
    parts.push(section("Experiments", &sections.experiments));
    parts.push(section("Patient follow-up drift", &sections.patient_drift));
    parts
        .into_iter()
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

fn section(title: &str, body: &str) -> String {
    let body = body.trim();
    if body.is_empty() {
        return String::new();
    }
    format!("## {title}\n\n{body}\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn today() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 6).unwrap()
    }

    #[test]
    fn render_with_empty_sections_produces_header_only() {
        let sections = DigestSections::default();
        let s = render(today(), &sections);
        assert!(s.contains("Weekly project digest"));
        assert!(s.contains("W19/2026"));
    }

    #[test]
    fn section_helper_skips_empty() {
        assert_eq!(section("X", ""), "");
        assert_eq!(section("X", "   "), "");
        let s = section("Title", "body");
        assert!(s.starts_with("## Title\n\nbody"));
    }

    #[test]
    fn resolve_relative_absolute_passthrough() {
        let p = PathBuf::from("/tmp/x");
        assert_eq!(resolve_relative(p.clone()), p);
    }

    #[test]
    fn render_projects_no_root_returns_placeholder() {
        // Force resolution to a non-existent dir
        std::env::set_var("AIM_PROJECTS_DIR", "/nonexistent_aim_test_root");
        let r = render_projects_section(today());
        assert!(r.contains("no projects"));
        std::env::remove_var("AIM_PROJECTS_DIR");
    }

    #[test]
    fn render_experiments_no_root_returns_placeholder() {
        std::env::set_var("AIM_EXPERIMENTS_DIR", "/nonexistent_aim_test_root");
        let r = render_experiments_section(today());
        assert!(r.contains("no experiments"));
        std::env::remove_var("AIM_EXPERIMENTS_DIR");
    }

    #[test]
    fn render_patient_drift_handles_empty_db() {
        let tmp = tempfile::TempDir::new().unwrap();
        let db = tmp.path().join("comms.db");
        std::env::set_var("AIM_HOME", tmp.path());
        // Force CommsStore to use tmp db via env
        let _ = CommsStore::new(&db);
        let r = render_patient_drift_section(today());
        assert!(r.contains("no overdue") || r.contains("unavailable"));
        std::env::remove_var("AIM_HOME");
    }

    #[test]
    fn compose_returns_all_sections_filled() {
        let s = compose(today());
        // None of the four sections should be empty string —
        // each at minimum has a placeholder.
        assert!(!s.projects.is_empty());
        assert!(!s.stakeholder_silence.is_empty());
        assert!(!s.experiments.is_empty());
        assert!(!s.patient_drift.is_empty());
    }
}
