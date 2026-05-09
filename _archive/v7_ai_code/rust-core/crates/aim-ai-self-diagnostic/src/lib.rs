//! aim-ai-self-diagnostic — SD1 prompt builder.
//!
//! Loads `AIM/AI/docs/SELF_DIAGNOSTIC_PROMPT.md`, attaches a
//! freshly-snapshotted inventory of `AIM/AI/ai/*.py` (LoC + public
//! API + imports), and produces ONE prompt string ready for an LLM.
//!
//! The reason for the wrapper: the prompt's Phase 0 wants ground-truth
//! about the surface being audited. We compute it deterministically
//! here and fold it into the prompt so the model can't fabricate the
//! file list, line counts, or import graph.
//!
//! Rust port of `AI/ai/self_diagnostic.py`. The Python version uses
//! the `ast` module for fully-accurate introspection; the Rust port
//! uses regex over the same files. For the inventory shape both
//! produce the same envelope.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SelfDiagError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("prompt file not found: {0}")]
    PromptNotFound(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModuleInventory {
    pub path: String,
    pub loc: u64,
    pub public_functions: Vec<String>,
    pub public_classes: Vec<String>,
    pub imports: Vec<String>,
    pub tests: Vec<TestFile>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestFile {
    pub path: String,
    pub loc: u64,
    pub test_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DirectionRuleStatus {
    pub clean: bool,
    pub violations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Inventory {
    pub generated_at: String,
    pub aim_root: String,
    pub n_modules: u64,
    pub modules: Vec<ModuleInventory>,
    pub direction_rule: DirectionRuleStatus,
}

pub fn project_root() -> PathBuf {
    if let Ok(p) = std::env::var("AIM_ROOT") {
        return PathBuf::from(p);
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub fn ai_root(repo_root: &Path) -> PathBuf {
    repo_root.join("AIM").join("AI")
}

pub fn prompt_path(repo_root: &Path) -> PathBuf {
    if let Ok(p) = std::env::var("AI_DIAGNOSTIC_PROMPT") {
        return PathBuf::from(p);
    }
    ai_root(repo_root).join("docs").join("SELF_DIAGNOSTIC_PROMPT.md")
}

// ── inventory ───────────────────────────────────────────────────

pub fn module_inventory(py_file: &Path) -> ModuleInventory {
    let path_str = py_file.display().to_string();
    let mut info = ModuleInventory {
        path: path_str,
        loc: 0,
        public_functions: Vec::new(),
        public_classes: Vec::new(),
        imports: Vec::new(),
        tests: Vec::new(),
        error: None,
    };
    let text = match std::fs::read_to_string(py_file) {
        Ok(s) => s,
        Err(e) => {
            info.error = Some(format!("{e}"));
            return info;
        }
    };
    info.loc = text.lines().count() as u64;

    use once_cell::sync::Lazy;
    use regex::Regex;
    // Top-level (no leading whitespace) public def / class
    static FN_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?m)^def ([a-zA-Z][\w]*)\s*\(").unwrap());
    static CLASS_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?m)^class ([a-zA-Z][\w]*)\b").unwrap());
    static IMPORT_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))").unwrap());

    for cap in FN_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1) {
            let name = m.as_str().to_string();
            if !name.starts_with('_') {
                info.public_functions.push(name);
            }
        }
    }
    for cap in CLASS_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1) {
            let name = m.as_str().to_string();
            if !name.starts_with('_') {
                info.public_classes.push(name);
            }
        }
    }
    let mut imports: BTreeSet<String> = BTreeSet::new();
    for cap in IMPORT_RE.captures_iter(&text) {
        if let Some(m) = cap.get(1).or_else(|| cap.get(2)) {
            imports.insert(m.as_str().to_string());
        }
    }
    info.imports = imports.into_iter().collect();
    info
}

pub fn ai_modules(repo_root: &Path) -> Vec<ModuleInventory> {
    let dir = ai_root(repo_root).join("ai");
    if !dir.exists() {
        return Vec::new();
    }
    let mut files: Vec<PathBuf> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.extension().and_then(|s| s.to_str()) == Some("py")
                && p.file_name().and_then(|s| s.to_str()) != Some("__init__.py")
            {
                files.push(p);
            }
        }
    }
    files.sort();
    let tests_dir = ai_root(repo_root).join("tests");
    files
        .iter()
        .map(|p| {
            let mut info = module_inventory(p);
            // Look up test file
            if let Some(stem) = p.file_stem().and_then(|s| s.to_str()) {
                let test_p = tests_dir.join(format!("test_{stem}.py"));
                if test_p.exists() {
                    if let Ok(tt) = std::fs::read_to_string(&test_p) {
                        info.tests.push(TestFile {
                            path: test_p.display().to_string(),
                            loc: tt.lines().count() as u64,
                            test_count: tt.matches("\ndef test_").count() as u64,
                        });
                    }
                }
            }
            info
        })
        .collect()
}

/// `AIM/agents/` must not import from `AIM/AI/`. Grep over `from AI.`
/// and `import AI.`, honour `# noqa: AI-direction`.
pub fn direction_rule_status(repo_root: &Path) -> DirectionRuleStatus {
    let agents = repo_root.join("AIM").join("agents");
    if !agents.exists() {
        return DirectionRuleStatus {
            clean: true,
            violations: Vec::new(),
        };
    }
    let mut violations: Vec<String> = Vec::new();
    let mut stack: Vec<PathBuf> = vec![agents];
    while let Some(d) = stack.pop() {
        let entries = match std::fs::read_dir(&d) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
                continue;
            }
            if p.extension().and_then(|s| s.to_str()) != Some("py") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&p) else {
                continue;
            };
            for (i, line) in text.lines().enumerate() {
                let t = line.trim_start();
                if (t.starts_with("from AI.") || t.starts_with("import AI."))
                    && !line.contains("# noqa: AI-direction")
                {
                    violations.push(format!("{}:{} {}", p.display(), i + 1, t.trim()));
                }
            }
        }
    }
    DirectionRuleStatus {
        clean: violations.is_empty(),
        violations,
    }
}

pub fn inventory(repo_root: &Path) -> Inventory {
    let modules = ai_modules(repo_root);
    Inventory {
        generated_at: chrono::Utc::now()
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        aim_root: repo_root.display().to_string(),
        n_modules: modules.len() as u64,
        modules,
        direction_rule: direction_rule_status(repo_root),
    }
}

/// Build the full prompt: SELF_DIAGNOSTIC_PROMPT.md content +
/// inventory snapshot (JSON-pretty appended).
pub fn build_prompt(repo_root: &Path) -> Result<String, SelfDiagError> {
    let p = prompt_path(repo_root);
    if !p.exists() {
        return Err(SelfDiagError::PromptNotFound(p.display().to_string()));
    }
    let body = std::fs::read_to_string(&p)?;
    let inv = inventory(repo_root);
    let inv_json = serde_json::to_string_pretty(&inv).unwrap_or_else(|_| "{}".to_string());
    Ok(format!(
        "{body}\n\n---\n\n## Phase 0 — frozen inventory (do not fabricate)\n\n```json\n{inv_json}\n```\n"
    ))
}

/// Write the rendered prompt to disk; default destination
/// `<repo>/AIM/AI/artifacts/self_diag_request_<ts>.md`.
pub fn write_prompt(repo_root: &Path, dest: Option<&Path>) -> Result<PathBuf, SelfDiagError> {
    let body = build_prompt(repo_root)?;
    let target = match dest {
        Some(p) => p.to_path_buf(),
        None => {
            let ts = chrono::Utc::now().format("%Y-%m-%dT%H%M%S").to_string();
            ai_root(repo_root)
                .join("artifacts")
                .join(format!("self_diag_request_{ts}.md"))
        }
    };
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&target, body)?;
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn write(d: &Path, name: &str, body: &str) -> PathBuf {
        let p = d.join(name);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn module_inventory_parses_simple_python() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            "from AI.ai.foo import bar\nimport os\n\ndef public_fn():\n    pass\n\nclass MyClass:\n    pass\n\ndef _private():\n    pass\n",
        );
        let info = module_inventory(&p);
        assert_eq!(info.loc, 11);
        assert_eq!(info.public_functions, vec!["public_fn".to_string()]);
        assert_eq!(info.public_classes, vec!["MyClass".to_string()]);
        assert!(info.imports.iter().any(|s| s == "AI.ai.foo"));
        assert!(info.imports.iter().any(|s| s == "os"));
    }

    #[test]
    fn module_inventory_handles_missing_file() {
        let info = module_inventory(Path::new("/nonexistent"));
        assert!(info.error.is_some());
    }

    #[test]
    fn ai_modules_returns_only_py_no_init() {
        let d = tempdir().unwrap();
        let ai_d = d.path().join("AIM").join("AI").join("ai");
        std::fs::create_dir_all(&ai_d).unwrap();
        write(&ai_d, "alpha.py", "def x(): pass\n");
        write(&ai_d, "beta.py", "def y(): pass\n");
        write(&ai_d, "__init__.py", "");
        write(&ai_d, "ignored.txt", "x");
        let mods = ai_modules(d.path());
        let names: Vec<&str> = mods
            .iter()
            .map(|m| Path::new(&m.path).file_name().unwrap().to_str().unwrap())
            .collect();
        assert_eq!(names.len(), 2);
        assert!(names.contains(&"alpha.py"));
        assert!(names.contains(&"beta.py"));
        assert!(!names.iter().any(|n| n.contains("__init__")));
    }

    #[test]
    fn direction_rule_clean_when_no_agents() {
        let d = tempdir().unwrap();
        let s = direction_rule_status(d.path());
        assert!(s.clean);
    }

    #[test]
    fn direction_rule_flags_violations() {
        let d = tempdir().unwrap();
        let agents = d.path().join("AIM").join("agents");
        std::fs::create_dir_all(&agents).unwrap();
        write(&agents, "bad.py", "from AI.ai.x import y\n");
        let s = direction_rule_status(d.path());
        assert!(!s.clean);
        assert_eq!(s.violations.len(), 1);
        assert!(s.violations[0].contains("bad.py"));
    }

    #[test]
    fn direction_rule_honours_noqa_marker() {
        let d = tempdir().unwrap();
        let agents = d.path().join("AIM").join("agents");
        std::fs::create_dir_all(&agents).unwrap();
        write(&agents, "ok.py", "from AI.ai.x import y  # noqa: AI-direction\n");
        let s = direction_rule_status(d.path());
        assert!(s.clean);
    }

    #[test]
    fn inventory_envelope_complete() {
        let d = tempdir().unwrap();
        let inv = inventory(d.path());
        assert_eq!(inv.n_modules, 0);
        assert_eq!(inv.modules.len(), 0);
        assert!(inv.direction_rule.clean);
    }

    #[test]
    fn build_prompt_missing_file_errors() {
        let d = tempdir().unwrap();
        let r = build_prompt(d.path());
        assert!(matches!(r, Err(SelfDiagError::PromptNotFound(_))));
    }

    #[test]
    fn build_prompt_appends_inventory_block() {
        let d = tempdir().unwrap();
        let docs = d.path().join("AIM").join("AI").join("docs");
        std::fs::create_dir_all(&docs).unwrap();
        write(&docs, "SELF_DIAGNOSTIC_PROMPT.md", "# Audit prompt\n\nDo X.\n");
        let body = build_prompt(d.path()).unwrap();
        assert!(body.starts_with("# Audit prompt"));
        assert!(body.contains("Phase 0 — frozen inventory"));
        assert!(body.contains("\"n_modules\": 0"));
    }

    #[test]
    fn write_prompt_writes_dated_file() {
        let d = tempdir().unwrap();
        let docs = d.path().join("AIM").join("AI").join("docs");
        std::fs::create_dir_all(&docs).unwrap();
        write(&docs, "SELF_DIAGNOSTIC_PROMPT.md", "Audit\n");
        let dest = write_prompt(d.path(), None).unwrap();
        assert!(dest.exists());
        let body = std::fs::read_to_string(&dest).unwrap();
        assert!(body.contains("Phase 0 — frozen inventory"));
    }

    #[test]
    fn lazy_import_inside_function_still_extracted() {
        let d = tempdir().unwrap();
        let p = write(
            d.path(),
            "x.py",
            "def fn():\n    from AI.ai.helper import thing\n    return thing\n",
        );
        let info = module_inventory(&p);
        assert!(info.imports.iter().any(|s| s == "AI.ai.helper"));
    }
}
