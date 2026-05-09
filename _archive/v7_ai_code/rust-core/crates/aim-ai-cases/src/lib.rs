//! aim-ai-cases — CV1 eval case validator.
//!
//! Walk every `*.yaml` in `AIM_EVAL_CASES_DIR` (or `~/.cache/aim/
//! eval_cases/` by default), parse it, verify required keys + rubric
//! shapes. Catches a malformed auto-generated case before the eval
//! harness trips on it during a run.
//!
//! Rust port of `AI/ai/case_validator.py`. Schema rules match exactly.

use serde::{Deserialize, Serialize};
use serde_yaml::Value as YamlValue;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CaseError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("glob: {0}")]
    Glob(#[from] glob::PatternError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseStatus {
    pub path: PathBuf,
    pub ok: bool,
    pub case_id: Option<String>,
    pub issues: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Report {
    pub n_cases: u64,
    pub n_ok: u64,
    pub n_failed: u64,
    pub statuses: Vec<CaseStatus>,
}

impl Report {
    pub fn all_ok(&self) -> bool {
        self.n_failed == 0
    }
}

const REQUIRED_KEYS: &[&str] = &["id", "task", "rubrics"];
const KNOWN_RUBRICS: &[&str] = &[
    "min_length",
    "max_length",
    "contains_all",
    "contains_any",
    "forbid_any",
    "regex_must_match",
    "regex_must_not_match",
    "json_keys",
];

pub fn cases_dir(explicit: Option<&Path>) -> PathBuf {
    if let Some(p) = explicit {
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

pub fn validate_one(path: &Path) -> CaseStatus {
    if !path.exists() {
        return CaseStatus {
            path: path.to_path_buf(),
            ok: false,
            case_id: None,
            issues: vec!["file does not exist".to_string()],
        };
    }
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) => {
            return CaseStatus {
                path: path.to_path_buf(),
                ok: false,
                case_id: None,
                issues: vec![format!("read failed: {e}")],
            };
        }
    };
    let doc: YamlValue = match serde_yaml::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            return CaseStatus {
                path: path.to_path_buf(),
                ok: false,
                case_id: None,
                issues: vec![format!("yaml parse: {e}")],
            };
        }
    };
    let issues = validate_doc(&doc);
    let case_id = doc
        .as_mapping()
        .and_then(|m| m.get(YamlValue::String("id".to_string())))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    CaseStatus {
        path: path.to_path_buf(),
        ok: issues.is_empty(),
        case_id,
        issues,
    }
}

pub fn validate_dir(explicit: Option<&Path>) -> Report {
    let dir = cases_dir(explicit);
    let mut statuses: Vec<CaseStatus> = Vec::new();
    if !dir.exists() {
        return Report {
            n_cases: 0,
            n_ok: 0,
            n_failed: 0,
            statuses,
        };
    }
    let pattern = format!("{}/*.yaml", dir.display());
    let mut paths: Vec<PathBuf> = match glob::glob(&pattern) {
        Ok(it) => it.filter_map(Result::ok).collect(),
        Err(_) => Vec::new(),
    };
    paths.sort();
    for p in paths {
        statuses.push(validate_one(&p));
    }
    let n_ok = statuses.iter().filter(|s| s.ok).count() as u64;
    let n = statuses.len() as u64;
    Report {
        n_cases: n,
        n_ok,
        n_failed: n - n_ok,
        statuses,
    }
}

fn validate_doc(doc: &YamlValue) -> Vec<String> {
    let mut issues: Vec<String> = Vec::new();
    let map = match doc.as_mapping() {
        Some(m) => m,
        None => {
            return vec![format!(
                "top-level must be a mapping, got {}",
                yaml_kind_name(doc)
            )]
        }
    };

    for k in REQUIRED_KEYS {
        if !map.contains_key(YamlValue::String((*k).into())) {
            issues.push(format!("missing required key: {k:?}"));
        }
    }

    if let Some(v) = map.get(YamlValue::String("id".into())) {
        match v.as_str() {
            None => issues.push("`id` must be a string".to_string()),
            Some(s) if s.trim().is_empty() => issues.push("`id` is empty".to_string()),
            _ => {}
        }
    }

    if let Some(v) = map.get(YamlValue::String("task".into())) {
        match v.as_str() {
            None => issues.push("`task` must be a string".to_string()),
            Some(s) if s.trim().is_empty() => issues.push("`task` is empty".to_string()),
            _ => {}
        }
    }

    if let Some(v) = map.get(YamlValue::String("rubrics".into())) {
        match v.as_mapping() {
            None => issues.push("`rubrics` must be a mapping".to_string()),
            Some(rmap) if rmap.is_empty() => issues
                .push("`rubrics` is empty — every case needs at least one".to_string()),
            Some(rmap) => {
                let known: BTreeSet<&'static str> = KNOWN_RUBRICS.iter().copied().collect();
                let mut unknown: Vec<String> = rmap
                    .iter()
                    .filter_map(|(k, _)| k.as_str().map(|s| s.to_string()))
                    .filter(|s| !known.contains(s.as_str()))
                    .collect();
                unknown.sort();
                if !unknown.is_empty() {
                    issues.push(format!("unknown rubric keys: {:?}", unknown));
                }
                for k in ["contains_all", "contains_any", "forbid_any"] {
                    if let Some(v) = rmap.get(YamlValue::String(k.into())) {
                        if !v.is_sequence() {
                            issues.push(format!("rubric {k:?} must be a list"));
                        }
                    }
                }
                for k in ["min_length", "max_length"] {
                    if let Some(v) = rmap.get(YamlValue::String(k.into())) {
                        if v.as_i64().is_none() {
                            issues.push(format!("rubric {k:?} must be an int"));
                        }
                    }
                }
                let min_v = rmap
                    .get(YamlValue::String("min_length".into()))
                    .and_then(|v| v.as_i64());
                let max_v = rmap
                    .get(YamlValue::String("max_length".into()))
                    .and_then(|v| v.as_i64());
                if let (Some(min), Some(max)) = (min_v, max_v) {
                    if min > max {
                        issues.push("min_length > max_length".to_string());
                    }
                }
            }
        }
    }

    if let Some(v) = map.get(YamlValue::String("tags".into())) {
        if !v.is_sequence() {
            issues.push("`tags` must be a list".to_string());
        }
    }

    issues
}

fn yaml_kind_name(v: &YamlValue) -> &'static str {
    match v {
        YamlValue::Null => "null",
        YamlValue::Bool(_) => "bool",
        YamlValue::Number(_) => "number",
        YamlValue::String(_) => "string",
        YamlValue::Sequence(_) => "sequence",
        YamlValue::Mapping(_) => "mapping",
        YamlValue::Tagged(_) => "tagged",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn write(dir: &Path, name: &str, contents: &str) -> PathBuf {
        let p = dir.join(name);
        std::fs::write(&p, contents).unwrap();
        p
    }

    #[test]
    fn valid_case_ok() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "good.yaml",
            "id: case-1\ntask: do X\nrubrics:\n  min_length: 1\n",
        );
        let s = validate_one(&p);
        assert!(s.ok, "got issues: {:?}", s.issues);
        assert_eq!(s.case_id.as_deref(), Some("case-1"));
    }

    #[test]
    fn missing_required_keys() {
        let d = tempdir().unwrap();
        let p = write(d.path(), "bad.yaml", "id: case-1\n");
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("\"task\"")));
        assert!(s.issues.iter().any(|i| i.contains("\"rubrics\"")));
    }

    #[test]
    fn empty_rubrics_blocked() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "bad.yaml",
            "id: c\ntask: t\nrubrics: {}\n",
        );
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("empty")));
    }

    #[test]
    fn unknown_rubric_keys_flagged() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "bad.yaml",
            "id: c\ntask: t\nrubrics:\n  weird_thing: 1\n  min_length: 1\n",
        );
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("unknown rubric keys")));
    }

    #[test]
    fn min_max_inversion_flagged() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "bad.yaml",
            "id: c\ntask: t\nrubrics:\n  min_length: 10\n  max_length: 5\n",
        );
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("min_length > max_length")));
    }

    #[test]
    fn rubrics_must_be_mapping() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "bad.yaml",
            "id: c\ntask: t\nrubrics: not-a-mapping\n",
        );
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("rubrics") && i.contains("mapping")));
    }

    #[test]
    fn list_rubrics_must_be_lists() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "bad.yaml",
            "id: c\ntask: t\nrubrics:\n  contains_all: \"not a list\"\n",
        );
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("contains_all") && i.contains("list")));
    }

    #[test]
    fn yaml_parse_error_reported() {
        let d = tempdir().unwrap();
        let p = write(d.path(), "bad.yaml", "id: c\n  task: bad-indent\n");
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("yaml parse")));
    }

    #[test]
    fn validate_dir_aggregates_counts() {
        let d = tempdir().unwrap();
        write(
            d.path(),
            "ok.yaml",
            "id: c1\ntask: t\nrubrics:\n  min_length: 1\n",
        );
        write(d.path(), "bad.yaml", "id: c2\n");
        let r = validate_dir(Some(d.path()));
        assert_eq!(r.n_cases, 2);
        assert_eq!(r.n_ok, 1);
        assert_eq!(r.n_failed, 1);
        assert!(!r.all_ok());
    }

    #[test]
    fn validate_dir_empty_when_dir_absent() {
        let d = tempdir().unwrap();
        let r = validate_dir(Some(&d.path().join("nope")));
        assert_eq!(r.n_cases, 0);
        assert!(r.all_ok());
    }

    #[test]
    fn top_level_must_be_mapping() {
        let d = tempdir().unwrap();
        let p = write(d.path(), "bad.yaml", "- list-not-map\n");
        let s = validate_one(&p);
        assert!(!s.ok);
        assert!(s.issues.iter().any(|i| i.contains("mapping")));
    }
}
