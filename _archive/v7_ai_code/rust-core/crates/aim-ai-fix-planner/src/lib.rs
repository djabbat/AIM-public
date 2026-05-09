//! aim-ai-fix-planner — S14.
//!
//! Turn shared self-diagnostic findings into an actionable punch-list.
//! For every cited `file:line`, read the actual source line and emit
//! a heuristic "open file X, look at line N, do thing Y" recommendation.
//!
//! Recommendations are deterministic (path-pattern + snippet keyword),
//! NOT LLM-generated — we don't introduce another stochastic layer
//! between the diagnostic loop and the human eye.
//!
//! Rust port of `AI/ai/fix_planner.py`. Suggestion list matches the
//! Python predecessor's order (path hints first, then snippet hints).

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileFix {
    /// repo-relative path
    pub path: String,
    /// sorted unique line numbers
    pub line_refs: Vec<u32>,
    /// {line: source line, no \n}
    pub snippets: BTreeMap<u32, String>,
    /// heuristic recommendation
    pub suggestion: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FixPlan {
    pub n_files: u64,
    pub n_lines: u64,
    pub files: Vec<FileFix>,
}

/// Parse `path[:line]` ref. Returns `None` for unparseable refs.
pub fn parse_ref(s: &str) -> Option<(String, Option<u32>)> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"^([\w./_\-]+\.\w+)(?::(\d+))?$").unwrap()
    });
    let stripped = s.trim().trim_matches('`');
    let caps = RE.captures(stripped)?;
    let path = caps.get(1)?.as_str().trim_start_matches("./").to_string();
    let line = caps
        .get(2)
        .and_then(|m| m.as_str().parse::<u32>().ok());
    Some((path, line))
}

/// Group findings by file; read cited source lines; emit one entry
/// per file with its suggestion.
///
/// `root` is the repo root that path refs are resolved against.
/// `context_lines` pulls extra surrounding lines into the snippet —
/// 0 means just the cited line.
pub fn plan<I, S>(shared_findings: I, root: &Path, context_lines: u32) -> FixPlan
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut by_file: BTreeMap<String, std::collections::BTreeSet<u32>> = BTreeMap::new();
    for ref_str in shared_findings {
        if let Some((path, line)) = parse_ref(ref_str.as_ref()) {
            let entry = by_file.entry(path).or_default();
            if let Some(l) = line {
                entry.insert(l);
            }
        }
    }

    let mut files: Vec<FileFix> = Vec::new();
    for (path, lines) in &by_file {
        let full: PathBuf = if Path::new(path).is_absolute() {
            PathBuf::from(path)
        } else {
            root.join(path)
        };
        let mut snippets: BTreeMap<u32, String> = BTreeMap::new();
        if full.is_file() {
            if let Ok(text) = std::fs::read_to_string(&full) {
                let source: Vec<&str> = text.split('\n').collect();
                for &ln in lines {
                    let start = ln.saturating_sub(context_lines).max(1);
                    let end = (ln + context_lines).min(source.len() as u32);
                    for j in start..=end {
                        if (1..=source.len() as u32).contains(&j) {
                            snippets.insert(j, source[(j - 1) as usize].to_string());
                        }
                    }
                }
            }
        }
        let suggestion = suggestion_for(path, &snippets);
        files.push(FileFix {
            path: path.clone(),
            line_refs: lines.iter().copied().collect(),
            snippets,
            suggestion,
        });
    }

    let n_lines = files.iter().map(|f| f.line_refs.len() as u64).sum();
    FixPlan {
        n_files: files.len() as u64,
        n_lines,
        files,
    }
}

// ── heuristics ──────────────────────────────────────────────────

const PATH_HINTS: &[(&str, &str)] = &[
    ("distillation_tracker",
     "DB hardening: WAL + UNIQUE index + INSERT OR REPLACE — see CRIT-2 fix pattern."),
    ("eval_synthesiser",
     "L_VERIFIABILITY: route persisted spec through citation_guard.extract — reject if fabricated PMID/DOI present."),
    ("gap_detector",
     "Iterator safety: materialise surrender_list with list(...) before second pass — CRIT-3 generator-safe pattern."),
    ("citation_guard",
     "Verifiability: pipe through citation_guard.verify(strict=true) before emit; reject fabricated refs."),
    ("patient",
     "Privacy: confirm Patients/ scope is gated; ensure L_PRIVACY check fires before any persist."),
    ("worktree",
     "Worktree isolation: ensure agents.worktree.isolate() wraps any code-modification flow before mutation."),
    ("self_modify",
     "Eval-gate: any self-modification must run through S1 evals (Δscore≥0.05, p≤0.05) before merging into main."),
    ("orchestrator",
     "Decision kernel: confirm L0–L3 + L_PRIVACY/CONSENT/VERIFIABILITY all fire on the path; do not bypass."),
];

pub fn suggestion_for(path: &str, snippets: &BTreeMap<u32, String>) -> String {
    let plow = path.to_lowercase();
    for (key, advice) in PATH_HINTS {
        if plow.contains(key) {
            return (*advice).to_string();
        }
    }
    let body: String = snippets
        .values()
        .cloned()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();

    if body.contains("patients/") {
        return "Privacy: confirm Patients/ scope is gated; ensure L_PRIVACY check fires before any persist.".into();
    }
    if body.contains("pmid") || body.contains("doi") || body.contains("citation") {
        return "Verifiability: pipe through citation_guard.verify(strict=true) before emit; reject fabricated refs.".into();
    }
    if body.contains("subprocess") || body.contains("shell=true") || body.contains("os.system") {
        return "Bash sandbox: route through agents.generalist._validate_bash or agents.worktree.isolate.".into();
    }
    if body.contains("sqlite") || body.contains("execute(") || body.contains("insert ") {
        return "DB hardening: use a guarded connection; WAL mode; INSERT OR REPLACE for idempotency.".into();
    }
    if body.contains("open(") || body.contains("write_text") || body.contains("file.write") {
        return "Path sandbox: validate target path against AIM_GENERALIST_ROOT and refuse secret-path patterns.".into();
    }
    if body.contains("except") && body.contains("pass") {
        return "Silent failure: swap `except: pass` for at least log.warning(...); preserve traceback.".into();
    }
    if body.contains("todo") || body.contains("fixme") || body.contains("xxx") {
        return "Stale TODO/FIXME — convert to GitHub issue or remove.".into();
    }
    if path.ends_with("_test.py") || path.starts_with("tests/") || path.contains("/tests/") {
        return "Test quality: add a negative-path assertion; freeze datetime.now() in fixtures.".into();
    }
    if has_magic_number(snippets) {
        return "Magic number — extract to module-level CONSTANT.".into();
    }
    if path.ends_with(".md") {
        return "Documentation: cross-check claim against source code.".into();
    }
    "Read the file at the cited line and decide if the model's concern is real before patching.".into()
}

fn has_magic_number(snippets: &BTreeMap<u32, String>) -> bool {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d{2,}\b").unwrap());
    snippets.values().any(|l| RE.is_match(l))
}

// ── render ──────────────────────────────────────────────────────

pub fn summary(plan_obj: &FixPlan) -> String {
    if plan_obj.n_files == 0 {
        return "(no shared findings to plan around)".into();
    }
    let mut out = vec![format!(
        "🛠 Fix plan — {} files, {} cited lines",
        plan_obj.n_files, plan_obj.n_lines
    )];
    for f in &plan_obj.files {
        let line_str = if f.line_refs.is_empty() {
            "—".to_string()
        } else {
            f.line_refs
                .iter()
                .map(|l| l.to_string())
                .collect::<Vec<_>>()
                .join(", ")
        };
        out.push(format!("  • {}  [L {}]", f.path, line_str));
        out.push(format!("      → {}", f.suggestion));
    }
    out.join("\n")
}

pub fn render_markdown(plan_obj: &FixPlan) -> String {
    let mut out: Vec<String> = Vec::new();
    out.push("# AIM/AI Fix Plan (from shared findings)".into());
    out.push(String::new());
    out.push(format!("**Files:** {}  ", plan_obj.n_files));
    out.push(format!("**Cited lines:** {}  ", plan_obj.n_lines));
    out.push(String::new());
    if plan_obj.n_files == 0 {
        out.push("_(no shared findings — nothing to plan)_".into());
        return out.join("\n");
    }
    for f in &plan_obj.files {
        out.push(format!("## `{}`", f.path));
        out.push(String::new());
        if !f.line_refs.is_empty() {
            out.push(format!(
                "Lines: {}",
                f.line_refs
                    .iter()
                    .map(|l| l.to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        out.push(String::new());
        out.push(format!("**Suggestion:** {}", f.suggestion));
        out.push(String::new());
        if !f.snippets.is_empty() {
            out.push("```".into());
            for (ln, line) in &f.snippets {
                out.push(format!("{:>4}: {}", ln, line));
            }
            out.push("```".into());
            out.push(String::new());
        }
    }
    out.join("\n")
}

pub fn write_plan(plan_obj: &FixPlan, dest: &Path) -> std::io::Result<PathBuf> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(dest, render_markdown(plan_obj))?;
    Ok(dest.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn parse_ref_with_line() {
        let r = parse_ref("agents/foo.py:42").unwrap();
        assert_eq!(r.0, "agents/foo.py");
        assert_eq!(r.1, Some(42));
    }

    #[test]
    fn parse_ref_without_line() {
        let r = parse_ref("README.md").unwrap();
        assert_eq!(r.0, "README.md");
        assert_eq!(r.1, None);
    }

    #[test]
    fn parse_ref_strips_leading_dotslash() {
        let r = parse_ref("./pkg/x.rs:7").unwrap();
        assert_eq!(r.0, "pkg/x.rs");
        assert_eq!(r.1, Some(7));
    }

    #[test]
    fn parse_ref_rejects_garbage() {
        assert!(parse_ref("just words").is_none());
        assert!(parse_ref("no_dot_at_all").is_none());
    }

    #[test]
    fn plan_groups_by_file() {
        let d = tempdir().unwrap();
        std::fs::write(d.path().join("a.rs"), "line1\nline2\nline3\n").unwrap();
        let p = plan(
            ["a.rs:1", "a.rs:3", "b.md:7", "garbage", "a.rs:1"],
            d.path(),
            0,
        );
        assert_eq!(p.n_files, 2);
        let a = p.files.iter().find(|f| f.path == "a.rs").unwrap();
        assert_eq!(a.line_refs, vec![1, 3]);
        assert_eq!(a.snippets.len(), 2);
        assert_eq!(a.snippets[&1], "line1");
        assert_eq!(a.snippets[&3], "line3");
    }

    #[test]
    fn suggestion_path_hint_matches() {
        let snip: BTreeMap<u32, String> = BTreeMap::new();
        let s = suggestion_for("AI/ai/eval_synthesiser.py", &snip);
        assert!(s.contains("L_VERIFIABILITY"));
    }

    #[test]
    fn suggestion_pmid_keyword_in_body() {
        let mut snip = BTreeMap::new();
        snip.insert(7, "verify PMID 36583780 here".to_string());
        let s = suggestion_for("notes.md", &snip);
        assert!(s.contains("citation_guard"));
    }

    #[test]
    fn suggestion_subprocess() {
        let mut snip = BTreeMap::new();
        snip.insert(1, "subprocess.run(['x'])".to_string());
        let s = suggestion_for("agents/x.py", &snip);
        assert!(s.contains("Bash sandbox"));
    }

    #[test]
    fn suggestion_test_path() {
        let s = suggestion_for("tests/test_x.py", &BTreeMap::new());
        assert!(s.contains("Test quality"));
    }

    #[test]
    fn suggestion_md_default() {
        let s = suggestion_for("README.md", &BTreeMap::new());
        assert!(s.contains("Documentation"));
    }

    #[test]
    fn suggestion_fallback() {
        let s = suggestion_for("some/random.txt", &BTreeMap::new());
        assert!(s.contains("Read the file"));
    }

    #[test]
    fn render_markdown_round_trip() {
        let d = tempdir().unwrap();
        std::fs::write(d.path().join("a.rs"), "let x = 7;\n").unwrap();
        let p = plan(["a.rs:1"], d.path(), 0);
        let dest = d.path().join("plan.md");
        write_plan(&p, &dest).unwrap();
        let body = std::fs::read_to_string(&dest).unwrap();
        assert!(body.contains("AIM/AI Fix Plan"));
        assert!(body.contains("`a.rs`"));
        assert!(body.contains("**Suggestion:**"));
    }

    #[test]
    fn empty_plan_summary() {
        let p = FixPlan {
            n_files: 0,
            n_lines: 0,
            files: vec![],
        };
        assert!(summary(&p).contains("no shared findings"));
    }
}
