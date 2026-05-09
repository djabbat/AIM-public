//! aim-ai-findings-to-evals — FE1.
//!
//! Convert shared findings (`file:line` refs) from the diagnostic
//! pipeline into eval cases that codify those concerns as regression
//! checks. After a fix lands, the case trips when the same bug
//! returns.
//!
//! Rust port of `AI/ai/findings_to_evals.py`. YAML emitter is the
//! same minimal shape as the Python predecessor (compatible with the
//! CV1 case-validator schema).

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseSpec {
    pub id: String,
    pub task: String,
    pub rubrics: Rubrics,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rubrics {
    pub contains_all: Vec<String>,
    pub min_length: u32,
    pub forbid_any: Vec<String>,
}

fn slug(s: &str) -> String {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z0-9]+").unwrap());
    RE.replace_all(&s.to_lowercase(), "-")
        .trim_matches('-')
        .to_string()
}

/// Extract `(path.py, line?)` from a ref. Other extensions return None
/// because the rubrics target Python diagnostics.
pub fn extract_path(ref_str: &str) -> Option<(String, Option<u32>)> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"^([\w./_\-]+\.py)(?::(\d+))?$").unwrap());
    let stripped = ref_str.trim().trim_start_matches("./");
    let caps = RE.captures(stripped)?;
    let path = caps.get(1)?.as_str().to_string();
    let line = caps.get(2).and_then(|m| m.as_str().parse().ok());
    Some((path, line))
}

pub fn case_from_finding(ref_str: &str) -> Option<CaseSpec> {
    let (path, line) = extract_path(ref_str)?;
    let suffix = line.map(|l| format!("-l{l}")).unwrap_or_default();
    let cid = format!("regr-{}{}", slug(&path), suffix);

    let line_part = line.map(|l| format!(" at line {l}")).unwrap_or_default();
    let task = format!(
        "Audit `{path}`{line_part}: identify the regression that a previous self-diagnostic flagged here, and propose the smallest patch that closes it without breaking adjacent behaviour."
    );

    let mut contains_all = vec![path.clone()];
    if let Some(l) = line {
        contains_all.push(l.to_string());
    }

    let mut tags = vec!["regression".to_string(), "from-diagnostic".to_string()];
    if path.contains("/tests/") || path.starts_with("tests/") {
        tags.push("test-gap".into());
    } else if path.contains("/AI/ai/") || path.starts_with("AI/ai/") {
        tags.push("ai-subproject".into());
    } else if path.starts_with("agents/") {
        tags.push("agents-runtime".into());
    }

    Some(CaseSpec {
        id: cid,
        task,
        rubrics: Rubrics {
            contains_all,
            min_length: 200,
            forbid_any: vec![
                "probably".into(),
                "should be fine".into(),
                "looks ok".into(),
            ],
        },
        tags,
    })
}

pub fn generate_cases<I, S>(refs: I) -> Vec<CaseSpec>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut out: Vec<CaseSpec> = Vec::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    for r in refs {
        if let Some(spec) = case_from_finding(r.as_ref()) {
            if seen.insert(spec.id.clone()) {
                out.push(spec);
            }
        }
    }
    out
}

/// Resolve target dir: explicit → AIM_EVAL_CASES_DIR → default cache.
fn cases_dir(dest: Option<&Path>) -> PathBuf {
    if let Some(p) = dest {
        return p.to_path_buf();
    }
    if let Ok(s) = std::env::var("AIM_EVAL_CASES_DIR") {
        return PathBuf::from(s);
    }
    if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
        return PathBuf::from(xdg).join("aim").join("eval_cases");
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("aim").join("eval_cases")
}

pub fn yaml_dump(spec: &CaseSpec) -> String {
    let mut parts: Vec<String> = Vec::new();
    parts.push(format!("id: {}", spec.id));
    parts.push("task: |".into());
    for line in spec.task.split('\n') {
        parts.push(format!("  {line}"));
    }
    parts.push("rubrics:".into());

    // contains_all
    let cn: Vec<String> = spec
        .rubrics
        .contains_all
        .iter()
        .map(|s| serde_json::to_string(s).unwrap())
        .collect();
    parts.push(format!("  contains_all: [{}]", cn.join(", ")));
    parts.push(format!("  min_length: {}", spec.rubrics.min_length));
    let fb: Vec<String> = spec
        .rubrics
        .forbid_any
        .iter()
        .map(|s| serde_json::to_string(s).unwrap())
        .collect();
    parts.push(format!("  forbid_any: [{}]", fb.join(", ")));

    let tags: Vec<String> = spec
        .tags
        .iter()
        .map(|s| serde_json::to_string(s).unwrap())
        .collect();
    parts.push(format!("tags: [{}]", tags.join(", ")));
    let mut s = parts.join("\n");
    s.push('\n');
    s
}

pub fn write_cases<I, S>(
    refs: I,
    dest: Option<&Path>,
    overwrite: bool,
) -> std::io::Result<Vec<PathBuf>>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let target = cases_dir(dest);
    std::fs::create_dir_all(&target)?;
    let mut written: Vec<PathBuf> = Vec::new();
    for spec in generate_cases(refs) {
        let p = target.join(format!("{}.yaml", spec.id));
        if p.exists() && !overwrite {
            continue;
        }
        std::fs::write(&p, yaml_dump(&spec))?;
        written.push(p);
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn case_from_path_with_line() {
        let c = case_from_finding("AI/ai/run.py:42").unwrap();
        assert_eq!(c.id, "regr-ai-ai-run-py-l42");
        assert!(c.tags.contains(&"ai-subproject".to_string()));
        assert!(c.rubrics.contains_all.contains(&"AI/ai/run.py".to_string()));
        assert!(c.rubrics.contains_all.contains(&"42".to_string()));
        assert_eq!(c.rubrics.min_length, 200);
    }

    #[test]
    fn case_from_path_without_line() {
        let c = case_from_finding("agents/foo.py").unwrap();
        assert_eq!(c.id, "regr-agents-foo-py");
        assert!(c.tags.contains(&"agents-runtime".to_string()));
        assert_eq!(c.rubrics.contains_all, vec!["agents/foo.py".to_string()]);
    }

    #[test]
    fn case_skips_non_python_refs() {
        assert!(case_from_finding("README.md:7").is_none());
        assert!(case_from_finding("just words").is_none());
    }

    #[test]
    fn case_test_path_gets_test_gap_tag() {
        let c = case_from_finding("tests/test_x.py:1").unwrap();
        assert!(c.tags.contains(&"test-gap".to_string()));
    }

    #[test]
    fn generate_dedupes_on_id() {
        let cases = generate_cases(["a/x.py:1", "a/x.py:1", "a/x.py:2"]);
        assert_eq!(cases.len(), 2);
    }

    #[test]
    fn yaml_dump_produces_parseable_shape() {
        let c = case_from_finding("a/x.py:7").unwrap();
        let y = yaml_dump(&c);
        assert!(y.contains("id: regr-a-x-py-l7"));
        assert!(y.contains("task: |"));
        assert!(y.contains("rubrics:"));
        assert!(y.contains("contains_all:"));
        assert!(y.contains("forbid_any:"));
        assert!(y.contains("tags: ["));
    }

    #[test]
    fn write_cases_idempotent() {
        let d = tempdir().unwrap();
        let w1 = write_cases(["a/x.py:1"], Some(d.path()), false).unwrap();
        assert_eq!(w1.len(), 1);
        let w2 = write_cases(["a/x.py:1"], Some(d.path()), false).unwrap();
        assert_eq!(w2.len(), 0, "second pass without overwrite must skip");
    }

    #[test]
    fn write_cases_overwrite_replaces() {
        let d = tempdir().unwrap();
        write_cases(["a/x.py:1"], Some(d.path()), false).unwrap();
        let w = write_cases(["a/x.py:1"], Some(d.path()), true).unwrap();
        assert_eq!(w.len(), 1);
    }

    #[test]
    fn rubrics_have_forbid_handwave_phrases() {
        let c = case_from_finding("a/x.py:1").unwrap();
        assert!(c.rubrics.forbid_any.iter().any(|s| s == "probably"));
    }
}

#[allow(dead_code)]
fn _unused() -> BTreeMap<String, String> {
    BTreeMap::new()
}
