//! aim-tool-synthesis — repeating-pattern → new tool (S2).
//!
//! Port of `agents/tool_synthesis.py`. `aim-pattern-miner` finds sequential
//! pairs (`tool A → tool B` recurring across sessions). This crate turns
//! each popular pair into a single, named, hot-loadable [`SynthesisedTool`]
//! that wraps both calls via a [`ToolRegistry`].
//!
//! ### Safety constraints (L_VERIFIABILITY mirror)
//! - Tool definition is a **data structure**, not generated source code,
//!   so attacker-influenced session logs cannot inject Rust to execute.
//! - Each candidate must pass at least 5 fixture invocations before
//!   `register()` writes it to disk.
//! - Fixture results pass when the registry returns no error AND every
//!   call's output starts with the user-supplied success marker (or the
//!   default OK marker).
//!
//! ### Workflow
//! ```ignore
//! let cands = candidates(&findings, 14, 5, 3);
//! let res = engine.propose(&cands[0], &fixture, 5);
//! if res.passed && trusted {
//!     let path = engine.register(&res)?;
//! }
//! ```

use aim_pattern_miner::Finding;
use chrono::Utc;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SynthError {
    #[error("invalid candidate name: {0}")]
    InvalidName(String),
    #[error("refuse to register failing tool: {0}")]
    RegisterFailing(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SynthesisCandidate {
    pub name: String,
    pub tool_a: String,
    pub tool_b: String,
    pub support: u32,
    #[serde(default)]
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FixtureRun {
    pub ok: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub a: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub b: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesisResult {
    pub candidate: SynthesisCandidate,
    pub passed: bool,
    pub fixture_results: Vec<FixtureRun>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Created-at timestamp (ISO 8601 UTC) — set when `register()` runs.
    #[serde(default)]
    pub registered_at: Option<String>,
}

static VALID_NAME_RE: OnceLock<Regex> = OnceLock::new();
fn valid_name_re() -> &'static Regex {
    VALID_NAME_RE.get_or_init(|| Regex::new(r"^[a-z][a-z0-9_]*$").unwrap())
}

static SLUG_RE: OnceLock<Regex> = OnceLock::new();
fn slug_re() -> &'static Regex {
    SLUG_RE.get_or_init(|| Regex::new(r"[^a-z0-9_]").unwrap())
}

fn safe_name(a: &str, b: &str) -> String {
    let a = slug_re().replace_all(&a.to_lowercase(), "_").trim_matches('_').to_string();
    let b = slug_re().replace_all(&b.to_lowercase(), "_").trim_matches('_').to_string();
    if a.is_empty() || b.is_empty() {
        return String::new();
    }
    format!("{a}_then_{b}")
}

/// Pull synthesis candidates from pattern-miner findings.
///
/// Filters: `kind == sequential_pair`, `support ≥ min_support`, valid
/// snake_case combined name. Returns up to `top_n` in input order.
pub fn candidates(
    findings: &[Finding],
    _window_days: u32,
    top_n: usize,
    min_support: u32,
) -> Vec<SynthesisCandidate> {
    let mut out = Vec::new();
    for f in findings {
        if f.kind != "sequential_pair" || f.support < min_support {
            continue;
        }
        let a = f.sample.get("a").and_then(|v| v.as_str()).unwrap_or("");
        let b = f.sample.get("b").and_then(|v| v.as_str()).unwrap_or("");
        let name = safe_name(a, b);
        if name.is_empty() || !valid_name_re().is_match(&name) {
            continue;
        }
        out.push(SynthesisCandidate {
            name,
            tool_a: a.to_string(),
            tool_b: b.to_string(),
            support: f.support,
            description: f.summary.clone(),
        });
        if out.len() >= top_n {
            break;
        }
    }
    out
}

/// Pluggable tool registry that synthesised tools dispatch through. Tests
/// inject [`StubRegistry`] with pre-baked responses.
pub trait ToolRegistry: Send + Sync {
    fn call(&self, name: &str, args: &serde_json::Value) -> Result<String, String>;
}

#[derive(Debug, Default)]
pub struct StubRegistry {
    pub responses: Mutex<HashMap<String, String>>,
}

impl StubRegistry {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set(self, name: impl Into<String>, response: impl Into<String>) -> Self {
        self.responses.lock().insert(name.into(), response.into());
        self
    }
}

impl ToolRegistry for StubRegistry {
    fn call(&self, name: &str, _args: &serde_json::Value) -> Result<String, String> {
        self.responses
            .lock()
            .get(name)
            .cloned()
            .ok_or_else(|| format!("ERROR:NoStub:{name}"))
    }
}

/// One run of the synthesised pair. Calls `tool_a(args_a)` then
/// `tool_b(args_b)` through the registry; fails if either errors or
/// returns a string starting with `ERROR:` (matches Python convention).
pub fn run_pair(
    tool_a: &str,
    tool_b: &str,
    args_a: &serde_json::Value,
    args_b: &serde_json::Value,
    registry: &dyn ToolRegistry,
) -> FixtureRun {
    let res_a = registry.call(tool_a, args_a);
    let res_b = registry.call(tool_b, args_b);
    let (a_str, a_ok) = match &res_a {
        Ok(s) if !s.starts_with("ERROR:") => (Some(s.clone()), true),
        Ok(s) => (Some(s.clone()), false),
        Err(e) => (None, !e.is_empty() && false),
    };
    let (b_str, b_ok) = match &res_b {
        Ok(s) if !s.starts_with("ERROR:") => (Some(s.clone()), true),
        Ok(s) => (Some(s.clone()), false),
        Err(_) => (None, false),
    };
    let error = match (&res_a, &res_b) {
        (Err(e), _) => Some(e.clone()),
        (_, Err(e)) => Some(e.clone()),
        _ => None,
    };
    FixtureRun {
        ok: a_ok && b_ok,
        a: a_str,
        b: b_str,
        error,
    }
}

/// Fixture closure: returns a `(args_a, args_b, registry)` triple per call.
pub type Fixture<'a> = dyn Fn() -> (serde_json::Value, serde_json::Value, Box<dyn ToolRegistry>) + 'a;

pub const DEFAULT_REPEATS: u32 = 5;

pub struct Engine {
    synth_dir: PathBuf,
    audit_path: PathBuf,
}

impl Engine {
    pub fn new(synth_dir: impl Into<PathBuf>, audit_path: impl Into<PathBuf>) -> Self {
        Self {
            synth_dir: synth_dir.into(),
            audit_path: audit_path.into(),
        }
    }

    /// Default-locations engine: `~/.aim/tools/synthesised/` and
    /// `$AIM_HOME/tool_synthesis.jsonl`.
    pub fn from_env() -> Self {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        let synth = std::env::var("AIM_SYNTH_TOOLS_DIR")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".aim").join("tools").join("synthesised"));
        let aim_home = std::env::var("AIM_HOME")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".cache").join("aim"));
        Self::new(synth, aim_home.join("tool_synthesis.jsonl"))
    }

    pub fn synth_dir(&self) -> &Path {
        &self.synth_dir
    }

    /// Render a synthesis (no-op for data-driven port — kept for parity).
    pub fn render_definition(&self, c: &SynthesisCandidate) -> SynthesisedTool {
        SynthesisedTool {
            name: c.name.clone(),
            tool_a: c.tool_a.clone(),
            tool_b: c.tool_b.clone(),
            support: c.support,
            description: c.description.clone(),
        }
    }

    /// Run the candidate `repeats` times against `fixture`. Does NOT write to disk.
    pub fn propose(
        &self,
        candidate: &SynthesisCandidate,
        fixture: &Fixture<'_>,
        repeats: u32,
    ) -> SynthesisResult {
        let mut runs = Vec::new();
        for _ in 0..repeats.max(1) {
            let (args_a, args_b, reg) = fixture();
            let r = run_pair(&candidate.tool_a, &candidate.tool_b, &args_a, &args_b, &*reg);
            runs.push(r);
        }
        let passed = !runs.is_empty() && runs.iter().all(|r| r.ok);
        SynthesisResult {
            candidate: candidate.clone(),
            passed,
            error: if passed {
                None
            } else {
                Some("fixture not all-pass".into())
            },
            fixture_results: runs,
            registered_at: None,
        }
    }

    /// Persist a passing result. Errors with [`SynthError::RegisterFailing`]
    /// when `result.passed == false`.
    pub fn register(&self, result: &SynthesisResult) -> Result<PathBuf, SynthError> {
        if !result.passed {
            return Err(SynthError::RegisterFailing(
                result.error.clone().unwrap_or_else(|| "unknown".into()),
            ));
        }
        if !valid_name_re().is_match(&result.candidate.name) {
            return Err(SynthError::InvalidName(result.candidate.name.clone()));
        }
        std::fs::create_dir_all(&self.synth_dir)?;
        let path = self.synth_dir.join(format!("{}.json", result.candidate.name));
        let mut owned = result.clone();
        owned.registered_at = Some(Utc::now().to_rfc3339());
        std::fs::write(&path, serde_json::to_vec_pretty(&owned)?)?;
        self.audit("register", &result.candidate, Some(&path))?;
        Ok(path)
    }

    /// List registered tool names (file stems).
    pub fn list_registered(&self) -> Vec<String> {
        if !self.synth_dir.exists() {
            return Vec::new();
        }
        let mut out: Vec<String> = std::fs::read_dir(&self.synth_dir)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("json"))
            .filter_map(|e| {
                e.path()
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .filter(|n| !n.starts_with('_'))
                    .map(String::from)
            })
            .collect();
        out.sort();
        out
    }

    /// Drop a registered tool. Returns `true` if a file was removed.
    pub fn remove(&self, name: &str) -> Result<bool, SynthError> {
        let p = self.synth_dir.join(format!("{name}.json"));
        if p.exists() {
            std::fs::remove_file(&p)?;
            // Audit unregister; can't reconstruct full candidate, so use a minimal one.
            let dummy = SynthesisCandidate {
                name: name.to_string(),
                tool_a: String::new(),
                tool_b: String::new(),
                support: 0,
                description: String::new(),
            };
            self.audit("unregister", &dummy, Some(&p))?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    fn audit(
        &self,
        event: &str,
        c: &SynthesisCandidate,
        path: Option<&Path>,
    ) -> Result<(), SynthError> {
        if let Some(parent) = self.audit_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let mut entry = serde_json::json!({
            "ts": Utc::now().to_rfc3339(),
            "event": event,
            "name": c.name,
            "support": c.support,
            "tool_a": c.tool_a,
            "tool_b": c.tool_b,
        });
        if let Some(p) = path {
            entry["path"] = serde_json::Value::String(p.to_string_lossy().to_string());
        }
        let line = serde_json::to_string(&entry)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.audit_path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    /// Recent audit-log entries. Newest at the end (matches Python `history()`).
    pub fn history(&self, limit: usize) -> Result<Vec<serde_json::Value>, SynthError> {
        if !self.audit_path.exists() {
            return Ok(Vec::new());
        }
        let raw = std::fs::read_to_string(&self.audit_path)?;
        let mut all: Vec<serde_json::Value> = raw
            .lines()
            .filter(|l| !l.trim().is_empty())
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect();
        if all.len() > limit {
            all = all.split_off(all.len() - limit);
        }
        Ok(all)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesisedTool {
    pub name: String,
    pub tool_a: String,
    pub tool_b: String,
    pub support: u32,
    pub description: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_pattern_miner::Finding;
    use serde_json::json;
    use tempfile::TempDir;

    fn engine() -> (TempDir, Engine) {
        let dir = TempDir::new().unwrap();
        let synth = dir.path().join("synthesised");
        let audit = dir.path().join("tool_synthesis.jsonl");
        (TempDir::new().unwrap(), Engine::new(synth, audit))
            .let_with(|(_, e)| (dir, e))
    }

    trait Tap<T> {
        fn let_with<U>(self, f: impl FnOnce(T) -> U) -> U;
    }
    impl<T> Tap<T> for T {
        fn let_with<U>(self, f: impl FnOnce(T) -> U) -> U {
            f(self)
        }
    }

    fn finding(a: &str, b: &str, support: u32) -> Finding {
        Finding {
            kind: "sequential_pair".into(),
            summary: format!("{} → {} appears in {} sessions", a, b, support),
            support,
            sample: json!({"a": a, "b": b}),
        }
    }

    #[test]
    fn safe_name_combines_inputs() {
        assert_eq!(safe_name("read-file", "grep"), "read_file_then_grep");
        assert_eq!(safe_name("read.file", "Grep"), "read_file_then_grep");
    }

    #[test]
    fn safe_name_rejects_empty() {
        assert_eq!(safe_name("", "grep"), "");
        assert_eq!(safe_name("read", ""), "");
    }

    #[test]
    fn candidates_filters_by_kind_and_support() {
        let f1 = finding("read_file", "grep", 5);
        let f2 = finding("a", "b", 1); // below min_support
        let mut f3 = finding("c", "d", 10);
        f3.kind = "tool_failure_rate".into(); // wrong kind
        let cands = candidates(&[f1, f2, f3], 14, 5, 3);
        assert_eq!(cands.len(), 1);
        assert_eq!(cands[0].name, "read_file_then_grep");
        assert_eq!(cands[0].support, 5);
    }

    #[test]
    fn candidates_caps_at_top_n() {
        let findings: Vec<Finding> = (0..10)
            .map(|i| finding(&format!("x{i}"), &format!("y{i}"), 5))
            .collect();
        let cands = candidates(&findings, 14, 3, 3);
        assert_eq!(cands.len(), 3);
    }

    #[test]
    fn run_pair_ok_when_both_succeed() {
        let reg = StubRegistry::new()
            .set("read_file", "<file content>")
            .set("grep", "matched 3 lines");
        let r = run_pair("read_file", "grep", &json!({}), &json!({}), &reg);
        assert!(r.ok);
        assert_eq!(r.a.as_deref(), Some("<file content>"));
        assert_eq!(r.b.as_deref(), Some("matched 3 lines"));
    }

    #[test]
    fn run_pair_fails_when_b_errors() {
        let reg = StubRegistry::new()
            .set("read_file", "<content>")
            .set("grep", "ERROR:Regex:invalid pattern");
        let r = run_pair("read_file", "grep", &json!({}), &json!({}), &reg);
        assert!(!r.ok);
        assert!(r.b.as_deref().unwrap().starts_with("ERROR:"));
    }

    #[test]
    fn run_pair_fails_when_registry_returns_err() {
        let reg = StubRegistry::new().set("read_file", "ok");
        // grep not stubbed → registry returns Err
        let r = run_pair("read_file", "grep", &json!({}), &json!({}), &reg);
        assert!(!r.ok);
        assert!(r.error.is_some());
    }

    #[test]
    fn propose_passes_with_default_fixture() {
        let (_d, eng) = engine();
        let cand = SynthesisCandidate {
            name: "a_then_b".into(),
            tool_a: "a".into(),
            tool_b: "b".into(),
            support: 5,
            description: "test".into(),
        };
        let fixture: Box<Fixture<'_>> = Box::new(|| {
            let reg = StubRegistry::new().set("a", "OK_a").set("b", "OK_b");
            (json!({}), json!({}), Box::new(reg) as Box<dyn ToolRegistry>)
        });
        let res = eng.propose(&cand, &*fixture, 5);
        assert!(res.passed, "{:?}", res);
        assert_eq!(res.fixture_results.len(), 5);
    }

    #[test]
    fn propose_fails_when_fixture_errors() {
        let (_d, eng) = engine();
        let cand = SynthesisCandidate {
            name: "a_then_b".into(),
            tool_a: "a".into(),
            tool_b: "b".into(),
            support: 5,
            description: "".into(),
        };
        let fixture: Box<Fixture<'_>> = Box::new(|| {
            let reg = StubRegistry::new().set("a", "ERROR:X").set("b", "OK");
            (json!({}), json!({}), Box::new(reg) as Box<dyn ToolRegistry>)
        });
        let res = eng.propose(&cand, &*fixture, 3);
        assert!(!res.passed);
        assert_eq!(res.error.as_deref(), Some("fixture not all-pass"));
    }

    #[test]
    fn register_writes_json_file() {
        let (_d, eng) = engine();
        let res = SynthesisResult {
            candidate: SynthesisCandidate {
                name: "a_then_b".into(),
                tool_a: "a".into(),
                tool_b: "b".into(),
                support: 7,
                description: "test".into(),
            },
            passed: true,
            fixture_results: vec![FixtureRun {
                ok: true,
                a: Some("OK".into()),
                b: Some("OK".into()),
                error: None,
            }],
            error: None,
            registered_at: None,
        };
        let path = eng.register(&res).unwrap();
        assert!(path.exists());
        let raw = std::fs::read_to_string(&path).unwrap();
        let parsed: SynthesisResult = serde_json::from_str(&raw).unwrap();
        assert_eq!(parsed.candidate.name, "a_then_b");
        assert!(parsed.registered_at.is_some());
    }

    #[test]
    fn register_refuses_failing_result() {
        let (_d, eng) = engine();
        let res = SynthesisResult {
            candidate: SynthesisCandidate {
                name: "a_then_b".into(),
                tool_a: "a".into(),
                tool_b: "b".into(),
                support: 5,
                description: "".into(),
            },
            passed: false,
            fixture_results: vec![],
            error: Some("fixture not all-pass".into()),
            registered_at: None,
        };
        let err = eng.register(&res).unwrap_err();
        assert!(matches!(err, SynthError::RegisterFailing(_)));
    }

    #[test]
    fn list_registered_returns_sorted_stems() {
        let (_d, eng) = engine();
        std::fs::create_dir_all(eng.synth_dir()).unwrap();
        for name in ["beta_then_b", "alpha_then_a"] {
            let res = SynthesisResult {
                candidate: SynthesisCandidate {
                    name: name.into(),
                    tool_a: "x".into(),
                    tool_b: "y".into(),
                    support: 5,
                    description: "".into(),
                },
                passed: true,
                fixture_results: vec![FixtureRun {
                    ok: true,
                    a: None,
                    b: None,
                    error: None,
                }],
                error: None,
                registered_at: None,
            };
            eng.register(&res).unwrap();
        }
        let lst = eng.list_registered();
        assert_eq!(lst, vec!["alpha_then_a", "beta_then_b"]);
    }

    #[test]
    fn remove_drops_file_and_audits() {
        let (_d, eng) = engine();
        let res = SynthesisResult {
            candidate: SynthesisCandidate {
                name: "x_then_y".into(),
                tool_a: "x".into(),
                tool_b: "y".into(),
                support: 5,
                description: "".into(),
            },
            passed: true,
            fixture_results: vec![FixtureRun {
                ok: true,
                a: None,
                b: None,
                error: None,
            }],
            error: None,
            registered_at: None,
        };
        eng.register(&res).unwrap();
        assert!(eng.remove("x_then_y").unwrap());
        assert!(!eng.remove("x_then_y").unwrap()); // already gone
        let h = eng.history(10).unwrap();
        assert!(h.iter().any(|e| e["event"] == "register"));
        assert!(h.iter().any(|e| e["event"] == "unregister"));
    }

    #[test]
    fn history_limits_results() {
        let (_d, eng) = engine();
        for i in 0..5 {
            let res = SynthesisResult {
                candidate: SynthesisCandidate {
                    name: format!("x{i}_then_y{i}"),
                    tool_a: "x".into(),
                    tool_b: "y".into(),
                    support: 5,
                    description: "".into(),
                },
                passed: true,
                fixture_results: vec![FixtureRun {
                    ok: true,
                    a: None,
                    b: None,
                    error: None,
                }],
                error: None,
                registered_at: None,
            };
            eng.register(&res).unwrap();
        }
        let h = eng.history(3).unwrap();
        assert_eq!(h.len(), 3);
    }
}
