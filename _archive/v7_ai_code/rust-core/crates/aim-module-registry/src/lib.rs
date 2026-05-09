//! aim-module-registry — capability map of `agents/` + `scripts/`.
//!
//! Port of `agents/module_registry.py`. Walks every `*.py` file under
//! the configured roots, records module name + public functions / classes
//! + one-line docstring summary + imports.
//!
//! The Python original uses `ast.parse`. The Rust port uses a regex-based
//! scanner for top-level `def `/`class `/`import `/`from … import` —
//! correct for 95%+ of well-formed Python and good enough for the
//! "discovery / health overview" use-case. (Treats indentation: only
//! considers definitions at column 0, mirroring `tree.body` semantics.)

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use walkdir::WalkDir;

#[derive(Debug, Error)]
pub enum RegistryError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, RegistryError>;

pub const DEFAULT_ROOTS: &[&str] = &["agents", "scripts"];

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Capability {
    pub module: String,
    pub path: PathBuf,
    pub description: String,
    pub public_functions: Vec<String>,
    pub public_classes: Vec<String>,
    pub imports: Vec<String>,
}

// ── parser ──────────────────────────────────────────────────────────────────

/// Convert a relative-to-`root` `.py` path to a dotted module name.
/// Trailing `__init__` is dropped, mirroring Python.
pub fn module_for(path: &Path, root: &Path) -> Option<String> {
    let rel = path.strip_prefix(root).ok()?;
    if rel.extension().and_then(|s| s.to_str()) != Some("py") {
        return None;
    }
    let mut parts: Vec<String> = rel
        .with_extension("")
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect();
    if parts.last().map(|s| s == "__init__").unwrap_or(false) {
        parts.pop();
    }
    if parts.is_empty() {
        None
    } else {
        Some(parts.join("."))
    }
}

/// Extract the leading triple-quoted docstring's first non-empty line.
pub fn extract_first_docstring_line(source: &str) -> String {
    let trimmed = source.trim_start();
    let (delim, body) = if let Some(rest) = trimmed.strip_prefix("\"\"\"") {
        ("\"\"\"", rest)
    } else if let Some(rest) = trimmed.strip_prefix("'''") {
        ("'''", rest)
    } else {
        return String::new();
    };
    let end = body.find(delim).unwrap_or(body.len());
    let docstring = &body[..end];
    docstring
        .lines()
        .map(|l| l.trim().to_string())
        .find(|l| !l.is_empty())
        .map(|s| s.chars().take(200).collect())
        .unwrap_or_default()
}

/// Parse a Python source file's top-level definitions + imports. Only
/// definitions at column 0 are considered (matches `ast.parse` body
/// semantics). Names starting with `_` are excluded from public lists.
pub fn parse_source(path: &Path, source: &str) -> Capability {
    // Compile once-per-call for simplicity; the registry walks small N.
    let def_re = Regex::new(r"(?m)^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(").unwrap();
    let class_re = Regex::new(r"(?m)^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]").unwrap();
    let import_re = Regex::new(r"(?m)^import\s+([A-Za-z_][A-Za-z0-9_.]*)").unwrap();
    let from_re = Regex::new(r"(?m)^from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import").unwrap();

    let mut funcs: Vec<String> = def_re
        .captures_iter(source)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .filter(|n| !n.starts_with('_'))
        .collect();
    funcs.sort();
    funcs.dedup();

    let mut classes: Vec<String> = class_re
        .captures_iter(source)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .filter(|n| !n.starts_with('_'))
        .collect();
    classes.sort();
    classes.dedup();

    let mut imports: Vec<String> = Vec::new();
    for cap in import_re.captures_iter(source) {
        if let Some(m) = cap.get(1) {
            imports.push(m.as_str().to_string());
        }
    }
    for cap in from_re.captures_iter(source) {
        if let Some(m) = cap.get(1) {
            imports.push(m.as_str().to_string());
        }
    }
    imports.sort();
    imports.dedup();

    Capability {
        module: String::new(), // filled by caller
        path: path.to_path_buf(),
        description: extract_first_docstring_line(source),
        public_functions: funcs,
        public_classes: classes,
        imports,
    }
}

// ── registry walk ───────────────────────────────────────────────────────────

pub fn registry(root: &Path, roots: &[&str]) -> Result<Vec<Capability>> {
    let mut out: Vec<Capability> = Vec::new();
    for sub in roots {
        let dir = root.join(sub);
        if !dir.exists() {
            continue;
        }
        let mut paths: Vec<PathBuf> = Vec::new();
        for entry in WalkDir::new(&dir).into_iter().filter_map(|e| e.ok()) {
            if !entry.file_type().is_file() {
                continue;
            }
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("py") {
                continue;
            }
            if path
                .components()
                .any(|c| {
                    matches!(
                        c.as_os_str().to_str(),
                        Some("__pycache__") | Some(".pytest_cache")
                    )
                })
            {
                continue;
            }
            paths.push(path.to_path_buf());
        }
        paths.sort();
        for path in paths {
            let Some(module) = module_for(&path, root) else {
                continue;
            };
            let Ok(source) = std::fs::read_to_string(&path) else {
                continue;
            };
            let mut cap = parse_source(&path, &source);
            cap.module = module;
            out.push(cap);
        }
    }
    Ok(out)
}

pub fn get<'a>(modules: &'a [Capability], name: &str) -> Option<&'a Capability> {
    modules.iter().find(|c| c.module == name)
}

/// Group capabilities by their top-level package (`agents`/`scripts`/…).
pub fn by_subsystem(modules: &[Capability]) -> BTreeMap<String, Vec<Capability>> {
    let mut out: BTreeMap<String, Vec<Capability>> = BTreeMap::new();
    for c in modules {
        let head = c
            .module
            .split('.')
            .next()
            .unwrap_or(&c.module)
            .to_string();
        out.entry(head).or_default().push(c.clone());
    }
    out
}

/// Markdown overview suitable for README / healthz.
pub fn summary_markdown(modules: &[Capability]) -> String {
    let groups = by_subsystem(modules);
    let total: usize = groups.values().map(|v| v.len()).sum();
    let mut parts: Vec<String> = vec![
        "# AIM module registry".into(),
        String::new(),
        format!("_{} modules in {} subsystems_", total, groups.len()),
        String::new(),
    ];
    for (head, caps) in &groups {
        parts.push(format!("## {} ({} modules)", head, caps.len()));
        for c in caps {
            let desc = if c.description.is_empty() {
                "_(no docstring)_".to_string()
            } else {
                c.description.clone()
            };
            parts.push(format!("- **{}** — {}", c.module, desc));
            let funcs: Vec<&String> = c.public_functions.iter().take(6).collect();
            let classes: Vec<&String> = c.public_classes.iter().take(4).collect();
            if !funcs.is_empty() || !classes.is_empty() {
                let mut api: Vec<String> = Vec::new();
                if !classes.is_empty() {
                    api.push(format!(
                        "classes: {}",
                        classes.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", ")
                    ));
                }
                if !funcs.is_empty() {
                    api.push(format!(
                        "fns: {}",
                        funcs.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", ")
                    ));
                }
                parts.push(format!("  - API: {}", api.join(" · ")));
            }
        }
        parts.push(String::new());
    }
    parts.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(root: &Path, rel: &str, content: &str) {
        let path = root.join(rel);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, content).unwrap();
    }

    // ── module_for ──────────────────────────────────────────────────────────

    #[test]
    fn module_for_simple_top_level() {
        let r = Path::new("/x/y");
        let p = Path::new("/x/y/agents/foo.py");
        assert_eq!(module_for(p, r), Some("agents.foo".to_string()));
    }

    #[test]
    fn module_for_init_drops_segment() {
        let r = Path::new("/x/y");
        let p = Path::new("/x/y/agents/sub/__init__.py");
        assert_eq!(module_for(p, r), Some("agents.sub".to_string()));
    }

    #[test]
    fn module_for_non_py_returns_none() {
        let r = Path::new("/x/y");
        let p = Path::new("/x/y/agents/foo.txt");
        assert!(module_for(p, r).is_none());
    }

    // ── extract_first_docstring_line ────────────────────────────────────────

    #[test]
    fn docstring_triple_double_quotes() {
        let src = "\"\"\"summary line\nbody\n\"\"\"\n\ndef foo(): pass";
        assert_eq!(extract_first_docstring_line(src), "summary line");
    }

    #[test]
    fn docstring_triple_single_quotes() {
        let src = "'''alt summary\nmore'''\n";
        assert_eq!(extract_first_docstring_line(src), "alt summary");
    }

    #[test]
    fn docstring_skips_blank_first_line() {
        let src = "\"\"\"\nsummary on second line\n\"\"\"";
        assert_eq!(extract_first_docstring_line(src), "summary on second line");
    }

    #[test]
    fn docstring_caps_at_200_chars() {
        let long = "x".repeat(500);
        let src = format!("\"\"\"{}\"\"\"", long);
        assert_eq!(extract_first_docstring_line(&src).chars().count(), 200);
    }

    #[test]
    fn docstring_missing_returns_empty() {
        assert_eq!(extract_first_docstring_line("def foo(): pass"), "");
    }

    // ── parse_source ────────────────────────────────────────────────────────

    #[test]
    fn parse_finds_public_top_level_defs_and_classes() {
        let src = r#""""hello world summary"""

import os
from datetime import datetime
from typing import Optional

def public_fn():
    pass

def _private():
    pass

class PublicClass:
    pass

class _PrivateClass:
    pass

def nested_helper():
    def inner():
        pass
"#;
        let cap = parse_source(Path::new("foo.py"), src);
        assert_eq!(cap.public_functions, vec!["nested_helper", "public_fn"]);
        assert_eq!(cap.public_classes, vec!["PublicClass"]);
        assert_eq!(cap.description, "hello world summary");
        assert!(cap.imports.contains(&"os".to_string()));
        assert!(cap.imports.contains(&"datetime".to_string()));
        assert!(cap.imports.contains(&"typing".to_string()));
    }

    #[test]
    fn parse_excludes_indented_definitions() {
        // Indented `def foo` is NOT top-level and should be ignored
        let src = "class A:\n    def foo(self):\n        pass\n";
        let cap = parse_source(Path::new("x.py"), src);
        assert!(cap.public_functions.is_empty());
        assert_eq!(cap.public_classes, vec!["A"]);
    }

    #[test]
    fn parse_dedupes_imports() {
        let src = "import os\nimport os\nfrom os import path\n";
        let cap = parse_source(Path::new("x.py"), src);
        assert_eq!(cap.imports.iter().filter(|i| *i == "os").count(), 1);
    }

    // ── registry walk ───────────────────────────────────────────────────────

    #[test]
    fn registry_walks_configured_roots_only() {
        let tmp = TempDir::new().unwrap();
        write(tmp.path(), "agents/a.py", "\"\"\"a summary\"\"\"\ndef foo(): pass");
        write(tmp.path(), "scripts/b.py", "\"\"\"b summary\"\"\"\nclass B: pass");
        write(tmp.path(), "other/c.py", "\"\"\"ignored\"\"\"\ndef noop(): pass");
        let caps = registry(tmp.path(), &["agents", "scripts"]).unwrap();
        let names: Vec<&str> = caps.iter().map(|c| c.module.as_str()).collect();
        assert!(names.contains(&"agents.a"));
        assert!(names.contains(&"scripts.b"));
        assert!(!names.contains(&"other.c"));
    }

    #[test]
    fn registry_skips_pycache() {
        let tmp = TempDir::new().unwrap();
        write(tmp.path(), "agents/__pycache__/a.cpython-311.pyc", "binary");
        write(tmp.path(), "agents/a.py", "\"\"\"real\"\"\"\ndef foo(): pass");
        let caps = registry(tmp.path(), &["agents"]).unwrap();
        // Only a.py — not the .pyc, nor anything in __pycache__
        assert_eq!(caps.len(), 1);
    }

    #[test]
    fn registry_returns_empty_for_missing_roots() {
        let tmp = TempDir::new().unwrap();
        let caps = registry(tmp.path(), &["agents", "scripts"]).unwrap();
        assert!(caps.is_empty());
    }

    #[test]
    fn registry_sorts_by_path() {
        let tmp = TempDir::new().unwrap();
        write(tmp.path(), "agents/zeta.py", "\"\"\"z\"\"\"");
        write(tmp.path(), "agents/alpha.py", "\"\"\"a\"\"\"");
        write(tmp.path(), "agents/middle.py", "\"\"\"m\"\"\"");
        let caps = registry(tmp.path(), &["agents"]).unwrap();
        let names: Vec<&str> = caps.iter().map(|c| c.module.as_str()).collect();
        assert_eq!(names, vec!["agents.alpha", "agents.middle", "agents.zeta"]);
    }

    // ── by_subsystem ───────────────────────────────────────────────────────

    #[test]
    fn by_subsystem_groups_by_top_level() {
        let modules = vec![
            Capability {
                module: "agents.a".into(),
                ..Default::default()
            },
            Capability {
                module: "agents.b".into(),
                ..Default::default()
            },
            Capability {
                module: "scripts.x".into(),
                ..Default::default()
            },
        ];
        let groups = by_subsystem(&modules);
        assert_eq!(groups["agents"].len(), 2);
        assert_eq!(groups["scripts"].len(), 1);
    }

    // ── summary_markdown ───────────────────────────────────────────────────

    #[test]
    fn summary_includes_module_count_and_groups() {
        let modules = vec![
            Capability {
                module: "agents.a".into(),
                description: "summary".into(),
                public_functions: vec!["foo".into()],
                public_classes: vec!["Bar".into()],
                ..Default::default()
            },
            Capability {
                module: "scripts.b".into(),
                ..Default::default()
            },
        ];
        let s = summary_markdown(&modules);
        assert!(s.contains("# AIM module registry"));
        assert!(s.contains("_2 modules in 2 subsystems_"));
        assert!(s.contains("## agents (1 modules)"));
        assert!(s.contains("## scripts (1 modules)"));
        assert!(s.contains("classes: Bar"));
        assert!(s.contains("fns: foo"));
        assert!(s.contains("_(no docstring)_"));
    }

    // ── get ─────────────────────────────────────────────────────────────────

    #[test]
    fn get_finds_module_by_name() {
        let modules = vec![Capability {
            module: "agents.foo".into(),
            ..Default::default()
        }];
        assert!(get(&modules, "agents.foo").is_some());
        assert!(get(&modules, "agents.missing").is_none());
    }
}
