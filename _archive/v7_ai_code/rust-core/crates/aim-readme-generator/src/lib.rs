//! aim-readme-generator — synthesise project README from state (PR1).
//!
//! Port of `agents/readme_generator.py`. Combines project YAML
//! (phase/goals/milestones/stakeholders/KPIs) with memory + git log +
//! phase-aware actions into a deterministic markdown skeleton.
//!
//! All side-effecting collaborators sit behind traits so the template
//! is testable without filesystem / git / LLM access.

use std::path::PathBuf;

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ReadmeError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, ReadmeError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Milestone {
    pub id: String,
    pub status: String,
    pub criticality: String,
    /// Days to deadline; `None` if no deadline set. Negative = overdue.
    pub days_to_deadline: Option<i32>,
    pub blockers: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Stakeholder {
    pub name: String,
    pub role: Option<String>,
    pub awaiting_reply: bool,
    pub expected_response_by: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ProjectState {
    pub name: String,
    pub phase: String,
    pub canonical: Option<String>,
    pub goals: Vec<String>,
    pub milestones: Vec<Milestone>,
    pub stakeholders: Vec<Stakeholder>,
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait KpiBlock: Send + Sync {
    fn render(&self, project: &str) -> Option<String>;
}

pub struct NoKpiBlock;
impl KpiBlock for NoKpiBlock {
    fn render(&self, _: &str) -> Option<String> {
        None
    }
}

pub trait PhaseActions: Send + Sync {
    fn next_actions(&self, phase: &str) -> Vec<String>;
}

pub struct NoPhaseActions;
impl PhaseActions for NoPhaseActions {
    fn next_actions(&self, _: &str) -> Vec<String> {
        Vec::new()
    }
}

pub trait GitLog: Send + Sync {
    fn recent(&self, project_root: &std::path::Path, limit: usize) -> Vec<String>;
}

pub struct NoGitLog;
impl GitLog for NoGitLog {
    fn recent(&self, _: &std::path::Path, _: usize) -> Vec<String> {
        Vec::new()
    }
}

pub trait MemoryTitles: Send + Sync {
    fn titles_for(&self, project: &str, max_n: usize) -> Vec<String>;
}

pub struct NoMemoryTitles;
impl MemoryTitles for NoMemoryTitles {
    fn titles_for(&self, _: &str, _: usize) -> Vec<String> {
        Vec::new()
    }
}

// ── deadline label ─────────────────────────────────────────────────────────

pub fn deadline_label(days_to_deadline: Option<i32>) -> Option<String> {
    match days_to_deadline {
        Some(d) if d > 0 => Some(format!("in {}d", d)),
        Some(0) => Some("TODAY".into()),
        Some(d) if d < 0 => Some(format!("OVERDUE {}d", -d)),
        _ => None,
    }
}

// ── generator ──────────────────────────────────────────────────────────────

pub struct Generator<'a> {
    pub kpi: &'a dyn KpiBlock,
    pub phase: &'a dyn PhaseActions,
    pub git: &'a dyn GitLog,
    pub memory: &'a dyn MemoryTitles,
}

impl<'a> Generator<'a> {
    pub fn new() -> GeneratorBuilder<'a> {
        GeneratorBuilder::default()
    }

    pub fn generate(&self, state: &ProjectState, project_root: &std::path::Path, today: NaiveDate) -> String {
        let mut md: Vec<String> = Vec::new();
        md.push(format!("# {}", state.name));
        md.push(String::new());
        md.push(format!(
            "_Last regenerated: {} via `agents.readme_generator` — review before committing._",
            today
        ));
        md.push(String::new());
        md.push(format!("**Phase:** `{}`", state.phase));
        if let Some(c) = &state.canonical {
            md.push(format!("**Canonical path:** `{}`", c));
        }
        md.push(String::new());

        if !state.goals.is_empty() {
            md.push("## Goals".into());
            for g in &state.goals {
                md.push(format!("- {}", g));
            }
            md.push(String::new());
        }

        if !state.milestones.is_empty() {
            md.push("## Milestones".into());
            for m in &state.milestones {
                let mut line = format!("- **{}** — {}, {}", m.id, m.status, m.criticality);
                if let Some(tag) = deadline_label(m.days_to_deadline) {
                    line.push_str(&format!("  ({})", tag));
                }
                md.push(line);
                for b in m.blockers.iter().take(3) {
                    md.push(format!("  - blocker: {}", b));
                }
            }
            md.push(String::new());
        }

        if !state.stakeholders.is_empty() {
            md.push("## Stakeholders".into());
            for s in &state.stakeholders {
                let mark = if s.awaiting_reply { "🟡" } else { "🟢" };
                let mut line = format!(
                    "- {} **{}** — {}",
                    mark,
                    s.name,
                    s.role.as_deref().unwrap_or("?")
                );
                if s.awaiting_reply {
                    if let Some(by) = &s.expected_response_by {
                        line.push_str(&format!("  (awaiting since {})", by));
                    }
                }
                md.push(line);
            }
            md.push(String::new());
        }

        let actions = self.phase.next_actions(&state.phase);
        if !actions.is_empty() {
            md.push(format!("## Next actions ({})", state.phase));
            for a in actions {
                md.push(format!("- {}", a));
            }
            md.push(String::new());
        }

        if let Some(kpi_block) = self.kpi.render(&state.name) {
            md.push("## KPIs".into());
            md.push("```".into());
            for line in kpi_block.lines() {
                md.push(line.to_string());
            }
            md.push("```".into());
            md.push(String::new());
        }

        let log_lines = self.git.recent(project_root, 8);
        if !log_lines.is_empty() {
            md.push("## Recent activity".into());
            for l in log_lines {
                md.push(format!("- {}", l));
            }
            md.push(String::new());
        }

        let titles = self.memory.titles_for(&state.name, 8);
        if !titles.is_empty() {
            md.push("## Project memory".into());
            for t in titles {
                md.push(format!("- {}", t));
            }
            md.push(String::new());
        }

        md.push("---".into());
        md.push("_Generated by AIM 2026-05-03 — see `agents/readme_generator.py`._".into());
        let mut text = md.join("\n");
        // Trim trailing whitespace, ensure single trailing newline
        while text.ends_with('\n') {
            text.pop();
        }
        text.push('\n');
        text
    }
}

#[derive(Default)]
pub struct GeneratorBuilder<'a> {
    kpi: Option<&'a dyn KpiBlock>,
    phase: Option<&'a dyn PhaseActions>,
    git: Option<&'a dyn GitLog>,
    memory: Option<&'a dyn MemoryTitles>,
}

impl<'a> GeneratorBuilder<'a> {
    pub fn kpi(mut self, k: &'a dyn KpiBlock) -> Self {
        self.kpi = Some(k);
        self
    }
    pub fn phase(mut self, p: &'a dyn PhaseActions) -> Self {
        self.phase = Some(p);
        self
    }
    pub fn git(mut self, g: &'a dyn GitLog) -> Self {
        self.git = Some(g);
        self
    }
    pub fn memory(mut self, m: &'a dyn MemoryTitles) -> Self {
        self.memory = Some(m);
        self
    }
    pub fn build(
        self,
        defaults_kpi: &'a dyn KpiBlock,
        defaults_phase: &'a dyn PhaseActions,
        defaults_git: &'a dyn GitLog,
        defaults_memory: &'a dyn MemoryTitles,
    ) -> Generator<'a> {
        Generator {
            kpi: self.kpi.unwrap_or(defaults_kpi),
            phase: self.phase.unwrap_or(defaults_phase),
            git: self.git.unwrap_or(defaults_git),
            memory: self.memory.unwrap_or(defaults_memory),
        }
    }
}

// ── filesystem write ───────────────────────────────────────────────────────

/// Write the generated text to `<project_root>/README_AUTO.md` (or a
/// caller-supplied destination). Mirrors Python `write()`.
pub fn write_readme(text: &str, dest: &std::path::Path) -> Result<PathBuf> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(dest, text)?;
    Ok(dest.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn date() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 5).unwrap()
    }

    fn minimal_state() -> ProjectState {
        ProjectState {
            name: "FCLC".into(),
            phase: "SUBMITTED".into(),
            ..Default::default()
        }
    }

    fn builder<'a>(
        k: &'a dyn KpiBlock,
        p: &'a dyn PhaseActions,
        g: &'a dyn GitLog,
        m: &'a dyn MemoryTitles,
    ) -> Generator<'a> {
        Generator::new().build(k, p, g, m)
    }

    fn default_gen<'a>() -> (NoKpiBlock, NoPhaseActions, NoGitLog, NoMemoryTitles) {
        (NoKpiBlock, NoPhaseActions, NoGitLog, NoMemoryTitles)
    }

    // ── deadline_label ─────────────────────────────────────────────────────

    #[test]
    fn deadline_label_branches() {
        assert_eq!(deadline_label(Some(7)).as_deref(), Some("in 7d"));
        assert_eq!(deadline_label(Some(0)).as_deref(), Some("TODAY"));
        assert_eq!(deadline_label(Some(-3)).as_deref(), Some("OVERDUE 3d"));
        assert_eq!(deadline_label(None), None);
    }

    // ── basic render ───────────────────────────────────────────────────────

    #[test]
    fn renders_minimal_skeleton() {
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("# FCLC"));
        assert!(s.contains("**Phase:** `SUBMITTED`"));
        assert!(s.contains("Last regenerated: 2026-05-05"));
        assert!(s.ends_with("\n"));
    }

    #[test]
    fn omits_optional_sections_when_empty() {
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(!s.contains("## Goals"));
        assert!(!s.contains("## Milestones"));
        assert!(!s.contains("## Stakeholders"));
        assert!(!s.contains("## KPIs"));
        assert!(!s.contains("## Recent activity"));
    }

    // ── goals / milestones / stakeholders ──────────────────────────────────

    #[test]
    fn renders_goals_section() {
        let mut state = minimal_state();
        state.goals = vec!["Land EIC submission".into(), "Maintain DB integrity".into()];
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&state, std::path::Path::new("/tmp"), date());
        assert!(s.contains("## Goals"));
        assert!(s.contains("- Land EIC submission"));
    }

    #[test]
    fn renders_milestones_with_deadline_and_blockers() {
        let mut state = minimal_state();
        state.milestones = vec![Milestone {
            id: "draft-deadline".into(),
            status: "open".into(),
            criticality: "high".into(),
            days_to_deadline: Some(5),
            blockers: vec!["BOM order".into(), "co-PI signoff".into()],
        }];
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&state, std::path::Path::new("/tmp"), date());
        assert!(s.contains("## Milestones"));
        assert!(s.contains("**draft-deadline** — open, high  (in 5d)"));
        assert!(s.contains("- blocker: BOM order"));
        assert!(s.contains("- blocker: co-PI signoff"));
    }

    #[test]
    fn renders_stakeholder_status_marks() {
        let mut state = minimal_state();
        state.stakeholders = vec![
            Stakeholder {
                name: "Geiger".into(),
                role: Some("Co-PI".into()),
                awaiting_reply: true,
                expected_response_by: Some("2026-05-10".into()),
            },
            Stakeholder {
                name: "Janke".into(),
                role: Some("Advisor".into()),
                awaiting_reply: false,
                expected_response_by: None,
            },
        ];
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&state, std::path::Path::new("/tmp"), date());
        assert!(s.contains("🟡 **Geiger** — Co-PI"));
        assert!(s.contains("(awaiting since 2026-05-10)"));
        assert!(s.contains("🟢 **Janke**"));
    }

    // ── pluggable sources ──────────────────────────────────────────────────

    struct StubKpi;
    impl KpiBlock for StubKpi {
        fn render(&self, _: &str) -> Option<String> {
            Some("kpi 1: 0.85\nkpi 2: 12.0".into())
        }
    }

    #[test]
    fn renders_kpi_block_when_present() {
        let k = StubKpi;
        let (.., p, g, m) = (NoKpiBlock, NoPhaseActions, NoGitLog, NoMemoryTitles);
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("## KPIs"));
        assert!(s.contains("```"));
        assert!(s.contains("kpi 1: 0.85"));
        assert!(s.contains("kpi 2: 12.0"));
    }

    struct StubPhase(Vec<String>);
    impl PhaseActions for StubPhase {
        fn next_actions(&self, _: &str) -> Vec<String> {
            self.0.clone()
        }
    }

    #[test]
    fn renders_phase_actions() {
        let k = NoKpiBlock;
        let p = StubPhase(vec!["Submit".into(), "Notify reviewers".into()]);
        let (g, m) = (NoGitLog, NoMemoryTitles);
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("## Next actions (SUBMITTED)"));
        assert!(s.contains("- Submit"));
        assert!(s.contains("- Notify reviewers"));
    }

    struct StubGit(Vec<String>);
    impl GitLog for StubGit {
        fn recent(&self, _: &std::path::Path, _: usize) -> Vec<String> {
            self.0.clone()
        }
    }

    #[test]
    fn renders_git_log_section() {
        let k = NoKpiBlock;
        let p = NoPhaseActions;
        let g = StubGit(vec!["abc1234 add tests".into(), "def5678 fix lint".into()]);
        let m = NoMemoryTitles;
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("## Recent activity"));
        assert!(s.contains("abc1234 add tests"));
        assert!(s.contains("def5678 fix lint"));
    }

    struct StubMemory(Vec<String>);
    impl MemoryTitles for StubMemory {
        fn titles_for(&self, _: &str, _: usize) -> Vec<String> {
            self.0.clone()
        }
    }

    #[test]
    fn renders_memory_titles() {
        let (k, p, g) = (NoKpiBlock, NoPhaseActions, NoGitLog);
        let m = StubMemory(vec!["`project_fclc.md` — main project file".into()]);
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("## Project memory"));
        assert!(s.contains("project_fclc.md"));
    }

    #[test]
    fn renders_canonical_path_when_present() {
        let mut state = minimal_state();
        state.canonical = Some("~/Desktop/FCLC".into());
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&state, std::path::Path::new("/tmp"), date());
        assert!(s.contains("**Canonical path:** `~/Desktop/FCLC`"));
    }

    #[test]
    fn ends_with_generator_attribution() {
        let (k, p, g, m) = default_gen();
        let gen = builder(&k, &p, &g, &m);
        let s = gen.generate(&minimal_state(), std::path::Path::new("/tmp"), date());
        assert!(s.contains("---"));
        assert!(s.contains("_Generated by AIM"));
    }

    // ── write_readme ───────────────────────────────────────────────────────

    #[test]
    fn write_readme_creates_file_under_dest() {
        let tmp = tempfile::TempDir::new().unwrap();
        let dest = tmp.path().join("FCLC").join("README_AUTO.md");
        let p = write_readme("# Hello\n", &dest).unwrap();
        assert!(p.exists());
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "# Hello\n");
    }

    #[test]
    fn write_readme_creates_parent_dirs() {
        let tmp = tempfile::TempDir::new().unwrap();
        let dest = tmp.path().join("nested/dir/README_AUTO.md");
        write_readme("body", &dest).unwrap();
        assert!(dest.exists());
    }
}
