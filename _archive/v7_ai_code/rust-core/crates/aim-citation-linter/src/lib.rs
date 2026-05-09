//! aim-citation-linter — repo-wide citation lint (PR2).
//!
//! Walks markdown files in a project tree, extracts every PMID/DOI/NCT/arXiv
//! reference via [`aim_citation_guard`], runs them through a [`Verifier`],
//! and reports unresolved references — the write-side analogue of the
//! runtime guard.
//!
//! Designed for two contexts:
//! - **weekly digest** — "X unresolved citations across N files"
//! - **pre-commit / pre-push hook** — exit non-zero if new unresolved
//!   refs land
//!
//! ## Public API
//! - [`Linter::lint`] — scan a directory, return a [`Report`]
//! - [`Report::has_problems`] / [`Report::summary`]

use aim_citation_guard::{extract, Citation, Kind, Verifier};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

const DEFAULT_IGNORE_DIRS: &[&str] = &[
    "_archive",
    "_exports",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "__pycache__",
    "_runtime_fixtures",
    "target",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Issue {
    pub file: String,
    pub line: u32,
    pub raw: String,
    pub kind: String,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Report {
    pub files_scanned: u32,
    pub files_with_issues: u32,
    pub issues: Vec<Issue>,
}

impl Report {
    pub fn has_problems(&self) -> bool {
        !self.issues.is_empty()
    }

    pub fn summary(&self) -> String {
        if self.issues.is_empty() {
            return format!("📚 Citations OK — scanned {} files.", self.files_scanned);
        }
        let head = format!(
            "📚 Citation lint — {} unresolved across {}/{} files",
            self.issues.len(),
            self.files_with_issues,
            self.files_scanned
        );
        let mut rows = vec![head];
        let mut by_file: std::collections::BTreeMap<&str, Vec<&Issue>> = Default::default();
        for i in &self.issues {
            by_file.entry(i.file.as_str()).or_default().push(i);
        }
        for (f, items) in by_file.iter().take(8) {
            rows.push(format!("  {}", f));
            for i in items.iter().take(3) {
                rows.push(format!(
                    "    L{}  {}:{}  — {}",
                    i.line, i.kind, i.raw, i.note
                ));
            }
        }
        rows.join("\n")
    }
}

#[derive(Debug, Clone, Default)]
pub struct LintOpts {
    pub ignore_globs: Vec<String>,
}

pub struct Linter<V: Verifier> {
    verifier: V,
}

impl<V: Verifier> Linter<V> {
    pub fn new(verifier: V) -> Self {
        Self { verifier }
    }

    pub fn lint(&self, root: &Path, opts: &LintOpts) -> Report {
        let mut files: Vec<PathBuf> = Vec::new();
        if root.exists() {
            for entry in walkdir::WalkDir::new(root)
                .follow_links(false)
                .into_iter()
                .filter_entry(|e| !is_ignored_component(e.path(), root))
            {
                let entry = match entry {
                    Ok(e) => e,
                    Err(_) => continue,
                };
                let p = entry.path();
                if !p.is_file() {
                    continue;
                }
                if p.extension().and_then(|s| s.to_str()) != Some("md") {
                    continue;
                }
                if matches_glob(p, root, &opts.ignore_globs) {
                    continue;
                }
                files.push(p.to_path_buf());
            }
        }
        files.sort();

        let mut issues: Vec<Issue> = Vec::new();
        let mut files_with_issues: BTreeSet<String> = BTreeSet::new();
        let scanned = files.len() as u32;

        for p in files {
            let text = match std::fs::read_to_string(&p) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let cites: Vec<Citation> = extract(&text);
            if cites.is_empty() {
                continue;
            }
            let mut produced_issues = false;
            for c in cites {
                let info = self.verifier.verify(c.kind, &c.raw);
                if !info.resolved {
                    let line = (text[..c.start].matches('\n').count() + 1) as u32;
                    let rel = p
                        .strip_prefix(root)
                        .unwrap_or(&p)
                        .to_string_lossy()
                        .to_string();
                    let note = if info.note.is_empty() {
                        "unresolved".to_string()
                    } else {
                        info.note.clone()
                    };
                    issues.push(Issue {
                        file: rel,
                        line,
                        raw: c.raw.clone(),
                        kind: kind_str(c.kind).to_string(),
                        note,
                    });
                    produced_issues = true;
                }
            }
            if produced_issues {
                files_with_issues.insert(p.to_string_lossy().to_string());
            }
        }
        Report {
            files_scanned: scanned,
            files_with_issues: files_with_issues.len() as u32,
            issues,
        }
    }
}

fn kind_str(k: Kind) -> &'static str {
    match k {
        Kind::Pmid => "pmid",
        Kind::Doi => "doi",
        Kind::Nct => "nct",
        Kind::Arxiv => "arxiv",
    }
}

fn is_ignored_component(path: &Path, root: &Path) -> bool {
    let rel = path.strip_prefix(root).unwrap_or(path);
    for comp in rel.components() {
        if let std::path::Component::Normal(name) = comp {
            if let Some(s) = name.to_str() {
                if DEFAULT_IGNORE_DIRS.contains(&s) {
                    return true;
                }
            }
        }
    }
    false
}

fn matches_glob(path: &Path, root: &Path, globs: &[String]) -> bool {
    if globs.is_empty() {
        return false;
    }
    let rel = path.strip_prefix(root).unwrap_or(path);
    let rel_str = rel.to_string_lossy();
    for pat in globs {
        if let Ok(g) = glob::Pattern::new(pat) {
            if g.matches(&rel_str) {
                return true;
            }
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_citation_guard::{AllowList, AlwaysUnresolved};
    use tempfile::TempDir;

    fn write(dir: &TempDir, rel: &str, body: &str) {
        let p = dir.path().join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(p, body).unwrap();
    }

    #[test]
    fn report_summary_when_clean() {
        let r = Report {
            files_scanned: 17,
            files_with_issues: 0,
            issues: vec![],
        };
        let s = r.summary();
        assert!(s.contains("📚 Citations OK"));
        assert!(s.contains("17"));
        assert!(!r.has_problems());
    }

    #[test]
    fn report_summary_groups_by_file() {
        let r = Report {
            files_scanned: 2,
            files_with_issues: 1,
            issues: vec![
                Issue {
                    file: "a.md".into(),
                    line: 7,
                    raw: "12345678".into(),
                    kind: "pmid".into(),
                    note: "not in PubMed".into(),
                },
                Issue {
                    file: "a.md".into(),
                    line: 9,
                    raw: "10.1000/x".into(),
                    kind: "doi".into(),
                    note: "Crossref miss".into(),
                },
            ],
        };
        let s = r.summary();
        assert!(s.contains("📚 Citation lint"));
        assert!(s.contains("L7"));
        assert!(s.contains("not in PubMed"));
    }

    #[test]
    fn lint_walks_md_files_only() {
        let dir = TempDir::new().unwrap();
        write(&dir, "a.md", "PMID: 12345678 here\n");
        write(&dir, "b.txt", "PMID: 99999999\n");
        write(&dir, "subdir/c.md", "doi:10.1000/abcd\n");
        let l = Linter::new(AlwaysUnresolved);
        let r = l.lint(dir.path(), &LintOpts::default());
        assert_eq!(r.files_scanned, 2);
        // Citation guard's PMID extractor only fires when PMID is in the
        // canonical form — confirm we got at least the issue from a.md.
        assert!(r.issues.iter().any(|i| i.file == "a.md"));
    }

    #[test]
    fn lint_skips_default_ignored_dirs() {
        let dir = TempDir::new().unwrap();
        write(&dir, "a.md", "PMID: 12345678\n");
        write(&dir, "_archive/old.md", "PMID: 99999999\n");
        write(&dir, "node_modules/x.md", "PMID: 11111111\n");
        write(&dir, ".git/y.md", "PMID: 22222222\n");
        let l = Linter::new(AlwaysUnresolved);
        let r = l.lint(dir.path(), &LintOpts::default());
        assert_eq!(r.files_scanned, 1);
        assert!(r.issues.iter().all(|i| i.file == "a.md"));
    }

    #[test]
    fn lint_respects_extra_globs() {
        let dir = TempDir::new().unwrap();
        write(&dir, "a.md", "PMID: 12345678\n");
        write(&dir, "draft.md", "PMID: 99999999\n");
        let opts = LintOpts {
            ignore_globs: vec!["draft*.md".into()],
        };
        let l = Linter::new(AlwaysUnresolved);
        let r = l.lint(dir.path(), &opts);
        assert_eq!(r.files_scanned, 1);
        assert!(r.issues.iter().all(|i| i.file == "a.md"));
    }

    #[test]
    fn lint_records_line_number() {
        let dir = TempDir::new().unwrap();
        // Citation appears on line 3
        write(&dir, "a.md", "intro\n\nPMID: 12345678\n");
        let l = Linter::new(AlwaysUnresolved);
        let r = l.lint(dir.path(), &LintOpts::default());
        assert!(!r.issues.is_empty());
        assert_eq!(r.issues[0].line, 3);
    }

    #[test]
    fn lint_clean_when_verifier_resolves_all() {
        let dir = TempDir::new().unwrap();
        write(&dir, "a.md", "PMID: 12345678\n");
        let allow = AllowList(&[("12345678", "Cited paper")]);
        let l = Linter::new(allow);
        let r = l.lint(dir.path(), &LintOpts::default());
        assert!(!r.has_problems(), "report: {}", r.summary());
    }

    #[test]
    fn lint_handles_missing_root() {
        let dir = TempDir::new().unwrap();
        let bogus = dir.path().join("does-not-exist");
        let l = Linter::new(AlwaysUnresolved);
        let r = l.lint(&bogus, &LintOpts::default());
        assert_eq!(r.files_scanned, 0);
        assert!(!r.has_problems());
    }
}
