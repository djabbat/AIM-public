//! aim-coder — closed-loop edit→test agent.
//!
//! Port of `agents/coder.py`. The Python original wraps `aider_tool` and
//! drives an iterate-until-tests-pass loop. In Rust we keep both
//! collaborators behind traits — `Editor` (the LLM-backed code editor)
//! and `TestRunner` (the shell test executor) — so the loop is testable
//! without invoking Aider or shelling out.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoderError {
    #[error("editor error: {0}")]
    Editor(String),
    #[error("test runner error: {0}")]
    TestRunner(String),
}

pub type Result<T> = std::result::Result<T, CoderError>;

// ── traits ──────────────────────────────────────────────────────────────────

/// Code editor — production binds to Aider; tests bind to a stub.
pub trait Editor: Send + Sync {
    /// Edit the configured file set with `instruction`. Returns the
    /// editor's combined stdout/stderr.
    fn edit(&self, instruction: &str) -> Result<String>;
}

/// Test command executor.
pub trait TestRunner: Send + Sync {
    /// Run `test_cmd` (shell-quoted, like Python's). Returns wrapped output
    /// containing the exit code marker.
    fn run(&self, test_cmd: &str) -> Result<String>;
}

// ── result type ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CoderResult {
    pub ok: bool,
    pub iters: usize,
    pub final_output: String,
    pub last_test: String,
    pub history: Vec<HistoryEntry>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub phase: String,
    pub out: String,
}

fn tail(s: &str, n: usize) -> String {
    if s.len() <= n {
        return s.to_string();
    }
    let start = s.len() - n;
    // step forward to a char boundary
    let mut i = start;
    while !s.is_char_boundary(i) {
        i += 1;
    }
    s[i..].to_string()
}

// ── exit-code parsing ───────────────────────────────────────────────────────

/// Mirrors Python `_tests_passed`: extract `[exit=N]` if present, else fall
/// back to runner-specific heuristics.
pub fn tests_passed(test_cmd: &str, output: &str) -> bool {
    let re = regex::Regex::new(r"\[exit=(-?\d+)\]").expect("regex compiles");
    if let Some(c) = re.captures(output) {
        return &c[1] == "0";
    }
    let out_low = output.to_lowercase();
    if test_cmd.to_lowercase().contains("pytest") {
        return out_low.contains("passed") && !out_low.contains("failed");
    }
    out_low.contains("ok") && !out_low.contains("fail")
}

/// Wrap a test command's exit-code + stdout + stderr into the same
/// envelope `tests_passed` understands. Useful for production
/// [`TestRunner`] implementations.
pub fn wrap_test_output(test_cmd: &str, exit_code: i32, stdout: &str, stderr: &str) -> String {
    format!(
        "$ {cmd}\n[exit={code}]\n{out}\n{err}",
        cmd = test_cmd,
        code = exit_code,
        out = stdout,
        err = stderr,
    )
}

// ── coder agent ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct CoderConfig {
    pub files: Vec<PathBuf>,
    pub model: Option<String>,
    pub max_iters: usize,
    pub edit_tail: usize,
    pub test_tail: usize,
    pub fix_tail: usize,
}

impl CoderConfig {
    /// Defaults match Python: max_iters=3, edit tail 1500, test tail 2000,
    /// fix-instruction tail 1800 (history truncation kept verbatim).
    pub fn new(files: Vec<PathBuf>) -> Self {
        Self {
            files,
            model: None,
            max_iters: 3,
            edit_tail: 1500,
            test_tail: 2000,
            fix_tail: 1800,
        }
    }
}

pub struct CoderAgent<'a> {
    pub config: CoderConfig,
    pub editor: &'a dyn Editor,
    pub tests: &'a dyn TestRunner,
}

impl<'a> CoderAgent<'a> {
    pub fn new(config: CoderConfig, editor: &'a dyn Editor, tests: &'a dyn TestRunner) -> Self {
        Self {
            config,
            editor,
            tests,
        }
    }

    /// One-shot edit, no test loop.
    pub fn edit(&self, instruction: &str) -> Result<String> {
        self.editor.edit(instruction)
    }

    /// Edit, then loop: run tests; on failure, feed output back to the
    /// editor with a fix instruction; retry up to `max_iters`.
    pub fn edit_and_test(&self, instruction: &str, test_cmd: &str) -> Result<CoderResult> {
        let mut history: Vec<HistoryEntry> = Vec::new();
        let mut last_edit = self.editor.edit(instruction)?;
        history.push(HistoryEntry {
            phase: "edit#1".into(),
            out: tail(&last_edit, self.config.edit_tail),
        });

        let mut last_test = String::new();
        for i in 1..=self.config.max_iters {
            let test_out = self.tests.run(test_cmd)?;
            history.push(HistoryEntry {
                phase: format!("test#{}", i),
                out: tail(&test_out, self.config.test_tail),
            });
            last_test = test_out.clone();

            if tests_passed(test_cmd, &test_out) {
                return Ok(CoderResult {
                    ok: true,
                    iters: i,
                    final_output: last_edit,
                    last_test: test_out,
                    history,
                });
            }

            if i == self.config.max_iters {
                break;
            }

            let fix_instr = format!(
                "The previous edit did not fix all tests. The current test \
                 output is:\n\n{}\n\nPlease update the code to make the failing tests pass. \
                 Do not weaken or skip tests.",
                tail(&test_out, self.config.fix_tail)
            );
            last_edit = self.editor.edit(&fix_instr)?;
            history.push(HistoryEntry {
                phase: format!("edit#{}", i + 1),
                out: tail(&last_edit, self.config.edit_tail),
            });
        }

        Ok(CoderResult {
            ok: false,
            iters: self.config.max_iters,
            final_output: last_edit,
            last_test,
            history,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    /// Programmable editor: returns the next pre-loaded response.
    struct ScriptedEditor {
        responses: Mutex<Vec<String>>,
        calls: Mutex<Vec<String>>,
    }

    impl ScriptedEditor {
        fn new(responses: Vec<&str>) -> Self {
            Self {
                responses: Mutex::new(responses.into_iter().map(String::from).collect()),
                calls: Mutex::new(Vec::new()),
            }
        }
    }

    impl Editor for ScriptedEditor {
        fn edit(&self, instruction: &str) -> Result<String> {
            self.calls.lock().push(instruction.to_string());
            let mut r = self.responses.lock();
            if r.is_empty() {
                Ok("(no scripted response)".into())
            } else {
                Ok(r.remove(0))
            }
        }
    }

    /// Programmable test runner.
    struct ScriptedRunner {
        outputs: Mutex<Vec<String>>,
        calls: Mutex<Vec<String>>,
    }

    impl ScriptedRunner {
        fn new(outputs: Vec<&str>) -> Self {
            Self {
                outputs: Mutex::new(outputs.into_iter().map(String::from).collect()),
                calls: Mutex::new(Vec::new()),
            }
        }
    }

    impl TestRunner for ScriptedRunner {
        fn run(&self, cmd: &str) -> Result<String> {
            self.calls.lock().push(cmd.to_string());
            let mut o = self.outputs.lock();
            if o.is_empty() {
                Ok("$ tests\n[exit=0]\nok".into())
            } else {
                Ok(o.remove(0))
            }
        }
    }

    fn cfg() -> CoderConfig {
        CoderConfig::new(vec!["src/lib.rs".into()])
    }

    // ── tests_passed ────────────────────────────────────────────────────────

    #[test]
    fn tests_passed_exit_zero() {
        assert!(tests_passed("pytest", "$ pytest\n[exit=0]\nfoo"));
    }

    #[test]
    fn tests_passed_exit_nonzero() {
        assert!(!tests_passed("pytest", "$ pytest\n[exit=1]\nfoo"));
    }

    #[test]
    fn tests_passed_negative_exit() {
        assert!(!tests_passed("pytest", "$ pytest\n[exit=-9]\nfoo"));
    }

    #[test]
    fn tests_passed_pytest_heuristic_when_no_exit() {
        assert!(tests_passed("pytest tests/", "5 passed in 0.1s"));
        assert!(!tests_passed("pytest tests/", "1 passed, 2 failed"));
    }

    #[test]
    fn tests_passed_generic_heuristic_when_no_exit() {
        assert!(tests_passed("cargo test", "test result: ok. 5 passed"));
        assert!(!tests_passed("cargo test", "test failures detected"));
    }

    // ── wrap_test_output ────────────────────────────────────────────────────

    #[test]
    fn wrap_test_output_includes_marker() {
        let s = wrap_test_output("pytest", 0, "ok", "");
        assert!(s.contains("[exit=0]"));
        assert!(s.contains("$ pytest"));
    }

    // ── tail ────────────────────────────────────────────────────────────────

    #[test]
    fn tail_returns_full_when_under_n() {
        assert_eq!(tail("hi", 100), "hi");
    }

    #[test]
    fn tail_returns_last_n_bytes() {
        assert_eq!(tail("0123456789", 4), "6789");
    }

    #[test]
    fn tail_handles_unicode_boundaries() {
        // "Иванов работал" — multi-byte chars; tail must land on a char boundary
        let s = "Иванов работал";
        let t = tail(s, 5);
        // shouldn't panic
        assert!(t.chars().count() > 0);
    }

    // ── edit (one-shot) ─────────────────────────────────────────────────────

    #[test]
    fn edit_one_shot_returns_editor_output() {
        let e = ScriptedEditor::new(vec!["edit applied"]);
        let r = ScriptedRunner::new(vec![]);
        let agent = CoderAgent::new(cfg(), &e, &r);
        let out = agent.edit("add foo()").unwrap();
        assert_eq!(out, "edit applied");
        assert_eq!(e.calls.lock()[0], "add foo()");
    }

    // ── edit_and_test ───────────────────────────────────────────────────────

    #[test]
    fn loop_succeeds_on_first_iter() {
        let e = ScriptedEditor::new(vec!["initial edit"]);
        let r = ScriptedRunner::new(vec!["$ pytest\n[exit=0]\nok"]);
        let agent = CoderAgent::new(cfg(), &e, &r);
        let result = agent.edit_and_test("add foo", "pytest").unwrap();
        assert!(result.ok);
        assert_eq!(result.iters, 1);
        // history: edit#1 + test#1
        assert_eq!(result.history.len(), 2);
        assert_eq!(result.history[0].phase, "edit#1");
        assert_eq!(result.history[1].phase, "test#1");
    }

    #[test]
    fn loop_recovers_on_second_iter() {
        let e = ScriptedEditor::new(vec!["edit-1", "edit-2"]);
        let r = ScriptedRunner::new(vec![
            "$ pytest\n[exit=1]\nfail",
            "$ pytest\n[exit=0]\nok",
        ]);
        let agent = CoderAgent::new(cfg(), &e, &r);
        let result = agent.edit_and_test("instr", "pytest").unwrap();
        assert!(result.ok);
        assert_eq!(result.iters, 2);
        // editor called twice (initial + 1 fix)
        assert_eq!(e.calls.lock().len(), 2);
        // 2nd call instruction should mention previous failure
        assert!(e.calls.lock()[1].contains("did not fix all tests"));
    }

    #[test]
    fn loop_exhausts_max_iters_and_returns_failure() {
        let mut c = cfg();
        c.max_iters = 3;
        let e = ScriptedEditor::new(vec!["e1", "e2", "e3"]);
        let r = ScriptedRunner::new(vec![
            "$ pytest\n[exit=1]\nfail",
            "$ pytest\n[exit=1]\nfail",
            "$ pytest\n[exit=1]\nfail",
        ]);
        let agent = CoderAgent::new(c, &e, &r);
        let result = agent.edit_and_test("instr", "pytest").unwrap();
        assert!(!result.ok);
        assert_eq!(result.iters, 3);
        // editor: initial + 2 fixes = 3 calls (no fix after final test)
        assert_eq!(e.calls.lock().len(), 3);
        // history: edit#1, test#1, edit#2, test#2, edit#3, test#3 = 6 entries
        assert_eq!(result.history.len(), 6);
    }

    #[test]
    fn loop_propagates_editor_error() {
        struct BrokenEditor;
        impl Editor for BrokenEditor {
            fn edit(&self, _: &str) -> Result<String> {
                Err(CoderError::Editor("boom".into()))
            }
        }
        let r = ScriptedRunner::new(vec![]);
        let agent = CoderAgent::new(cfg(), &BrokenEditor, &r);
        let err = agent.edit_and_test("instr", "pytest").unwrap_err();
        assert!(matches!(err, CoderError::Editor(_)));
    }

    #[test]
    fn loop_propagates_runner_error() {
        struct BrokenRunner;
        impl TestRunner for BrokenRunner {
            fn run(&self, _: &str) -> Result<String> {
                Err(CoderError::TestRunner("nope".into()))
            }
        }
        let e = ScriptedEditor::new(vec!["x"]);
        let agent = CoderAgent::new(cfg(), &e, &BrokenRunner);
        let err = agent.edit_and_test("instr", "pytest").unwrap_err();
        assert!(matches!(err, CoderError::TestRunner(_)));
    }

    #[test]
    fn fix_instruction_carries_failure_tail() {
        let mut c = cfg();
        c.fix_tail = 50;
        let e = ScriptedEditor::new(vec!["e1", "e2"]);
        let r = ScriptedRunner::new(vec![
            &format!("$ pytest\n[exit=1]\n{}", "F".repeat(200)),
            "$ pytest\n[exit=0]\nok",
        ]);
        let agent = CoderAgent::new(c, &e, &r);
        let _ = agent.edit_and_test("instr", "pytest").unwrap();
        let fix_call = &e.calls.lock()[1];
        // tail length is 50 so the fix instruction includes only ~50 'F's
        assert!(fix_call.contains("Please update the code"));
        assert!(fix_call.contains("FFFFF"));
    }

    #[test]
    fn coder_config_defaults() {
        let c = CoderConfig::new(vec!["a".into()]);
        assert_eq!(c.max_iters, 3);
        assert_eq!(c.edit_tail, 1500);
        assert_eq!(c.test_tail, 2000);
        assert_eq!(c.fix_tail, 1800);
    }
}
