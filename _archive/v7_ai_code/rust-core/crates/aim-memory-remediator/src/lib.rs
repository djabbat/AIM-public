//! aim-memory-remediator — suggest fixes for broken paths (RM1).
//!
//! Port of `agents/memory_remediator.py`. memory_monitor reports
//! `broken_path: missing` references in memory files. Most of those
//! paths weren't deleted — they were *renamed* (e.g. `~/Desktop/E0/`
//! → `~/Desktop/PhD/E0/` per the project relocation memory). This
//! crate:
//!
//! 1. Takes a list of `(memory_file, broken_path)` findings (the host
//!    threads them in from `aim-memory-monitor` once that lands).
//! 2. For each broken path, walks `desktop_roots` looking for files
//!    or dirs whose basename matches; ranks candidates by how many
//!    of the original path components reappear in the candidate.
//! 3. Returns [`Suggestion`] with `confidence` (high / medium / low).
//!
//! Never auto-edits memory. The output is a punch list for the human.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RemediatorError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    High,
    Medium,
    Low,
}

impl Confidence {
    pub fn as_str(self) -> &'static str {
        match self {
            Confidence::High => "high",
            Confidence::Medium => "medium",
            Confidence::Low => "low",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BrokenPath {
    pub memory_file: String,
    pub broken_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Suggestion {
    pub memory_file: String,
    pub broken_path: String,
    pub candidates: Vec<String>,
    pub confidence: Confidence,
}

impl Suggestion {
    pub fn best(&self) -> Option<&str> {
        self.candidates.first().map(|s| s.as_str())
    }
}

pub fn default_desktop_roots() -> Vec<PathBuf> {
    if let Ok(env) = std::env::var("AIM_DESKTOP_ROOTS") {
        let trimmed = env.trim();
        if !trimmed.is_empty() {
            return env
                .split(':')
                .filter(|s| !s.trim().is_empty())
                .map(expand_tilde)
                .collect();
        }
    }
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    vec![home.join("Desktop")]
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

fn basename(path: &str) -> String {
    Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string()
}

fn path_components(path: &str) -> HashSet<String> {
    let p = expand_tilde(path);
    p.components()
        .filter_map(|c| match c {
            std::path::Component::Normal(s) => s.to_str().map(String::from),
            _ => None,
        })
        .filter(|s| s.len() > 2 && s != "Desktop" && s != "home" && s != "/")
        .collect()
}

fn confidence(n_candidates: usize, basename: &str) -> Confidence {
    if n_candidates == 0 {
        return Confidence::Low;
    }
    if n_candidates == 1 {
        return Confidence::High;
    }
    if basename.chars().count() > 8 && n_candidates <= 3 {
        return Confidence::Medium;
    }
    Confidence::Low
}

#[derive(Debug, Clone, Copy)]
pub struct FindOpts {
    pub max_results: usize,
    pub max_walk: usize,
}

impl Default for FindOpts {
    fn default() -> Self {
        Self {
            max_results: 5,
            max_walk: 50_000,
        }
    }
}

/// Walk `roots` looking for files/dirs whose basename matches the broken
/// path's basename. Score each by the number of path components that
/// also appear in the candidate's full path.
pub fn find_candidates(
    broken_path: &str,
    roots: &[PathBuf],
    opts: FindOpts,
) -> Vec<String> {
    let target = basename(broken_path);
    if target.is_empty() {
        return Vec::new();
    }
    let mut components = path_components(broken_path);
    components.remove(&target);
    let mut walked = 0usize;
    let mut matches: Vec<(i32, String)> = Vec::new();
    for root in roots {
        if !root.exists() {
            continue;
        }
        for entry in walkdir::WalkDir::new(root).follow_links(false) {
            let entry = match entry {
                Ok(e) => e,
                Err(_) => continue,
            };
            walked += 1;
            if walked > opts.max_walk {
                break;
            }
            let p = entry.path();
            let name = match p.file_name().and_then(|s| s.to_str()) {
                Some(n) => n,
                None => continue,
            };
            if name != target {
                continue;
            }
            let mut score = 0i32;
            let parts: HashSet<String> = p
                .components()
                .filter_map(|c| match c {
                    std::path::Component::Normal(s) => s.to_str().map(String::from),
                    _ => None,
                })
                .collect();
            for c in &components {
                if parts.contains(c) {
                    score += 1;
                }
            }
            matches.push((score, p.to_string_lossy().to_string()));
        }
        if walked > opts.max_walk {
            break;
        }
    }
    matches.sort_by(|a, b| b.0.cmp(&a.0));
    matches.into_iter().take(opts.max_results).map(|(_, p)| p).collect()
}

/// Build suggestions from a list of broken-path findings. The Python
/// module pulls these from `agents.memory_monitor.scan()`; the Rust
/// port lets the caller thread them in directly so this crate has no
/// dep on memory_monitor (not yet ported).
pub fn suggestions(
    findings: &[BrokenPath],
    roots: &[PathBuf],
    opts: FindOpts,
) -> Vec<Suggestion> {
    let mut out = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();
    for f in findings {
        let key = (f.memory_file.clone(), f.broken_path.clone());
        if !seen.insert(key) {
            continue;
        }
        let cands = find_candidates(&f.broken_path, roots, opts);
        let conf = confidence(cands.len(), &basename(&f.broken_path));
        out.push(Suggestion {
            memory_file: f.memory_file.clone(),
            broken_path: f.broken_path.clone(),
            candidates: cands,
            confidence: conf,
        });
    }
    out
}

pub fn summary(suggestions: &[Suggestion]) -> String {
    if suggestions.is_empty() {
        return "(no broken-path findings to remediate)".into();
    }
    let high: Vec<&Suggestion> = suggestions.iter().filter(|s| s.confidence == Confidence::High).collect();
    let med: Vec<&Suggestion> = suggestions.iter().filter(|s| s.confidence == Confidence::Medium).collect();
    let low: Vec<&Suggestion> = suggestions.iter().filter(|s| s.confidence == Confidence::Low).collect();
    let mut parts = vec![
        format!("🔧 Memory remediator — {} broken refs", suggestions.len()),
        format!(
            "  high: {} · medium: {} · low: {}",
            high.len(),
            med.len(),
            low.len()
        ),
    ];
    for s in high.iter().take(6) {
        parts.push(format!(
            "  • {}  →  replace `{}` with `{}`",
            s.memory_file,
            s.broken_path,
            s.best().unwrap_or("?")
        ));
    }
    for s in med.iter().take(4) {
        parts.push(format!(
            "  • {}  ({} candidates)  `{}` ≈ `{}` ?",
            s.memory_file,
            s.candidates.len(),
            s.broken_path,
            s.candidates.first().map(|s| s.as_str()).unwrap_or("?"),
        ));
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &Path, rel: &str, body: &str) -> PathBuf {
        let p = dir.join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn basename_extracts_filename() {
        assert_eq!(basename("/home/oem/Desktop/PhD/E0/README.md"), "README.md");
        assert_eq!(basename("E0"), "E0");
        assert_eq!(basename(""), "");
    }

    #[test]
    fn path_components_drops_short_and_special() {
        let c = path_components("/home/oem/Desktop/PhD/E0/Техническая_реализация.md");
        assert!(c.contains("oem"));
        assert!(c.contains("PhD"));
        // "E0" is len==2 → dropped by `len > 2` filter (matches Python)
        assert!(!c.contains("E0"));
        assert!(c.contains("Техническая_реализация.md"));
        assert!(!c.contains("Desktop"));
        assert!(!c.contains("home"));
    }

    #[test]
    fn confidence_zero_candidates_low() {
        assert_eq!(confidence(0, "name.md"), Confidence::Low);
    }

    #[test]
    fn confidence_one_candidate_high() {
        assert_eq!(confidence(1, "name.md"), Confidence::High);
    }

    #[test]
    fn confidence_short_basename_low() {
        assert_eq!(confidence(2, "x.md"), Confidence::Low);
    }

    #[test]
    fn confidence_long_basename_few_candidates_medium() {
        assert_eq!(confidence(2, "long_file_name.md"), Confidence::Medium);
        assert_eq!(confidence(3, "long_file_name.md"), Confidence::Medium);
        assert_eq!(confidence(4, "long_file_name.md"), Confidence::Low);
    }

    #[test]
    fn find_candidates_locates_renamed_basename() {
        let dir = TempDir::new().unwrap();
        // Old reference: ~/Desktop/E0/README.md (gone)
        // Real location:  ~/Desktop/PhD/E0/README.md
        let new_loc = write(&dir.path().join("PhD/E0"), "README.md", "x");
        let cands = find_candidates(
            &format!("{}/E0/README.md", dir.path().display()),
            &[dir.path().to_path_buf()],
            FindOpts::default(),
        );
        assert_eq!(cands.len(), 1);
        assert_eq!(cands[0], new_loc.to_string_lossy());
    }

    #[test]
    fn find_candidates_ranks_by_component_overlap() {
        let dir = TempDir::new().unwrap();
        // Two files share the basename, but one has more matching parts
        let close = write(&dir.path().join("PhD/E0"), "rig.md", "best");
        let far = write(&dir.path().join("Other/Random"), "rig.md", "noise");
        let cands = find_candidates(
            "/home/oem/Desktop/E0/PhD/rig.md",
            &[dir.path().to_path_buf()],
            FindOpts::default(),
        );
        // The candidate under PhD/E0 shares E0 + PhD with the broken path → higher score
        assert_eq!(cands[0], close.to_string_lossy());
        assert!(cands.contains(&far.to_string_lossy().to_string()));
    }

    #[test]
    fn find_candidates_empty_when_basename_absent() {
        let dir = TempDir::new().unwrap();
        write(&dir.path().join("a"), "different.md", "x");
        let cands = find_candidates(
            "/anywhere/wanted.md",
            &[dir.path().to_path_buf()],
            FindOpts::default(),
        );
        assert!(cands.is_empty());
    }

    #[test]
    fn find_candidates_respects_max_results() {
        let dir = TempDir::new().unwrap();
        for i in 0..10 {
            write(&dir.path().join(format!("d{i}")), "shared.md", "x");
        }
        let cands = find_candidates(
            "/path/to/shared.md",
            &[dir.path().to_path_buf()],
            FindOpts {
                max_results: 3,
                max_walk: 50_000,
            },
        );
        assert_eq!(cands.len(), 3);
    }

    #[test]
    fn find_candidates_skips_missing_root() {
        let cands = find_candidates(
            "/anywhere/wanted.md",
            &[PathBuf::from("/nonexistent/path")],
            FindOpts::default(),
        );
        assert!(cands.is_empty());
    }

    #[test]
    fn find_candidates_empty_basename_returns_empty() {
        let dir = TempDir::new().unwrap();
        let cands = find_candidates("", &[dir.path().to_path_buf()], FindOpts::default());
        assert!(cands.is_empty());
    }

    #[test]
    fn suggestions_dedups_repeat_findings() {
        let dir = TempDir::new().unwrap();
        write(&dir.path().join("PhD/E0"), "README.md", "x");
        let path = format!("{}/E0/README.md", dir.path().display());
        let findings = vec![
            BrokenPath {
                memory_file: "memo.md".into(),
                broken_path: path.clone(),
            },
            BrokenPath {
                memory_file: "memo.md".into(),
                broken_path: path.clone(),
            },
        ];
        let s = suggestions(
            &findings,
            &[dir.path().to_path_buf()],
            FindOpts::default(),
        );
        assert_eq!(s.len(), 1);
        assert_eq!(s[0].confidence, Confidence::High);
    }

    #[test]
    fn suggestions_distinct_findings_kept_separate() {
        let dir = TempDir::new().unwrap();
        write(&dir.path().join("PhD/E0"), "a.md", "x");
        write(&dir.path().join("PhD/E0"), "b.md", "y");
        let findings = vec![
            BrokenPath {
                memory_file: "m1.md".into(),
                broken_path: format!("{}/E0/a.md", dir.path().display()),
            },
            BrokenPath {
                memory_file: "m2.md".into(),
                broken_path: format!("{}/E0/b.md", dir.path().display()),
            },
        ];
        let s = suggestions(&findings, &[dir.path().to_path_buf()], FindOpts::default());
        assert_eq!(s.len(), 2);
    }

    #[test]
    fn suggestion_best_returns_first_candidate() {
        let s = Suggestion {
            memory_file: "m.md".into(),
            broken_path: "x.md".into(),
            candidates: vec!["a.md".into(), "b.md".into()],
            confidence: Confidence::Medium,
        };
        assert_eq!(s.best(), Some("a.md"));
    }

    #[test]
    fn suggestion_best_none_when_empty() {
        let s = Suggestion {
            memory_file: "m.md".into(),
            broken_path: "x.md".into(),
            candidates: vec![],
            confidence: Confidence::Low,
        };
        assert!(s.best().is_none());
    }

    #[test]
    fn summary_empty_input() {
        assert!(summary(&[]).contains("no broken-path findings"));
    }

    #[test]
    fn summary_groups_by_confidence() {
        let s = vec![
            Suggestion {
                memory_file: "m1.md".into(),
                broken_path: "old/x.md".into(),
                candidates: vec!["new/x.md".into()],
                confidence: Confidence::High,
            },
            Suggestion {
                memory_file: "m2.md".into(),
                broken_path: "longer_name.md".into(),
                candidates: vec!["a.md".into(), "b.md".into()],
                confidence: Confidence::Medium,
            },
        ];
        let txt = summary(&s);
        assert!(txt.contains("🔧 Memory remediator"));
        assert!(txt.contains("high: 1"));
        assert!(txt.contains("medium: 1"));
        assert!(txt.contains("replace `old/x.md`"));
        assert!(txt.contains("longer_name.md"));
    }
}
