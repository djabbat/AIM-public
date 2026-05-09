//! aim-diff-analyser — git-diff classifier + commit suggester (DA1).
//!
//! Port of `agents/diff_analyser.py`. Classifies a working-tree change set
//! into Conventional-Commit buckets (test/feat/fix/refactor/docs/build/
//! chore/perf/style/ci) and produces a short commit-message suggestion.
//!
//! Git access is abstracted behind [`GitContext`] so the classifier and
//! suggester are testable without invoking `git` or even having a repo.

use std::collections::BTreeMap;

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DiffError {
    #[error("git error: {0}")]
    Git(String),
}

pub type Result<T> = std::result::Result<T, DiffError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Analysis {
    pub files_changed: Vec<String>,
    pub files_added: Vec<String>,
    pub files_deleted: Vec<String>,
    pub insertions: u64,
    pub deletions: u64,
    pub bucket_counts: BTreeMap<String, usize>,
    pub primary_bucket: String,
    pub short_summary: String,
}

impl Analysis {
    pub fn is_empty(&self) -> bool {
        self.files_changed.is_empty()
            && self.files_added.is_empty()
            && self.files_deleted.is_empty()
    }
}

// ── git context trait ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct StatusRow {
    pub status: String,
    pub path: String,
}

pub trait GitContext: Send + Sync {
    fn porcelain(&self) -> Vec<StatusRow>;
    /// Combined HEAD diff text (used for keyword classification).
    fn diff_text(&self) -> String;
    fn diff_staged(&self) -> String;
    /// `(insertions, deletions)`.
    fn diff_stat(&self) -> (u64, u64);
}

/// Parse a `git status --porcelain=v1` line into a [`StatusRow`].
pub fn parse_porcelain_line(line: &str) -> Option<StatusRow> {
    if line.len() < 4 {
        return None;
    }
    let status = line[..2].to_string();
    let path = line[3..].trim().to_string();
    Some(StatusRow { status, path })
}

/// Parse the entire output of `git status --porcelain=v1`.
pub fn parse_porcelain(output: &str) -> Vec<StatusRow> {
    output
        .lines()
        .filter_map(parse_porcelain_line)
        .collect()
}

/// Parse `(ins, del)` from a `git diff --shortstat` line.
pub fn parse_shortstat(text: &str) -> (u64, u64) {
    let ins_re = Regex::new(r"(\d+)\s+insertion").unwrap();
    let del_re = Regex::new(r"(\d+)\s+deletion").unwrap();
    let ins = ins_re
        .captures(text)
        .and_then(|c| c.get(1))
        .and_then(|m| m.as_str().parse().ok())
        .unwrap_or(0);
    let del = del_re
        .captures(text)
        .and_then(|c| c.get(1))
        .and_then(|m| m.as_str().parse().ok())
        .unwrap_or(0);
    (ins, del)
}

// ── classification rules (order matters: first match wins) ─────────────────

static RULES: Lazy<Vec<(&'static str, Regex)>> = Lazy::new(|| {
    vec![
        (
            "test",
            Regex::new(r"(?:^|/)tests?(?:/|$)|_test\.|\.test\.|test_[\w\-]+\.py").unwrap(),
        ),
        ("docs", Regex::new(r"(?i)\.md$|\.rst$|^docs/|^README").unwrap()),
        (
            "ci",
            Regex::new(r"^\.github/|^\.gitlab-ci\.yml$|/ci\.yml$|circleci").unwrap(),
        ),
        (
            "build",
            Regex::new(r"^Cargo\.toml$|^pyproject\.toml$|^package\.json$|^Dockerfile|^Makefile$|requirements.*\.txt$").unwrap(),
        ),
        ("style", Regex::new(r"\.css$|\.scss$|\.sass$|\.less$").unwrap()),
        (
            "chore",
            Regex::new(r"^\.gitignore$|^LICENSE$|^\.editorconfig$").unwrap(),
        ),
        ("perf", Regex::new(r"(?i)perf|bench|optimi[sz]e").unwrap()),
    ]
});

pub fn bucket_for_path(path: &str) -> &'static str {
    for (name, pat) in RULES.iter() {
        if pat.is_match(path) {
            return name;
        }
    }
    "code"
}

/// Decide feat/fix/refactor for the "code" bucket using diff text + line counts.
pub fn heuristic_code_subtype(diff_text: &str, ins: u64, del: u64) -> &'static str {
    let low = diff_text.to_lowercase();
    let fix_signals = [
        "fix(", "fix:", "fixed ", "bugfix", "regression", "крэш", "ошибк",
    ];
    if fix_signals.iter().any(|kw| low.contains(kw)) {
        return "fix";
    }
    if ins > 5 * del.max(1) {
        return "feat";
    }
    if del > 2 * ins.max(1) {
        return "refactor";
    }
    "feat"
}

// ── analyse ────────────────────────────────────────────────────────────────

pub fn analyse(git: &dyn GitContext) -> Analysis {
    let rows = git.porcelain();
    let mut files_added: Vec<String> = Vec::new();
    let mut files_deleted: Vec<String> = Vec::new();
    let mut files_changed: Vec<String> = Vec::new();
    for row in &rows {
        let s = row.status.as_str();
        if s.contains('?') || s.contains('A') {
            files_added.push(row.path.clone());
        } else if s.contains('D') {
            files_deleted.push(row.path.clone());
        } else {
            files_changed.push(row.path.clone());
        }
    }

    let mut all_files: Vec<String> = files_added.iter().cloned().collect();
    all_files.extend(files_deleted.iter().cloned());
    all_files.extend(files_changed.iter().cloned());

    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    for p in &all_files {
        *counts.entry(bucket_for_path(p).to_string()).or_insert(0) += 1;
    }

    let (ins, del) = git.diff_stat();
    let mut primary = "chore".to_string();
    if !counts.is_empty() {
        // pick the bucket with the highest count; on tie, alphabetical (BTreeMap order)
        let max = *counts.values().max().unwrap_or(&0);
        if let Some((name, _)) = counts.iter().find(|(_, &v)| v == max) {
            primary = name.clone();
        }
    }
    if primary == "code" {
        let combined = format!("{}{}", git.diff_text(), git.diff_staged());
        primary = heuristic_code_subtype(&combined, ins, del).to_string();
    }

    let mut summary_parts: Vec<String> = Vec::new();
    if !files_added.is_empty() {
        summary_parts.push(format!("+{}", files_added.len()));
    }
    if !files_changed.is_empty() {
        summary_parts.push(format!("~{}", files_changed.len()));
    }
    if !files_deleted.is_empty() {
        summary_parts.push(format!("-{}", files_deleted.len()));
    }
    let short = format!(
        "{}  ({}+/{}- lines)",
        summary_parts.join(" "),
        ins,
        del
    )
    .trim()
    .to_string();

    Analysis {
        files_changed,
        files_added,
        files_deleted,
        insertions: ins,
        deletions: del,
        bucket_counts: counts,
        primary_bucket: primary,
        short_summary: short,
    }
}

// ── commit message suggestion ──────────────────────────────────────────────

/// Pick a scope from the most common top-level directory.
pub fn scope_hint(files: &[String]) -> String {
    if files.is_empty() {
        return String::new();
    }
    let mut tops: BTreeMap<&str, usize> = BTreeMap::new();
    for f in files {
        let head = f.split_once('/').map(|(h, _)| h).unwrap_or(f.as_str());
        *tops.entry(head).or_insert(0) += 1;
    }
    tops.into_iter()
        .max_by_key(|&(_, n)| n)
        .map(|(k, _)| k.to_string())
        .unwrap_or_default()
}

fn descr_for(bucket: &str, n_files: usize) -> String {
    match bucket {
        "test" => format!("add/update tests across {} files", n_files),
        "docs" => "update documentation".into(),
        "ci" => "tweak CI configuration".into(),
        "build" => "update build / dependencies".into(),
        "fix" => "fix bug".into(),
        "feat" => "add new functionality".into(),
        "refactor" => "refactor".into(),
        "perf" => "performance improvement".into(),
        "style" => "style updates".into(),
        _ => "chores".into(),
    }
}

pub fn suggest_message(analysis: &Analysis) -> String {
    if analysis.is_empty() {
        return "(no changes to commit)".into();
    }
    let mut all_files: Vec<String> = analysis.files_added.iter().cloned().collect();
    all_files.extend(analysis.files_changed.iter().cloned());
    all_files.extend(analysis.files_deleted.iter().cloned());
    let scope = scope_hint(&all_files);
    let bucket = analysis.primary_bucket.as_str();

    let subject_prefix = if !scope.is_empty() && scope != bucket {
        format!("{}({}): ", bucket, scope)
    } else {
        format!("{}: ", bucket)
    };

    let n_for_test = analysis.files_added.len() + analysis.files_changed.len();
    let descr = descr_for(bucket, n_for_test);
    let mut body = vec![
        format!("{}{}", subject_prefix, descr),
        "".into(),
        analysis.short_summary.clone(),
    ];
    if !analysis.bucket_counts.is_empty() {
        let mut entries: Vec<(&String, &usize)> = analysis.bucket_counts.iter().collect();
        entries.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
        let parts: Vec<String> = entries.iter().map(|(k, v)| format!("{}={}", k, v)).collect();
        body.push(format!("Buckets: {}", parts.join(", ")));
    }
    body.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stub git context ────────────────────────────────────────────────────

    #[derive(Default)]
    struct StubGit {
        rows: Mutex<Vec<StatusRow>>,
        diff: Mutex<String>,
        staged: Mutex<String>,
        stat: Mutex<(u64, u64)>,
    }
    impl StubGit {
        fn new() -> Self {
            Self::default()
        }
        fn add_row(&self, status: &str, path: &str) {
            self.rows.lock().push(StatusRow {
                status: status.into(),
                path: path.into(),
            });
        }
    }
    impl GitContext for StubGit {
        fn porcelain(&self) -> Vec<StatusRow> {
            self.rows.lock().clone()
        }
        fn diff_text(&self) -> String {
            self.diff.lock().clone()
        }
        fn diff_staged(&self) -> String {
            self.staged.lock().clone()
        }
        fn diff_stat(&self) -> (u64, u64) {
            *self.stat.lock()
        }
    }

    // ── parsers ────────────────────────────────────────────────────────────

    #[test]
    fn parse_porcelain_handles_modified_added_untracked() {
        let out = " M src/lib.rs\n?? new.txt\nA  staged.rs\n";
        let rows = parse_porcelain(out);
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0].path, "src/lib.rs");
        assert_eq!(rows[1].status.trim(), "??");
        assert_eq!(rows[2].path, "staged.rs");
    }

    #[test]
    fn parse_porcelain_skips_short_lines() {
        assert!(parse_porcelain("xx").is_empty());
        assert!(parse_porcelain_line("xx").is_none());
    }

    #[test]
    fn parse_shortstat_extracts_numbers() {
        let s = " 5 files changed, 123 insertions(+), 45 deletions(-)";
        assert_eq!(parse_shortstat(s), (123, 45));
    }

    #[test]
    fn parse_shortstat_handles_missing_fields() {
        assert_eq!(parse_shortstat(""), (0, 0));
        assert_eq!(
            parse_shortstat("only insertions: 7 insertions(+)"),
            (7, 0)
        );
    }

    // ── bucket_for_path ────────────────────────────────────────────────────

    #[test]
    fn bucket_test_files() {
        assert_eq!(bucket_for_path("tests/foo.rs"), "test");
        assert_eq!(bucket_for_path("src/foo_test.py"), "test");
        assert_eq!(bucket_for_path("src/test_widget.py"), "test");
    }

    #[test]
    fn bucket_docs_files() {
        assert_eq!(bucket_for_path("README.md"), "docs");
        assert_eq!(bucket_for_path("docs/intro.md"), "docs");
        assert_eq!(bucket_for_path("notes.rst"), "docs");
    }

    #[test]
    fn bucket_ci_files() {
        assert_eq!(bucket_for_path(".github/workflows/test.yml"), "ci");
        assert_eq!(bucket_for_path(".gitlab-ci.yml"), "ci");
    }

    #[test]
    fn bucket_build_files() {
        assert_eq!(bucket_for_path("Cargo.toml"), "build");
        assert_eq!(bucket_for_path("pyproject.toml"), "build");
        assert_eq!(bucket_for_path("Dockerfile"), "build");
        assert_eq!(bucket_for_path("requirements-dev.txt"), "build");
    }

    #[test]
    fn bucket_style_files() {
        assert_eq!(bucket_for_path("ui/main.css"), "style");
        assert_eq!(bucket_for_path("ui/main.scss"), "style");
    }

    #[test]
    fn bucket_chore_files() {
        assert_eq!(bucket_for_path(".gitignore"), "chore");
        assert_eq!(bucket_for_path("LICENSE"), "chore");
    }

    #[test]
    fn bucket_perf_keyword() {
        assert_eq!(bucket_for_path("src/perf_loop.rs"), "perf");
        assert_eq!(bucket_for_path("benchmarks/run.rs"), "perf");
    }

    #[test]
    fn bucket_code_default() {
        assert_eq!(bucket_for_path("src/lib.rs"), "code");
        assert_eq!(bucket_for_path("foo.go"), "code");
    }

    // ── heuristic_code_subtype ─────────────────────────────────────────────

    #[test]
    fn subtype_fix_keyword_in_diff() {
        assert_eq!(heuristic_code_subtype("fix: regression in parser", 10, 5), "fix");
        assert_eq!(heuristic_code_subtype("исправил ошибку", 10, 5), "fix");
    }

    #[test]
    fn subtype_feat_when_insertions_dominate() {
        // insertions 60, deletions 5 → 60 > 5*5 → feat
        assert_eq!(heuristic_code_subtype("", 60, 5), "feat");
    }

    #[test]
    fn subtype_refactor_when_deletions_dominate() {
        // deletions 30, insertions 10 → 30 > 2*10 → refactor
        assert_eq!(heuristic_code_subtype("", 10, 30), "refactor");
    }

    #[test]
    fn subtype_default_feat_when_unclear() {
        assert_eq!(heuristic_code_subtype("", 10, 8), "feat");
    }

    // ── analyse ────────────────────────────────────────────────────────────

    #[test]
    fn analyse_classifies_files_into_buckets() {
        let g = StubGit::new();
        g.add_row("M ", "src/lib.rs");
        g.add_row("??", "tests/new_test.rs");
        g.add_row("M ", "README.md");
        g.add_row("D ", "old.css");
        *g.stat.lock() = (50, 10);
        let a = analyse(&g);
        assert_eq!(a.files_changed.len(), 2);
        assert_eq!(a.files_added.len(), 1);
        assert_eq!(a.files_deleted.len(), 1);
        assert!(a.bucket_counts.contains_key("docs"));
        assert!(a.bucket_counts.contains_key("test"));
        assert!(a.bucket_counts.contains_key("style"));
        assert!(a.bucket_counts.contains_key("code"));
        // primary_bucket: 1+1+1+1 buckets, ties broken alphabetically; 'code'
        // collapses to feat/refactor/fix because of subtype heuristic
        assert!(matches!(
            a.primary_bucket.as_str(),
            "code" | "docs" | "test" | "style"
        ) || matches!(
            a.primary_bucket.as_str(),
            "feat" | "fix" | "refactor"
        ));
    }

    #[test]
    fn analyse_promotes_code_bucket_to_feat_when_insertions_dominate() {
        let g = StubGit::new();
        g.add_row("M ", "src/lib.rs");
        g.add_row("M ", "src/main.rs");
        *g.stat.lock() = (60, 5);
        let a = analyse(&g);
        assert_eq!(a.primary_bucket, "feat");
    }

    #[test]
    fn analyse_promotes_code_bucket_to_fix_on_keyword() {
        let g = StubGit::new();
        g.add_row("M ", "src/lib.rs");
        *g.diff.lock() = "fix: parser regression".into();
        *g.stat.lock() = (10, 5);
        let a = analyse(&g);
        assert_eq!(a.primary_bucket, "fix");
    }

    #[test]
    fn analyse_summary_format() {
        let g = StubGit::new();
        g.add_row("M ", "x.rs");
        g.add_row("??", "y.md");
        g.add_row("D ", "z.txt");
        *g.stat.lock() = (10, 5);
        let a = analyse(&g);
        // +1 ~1 -1
        assert!(a.short_summary.contains("+1"));
        assert!(a.short_summary.contains("~1"));
        assert!(a.short_summary.contains("-1"));
        assert!(a.short_summary.contains("(10+/5- lines)"));
    }

    #[test]
    fn analyse_empty_repo_returns_empty_analysis() {
        let g = StubGit::new();
        let a = analyse(&g);
        assert!(a.is_empty());
        assert_eq!(a.primary_bucket, "chore");
    }

    // ── scope_hint ─────────────────────────────────────────────────────────

    #[test]
    fn scope_hint_returns_most_common_top_dir() {
        let files = vec![
            "src/a.rs".to_string(),
            "src/b.rs".into(),
            "tests/c.rs".into(),
        ];
        assert_eq!(scope_hint(&files), "src");
    }

    #[test]
    fn scope_hint_handles_top_level_files() {
        let files = vec!["README.md".to_string()];
        assert_eq!(scope_hint(&files), "README.md");
    }

    #[test]
    fn scope_hint_empty_input() {
        assert_eq!(scope_hint(&[]), "");
    }

    // ── suggest_message ────────────────────────────────────────────────────

    #[test]
    fn suggest_message_no_changes() {
        let a = Analysis::default();
        assert_eq!(suggest_message(&a), "(no changes to commit)");
    }

    #[test]
    fn suggest_message_renders_subject_and_buckets() {
        let g = StubGit::new();
        g.add_row("??", "tests/new_test.rs");
        g.add_row("M ", "tests/foo_test.rs");
        *g.stat.lock() = (40, 5);
        let a = analyse(&g);
        let msg = suggest_message(&a);
        assert!(msg.starts_with("test"));
        assert!(msg.contains("add/update tests across 2 files"));
        assert!(msg.contains("Buckets: test=2"));
    }

    #[test]
    fn suggest_message_includes_scope_when_distinct() {
        let g = StubGit::new();
        g.add_row("M ", "src/lib.rs");
        g.add_row("M ", "src/main.rs");
        *g.stat.lock() = (60, 5);
        let a = analyse(&g);
        let msg = suggest_message(&a);
        assert!(msg.starts_with("feat(src):"));
    }
}
