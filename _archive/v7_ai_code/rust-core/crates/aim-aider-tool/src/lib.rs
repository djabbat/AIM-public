//! aim-aider-tool — Aider wrapper with post-edit validation.
//!
//! Port of `agents/aider_tool.py`. The Python original shells out to the
//! `aider` CLI, then runs lightweight per-extension linters against
//! changed files. In Rust both shell escapes are abstracted behind
//! [`AiderRunner`] + [`Validator`] traits — the wrapper logic itself
//! (per-extension command tables, validation summary, formatter) is
//! testable without actually running aider.

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AiderError {
    #[error("runner error: {0}")]
    Runner(String),
}

pub type Result<T> = std::result::Result<T, AiderError>;

pub const DEFAULT_MODEL: &str = "deepseek/deepseek-chat";
pub const DEFAULT_TIMEOUT_S: u64 = 180;

// ── per-extension validation table ──────────────────────────────────────────

/// `(file_extension → list of `cmd_template`)` where `{file}` is replaced
/// with the absolute path. Extensions are lowercase, dot-prefixed.
/// Mirrors VALIDATION_COMMANDS in the Python original.
pub fn default_validation_commands() -> HashMap<&'static str, Vec<&'static str>> {
    let mut m = HashMap::new();
    m.insert(
        ".py",
        vec![
            "python3 -m py_compile {file}",
            "ruff check {file}",
        ],
    );
    m.insert(
        ".sh",
        vec![
            "bash -n {file}",
            "shellcheck {file}",
        ],
    );
    m.insert(
        ".json",
        vec!["python3 -c 'import json,sys; json.load(open(sys.argv[1]))' {file}"],
    );
    m.insert(".md", vec![]);
    m
}

// ── data types ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ValidationResult {
    pub success: bool,
    pub errors: Vec<String>,
    pub summary: String,
}

impl ValidationResult {
    pub fn ok(summary: &str) -> Self {
        Self {
            success: true,
            errors: Vec::new(),
            summary: summary.into(),
        }
    }
    pub fn fail(errors: Vec<String>, summary: &str) -> Self {
        Self {
            success: false,
            errors,
            summary: summary.into(),
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AiderResult {
    pub success: bool,
    pub stdout: String,
    pub validation: ValidationResult,
    pub diff: String,
}

#[derive(Clone, Debug, Default)]
pub struct AiderInvocation {
    pub returncode: i32,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait AiderRunner: Send + Sync {
    /// Was the aider binary detected?
    fn is_available(&self) -> bool;
    /// Run aider with the given files + instruction.
    fn run(&self, files: &[PathBuf], model: &str, instruction: &str, timeout_s: u64)
        -> Result<AiderInvocation>;
    /// Best-effort `git diff` for the affected files. Empty string if not a repo.
    fn git_diff(&self, files: &[PathBuf]) -> Result<String>;
}

pub trait Validator: Send + Sync {
    /// Return `Ok(())` on pass, `Err(stderr)` on failure. The `cmd_template`
    /// is from [`default_validation_commands`] (e.g. `"ruff check {file}"`).
    fn run_command(&self, cmd_template: &str, file: &std::path::Path) -> std::result::Result<(), String>;
    /// Whether the named tool (first whitespace-separated token of the
    /// template) is on PATH. Mirrors Python `shutil.which(...)`.
    fn tool_on_path(&self, tool: &str) -> bool;
}

// ── tool ────────────────────────────────────────────────────────────────────

pub struct AiderTool<'a> {
    pub files: Vec<PathBuf>,
    pub model: String,
    pub timeout_s: u64,
    pub runner: &'a dyn AiderRunner,
    pub validator: &'a dyn Validator,
    pub validation_commands: HashMap<&'static str, Vec<&'static str>>,
}

impl<'a> AiderTool<'a> {
    pub fn new(
        files: Vec<PathBuf>,
        runner: &'a dyn AiderRunner,
        validator: &'a dyn Validator,
    ) -> Self {
        Self {
            files,
            model: DEFAULT_MODEL.to_string(),
            timeout_s: DEFAULT_TIMEOUT_S,
            runner,
            validator,
            validation_commands: default_validation_commands(),
        }
    }

    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Edit + validate flow. Mirrors Python `AiderTool.edit`.
    pub fn edit(&self, instruction: &str) -> Result<AiderResult> {
        if self.files.is_empty() {
            return Ok(AiderResult {
                success: false,
                stdout: "нет файлов".into(),
                validation: ValidationResult::fail(
                    vec!["files=[]".into()],
                    "no files supplied",
                ),
                diff: String::new(),
            });
        }
        if !self.runner.is_available() {
            return Ok(AiderResult {
                success: false,
                stdout: String::new(),
                validation: ValidationResult::fail(
                    vec!["aider not installed".into()],
                    "❌ aider not on PATH",
                ),
                diff: String::new(),
            });
        }
        let inv = match self.runner.run(&self.files, &self.model, instruction, self.timeout_s) {
            Ok(i) => i,
            Err(e) => {
                return Ok(AiderResult {
                    success: false,
                    stdout: String::new(),
                    validation: ValidationResult::fail(
                        vec![format!("runner error: {}", e)],
                        "❌ runner error",
                    ),
                    diff: String::new(),
                });
            }
        };
        if inv.timed_out {
            return Ok(AiderResult {
                success: false,
                stdout: String::new(),
                validation: ValidationResult::fail(
                    vec!["aider timeout".into()],
                    &format!("⚠️  timeout after {}s", self.timeout_s),
                ),
                diff: String::new(),
            });
        }
        let exit_ok = inv.returncode == 0;
        let validation = if exit_ok {
            self.validate()
        } else {
            let stderr_truncated: String = inv.stderr.chars().take(600).collect();
            ValidationResult::fail(
                vec![stderr_truncated],
                &format!("❌ aider exit code {}", inv.returncode),
            )
        };
        let stdout_tail: String = if inv.stdout.len() > 2000 {
            inv.stdout
                .chars()
                .rev()
                .take(2000)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect()
        } else {
            inv.stdout.clone()
        };
        let diff = self.runner.git_diff(&self.files).unwrap_or_default();
        Ok(AiderResult {
            success: exit_ok && validation.success,
            stdout: stdout_tail,
            validation,
            diff,
        })
    }

    /// Run extension-specific validators on each file. Tools missing from
    /// PATH are skipped (mirrors Python's `shutil.which` guard).
    pub fn validate(&self) -> ValidationResult {
        let mut errors: Vec<String> = Vec::new();
        let mut success = true;
        for f in &self.files {
            let ext = f
                .extension()
                .and_then(|s| s.to_str())
                .map(|s| format!(".{}", s.to_lowercase()))
                .unwrap_or_default();
            let cmds = match self.validation_commands.get(ext.as_str()) {
                Some(c) => c,
                None => continue,
            };
            for tpl in cmds {
                let tool = tpl.split_whitespace().next().unwrap_or("");
                if !self.validator.tool_on_path(tool) {
                    continue;
                }
                if let Err(stderr) = self.validator.run_command(tpl, f) {
                    success = false;
                    let name = f
                        .file_name()
                        .and_then(|s| s.to_str())
                        .unwrap_or("?");
                    let truncated: String = stderr.chars().take(300).collect();
                    errors.push(format!("{}: {}\n{}", name, tool, truncated));
                }
            }
        }
        if success {
            ValidationResult::ok("✅ валидация пройдена")
        } else {
            let n = errors.len();
            ValidationResult::fail(errors, &format!("❌ ошибок валидации: {}", n))
        }
    }
}

// ── formatter ──────────────────────────────────────────────────────────────

/// Render an [`AiderResult`] as a markdown block — mirrors Python
/// `_format_for_executor`. Caps stdout/diff at 1500 chars each.
pub fn format_for_executor(result: &AiderResult) -> String {
    let mut pieces: Vec<String> = vec!["[aider]".into()];
    pieces.push(result.validation.summary.clone());
    if !result.success {
        for e in result.validation.errors.iter().take(5) {
            pieces.push(format!("  - {}", e));
        }
    }
    let stdout_trimmed = result.stdout.trim();
    if !stdout_trimmed.is_empty() {
        let tail: String = if stdout_trimmed.len() > 1500 {
            stdout_trimmed
                .chars()
                .rev()
                .take(1500)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect()
        } else {
            stdout_trimmed.to_string()
        };
        pieces.push(format!("\n```\n{}\n```", tail));
    }
    if !result.diff.is_empty() {
        let diff_head: String = result.diff.chars().take(1500).collect();
        pieces.push(format!("\n```diff\n{}\n```", diff_head));
    }
    pieces.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct StubRunner {
        available: bool,
        invocations: Mutex<Vec<(Vec<PathBuf>, String, String, u64)>>,
        canned: Mutex<Vec<AiderInvocation>>,
        diff: Mutex<String>,
    }
    impl StubRunner {
        fn new(available: bool, canned: Vec<AiderInvocation>) -> Self {
            Self {
                available,
                invocations: Mutex::new(Vec::new()),
                canned: Mutex::new(canned),
                diff: Mutex::new(String::new()),
            }
        }
    }
    impl AiderRunner for StubRunner {
        fn is_available(&self) -> bool {
            self.available
        }
        fn run(&self, files: &[PathBuf], model: &str, instr: &str, t: u64) -> Result<AiderInvocation> {
            self.invocations.lock().push((
                files.to_vec(),
                model.into(),
                instr.into(),
                t,
            ));
            let mut q = self.canned.lock();
            if q.is_empty() {
                Ok(AiderInvocation::default())
            } else {
                Ok(q.remove(0))
            }
        }
        fn git_diff(&self, _files: &[PathBuf]) -> Result<String> {
            Ok(self.diff.lock().clone())
        }
    }

    struct StubValidator {
        on_path: Mutex<HashMap<String, bool>>,
        responses: Mutex<HashMap<String, std::result::Result<(), String>>>,
        ran: Mutex<Vec<(String, PathBuf)>>,
    }
    impl StubValidator {
        fn new() -> Self {
            Self {
                on_path: Mutex::new(HashMap::new()),
                responses: Mutex::new(HashMap::new()),
                ran: Mutex::new(Vec::new()),
            }
        }
        fn allow(&self, tool: &str) {
            self.on_path.lock().insert(tool.into(), true);
        }
        fn reject(&self, tool: &str) {
            self.on_path.lock().insert(tool.into(), false);
        }
        fn respond(&self, cmd_tpl: &str, r: std::result::Result<(), String>) {
            self.responses.lock().insert(cmd_tpl.into(), r);
        }
    }
    impl Validator for StubValidator {
        fn tool_on_path(&self, tool: &str) -> bool {
            *self.on_path.lock().get(tool).unwrap_or(&false)
        }
        fn run_command(&self, tpl: &str, file: &std::path::Path) -> std::result::Result<(), String> {
            self.ran.lock().push((tpl.into(), file.to_path_buf()));
            self.responses
                .lock()
                .get(tpl)
                .cloned()
                .unwrap_or(Ok(()))
        }
    }

    fn make_invocation(rc: i32, stdout: &str, stderr: &str) -> AiderInvocation {
        AiderInvocation {
            returncode: rc,
            stdout: stdout.into(),
            stderr: stderr.into(),
            timed_out: false,
        }
    }

    // ── default validation commands ─────────────────────────────────────────

    #[test]
    fn default_validation_commands_includes_python_sh_json_md() {
        let m = default_validation_commands();
        assert!(m.contains_key(".py"));
        assert!(m.contains_key(".sh"));
        assert!(m.contains_key(".json"));
        assert!(m.contains_key(".md"));
        assert!(m[".md"].is_empty());
    }

    #[test]
    fn python_validation_uses_py_compile_and_ruff() {
        let m = default_validation_commands();
        let py = &m[".py"];
        assert!(py.iter().any(|c| c.contains("py_compile")));
        assert!(py.iter().any(|c| c.contains("ruff")));
    }

    // ── edit guards ─────────────────────────────────────────────────────────

    #[test]
    fn edit_no_files_returns_canned_failure() {
        let r = StubRunner::new(true, vec![]);
        let v = StubValidator::new();
        let t = AiderTool::new(vec![], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(!res.success);
        assert_eq!(res.stdout, "нет файлов");
        assert_eq!(res.validation.errors[0], "files=[]");
    }

    #[test]
    fn edit_aider_unavailable_returns_canned_failure() {
        let r = StubRunner::new(false, vec![]);
        let v = StubValidator::new();
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(!res.success);
        assert!(res.validation.errors[0].contains("aider not installed"));
    }

    #[test]
    fn edit_timeout_returns_timeout_failure() {
        let mut inv = AiderInvocation::default();
        inv.timed_out = true;
        let r = StubRunner::new(true, vec![inv]);
        let v = StubValidator::new();
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(!res.success);
        assert!(res.validation.summary.contains("timeout"));
    }

    #[test]
    fn edit_nonzero_exit_records_stderr_truncated() {
        let big_err = "E".repeat(2000);
        let r = StubRunner::new(true, vec![make_invocation(1, "", &big_err)]);
        let v = StubValidator::new();
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(!res.success);
        // truncated to 600 chars
        assert_eq!(res.validation.errors[0].chars().count(), 600);
        assert!(res.validation.summary.contains("exit code 1"));
    }

    #[test]
    fn edit_zero_exit_runs_validate() {
        // Python file → py_compile + ruff. Allow py_compile only; ruff missing.
        let r = StubRunner::new(true, vec![make_invocation(0, "ok\n", "")]);
        let v = StubValidator::new();
        v.allow("python3");
        v.respond("python3 -m py_compile {file}", Ok(()));
        let t = AiderTool::new(vec!["foo.py".into()], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(res.success);
        assert!(res.validation.success);
        assert_eq!(res.stdout, "ok\n");
    }

    #[test]
    fn edit_zero_exit_with_validation_failure_marks_unsuccessful() {
        let r = StubRunner::new(true, vec![make_invocation(0, "ok", "")]);
        let v = StubValidator::new();
        v.allow("python3");
        v.respond(
            "python3 -m py_compile {file}",
            Err("SyntaxError on line 5".into()),
        );
        let t = AiderTool::new(vec!["foo.py".into()], &r, &v);
        let res = t.edit("noop").unwrap();
        assert!(!res.success);
        assert!(!res.validation.success);
        assert!(res.validation.errors[0].contains("foo.py"));
        assert!(res.validation.errors[0].contains("SyntaxError"));
    }

    #[test]
    fn edit_includes_git_diff() {
        let r = StubRunner::new(true, vec![make_invocation(0, "", "")]);
        *r.diff.lock() = "diff --git a/foo b/foo\n+added\n".into();
        let v = StubValidator::new();
        let t = AiderTool::new(vec!["foo.py".into()], &r, &v);
        let res = t.edit("instr").unwrap();
        assert!(res.diff.contains("diff --git"));
    }

    #[test]
    fn edit_passes_instruction_and_model_to_runner() {
        let r = StubRunner::new(true, vec![make_invocation(0, "", "")]);
        let v = StubValidator::new();
        let t = AiderTool::new(vec!["foo.py".into()], &r, &v).with_model("custom/model");
        t.edit("rewrite this").unwrap();
        let inv = r.invocations.lock();
        assert_eq!(inv.len(), 1);
        assert_eq!(inv[0].1, "custom/model");
        assert_eq!(inv[0].2, "rewrite this");
    }

    // ── validate() standalone ───────────────────────────────────────────────

    #[test]
    fn validate_skips_unknown_extension() {
        let v = StubValidator::new();
        v.allow("ruff"); // wouldn't matter for unknown ext
        let r = StubRunner::new(true, vec![]);
        let t = AiderTool::new(vec!["x.txt".into()], &r, &v);
        let result = t.validate();
        assert!(result.success);
    }

    #[test]
    fn validate_skips_tools_not_on_path() {
        let v = StubValidator::new();
        v.reject("python3");
        v.reject("ruff");
        let r = StubRunner::new(true, vec![]);
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let result = t.validate();
        assert!(result.success);
        assert!(v.ran.lock().is_empty());
    }

    #[test]
    fn validate_runs_each_present_tool() {
        let v = StubValidator::new();
        v.allow("python3");
        v.allow("ruff");
        v.respond("python3 -m py_compile {file}", Ok(()));
        v.respond("ruff check {file}", Ok(()));
        let r = StubRunner::new(true, vec![]);
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let result = t.validate();
        assert!(result.success);
        assert_eq!(v.ran.lock().len(), 2);
    }

    #[test]
    fn validate_collects_errors_from_failing_tools() {
        let v = StubValidator::new();
        v.allow("python3");
        v.allow("ruff");
        v.respond(
            "python3 -m py_compile {file}",
            Err("compile error".into()),
        );
        v.respond("ruff check {file}", Err("lint error".into()));
        let r = StubRunner::new(true, vec![]);
        let t = AiderTool::new(vec!["x.py".into()], &r, &v);
        let result = t.validate();
        assert!(!result.success);
        assert_eq!(result.errors.len(), 2);
        assert!(result.summary.contains("ошибок валидации: 2"));
    }

    // ── format_for_executor ────────────────────────────────────────────────

    #[test]
    fn format_includes_aider_header_and_summary() {
        let r = AiderResult {
            success: true,
            stdout: "ran".into(),
            validation: ValidationResult::ok("✅ ok"),
            diff: String::new(),
        };
        let s = format_for_executor(&r);
        assert!(s.starts_with("[aider]"));
        assert!(s.contains("✅ ok"));
    }

    #[test]
    fn format_caps_first_5_errors() {
        let r = AiderResult {
            success: false,
            stdout: String::new(),
            validation: ValidationResult::fail(
                (0..10).map(|i| format!("err{}", i)).collect(),
                "❌ many",
            ),
            diff: String::new(),
        };
        let s = format_for_executor(&r);
        assert!(s.contains("err0"));
        assert!(s.contains("err4"));
        assert!(!s.contains("err5"));
    }

    #[test]
    fn format_includes_diff_when_present() {
        let r = AiderResult {
            success: true,
            stdout: String::new(),
            validation: ValidationResult::ok("ok"),
            diff: "diff body".into(),
        };
        let s = format_for_executor(&r);
        assert!(s.contains("```diff"));
        assert!(s.contains("diff body"));
    }
}
