//! aim-routines — named bundle launcher (RB1).
//!
//! Port of `agents/routines.py`. Composes multiple existing CLI actions
//! into a single named "routine" defined in a YAML preferences file.
//!
//! YAML shape (verbatim from Python):
//!
//! ```yaml
//! routines:
//!   morning:
//!     - escalate
//!     - brief
//!     - { do: "follow-up everyone" }
//!     - memory
//!   pre-grant-submit:
//!     - { project: brief, args: ["FCLC"] }
//!     - { do: "what's hot" }
//!     - cost
//! ```
//!
//! Each step is one of: `String` (simple handler name), `{do: …}`,
//! `{recall: …, k?}`, `{project: …, args: […]}`, `{brief: <project>}`.
//!
//! Step execution sits behind a [`StepRunner`] trait so the orchestration
//! is testable without pulling in every backend.

use std::path::Path;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RoutinesError {
    #[error("unknown routine: {0}")]
    Unknown(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml error: {0}")]
    Yaml(String),
}

pub type Result<T> = std::result::Result<T, RoutinesError>;

// ── step shape ──────────────────────────────────────────────────────────────

/// A single step in a routine. Maps 1:1 to the four Python branches plus
/// the `Simple` handler-by-name shortcut.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Step {
    /// `escalate` / `brief` / `memory` / etc.
    Simple(String),
    Mapping(StepMap),
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct StepMap {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#do: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recall: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub k: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub project: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub args: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub brief: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct RoutinesFile {
    #[serde(default)]
    routines: serde_yaml::Mapping,
}

// ── results ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct StepResult {
    pub step: usize,
    pub action: String,
    pub output: serde_json::Value,
    pub ok: bool,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct RoutineResult {
    pub name: String,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub steps: Vec<StepResult>,
}

impl RoutineResult {
    pub fn ok(&self) -> bool {
        self.steps.iter().all(|s| s.ok)
    }
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait StepRunner: Send + Sync {
    fn run_simple(&self, name: &str) -> std::result::Result<serde_json::Value, String>;
    fn run_do(&self, query: &str) -> std::result::Result<serde_json::Value, String>;
    fn run_recall(&self, query: &str, k: usize)
        -> std::result::Result<serde_json::Value, String>;
    fn run_project(
        &self,
        sub: &str,
        args: &[String],
    ) -> std::result::Result<serde_json::Value, String>;
    fn run_brief(
        &self,
        project: Option<&str>,
    ) -> std::result::Result<serde_json::Value, String>;
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

pub trait AuditSink: Send + Sync {
    fn record(&self, result: &RoutineResult);
}

pub struct NoopAudit;
impl AuditSink for NoopAudit {
    fn record(&self, _: &RoutineResult) {}
}

// ── loader ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct RoutineLibrary {
    pub items: std::collections::BTreeMap<String, Vec<Step>>,
}

impl RoutineLibrary {
    pub fn load_from_yaml(yaml: &str) -> Result<Self> {
        if yaml.trim().is_empty() {
            return Ok(Self::default());
        }
        let file: RoutinesFile = serde_yaml::from_str(yaml).map_err(|e| {
            RoutinesError::Yaml(e.to_string())
        })?;
        let mut items = std::collections::BTreeMap::new();
        for (k, v) in file.routines {
            let name = match k.as_str() {
                Some(s) => s.to_string(),
                None => continue,
            };
            let steps_yaml = match v {
                serde_yaml::Value::Sequence(s) => s,
                _ => continue,
            };
            let mut steps: Vec<Step> = Vec::new();
            for raw in steps_yaml {
                match serde_yaml::from_value::<Step>(raw) {
                    Ok(s) => steps.push(s),
                    Err(_) => continue,
                }
            }
            items.insert(name, steps);
        }
        Ok(Self { items })
    }

    pub fn load_from_file(path: &Path) -> Result<Self> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let text = std::fs::read_to_string(path)?;
        Self::load_from_yaml(&text)
    }

    pub fn list(&self) -> Vec<String> {
        self.items.keys().cloned().collect()
    }

    pub fn steps(&self, name: &str) -> Option<&[Step]> {
        self.items.get(name).map(Vec::as_slice)
    }
}

// ── orchestrator ───────────────────────────────────────────────────────────

pub struct Routines<'a> {
    pub library: &'a RoutineLibrary,
    pub runner: &'a dyn StepRunner,
    pub clock: &'a dyn Clock,
    pub audit: &'a dyn AuditSink,
}

impl<'a> Routines<'a> {
    pub fn new(
        library: &'a RoutineLibrary,
        runner: &'a dyn StepRunner,
        clock: &'a dyn Clock,
        audit: &'a dyn AuditSink,
    ) -> Self {
        Self {
            library,
            runner,
            clock,
            audit,
        }
    }

    pub fn run(&self, name: &str) -> Result<RoutineResult> {
        let steps = self
            .library
            .steps(name)
            .ok_or_else(|| RoutinesError::Unknown(name.into()))?;
        let started = self.clock.now();
        let mut out: Vec<StepResult> = Vec::with_capacity(steps.len());
        for (i, raw) in steps.iter().enumerate() {
            out.push(self.run_step(i + 1, raw));
        }
        let finished = self.clock.now();
        let result = RoutineResult {
            name: name.to_string(),
            started_at: started,
            finished_at: finished,
            steps: out,
        };
        self.audit.record(&result);
        Ok(result)
    }

    fn run_step(&self, idx: usize, step: &Step) -> StepResult {
        let (action, outcome): (String, std::result::Result<serde_json::Value, String>) = match step {
            Step::Simple(s) => (s.clone(), self.runner.run_simple(s)),
            Step::Mapping(m) => {
                if let Some(q) = &m.r#do {
                    let head: String = q.chars().take(60).collect();
                    (format!("do:{}", head), self.runner.run_do(q))
                } else if let Some(q) = &m.recall {
                    let head: String = q.chars().take(60).collect();
                    let k = m.k.unwrap_or(5);
                    (format!("recall:{}", head), self.runner.run_recall(q, k))
                } else if let Some(p) = &m.project {
                    (format!("project:{}", p), self.runner.run_project(p, &m.args))
                } else if let Some(p) = &m.brief {
                    let proj = if p.is_empty() { None } else { Some(p.as_str()) };
                    ("brief".into(), self.runner.run_brief(proj))
                } else {
                    (
                        "?".into(),
                        Err(format!("unsupported step shape: {:?}", m)),
                    )
                }
            }
        };
        match outcome {
            Ok(v) => StepResult {
                step: idx,
                action,
                output: v,
                ok: true,
                error: None,
            },
            Err(e) => StepResult {
                step: idx,
                action,
                output: serde_json::Value::Null,
                ok: false,
                error: Some(e),
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use parking_lot::Mutex;
    use std::collections::HashMap;
    use tempfile::TempDir;

    // ── stub runner ────────────────────────────────────────────────────────

    #[derive(Default)]
    struct StubRunner {
        simple_responses: Mutex<HashMap<String, std::result::Result<serde_json::Value, String>>>,
        do_calls: Mutex<Vec<String>>,
        recall_calls: Mutex<Vec<(String, usize)>>,
        project_calls: Mutex<Vec<(String, Vec<String>)>>,
        brief_calls: Mutex<Vec<Option<String>>>,
    }
    impl StubRunner {
        fn new() -> Self {
            Self::default()
        }
        fn set_simple(&self, name: &str, r: std::result::Result<serde_json::Value, String>) {
            self.simple_responses.lock().insert(name.into(), r);
        }
    }
    impl StepRunner for StubRunner {
        fn run_simple(&self, name: &str) -> std::result::Result<serde_json::Value, String> {
            self.simple_responses
                .lock()
                .get(name)
                .cloned()
                .unwrap_or_else(|| Err(format!("unknown routine step: {:?}", name)))
        }
        fn run_do(&self, q: &str) -> std::result::Result<serde_json::Value, String> {
            self.do_calls.lock().push(q.into());
            Ok(serde_json::json!({"do": q}))
        }
        fn run_recall(&self, q: &str, k: usize) -> std::result::Result<serde_json::Value, String> {
            self.recall_calls.lock().push((q.into(), k));
            Ok(serde_json::json!({"recall": q, "k": k}))
        }
        fn run_project(
            &self,
            sub: &str,
            args: &[String],
        ) -> std::result::Result<serde_json::Value, String> {
            self.project_calls
                .lock()
                .push((sub.into(), args.to_vec()));
            Ok(serde_json::json!({"project": sub, "args": args}))
        }
        fn run_brief(
            &self,
            project: Option<&str>,
        ) -> std::result::Result<serde_json::Value, String> {
            self.brief_calls.lock().push(project.map(String::from));
            Ok(serde_json::json!({"brief_for": project}))
        }
    }

    fn fixed() -> FixedClock {
        let dt: DateTime<Utc> = Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap();
        FixedClock(dt)
    }

    // ── load_from_yaml ────────────────────────────────────────────────────

    #[test]
    fn load_yaml_simple() {
        let yaml = "routines:\n  morning:\n    - escalate\n    - brief\n";
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        assert_eq!(lib.list(), vec!["morning"]);
        assert_eq!(lib.steps("morning").unwrap().len(), 2);
        assert!(matches!(&lib.steps("morning").unwrap()[0], Step::Simple(s) if s == "escalate"));
    }

    #[test]
    fn load_yaml_mixed_step_shapes() {
        let yaml = r#"routines:
  pre-grant-submit:
    - { project: brief, args: ["FCLC"] }
    - { do: "what's hot" }
    - cost
    - { recall: "Geiger", k: 3 }
"#;
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        let steps = lib.steps("pre-grant-submit").unwrap();
        assert_eq!(steps.len(), 4);
        if let Step::Mapping(m) = &steps[0] {
            assert_eq!(m.project.as_deref(), Some("brief"));
            assert_eq!(m.args, vec!["FCLC".to_string()]);
        } else {
            panic!();
        }
        if let Step::Mapping(m) = &steps[1] {
            assert_eq!(m.r#do.as_deref(), Some("what's hot"));
        } else {
            panic!();
        }
        if let Step::Mapping(m) = &steps[3] {
            assert_eq!(m.recall.as_deref(), Some("Geiger"));
            assert_eq!(m.k, Some(3));
        } else {
            panic!();
        }
    }

    #[test]
    fn load_yaml_empty_returns_empty_lib() {
        let lib = RoutineLibrary::load_from_yaml("").unwrap();
        assert!(lib.list().is_empty());
    }

    #[test]
    fn load_yaml_no_routines_key_returns_empty() {
        let lib = RoutineLibrary::load_from_yaml("other: stuff\n").unwrap();
        assert!(lib.list().is_empty());
    }

    #[test]
    fn load_yaml_invalid_propagates_error() {
        assert!(RoutineLibrary::load_from_yaml("[[invalid").is_err());
    }

    #[test]
    fn load_from_file_missing_returns_empty_lib() {
        let tmp = TempDir::new().unwrap();
        let lib = RoutineLibrary::load_from_file(&tmp.path().join("nope.yaml")).unwrap();
        assert!(lib.list().is_empty());
    }

    // ── run dispatch ───────────────────────────────────────────────────────

    #[test]
    fn run_simple_step_invokes_runner() {
        let lib = RoutineLibrary::load_from_yaml(
            "routines:\n  morning:\n    - escalate\n",
        )
        .unwrap();
        let runner = StubRunner::new();
        runner.set_simple("escalate", Ok(serde_json::json!(["alert1"])));
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        let res = r.run("morning").unwrap();
        assert_eq!(res.steps.len(), 1);
        assert!(res.ok());
        assert_eq!(res.steps[0].action, "escalate");
        assert_eq!(res.steps[0].output, serde_json::json!(["alert1"]));
    }

    #[test]
    fn run_do_step_dispatches_and_truncates_action() {
        let yaml = r#"routines:
  m:
    - { do: "очень длинный запрос которому не хватит шестидесяти символов чтобы поместиться целиком в action" }
"#;
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        let runner = StubRunner::new();
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        let res = r.run("m").unwrap();
        assert_eq!(res.steps[0].action.chars().take(3).collect::<String>(), "do:");
        // 60-char head + "do:" prefix = 63 chars
        assert!(res.steps[0].action.chars().count() <= 63);
        assert_eq!(runner.do_calls.lock().len(), 1);
    }

    #[test]
    fn run_recall_uses_default_k_when_missing() {
        let yaml = r#"routines:
  m:
    - { recall: "Geiger" }
"#;
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        let runner = StubRunner::new();
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        r.run("m").unwrap();
        let calls = runner.recall_calls.lock();
        assert_eq!(calls[0].1, 5);
    }

    #[test]
    fn run_project_passes_args_through() {
        let yaml = r#"routines:
  m:
    - { project: list, args: ["A", "B"] }
"#;
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        let runner = StubRunner::new();
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        r.run("m").unwrap();
        let calls = runner.project_calls.lock();
        assert_eq!(calls[0].0, "list");
        assert_eq!(calls[0].1, vec!["A", "B"]);
    }

    #[test]
    fn run_brief_with_project() {
        let yaml = r#"routines:
  m:
    - { brief: "FCLC" }
"#;
        let lib = RoutineLibrary::load_from_yaml(yaml).unwrap();
        let runner = StubRunner::new();
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        r.run("m").unwrap();
        let calls = runner.brief_calls.lock();
        assert_eq!(calls[0].as_deref(), Some("FCLC"));
    }

    // ── error paths ────────────────────────────────────────────────────────

    #[test]
    fn run_unknown_routine_errors() {
        let lib = RoutineLibrary::default();
        let runner = StubRunner::new();
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        let err = r.run("missing").unwrap_err();
        assert!(matches!(err, RoutinesError::Unknown(_)));
    }

    #[test]
    fn run_step_failure_is_recorded_not_propagated() {
        let lib = RoutineLibrary::load_from_yaml(
            "routines:\n  m:\n    - escalate\n    - brief\n",
        )
        .unwrap();
        let runner = StubRunner::new();
        runner.set_simple("escalate", Err("boom".into()));
        runner.set_simple("brief", Ok(serde_json::Value::Null));
        let clock = fixed();
        let r = Routines::new(&lib, &runner, &clock, &NoopAudit);
        let res = r.run("m").unwrap();
        assert_eq!(res.steps.len(), 2);
        assert!(!res.ok());
        assert_eq!(res.steps[0].error.as_deref(), Some("boom"));
        assert!(res.steps[1].ok);
    }

    // ── audit ──────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct CountingAudit(Mutex<Vec<RoutineResult>>);
    impl AuditSink for CountingAudit {
        fn record(&self, r: &RoutineResult) {
            self.0.lock().push(r.clone());
        }
    }

    #[test]
    fn run_calls_audit_sink_with_full_result() {
        let lib = RoutineLibrary::load_from_yaml(
            "routines:\n  morning:\n    - escalate\n",
        )
        .unwrap();
        let runner = StubRunner::new();
        runner.set_simple("escalate", Ok(serde_json::Value::Null));
        let clock = fixed();
        let aud = CountingAudit::default();
        let r = Routines::new(&lib, &runner, &clock, &aud);
        r.run("morning").unwrap();
        let recs = aud.0.lock();
        assert_eq!(recs.len(), 1);
        assert_eq!(recs[0].name, "morning");
        assert_eq!(recs[0].steps.len(), 1);
    }
}
