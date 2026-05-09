//! aim-brief-preferences — user-tunable brief delivery (B2).
//!
//! Port of `agents/brief_preferences.py`. Reads `USER/preferences/brief.yaml`
//! (or `$AIM_BRIEF_PREFS` override) and returns a single resolved
//! [`Preferences`] object that the daily / weekly digest scripts consult
//! before delivery.
//!
//! ## Schema
//!
//! ```yaml
//! lang:        ru                # default RU; ka / en
//! user_name:   Джаба             # injected into preamble
//! quiet_hours: ["23:00", "07:00"]
//! channels:
//!   daily:     [telegram, stdout]
//!   weekly:    [telegram, email, stdout]
//! include:
//!   sections:  [hot_milestones, overdue_followups, ...]
//!   projects:  ["FCLC", "MCOA"]
//! exclude:
//!   projects:  []
//! digest:
//!   window_days: 7
//! ```
//!
//! Defaults are conservative — missing fields fall back to lang=ru,
//! channels=[telegram,stdout], all sections, all projects.

use chrono::NaiveTime;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PrefsError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Preferences {
    pub lang: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quiet_start: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quiet_end: Option<String>,
    pub daily_channels: Vec<String>,
    pub weekly_channels: Vec<String>,
    pub include_sections: Vec<String>,
    pub include_projects: Vec<String>,
    pub exclude_projects: Vec<String>,
    pub digest_window_days: u32,
}

impl Default for Preferences {
    fn default() -> Self {
        Self {
            lang: "ru".into(),
            user_name: None,
            quiet_start: None,
            quiet_end: None,
            daily_channels: vec!["telegram".into(), "stdout".into()],
            weekly_channels: vec!["telegram".into(), "email".into(), "stdout".into()],
            include_sections: vec![
                "hot_milestones".into(),
                "overdue_followups".into(),
                "awaiting_reply".into(),
                "deadlines".into(),
                "kpis".into(),
                "phase_actions".into(),
            ],
            include_projects: Vec::new(),
            exclude_projects: Vec::new(),
            digest_window_days: 7,
        }
    }
}

impl Preferences {
    pub fn project_visible(&self, name: &str) -> bool {
        if !self.exclude_projects.is_empty() && self.exclude_projects.iter().any(|p| p == name) {
            return false;
        }
        if !self.include_projects.is_empty() {
            return self.include_projects.iter().any(|p| p == name);
        }
        true
    }

    pub fn section_visible(&self, name: &str) -> bool {
        self.include_sections.is_empty() || self.include_sections.iter().any(|s| s == name)
    }
}

pub fn default_prefs_path() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_BRIEF_PREFS") {
        let p = p.trim();
        if !p.is_empty() {
            return expand_tilde(p);
        }
    }
    PathBuf::from("USER/preferences/brief.yaml")
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

pub fn load(path: &Path) -> Preferences {
    let mut prefs = Preferences::default();
    if !path.exists() {
        return prefs;
    }
    let raw = match std::fs::read_to_string(path) {
        Ok(r) => r,
        Err(_) => return prefs,
    };
    let parsed: serde_yaml::Value = match serde_yaml::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("brief prefs parse failed ({}): {e}", path.display());
            return prefs;
        }
    };
    let map = match parsed.as_mapping() {
        Some(m) => m,
        None => return prefs,
    };

    if let Some(v) = map.get("lang").and_then(|v| v.as_str()) {
        prefs.lang = v.to_lowercase();
    }
    if let Some(v) = map.get("user_name").and_then(|v| v.as_str()) {
        prefs.user_name = Some(v.to_string());
    }
    let (qs, qe) = parse_quiet(map.get("quiet_hours"));
    prefs.quiet_start = qs;
    prefs.quiet_end = qe;

    if let Some(channels) = map.get("channels").and_then(|v| v.as_mapping()) {
        if let Some(v) = channels.get("daily").and_then(|v| v.as_sequence()) {
            prefs.daily_channels = v
                .iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect();
        }
        if let Some(v) = channels.get("weekly").and_then(|v| v.as_sequence()) {
            prefs.weekly_channels = v
                .iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect();
        }
    }

    if let Some(include) = map.get("include").and_then(|v| v.as_mapping()) {
        if let Some(v) = include.get("sections").and_then(|v| v.as_sequence()) {
            prefs.include_sections = v
                .iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect();
        }
        if let Some(v) = include.get("projects").and_then(|v| v.as_sequence()) {
            prefs.include_projects = v
                .iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect();
        }
    }

    if let Some(exclude) = map.get("exclude").and_then(|v| v.as_mapping()) {
        if let Some(v) = exclude.get("projects").and_then(|v| v.as_sequence()) {
            prefs.exclude_projects = v
                .iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect();
        }
    }

    if let Some(digest) = map.get("digest").and_then(|v| v.as_mapping()) {
        if let Some(v) = digest.get("window_days").and_then(|v| v.as_u64()) {
            prefs.digest_window_days = v as u32;
        } else if let Some(v) = digest.get("window_days").and_then(|v| v.as_str()) {
            if let Ok(n) = v.parse() {
                prefs.digest_window_days = n;
            }
        }
    }

    prefs
}

fn parse_quiet(v: Option<&serde_yaml::Value>) -> (Option<String>, Option<String>) {
    let Some(v) = v else {
        return (None, None);
    };
    if let Some(seq) = v.as_sequence() {
        if seq.len() == 2 {
            let a = seq[0].as_str().map(String::from).unwrap_or_default();
            let b = seq[1].as_str().map(String::from).unwrap_or_default();
            return (Some(a), Some(b));
        }
    }
    (None, None)
}

/// True if `now` falls inside [quiet_start, quiet_end). Wraps midnight.
pub fn in_quiet_hours(prefs: &Preferences, now: NaiveTime) -> bool {
    let (Some(qs), Some(qe)) = (prefs.quiet_start.as_deref(), prefs.quiet_end.as_deref()) else {
        return false;
    };
    let start = match NaiveTime::parse_from_str(qs, "%H:%M") {
        Ok(t) => t,
        Err(_) => return false,
    };
    let end = match NaiveTime::parse_from_str(qe, "%H:%M") {
        Ok(t) => t,
        Err(_) => return false,
    };
    if start == end {
        return false;
    }
    if start < end {
        start <= now && now < end
    } else {
        // Wraps midnight (e.g. 23:00 → 07:00)
        now >= start || now < end
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveTime;
    use tempfile::TempDir;

    fn t(s: &str) -> NaiveTime {
        NaiveTime::parse_from_str(s, "%H:%M").unwrap()
    }

    #[test]
    fn default_matches_python_module() {
        let p = Preferences::default();
        assert_eq!(p.lang, "ru");
        assert_eq!(p.daily_channels, vec!["telegram", "stdout"]);
        assert_eq!(p.weekly_channels, vec!["telegram", "email", "stdout"]);
        assert_eq!(p.digest_window_days, 7);
        assert_eq!(p.include_sections.len(), 6);
    }

    #[test]
    fn load_returns_default_when_missing() {
        let dir = TempDir::new().unwrap();
        let p = load(&dir.path().join("missing.yaml"));
        assert_eq!(p, Preferences::default());
    }

    #[test]
    fn load_reads_lang_user_name_and_channels() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("brief.yaml");
        std::fs::write(
            &path,
            r#"lang: KA
user_name: Джаба
channels:
  daily: [stdout]
  weekly: [email, stdout]
"#,
        )
        .unwrap();
        let p = load(&path);
        assert_eq!(p.lang, "ka");
        assert_eq!(p.user_name.as_deref(), Some("Джаба"));
        assert_eq!(p.daily_channels, vec!["stdout"]);
        assert_eq!(p.weekly_channels, vec!["email", "stdout"]);
    }

    #[test]
    fn load_quiet_hours_parsed() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("brief.yaml");
        std::fs::write(
            &path,
            r#"quiet_hours: ["23:00", "07:00"]
"#,
        )
        .unwrap();
        let p = load(&path);
        assert_eq!(p.quiet_start.as_deref(), Some("23:00"));
        assert_eq!(p.quiet_end.as_deref(), Some("07:00"));
    }

    #[test]
    fn load_include_exclude_lists() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("brief.yaml");
        std::fs::write(
            &path,
            r#"include:
  sections: [deadlines, kpis]
  projects: [FCLC, MCOA]
exclude:
  projects: [HAP]
digest:
  window_days: 14
"#,
        )
        .unwrap();
        let p = load(&path);
        assert_eq!(p.include_sections, vec!["deadlines", "kpis"]);
        assert_eq!(p.include_projects, vec!["FCLC", "MCOA"]);
        assert_eq!(p.exclude_projects, vec!["HAP"]);
        assert_eq!(p.digest_window_days, 14);
    }

    #[test]
    fn project_visible_with_include_whitelist() {
        let mut p = Preferences::default();
        p.include_projects = vec!["FCLC".into(), "MCOA".into()];
        assert!(p.project_visible("FCLC"));
        assert!(p.project_visible("MCOA"));
        assert!(!p.project_visible("Other"));
    }

    #[test]
    fn project_visible_with_exclude_blacklist() {
        let mut p = Preferences::default();
        p.exclude_projects = vec!["HAP".into()];
        assert!(p.project_visible("FCLC"));
        assert!(!p.project_visible("HAP"));
    }

    #[test]
    fn project_visible_no_filters_returns_true() {
        let p = Preferences::default();
        assert!(p.project_visible("any"));
    }

    #[test]
    fn section_visible_basic() {
        let p = Preferences::default();
        assert!(p.section_visible("deadlines"));
        assert!(!p.section_visible("not_in_default_list"));
    }

    #[test]
    fn quiet_hours_normal_window() {
        let mut p = Preferences::default();
        p.quiet_start = Some("13:00".into());
        p.quiet_end = Some("14:00".into());
        assert!(in_quiet_hours(&p, t("13:30")));
        assert!(!in_quiet_hours(&p, t("12:59")));
        assert!(!in_quiet_hours(&p, t("14:00")));
    }

    #[test]
    fn quiet_hours_wraps_midnight() {
        let mut p = Preferences::default();
        p.quiet_start = Some("23:00".into());
        p.quiet_end = Some("07:00".into());
        assert!(in_quiet_hours(&p, t("23:30")));
        assert!(in_quiet_hours(&p, t("03:00")));
        assert!(!in_quiet_hours(&p, t("12:00")));
        assert!(!in_quiet_hours(&p, t("07:00")));
    }

    #[test]
    fn quiet_hours_unset_returns_false() {
        let p = Preferences::default();
        assert!(!in_quiet_hours(&p, t("03:00")));
    }

    #[test]
    fn quiet_hours_equal_returns_false() {
        let mut p = Preferences::default();
        p.quiet_start = Some("12:00".into());
        p.quiet_end = Some("12:00".into());
        assert!(!in_quiet_hours(&p, t("12:00")));
    }

    #[test]
    fn malformed_yaml_returns_default() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("broken.yaml");
        std::fs::write(&path, "lang: ru\nbad: : :").unwrap();
        let p = load(&path);
        // YAML parse fails → defaults
        assert_eq!(p, Preferences::default());
    }
}
