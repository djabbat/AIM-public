//! aim-impact-analyser — Python code change-impact analyser (SC1).
//!
//! Port of `agents/impact_analyser.py`. Walks `agents/`, `scripts/`,
//! `tests/` in the AIM repo and parses each `.py` file for `import` /
//! `from … import` statements via regex (no Python parser dependency).
//! Building this as a Rust tool means CI / pre-commit hooks can run it
//! without spinning up a Python interpreter.
//!
//! ## Public API
//! - [`build_index`] — walk `sub_roots` rooted at a path
//! - [`Index::impact_for`] — list direct + transitive dependents and
//!   importing test files for a changed module
//! - [`summary`] — text rendering for terminal / CI output

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ImpactError {
    #[error("unknown target: {0}")]
    UnknownTarget(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Index {
    /// `forward[module]` = set of modules `module` imports.
    pub forward: BTreeMap<String, BTreeSet<String>>,
    /// `reverse[module]` = set of modules that import `module`.
    pub reverse: BTreeMap<String, BTreeSet<String>>,
    /// `path[module]` = filesystem path on disk.
    pub path: BTreeMap<String, PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Impact {
    pub target_module: String,
    pub target_path: String,
    pub direct_dependents: Vec<String>,
    pub transitive_dependents: Vec<String>,
    pub test_files: Vec<String>,
}

// ── module-name resolution ─────────────────────────────────────────────────

/// `agents/foo.py` → `agents.foo`; `agents/__init__.py` → `agents`.
pub fn path_to_module(path: &Path, root: &Path) -> Option<String> {
    let rel = path.strip_prefix(root).ok()?;
    if rel.extension().and_then(|s| s.to_str()) != Some("py") {
        return None;
    }
    let no_ext = rel.with_extension("");
    let mut parts: Vec<String> = no_ext
        .components()
        .filter_map(|c| match c {
            std::path::Component::Normal(s) => s.to_str().map(String::from),
            _ => None,
        })
        .collect();
    if parts.last().map(|s| s == "__init__").unwrap_or(false) {
        parts.pop();
    }
    if parts.is_empty() {
        return None;
    }
    Some(parts.join("."))
}

// ── import scanning via regex ──────────────────────────────────────────────

static IMPORT_RE: OnceLock<Regex> = OnceLock::new();
static FROM_IMPORT_RE: OnceLock<Regex> = OnceLock::new();

fn import_re() -> &'static Regex {
    IMPORT_RE.get_or_init(|| {
        // `import X` or `import X.Y` or `import X as Z`. Captures dotted name.
        Regex::new(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)").unwrap()
    })
}
fn from_import_re() -> &'static Regex {
    FROM_IMPORT_RE.get_or_init(|| {
        // `from X.Y import …`. Skips relative imports (`from . import`).
        Regex::new(r"^\s*from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\b").unwrap()
    })
}

pub fn imports_in_source(src: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for line in src.lines() {
        if let Some(cap) = from_import_re().captures(line) {
            if let Some(m) = cap.get(1) {
                out.insert(m.as_str().to_string());
            }
            continue;
        }
        if let Some(cap) = import_re().captures(line) {
            if let Some(m) = cap.get(1) {
                // `import X, Y` is rare; matches the first only — same as
                // Python ast.Import.names[0]. The Python port catches all,
                // so we extend by splitting on `,`.
                let raw = m.as_str();
                let after = &line[m.end()..];
                let mut names = vec![raw.to_string()];
                if after.contains(',') {
                    // Best-effort multi-name import line: split tail on commas.
                    for chunk in after.split(',').skip(1) {
                        let chunk = chunk.split(" as ").next().unwrap_or("");
                        let token = chunk
                            .trim()
                            .split_whitespace()
                            .next()
                            .unwrap_or("")
                            .trim_end_matches(|c: char| c == '#');
                        if !token.is_empty() && token.chars().next().unwrap().is_alphabetic() {
                            names.push(token.to_string());
                        }
                    }
                }
                for n in names {
                    out.insert(n);
                }
            }
        }
    }
    out
}

pub fn imports_in_file(path: &Path) -> BTreeSet<String> {
    match std::fs::read_to_string(path) {
        Ok(s) => imports_in_source(&s),
        Err(_) => BTreeSet::new(),
    }
}

fn walk_py_files(root: &Path, sub_roots: &[&str]) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for sub in sub_roots {
        let d = root.join(sub);
        if !d.exists() {
            continue;
        }
        for entry in walkdir::WalkDir::new(&d).follow_links(false) {
            let entry = match entry {
                Ok(e) => e,
                Err(_) => continue,
            };
            let p = entry.path();
            if !p.is_file() || p.extension().and_then(|s| s.to_str()) != Some("py") {
                continue;
            }
            let bad_dir = p
                .components()
                .any(|c| matches!(c, std::path::Component::Normal(s)
                    if s == "__pycache__" || s == ".pytest_cache" || s == "venv" || s == ".venv"));
            if bad_dir {
                continue;
            }
            out.push(p.to_path_buf());
        }
    }
    out
}

/// Build the forward + reverse import index across `sub_roots` (default
/// `agents`, `scripts`, `tests`).
pub fn build_index(root: &Path, sub_roots: &[&str]) -> Index {
    let mut forward: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut reverse: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut paths: BTreeMap<String, PathBuf> = BTreeMap::new();

    for f in walk_py_files(root, sub_roots) {
        let module = match path_to_module(&f, root) {
            Some(m) => m,
            None => continue,
        };
        paths.insert(module.clone(), f.clone());
        let deps = imports_in_file(&f);
        for d in &deps {
            reverse
                .entry(d.clone())
                .or_default()
                .insert(module.clone());
            // Register every prefix — `agents.X.foo` resolves at the
            // `agents.X` boundary too.
            let mut head = d.clone();
            while let Some(idx) = head.rfind('.') {
                head.truncate(idx);
                if head.is_empty() {
                    break;
                }
                reverse
                    .entry(head.clone())
                    .or_default()
                    .insert(module.clone());
            }
        }
        forward.insert(module, deps);
    }
    Index {
        forward,
        reverse,
        path: paths,
    }
}

impl Index {
    /// Take a path-or-module spec and return the canonical module.
    pub fn resolve(&self, target: &str, root: &Path) -> Option<String> {
        if self.path.contains_key(target) {
            return Some(target.to_string());
        }
        if self.forward.contains_key(target) {
            return Some(target.to_string());
        }
        let p = Path::new(target);
        let absolute: PathBuf = if p.is_absolute() {
            p.to_path_buf()
        } else {
            root.join(p)
        };
        if let Some(m) = path_to_module(&absolute, root) {
            if self.path.contains_key(&m) {
                return Some(m);
            }
        }
        None
    }

    /// Compute the impact graph for `target`. Excludes test modules from
    /// the transitive walk but exposes them in the dedicated `test_files`
    /// list (mirrors Python).
    pub fn impact_for(&self, target: &str, root: &Path) -> Result<Impact, ImpactError> {
        let module = self
            .resolve(target, root)
            .ok_or_else(|| ImpactError::UnknownTarget(target.to_string()))?;

        let direct: Vec<String> = self
            .reverse
            .get(&module)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .collect();

        // BFS over reverse map; skip test modules.
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let mut queue: Vec<String> = direct
            .iter()
            .filter(|m| !is_test_module(m))
            .cloned()
            .collect();
        while let Some(cur) = queue.pop() {
            if !seen.insert(cur.clone()) {
                continue;
            }
            if let Some(parents) = self.reverse.get(&cur) {
                for p in parents {
                    if is_test_module(p) || seen.contains(p) {
                        continue;
                    }
                    queue.push(p.clone());
                }
            }
        }
        seen.remove(&module);
        let transitive: Vec<String> = seen.into_iter().collect();
        let test_files: Vec<String> = direct
            .iter()
            .filter(|m| is_test_module(m))
            .cloned()
            .collect();

        let target_path = self
            .path
            .get(&module)
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default();

        Ok(Impact {
            target_module: module,
            target_path,
            direct_dependents: direct,
            transitive_dependents: transitive,
            test_files,
        })
    }
}

fn is_test_module(name: &str) -> bool {
    name == "tests" || name.starts_with("tests.")
}

pub fn summary(impact: &Impact) -> String {
    let mut parts = vec![
        format!(
            "📡 Impact for {} ({})",
            impact.target_module, impact.target_path
        ),
        format!("  direct dependents:    {}", impact.direct_dependents.len()),
        format!(
            "  transitive (no tests): {}",
            impact.transitive_dependents.len()
        ),
        format!(
            "  test files importing: {}",
            impact.test_files.len()
        ),
    ];
    if !impact.test_files.is_empty() {
        parts.push("  recommended test runs:".to_string());
        for t in impact.test_files.iter().take(8) {
            parts.push(format!("    - {t}"));
        }
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &TempDir, rel: &str, body: &str) -> PathBuf {
        let p = dir.path().join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn path_to_module_basic() {
        let root = Path::new("/repo");
        let p = Path::new("/repo/agents/foo.py");
        assert_eq!(path_to_module(p, root).as_deref(), Some("agents.foo"));
    }

    #[test]
    fn path_to_module_init_collapses_to_pkg() {
        let root = Path::new("/repo");
        let p = Path::new("/repo/agents/__init__.py");
        assert_eq!(path_to_module(p, root).as_deref(), Some("agents"));
    }

    #[test]
    fn imports_in_source_handles_basic_forms() {
        let src = "import os\nfrom pathlib import Path\nfrom agents.foo import bar\nimport sys, json\n";
        let s = imports_in_source(src);
        assert!(s.contains("os"));
        assert!(s.contains("pathlib"));
        assert!(s.contains("agents.foo"));
        assert!(s.contains("sys"));
        assert!(s.contains("json"));
    }

    #[test]
    fn imports_in_source_skips_relative_from() {
        let src = "from . import sibling\nfrom ..pkg import x\n";
        let s = imports_in_source(src);
        // Both relative; should NOT show up
        assert!(!s.iter().any(|m| m == "sibling"));
    }

    #[test]
    fn build_index_simple_repo() {
        let dir = TempDir::new().unwrap();
        write(
            &dir,
            "agents/foo.py",
            "import os\nfrom agents.bar import helper\n",
        );
        write(&dir, "agents/bar.py", "import json\n");
        write(&dir, "tests/test_foo.py", "from agents.foo import x\n");

        let idx = build_index(dir.path(), &["agents", "tests"]);
        assert!(idx.forward.contains_key("agents.foo"));
        assert!(idx.forward.contains_key("agents.bar"));
        assert!(idx.forward.contains_key("tests.test_foo"));

        // agents.bar is imported by agents.foo
        assert!(idx.reverse["agents.bar"].contains("agents.foo"));
        // agents.foo is imported by tests.test_foo
        assert!(idx.reverse["agents.foo"].contains("tests.test_foo"));
    }

    #[test]
    fn impact_for_lists_direct_and_tests() {
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/foo.py", "x = 1\n");
        write(&dir, "agents/bar.py", "from agents.foo import x\n");
        write(&dir, "tests/test_foo.py", "from agents.foo import x\n");

        let idx = build_index(dir.path(), &["agents", "tests"]);
        let imp = idx.impact_for("agents.foo", dir.path()).unwrap();
        assert_eq!(imp.target_module, "agents.foo");
        assert!(imp.direct_dependents.contains(&"agents.bar".to_string()));
        assert!(imp.direct_dependents.contains(&"tests.test_foo".to_string()));
        assert_eq!(imp.test_files, vec!["tests.test_foo"]);
    }

    #[test]
    fn impact_transitive_excludes_tests() {
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/a.py", "x = 1\n");
        write(&dir, "agents/b.py", "from agents.a import x\n");
        write(&dir, "agents/c.py", "from agents.b import x\n");
        write(&dir, "tests/test_a.py", "from agents.a import x\n");

        let idx = build_index(dir.path(), &["agents", "tests"]);
        let imp = idx.impact_for("agents.a", dir.path()).unwrap();
        // direct: agents.b + tests.test_a
        // transitive (BFS, no tests): both agents.b and agents.c — Python
        // adds every visited node to `seen`, including BFS roots.
        assert_eq!(imp.transitive_dependents, vec!["agents.b", "agents.c"]);
        assert_eq!(imp.test_files, vec!["tests.test_a"]);
        // tests.test_a is NEVER in transitive
        assert!(!imp
            .transitive_dependents
            .iter()
            .any(|m| m.starts_with("tests.")));
    }

    #[test]
    fn impact_resolves_path_input() {
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/foo.py", "x = 1\n");
        write(&dir, "agents/bar.py", "from agents.foo import x\n");

        let idx = build_index(dir.path(), &["agents"]);
        let imp = idx.impact_for("agents/foo.py", dir.path()).unwrap();
        assert_eq!(imp.target_module, "agents.foo");
    }

    #[test]
    fn impact_unknown_target_errors() {
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/foo.py", "x = 1\n");
        let idx = build_index(dir.path(), &["agents"]);
        let err = idx.impact_for("agents.ghost", dir.path()).unwrap_err();
        assert!(matches!(err, ImpactError::UnknownTarget(_)));
    }

    #[test]
    fn impact_prefix_registration() {
        // Importing `agents.X.sub` should also register reverse for `agents.X`.
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/__init__.py", "");
        write(&dir, "agents/X/__init__.py", "");
        write(&dir, "agents/X/sub.py", "x=1\n");
        write(&dir, "scripts/use.py", "from agents.X.sub import x\n");

        let idx = build_index(dir.path(), &["agents", "scripts"]);
        // scripts.use should appear under agents.X reverse via prefix walk
        assert!(idx.reverse.get("agents.X").map(|s| s.contains("scripts.use")).unwrap_or(false));
    }

    #[test]
    fn summary_renders_recommended_tests() {
        let imp = Impact {
            target_module: "agents.foo".into(),
            target_path: "/repo/agents/foo.py".into(),
            direct_dependents: vec!["agents.bar".into(), "tests.test_foo".into()],
            transitive_dependents: vec![],
            test_files: vec!["tests.test_foo".into()],
        };
        let s = summary(&imp);
        assert!(s.contains("📡 Impact for agents.foo"));
        assert!(s.contains("recommended test runs"));
        assert!(s.contains("- tests.test_foo"));
    }

    #[test]
    fn walk_skips_pycache_and_venv() {
        let dir = TempDir::new().unwrap();
        write(&dir, "agents/__pycache__/junk.py", "x=1\n");
        write(&dir, "agents/foo.py", "x=1\n");
        write(&dir, "agents/.venv/lib.py", "x=1\n");
        let files = walk_py_files(dir.path(), &["agents"]);
        // Only foo.py survives
        assert_eq!(files.len(), 1);
        assert!(files[0].ends_with("agents/foo.py"));
    }
}
