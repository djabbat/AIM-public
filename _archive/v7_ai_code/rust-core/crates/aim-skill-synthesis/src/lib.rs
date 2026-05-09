//! aim-skill-synthesis — named-macro skills (S7).
//!
//! Port of `agents/skill_synthesis.py`. Where [`aim_tool_synthesis`] turns
//! 2-tool sequences into single tools, this crate turns longer recurring
//! tool sequences (3+ steps) into named **skills** the model can invoke
//! by name.
//!
//! Skills are persisted as YAML in `~/.aim/skills/<name>.yaml`. Each
//! skill declares an ordered list of `(tool, args_template)` pairs. At
//! invocation time, args templates are formatted with user-supplied
//! parameters (Rust-flavoured `{key}` placeholders) before each tool fires.
//!
//! ## Workflow
//! ```ignore
//! let cands = candidates(&events, 3, 3, 5);
//! let skill = propose("publish_paper", &steps, "publish via journal cascade")?;
//! engine.register(&skill)?;
//! let result = engine.invoke("publish_paper", &params, &registry);
//! ```

use aim_tool_synthesis::ToolRegistry;
use chrono::Utc;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SkillError {
    #[error("invalid skill name: {0}")]
    InvalidName(String),
    #[error("skill must have at least one step")]
    EmptySteps,
    #[error("step missing tool: {0}")]
    StepMissingTool(String),
    #[error("skill not found: {0}")]
    NotFound(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SkillStep {
    pub tool: String,
    /// String args may contain `{placeholder}` that get formatted at
    /// invocation time. Non-string args pass through unchanged.
    #[serde(default)]
    pub args: BTreeMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Skill {
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub steps: Vec<SkillStep>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SkillCandidate {
    pub name: String,
    pub steps: Vec<String>,
    pub support: u32,
}

static VALID_NAME_RE: OnceLock<Regex> = OnceLock::new();
fn valid_name_re() -> &'static Regex {
    VALID_NAME_RE.get_or_init(|| Regex::new(r"^[a-z][a-z0-9_]*$").unwrap())
}

static SLUG_RE: OnceLock<Regex> = OnceLock::new();
fn slug_re() -> &'static Regex {
    SLUG_RE.get_or_init(|| Regex::new(r"[^a-z0-9_]").unwrap())
}

fn slug(s: &str) -> String {
    slug_re()
        .replace_all(&s.to_lowercase(), "_")
        .trim_matches('_')
        .to_string()
}

/// Cluster session tool-call sequences (one per `tool_call` event) into
/// recurring N-grams of length [`min_length` .. `min_length+2`].
///
/// Each session contributes ONE vote per distinct sequence (matches
/// Python). Returns up to `top_n` candidates sorted by support desc.
pub fn candidates(
    events: &[serde_json::Value],
    min_length: usize,
    min_support: u32,
    top_n: usize,
) -> Vec<SkillCandidate> {
    if min_length == 0 {
        return Vec::new();
    }
    let mut sessions: HashMap<String, Vec<String>> = HashMap::new();
    for ev in events {
        if ev.get("type").and_then(|v| v.as_str()) != Some("tool_call") {
            continue;
        }
        let sid = ev
            .get("session_id")
            .and_then(|v| v.as_str())
            .or_else(|| ev.get("run_id").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        let name = ev
            .get("tool")
            .and_then(|v| v.as_str())
            .or_else(|| ev.get("name").and_then(|v| v.as_str()))
            .unwrap_or("");
        if name.is_empty() {
            continue;
        }
        sessions.entry(sid).or_default().push(name.to_string());
    }

    let mut counts: HashMap<Vec<String>, u32> = HashMap::new();
    for (_sid, calls) in &sessions {
        let mut seen_local: std::collections::HashSet<Vec<String>> = Default::default();
        for l in min_length..=min_length + 2 {
            if l > calls.len() {
                continue;
            }
            for i in 0..=(calls.len() - l) {
                let seq = calls[i..i + l].to_vec();
                if seen_local.insert(seq.clone()) {
                    *counts.entry(seq).or_insert(0) += 1;
                }
            }
        }
    }

    let mut sorted: Vec<(Vec<String>, u32)> = counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1));

    let mut out = Vec::new();
    for (seq, n) in sorted {
        if n < min_support {
            continue;
        }
        let mut name: String = seq.iter().map(|t| slug(t)).collect::<Vec<_>>().join("_then_");
        name.truncate(60);
        if !valid_name_re().is_match(&name) {
            continue;
        }
        out.push(SkillCandidate {
            name,
            steps: seq,
            support: n,
        });
        if out.len() >= top_n {
            break;
        }
    }
    out
}

/// Build a [`Skill`] from a name + step list. Validates the name and
/// rejects empty steps lists.
pub fn propose(name: &str, steps: Vec<SkillStep>, description: &str) -> Result<Skill, SkillError> {
    if !valid_name_re().is_match(name) {
        return Err(SkillError::InvalidName(name.to_string()));
    }
    if steps.is_empty() {
        return Err(SkillError::EmptySteps);
    }
    for (i, s) in steps.iter().enumerate() {
        if s.tool.is_empty() {
            return Err(SkillError::StepMissingTool(format!("index {i}")));
        }
    }
    Ok(Skill {
        name: name.to_string(),
        description: description.to_string(),
        steps,
    })
}

/// Format a single string arg by substituting `{key}` → params[key].
/// Unknown keys are left as-is (matches Python's `str.format` with
/// `KeyError` swallowed).
pub fn format_string(template: &str, params: &HashMap<String, String>) -> String {
    let mut out = String::with_capacity(template.len());
    let bytes = template.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == '{' {
            // Find matching close brace
            if let Some(end) = template[i + 1..].find('}') {
                let key = &template[i + 1..i + 1 + end];
                if let Some(v) = params.get(key) {
                    out.push_str(v);
                } else {
                    // Unknown key — keep literal
                    out.push_str(&template[i..i + 1 + end + 1]);
                }
                i += 1 + end + 1;
                continue;
            }
        }
        out.push(c);
        i += 1;
    }
    out
}

fn format_args(
    args: &BTreeMap<String, serde_yaml::Value>,
    params: &HashMap<String, String>,
) -> serde_json::Value {
    let mut out = serde_json::Map::new();
    for (k, v) in args {
        let new_v = match v {
            serde_yaml::Value::String(s) => serde_json::Value::String(format_string(s, params)),
            other => yaml_to_json(other),
        };
        out.insert(k.clone(), new_v);
    }
    serde_json::Value::Object(out)
}

fn yaml_to_json(v: &serde_yaml::Value) -> serde_json::Value {
    match v {
        serde_yaml::Value::Null => serde_json::Value::Null,
        serde_yaml::Value::Bool(b) => serde_json::Value::Bool(*b),
        serde_yaml::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                serde_json::Value::Number(serde_json::Number::from(i))
            } else if let Some(f) = n.as_f64() {
                serde_json::Number::from_f64(f)
                    .map(serde_json::Value::Number)
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        serde_yaml::Value::String(s) => serde_json::Value::String(s.clone()),
        serde_yaml::Value::Sequence(s) => {
            serde_json::Value::Array(s.iter().map(yaml_to_json).collect())
        }
        serde_yaml::Value::Mapping(m) => {
            let mut o = serde_json::Map::new();
            for (k, v) in m {
                let key = match k {
                    serde_yaml::Value::String(s) => s.clone(),
                    other => serde_yaml::to_string(other).unwrap_or_default().trim().to_string(),
                };
                o.insert(key, yaml_to_json(v));
            }
            serde_json::Value::Object(o)
        }
        serde_yaml::Value::Tagged(t) => yaml_to_json(&t.value),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InvokeResult {
    pub ok: bool,
    pub results: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failed_at: Option<usize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

pub struct Engine {
    skills_dir: PathBuf,
    audit_path: PathBuf,
}

impl Engine {
    pub fn new(skills_dir: impl Into<PathBuf>, audit_path: impl Into<PathBuf>) -> Self {
        Self {
            skills_dir: skills_dir.into(),
            audit_path: audit_path.into(),
        }
    }

    /// Default-locations engine: `$AIM_SKILLS_DIR` (or `~/.aim/skills/`)
    /// and `$AIM_HOME/skill_synthesis.jsonl`.
    pub fn from_env() -> Self {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        let skills = std::env::var("AIM_SKILLS_DIR")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".aim").join("skills"));
        let aim_home = std::env::var("AIM_HOME")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".cache").join("aim"));
        Self::new(skills, aim_home.join("skill_synthesis.jsonl"))
    }

    pub fn skills_dir(&self) -> &Path {
        &self.skills_dir
    }

    pub fn register(&self, skill: &Skill) -> Result<PathBuf, SkillError> {
        if !valid_name_re().is_match(&skill.name) {
            return Err(SkillError::InvalidName(skill.name.clone()));
        }
        std::fs::create_dir_all(&self.skills_dir)?;
        let path = self.skills_dir.join(format!("{}.yaml", skill.name));
        let body = serde_yaml::to_string(&skill)?;
        std::fs::write(&path, body)?;
        let extra = serde_json::json!({
            "steps": skill.steps.iter().map(|s| s.tool.clone()).collect::<Vec<_>>()
        });
        self.audit("register", &skill.name, &extra)?;
        Ok(path)
    }

    pub fn load(&self, name: &str) -> Result<Skill, SkillError> {
        let path = self.skills_dir.join(format!("{name}.yaml"));
        if !path.exists() {
            return Err(SkillError::NotFound(name.to_string()));
        }
        let raw = std::fs::read_to_string(&path)?;
        let skill: Skill = serde_yaml::from_str(&raw)?;
        Ok(skill)
    }

    pub fn list_registered(&self) -> Vec<String> {
        if !self.skills_dir.exists() {
            return Vec::new();
        }
        let mut out: Vec<String> = std::fs::read_dir(&self.skills_dir)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("yaml"))
            .filter_map(|e| {
                e.path()
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .map(String::from)
            })
            .collect();
        out.sort();
        out
    }

    pub fn remove(&self, name: &str) -> Result<bool, SkillError> {
        let p = self.skills_dir.join(format!("{name}.yaml"));
        if p.exists() {
            std::fs::remove_file(&p)?;
            self.audit("unregister", name, &serde_json::json!({}))?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Execute every step in the skill, stopping at the first registry
    /// error or `ERROR:`-prefixed result.
    pub fn invoke(
        &self,
        name: &str,
        params: &HashMap<String, String>,
        registry: &dyn ToolRegistry,
    ) -> Result<InvokeResult, SkillError> {
        let skill = self.load(name)?;
        let mut results = Vec::with_capacity(skill.steps.len());
        for (i, step) in skill.steps.iter().enumerate() {
            let args = format_args(&step.args, params);
            match registry.call(&step.tool, &args) {
                Ok(s) if !s.starts_with("ERROR:") => {
                    results.push(s);
                }
                Ok(s) => {
                    let _ = self.audit(
                        "invoke_failed",
                        name,
                        &serde_json::json!({ "step": i, "tool": step.tool, "error": truncate(&s, 200) }),
                    );
                    let mut all = results;
                    all.push(s.clone());
                    return Ok(InvokeResult {
                        ok: false,
                        results: all,
                        failed_at: Some(i),
                        tool: Some(step.tool.clone()),
                        error: Some(s),
                    });
                }
                Err(e) => {
                    let _ = self.audit(
                        "invoke_failed",
                        name,
                        &serde_json::json!({ "step": i, "tool": step.tool, "error": truncate(&e, 200) }),
                    );
                    return Ok(InvokeResult {
                        ok: false,
                        results,
                        failed_at: Some(i),
                        tool: Some(step.tool.clone()),
                        error: Some(e),
                    });
                }
            }
        }
        let _ = self.audit(
            "invoke_ok",
            name,
            &serde_json::json!({ "steps": skill.steps.len() }),
        );
        Ok(InvokeResult {
            ok: true,
            results,
            failed_at: None,
            tool: None,
            error: None,
        })
    }

    fn audit(
        &self,
        event: &str,
        name: &str,
        extra: &serde_json::Value,
    ) -> Result<(), SkillError> {
        if let Some(parent) = self.audit_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let mut entry = serde_json::Map::new();
        entry.insert("ts".into(), serde_json::Value::String(Utc::now().to_rfc3339()));
        entry.insert("event".into(), serde_json::Value::String(event.into()));
        entry.insert("name".into(), serde_json::Value::String(name.into()));
        if let Some(o) = extra.as_object() {
            for (k, v) in o {
                entry.insert(k.clone(), v.clone());
            }
        }
        let line = serde_json::to_string(&serde_json::Value::Object(entry))? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.audit_path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }

    /// Recent audit-log entries. Newest at the end (matches Python).
    pub fn history(&self, limit: usize) -> Result<Vec<serde_json::Value>, SkillError> {
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

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        s.chars().take(max).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use aim_tool_synthesis::StubRegistry;
    use serde_json::json;
    use tempfile::TempDir;

    fn engine() -> (TempDir, Engine) {
        let dir = TempDir::new().unwrap();
        let skills = dir.path().join("skills");
        let audit = dir.path().join("skill_synth.jsonl");
        let eng = Engine::new(skills, audit);
        (dir, eng)
    }

    fn ev_call(tool: &str, sid: &str) -> serde_json::Value {
        json!({"type": "tool_call", "tool": tool, "session_id": sid})
    }

    #[test]
    fn candidates_clusters_recurring_ngrams() {
        let mut events = Vec::new();
        for sid in ["s1", "s2", "s3"] {
            events.push(ev_call("a", sid));
            events.push(ev_call("b", sid));
            events.push(ev_call("c", sid));
        }
        let cands = candidates(&events, 3, 3, 5);
        assert_eq!(cands.len(), 1);
        assert_eq!(cands[0].name, "a_then_b_then_c");
        assert_eq!(cands[0].support, 3);
    }

    #[test]
    fn candidates_below_min_support_filtered() {
        let mut events = Vec::new();
        events.push(ev_call("a", "s1"));
        events.push(ev_call("b", "s1"));
        events.push(ev_call("c", "s1"));
        let cands = candidates(&events, 3, 3, 5);
        assert!(cands.is_empty());
    }

    #[test]
    fn candidates_dedup_within_session() {
        // Same 3-gram repeated in s1 should count once
        let mut events = Vec::new();
        for _ in 0..2 {
            events.push(ev_call("a", "s1"));
            events.push(ev_call("b", "s1"));
            events.push(ev_call("c", "s1"));
        }
        events.push(ev_call("a", "s2"));
        events.push(ev_call("b", "s2"));
        events.push(ev_call("c", "s2"));
        let cands = candidates(&events, 3, 2, 5);
        assert!(cands.iter().any(|c| c.steps == vec!["a", "b", "c"] && c.support == 2));
    }

    #[test]
    fn propose_validates_name() {
        let step = SkillStep {
            tool: "x".into(),
            args: BTreeMap::new(),
        };
        assert!(propose("Bad-Name", vec![step.clone()], "").is_err());
        assert!(propose("good_name", vec![step.clone()], "").is_ok());
    }

    #[test]
    fn propose_rejects_empty_steps() {
        let err = propose("good", vec![], "").unwrap_err();
        assert!(matches!(err, SkillError::EmptySteps));
    }

    #[test]
    fn register_then_load_round_trip() {
        let (_d, eng) = engine();
        let mut args = BTreeMap::new();
        args.insert(
            "path".to_string(),
            serde_yaml::Value::String("{repo}/README.md".into()),
        );
        let step = SkillStep {
            tool: "read_file".into(),
            args,
        };
        let skill = propose("readme_chain", vec![step], "demo skill").unwrap();
        eng.register(&skill).unwrap();
        let loaded = eng.load("readme_chain").unwrap();
        assert_eq!(loaded.name, "readme_chain");
        assert_eq!(loaded.steps.len(), 1);
        assert_eq!(loaded.steps[0].tool, "read_file");
    }

    #[test]
    fn list_registered_sorted_stems() {
        let (_d, eng) = engine();
        for n in ["beta_skill", "alpha_skill"] {
            let step = SkillStep {
                tool: "x".into(),
                args: BTreeMap::new(),
            };
            let s = propose(n, vec![step], "").unwrap();
            eng.register(&s).unwrap();
        }
        assert_eq!(eng.list_registered(), vec!["alpha_skill", "beta_skill"]);
    }

    #[test]
    fn remove_drops_file_and_audits() {
        let (_d, eng) = engine();
        let s = propose(
            "tmp_skill",
            vec![SkillStep {
                tool: "x".into(),
                args: BTreeMap::new(),
            }],
            "",
        )
        .unwrap();
        eng.register(&s).unwrap();
        assert!(eng.remove("tmp_skill").unwrap());
        assert!(!eng.remove("tmp_skill").unwrap());
        let h = eng.history(10).unwrap();
        assert!(h.iter().any(|e| e["event"] == "register"));
        assert!(h.iter().any(|e| e["event"] == "unregister"));
    }

    #[test]
    fn invoke_runs_all_steps() {
        let (_d, eng) = engine();
        let s = propose(
            "two_step",
            vec![
                SkillStep {
                    tool: "a".into(),
                    args: BTreeMap::new(),
                },
                SkillStep {
                    tool: "b".into(),
                    args: BTreeMap::new(),
                },
            ],
            "",
        )
        .unwrap();
        eng.register(&s).unwrap();
        let reg = StubRegistry::new().set("a", "ok-a").set("b", "ok-b");
        let r = eng
            .invoke("two_step", &HashMap::new(), &reg)
            .unwrap();
        assert!(r.ok);
        assert_eq!(r.results, vec!["ok-a", "ok-b"]);
    }

    #[test]
    fn invoke_stops_at_first_error() {
        let (_d, eng) = engine();
        let s = propose(
            "fail_chain",
            vec![
                SkillStep {
                    tool: "a".into(),
                    args: BTreeMap::new(),
                },
                SkillStep {
                    tool: "b".into(),
                    args: BTreeMap::new(),
                },
                SkillStep {
                    tool: "c".into(),
                    args: BTreeMap::new(),
                },
            ],
            "",
        )
        .unwrap();
        eng.register(&s).unwrap();
        let reg = StubRegistry::new().set("a", "ok-a").set("b", "ERROR:Boom").set("c", "ok-c");
        let r = eng
            .invoke("fail_chain", &HashMap::new(), &reg)
            .unwrap();
        assert!(!r.ok);
        assert_eq!(r.failed_at, Some(1));
        assert_eq!(r.tool.as_deref(), Some("b"));
        assert_eq!(r.results.len(), 2); // ok-a + ERROR:
    }

    #[test]
    fn format_string_substitutes_known_keys() {
        let mut params = HashMap::new();
        params.insert("repo".to_string(), "AIM".to_string());
        let s = format_string("path={repo}/README.md", &params);
        assert_eq!(s, "path=AIM/README.md");
    }

    #[test]
    fn format_string_keeps_unknown_keys() {
        let params = HashMap::new();
        let s = format_string("hi {name}", &params);
        assert_eq!(s, "hi {name}");
    }

    #[test]
    fn invoke_formats_args_with_params() {
        let (_d, eng) = engine();
        let mut args = BTreeMap::new();
        args.insert(
            "path".to_string(),
            serde_yaml::Value::String("{repo}/README.md".into()),
        );
        let s = propose(
            "args_test",
            vec![SkillStep {
                tool: "read_file".into(),
                args,
            }],
            "",
        )
        .unwrap();
        eng.register(&s).unwrap();
        struct Recorder {
            seen: parking_lot::Mutex<Vec<serde_json::Value>>,
        }
        impl ToolRegistry for Recorder {
            fn call(&self, _name: &str, args: &serde_json::Value) -> Result<String, String> {
                self.seen.lock().push(args.clone());
                Ok("ok".into())
            }
        }
        let rec = Recorder {
            seen: parking_lot::Mutex::new(Vec::new()),
        };
        let mut params = HashMap::new();
        params.insert("repo".to_string(), "AIM".to_string());
        eng.invoke("args_test", &params, &rec).unwrap();
        let calls = rec.seen.lock();
        assert_eq!(calls[0]["path"], "AIM/README.md");
    }

    #[test]
    fn history_limits_results() {
        let (_d, eng) = engine();
        for i in 0..5 {
            let s = propose(
                &format!("s{i}"),
                vec![SkillStep {
                    tool: "x".into(),
                    args: BTreeMap::new(),
                }],
                "",
            )
            .unwrap();
            eng.register(&s).unwrap();
        }
        let h = eng.history(3).unwrap();
        assert_eq!(h.len(), 3);
    }

    #[test]
    fn load_missing_returns_not_found() {
        let (_d, eng) = engine();
        let err = eng.load("ghost").unwrap_err();
        assert!(matches!(err, SkillError::NotFound(_)));
    }
}
