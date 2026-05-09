//! aim-graph — sequential planner/executor/reviewer state machine.
//!
//! Port of `agents/graph.py` (the `LangGraph`-orchestrated multi-step
//! agent). LangGraph itself doesn't have a Rust port; we re-express the
//! flow as a typed state passed through a `Node` chain. Test stubs cover
//! the planner→executor→reviewer happy-path + retry on weak review.
//!
//! Skipped (deferred to future binary integration with real LLM):
//!   • streaming reviewer
//!   • interactive HITL plan editing
//!   • debate / tree-of-thoughts (other crates own those)
//!   • DeepSeek prefix-cache warmup, OpenTelemetry tracing
//!   • subprocess Aider integration (covered by aim-coder)

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum GraphError {
    #[error("llm error: {0}")]
    Llm(String),
    #[error("graph aborted: {0}")]
    Aborted(String),
}

pub type Result<T> = std::result::Result<T, GraphError>;

// ── AIMFlags bitmask ────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct AimFlags(pub u32);

impl AimFlags {
    pub const NO_MEM: u32 = 1 << 0;
    pub const REVIEW: u32 = 1 << 1;
    pub const FULL_MEM: u32 = 1 << 2;
    pub const AIDER: u32 = 1 << 3;

    pub fn new(value: u32) -> Self {
        Self(value)
    }
    pub fn set(&mut self, flag: u32) {
        self.0 |= flag;
    }
    pub fn clear(&mut self, flag: u32) {
        self.0 &= !flag;
    }
    pub fn toggle(&mut self, flag: u32) {
        self.0 ^= flag;
    }
    pub fn has(&self, flag: u32) -> bool {
        self.0 & flag != 0
    }

    pub fn names(&self) -> Vec<&'static str> {
        let mut out = Vec::new();
        for (name, flag) in [
            ("NO_MEM", Self::NO_MEM),
            ("REVIEW", Self::REVIEW),
            ("FULL_MEM", Self::FULL_MEM),
            ("AIDER", Self::AIDER),
        ] {
            if self.has(flag) {
                out.push(name);
            }
        }
        out
    }
}

impl std::fmt::Display for AimFlags {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let names = self.names();
        if names.is_empty() {
            write!(f, "AimFlags(0)")
        } else {
            write!(f, "AimFlags({})", names.join("|"))
        }
    }
}

// ── translit detection ──────────────────────────────────────────────────────

/// Heuristic: text is Latin-only and contains common Russian translit
/// patterns. Matches Python `_looks_like_translit`.
pub fn looks_like_translit(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    // any Cyrillic char? → not translit
    if text.chars().any(|c| ('\u{0400}'..='\u{04FF}').contains(&c)) {
        return false;
    }
    let sample = text.to_lowercase();
    const CUES: &[&str] = &[
        "ya ", "iy ", "oye ", "sh", "ch", "zh", "kh", "shch",
        " kak ", " chto ", " eto ", " ne ", " ya ", " ty ",
        "ovat'", "tsya", "pochemu", "ozhalui", "pozhalu",
        "sdelay", "sdelai", "napishi", "proverit", "zagruzh",
    ];
    CUES.iter().any(|cue| sample.contains(cue))
}

/// Prepend a translit-decode hint when the input looks transliterated.
pub fn wrap_task_for_llm(task: &str) -> String {
    if looks_like_translit(task) {
        format!(
            "ВНИМАНИЕ: следующий текст написан транслитом — это русский язык \
             латинскими буквами. Сначала мысленно преобразуй его в кириллицу, \
             затем обрабатывай как обычный русский текст.\n\n{}",
            task
        )
    } else {
        task.to_string()
    }
}

// ── plan-size heuristic ────────────────────────────────────────────────────

const REASONING_CUES: &[&str] = &[
    "докажи", "проанализируй", "проведи", "разбери", "сравни",
    "почему", "как именно", "обоснуй", "оптимизируй", "разработай",
    "prove", "analyse", "analyze", "compare", "design", "audit",
];

pub fn suggest_plan_size(task: &str) -> usize {
    let sample = task.to_lowercase();
    let n_chars = task.chars().count();
    let has_reasoning = REASONING_CUES.iter().any(|cue| sample.contains(cue));
    if n_chars < 120 && !has_reasoning {
        1
    } else if n_chars < 350 && !has_reasoning {
        2
    } else if n_chars < 1200 {
        if has_reasoning {
            4
        } else {
            3
        }
    } else {
        5
    }
}

// ── traits ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LlmTier {
    Default,
    Deep,
}

pub trait Llm: Send + Sync {
    fn complete(&self, tier: LlmTier, system: &str, prompt: &str) -> Result<String>;
}

pub trait DaemonProbe: Send + Sync {
    fn is_alive(&self) -> bool;
}

pub struct AlwaysAliveProbe;
impl DaemonProbe for AlwaysAliveProbe {
    fn is_alive(&self) -> bool {
        true
    }
}
pub struct AlwaysDeadProbe;
impl DaemonProbe for AlwaysDeadProbe {
    fn is_alive(&self) -> bool {
        false
    }
}

// ── state ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AgentState {
    pub task: String,
    pub plan: Vec<String>,
    pub step_results: Vec<String>,
    pub final_answer: String,
    pub review: String,
    pub iteration: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReviewVerdict {
    Accept,
    Retry,
}

// ── nodes ───────────────────────────────────────────────────────────────────

pub fn planner_step(llm: &dyn Llm, task: &str) -> Result<Vec<String>> {
    let n = suggest_plan_size(task);
    if n == 1 {
        return Ok(vec![task.to_string()]);
    }
    let wrapped = wrap_task_for_llm(task);
    let prompt = format!(
        "ЗАДАЧА:\n{}\n\n━━━ ИНСТРУКЦИЯ ДЛЯ ЭТОГО ВЫЗОВА (PLANNER) ━━━\n\
         РОЛЬ: ты планировщик многошаговой задачи.\n\
         ВЫХОД: ровно {} строк, каждая = одна подзадача в повелительном наклонении, ≤120 символов.\n\
         ФОРМАТ: без нумерации, без маркеров, без префиксов «Шаг N:», без пояснений до или после.",
        wrapped, n
    );
    let raw = llm.complete(LlmTier::Deep, "planner", &prompt)?;
    let lines: Vec<String> = raw
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .take(n)
        .collect();
    if lines.is_empty() {
        return Err(GraphError::Llm("planner returned no lines".into()));
    }
    Ok(lines)
}

pub fn executor_step(llm: &dyn Llm, task: &str, plan: &[String]) -> Result<Vec<String>> {
    let mut results = Vec::with_capacity(plan.len());
    for (i, step) in plan.iter().enumerate() {
        let prompt = format!(
            "ОСНОВНАЯ ЗАДАЧА:\n{}\n\nТЕКУЩИЙ ШАГ ({}/{}): {}\n\n\
             Выполни этот шаг. Возвращай только результат шага.",
            task,
            i + 1,
            plan.len(),
            step
        );
        let out = llm.complete(LlmTier::Default, "executor", &prompt)?;
        results.push(out);
    }
    Ok(results)
}

pub fn reviewer_step(llm: &dyn Llm, task: &str, draft: &str) -> Result<(String, ReviewVerdict)> {
    let prompt = format!(
        "ЗАДАЧА:\n{}\n\nЧЕРНОВИК ОТВЕТА:\n{}\n\n\
         Проверь черновик. Если результат удовлетворителен — начни ответ со слова ПРИНЯТЬ. \
         Если нужно переделать — начни со слова ПЕРЕДЕЛАТЬ и кратко укажи что не так.",
        task, draft
    );
    let raw = llm.complete(LlmTier::Deep, "reviewer", &prompt)?;
    let upper = raw.trim_start().to_uppercase();
    let verdict = if upper.starts_with("ПРИНЯТЬ") {
        ReviewVerdict::Accept
    } else {
        ReviewVerdict::Retry
    };
    Ok((raw, verdict))
}

// ── runner ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct GraphConfig {
    pub max_iters: usize,
    pub require_review: bool,
}

impl Default for GraphConfig {
    fn default() -> Self {
        Self {
            max_iters: 2,
            require_review: true,
        }
    }
}

pub fn run(llm: &dyn Llm, task: &str, config: &GraphConfig) -> Result<AgentState> {
    let mut state = AgentState {
        task: task.into(),
        ..Default::default()
    };
    for iter in 0..=config.max_iters {
        state.iteration = iter;
        state.plan = planner_step(llm, &state.task)?;
        state.step_results = executor_step(llm, &state.task, &state.plan)?;
        state.final_answer = state.step_results.join("\n\n");
        if !config.require_review {
            return Ok(state);
        }
        let (review, verdict) = reviewer_step(llm, &state.task, &state.final_answer)?;
        state.review = review;
        if verdict == ReviewVerdict::Accept {
            return Ok(state);
        }
        if iter == config.max_iters {
            return Ok(state);
        }
    }
    Ok(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct ScriptedLlm {
        responses: Mutex<Vec<String>>,
        calls: Mutex<Vec<(LlmTier, String, String)>>,
    }
    impl ScriptedLlm {
        fn new(responses: Vec<&str>) -> Self {
            Self {
                responses: Mutex::new(responses.into_iter().map(String::from).collect()),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for ScriptedLlm {
        fn complete(&self, tier: LlmTier, system: &str, prompt: &str) -> Result<String> {
            self.calls
                .lock()
                .push((tier, system.into(), prompt.into()));
            let mut r = self.responses.lock();
            if r.is_empty() {
                Ok(String::from("(no response scripted)"))
            } else {
                Ok(r.remove(0))
            }
        }
    }

    // ── AimFlags ────────────────────────────────────────────────────────────

    #[test]
    fn flags_set_clear_toggle() {
        let mut f = AimFlags::new(0);
        f.set(AimFlags::AIDER);
        assert!(f.has(AimFlags::AIDER));
        f.clear(AimFlags::AIDER);
        assert!(!f.has(AimFlags::AIDER));
        f.toggle(AimFlags::REVIEW);
        assert!(f.has(AimFlags::REVIEW));
    }

    #[test]
    fn flags_display_lists_set_names() {
        let mut f = AimFlags::new(0);
        f.set(AimFlags::NO_MEM);
        f.set(AimFlags::AIDER);
        let s = f.to_string();
        assert!(s.contains("NO_MEM"));
        assert!(s.contains("AIDER"));
    }

    #[test]
    fn flags_display_zero_is_explicit() {
        assert_eq!(AimFlags::default().to_string(), "AimFlags(0)");
    }

    // ── translit ────────────────────────────────────────────────────────────

    #[test]
    fn translit_detects_common_cyrillic_in_latin() {
        assert!(looks_like_translit("4to eto za fail"));
        assert!(looks_like_translit("pochemu ne rabotaet"));
        assert!(looks_like_translit("zagruzhi i sdelay parse"));
    }

    #[test]
    fn translit_rejects_pure_cyrillic() {
        assert!(!looks_like_translit("привет мир"));
    }

    #[test]
    fn translit_rejects_pure_english() {
        assert!(!looks_like_translit("Hello, how are you today?"));
    }

    #[test]
    fn translit_rejects_empty() {
        assert!(!looks_like_translit(""));
    }

    #[test]
    fn wrap_prepends_hint_for_translit() {
        let out = wrap_task_for_llm("zagruzhi file");
        assert!(out.starts_with("ВНИМАНИЕ"));
        assert!(out.contains("zagruzhi file"));
    }

    #[test]
    fn wrap_passes_through_cyrillic() {
        assert_eq!(wrap_task_for_llm("привет"), "привет");
    }

    #[test]
    fn wrap_passes_through_english() {
        assert_eq!(wrap_task_for_llm("hello"), "hello");
    }

    // ── suggest_plan_size ──────────────────────────────────────────────────

    #[test]
    fn plan_size_short_no_reasoning_is_one() {
        assert_eq!(suggest_plan_size("привет"), 1);
    }

    #[test]
    fn plan_size_medium_no_reasoning_is_two() {
        let s = "x".repeat(200);
        assert_eq!(suggest_plan_size(&s), 2);
    }

    #[test]
    fn plan_size_long_default_three() {
        let s = "x".repeat(800);
        assert_eq!(suggest_plan_size(&s), 3);
    }

    #[test]
    fn plan_size_reasoning_bumps_to_four() {
        let s = format!("проанализируй и {} ", "x".repeat(800));
        assert_eq!(suggest_plan_size(&s), 4);
    }

    #[test]
    fn plan_size_very_long_is_five() {
        let s = "x".repeat(1500);
        assert_eq!(suggest_plan_size(&s), 5);
    }

    #[test]
    fn plan_size_short_with_reasoning_jumps_past_one() {
        // "докажи теорему" — short but reasoning cue → fall through past short-no-reasoning
        let s = "докажи теорему";
        let n = suggest_plan_size(s);
        assert!(n >= 2);
    }

    // ── DaemonProbe ────────────────────────────────────────────────────────

    #[test]
    fn daemon_probe_stubs() {
        assert!(AlwaysAliveProbe.is_alive());
        assert!(!AlwaysDeadProbe.is_alive());
    }

    // ── planner_step ───────────────────────────────────────────────────────

    #[test]
    fn planner_short_task_skips_llm() {
        let llm = ScriptedLlm::new(vec![]);
        let plan = planner_step(&llm, "do x").unwrap();
        assert_eq!(plan, vec!["do x".to_string()]);
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn planner_uses_deep_tier() {
        let llm = ScriptedLlm::new(vec!["step 1\nstep 2"]);
        let task = "x".repeat(200);
        let plan = planner_step(&llm, &task).unwrap();
        assert_eq!(plan.len(), 2);
        assert_eq!(llm.calls.lock()[0].0, LlmTier::Deep);
    }

    #[test]
    fn planner_caps_at_n_lines() {
        let llm = ScriptedLlm::new(vec!["a\nb\nc\nd\ne\nf\ng"]);
        let task = "x".repeat(200);
        let plan = planner_step(&llm, &task).unwrap();
        assert_eq!(plan.len(), 2);
    }

    #[test]
    fn planner_errors_on_empty_response() {
        let llm = ScriptedLlm::new(vec![""]);
        let task = "x".repeat(200);
        assert!(planner_step(&llm, &task).is_err());
    }

    // ── executor_step ──────────────────────────────────────────────────────

    #[test]
    fn executor_runs_per_step() {
        let llm = ScriptedLlm::new(vec!["r1", "r2", "r3"]);
        let plan: Vec<String> = vec!["s1".into(), "s2".into(), "s3".into()];
        let results = executor_step(&llm, "task", &plan).unwrap();
        assert_eq!(results, vec!["r1".to_string(), "r2".into(), "r3".into()]);
        assert_eq!(llm.calls.lock().len(), 3);
        for c in llm.calls.lock().iter() {
            assert_eq!(c.0, LlmTier::Default);
        }
    }

    // ── reviewer_step ──────────────────────────────────────────────────────

    #[test]
    fn reviewer_accept_branch() {
        let llm = ScriptedLlm::new(vec!["ПРИНЯТЬ — всё ок"]);
        let (_text, v) = reviewer_step(&llm, "task", "draft").unwrap();
        assert_eq!(v, ReviewVerdict::Accept);
    }

    #[test]
    fn reviewer_retry_branch() {
        let llm = ScriptedLlm::new(vec!["ПЕРЕДЕЛАТЬ: добавь источники"]);
        let (_text, v) = reviewer_step(&llm, "task", "draft").unwrap();
        assert_eq!(v, ReviewVerdict::Retry);
    }

    #[test]
    fn reviewer_unrecognised_treated_as_retry() {
        let llm = ScriptedLlm::new(vec!["wat"]);
        let (_text, v) = reviewer_step(&llm, "task", "draft").unwrap();
        assert_eq!(v, ReviewVerdict::Retry);
    }

    // ── run (full graph) ───────────────────────────────────────────────────

    #[test]
    fn run_skips_review_when_disabled() {
        // short task → planner_step does not consume LLM responses
        // → only executor consumes (1 response)
        let llm = ScriptedLlm::new(vec!["r1"]);
        let cfg = GraphConfig {
            max_iters: 1,
            require_review: false,
        };
        let state = run(&llm, "short", &cfg).unwrap();
        assert_eq!(state.final_answer, "r1");
        assert_eq!(llm.calls.lock().len(), 1);
    }

    #[test]
    fn run_succeeds_on_first_review_accept() {
        // task short → no planner LLM call.
        // executor: 1 step → 1 LLM call
        // reviewer: 1 LLM call
        let llm = ScriptedLlm::new(vec!["body", "ПРИНЯТЬ"]);
        let cfg = GraphConfig {
            max_iters: 2,
            require_review: true,
        };
        let state = run(&llm, "short task", &cfg).unwrap();
        assert_eq!(state.final_answer, "body");
        assert!(state.review.starts_with("ПРИНЯТЬ"));
        assert_eq!(state.iteration, 0);
        assert_eq!(llm.calls.lock().len(), 2);
    }

    #[test]
    fn run_retries_on_first_review_then_accepts() {
        // iter 0: executor "v1", reviewer ПЕРЕДЕЛАТЬ
        // iter 1: executor "v2", reviewer ПРИНЯТЬ
        let llm = ScriptedLlm::new(vec!["v1", "ПЕРЕДЕЛАТЬ", "v2", "ПРИНЯТЬ"]);
        let state = run(&llm, "short task", &GraphConfig::default()).unwrap();
        assert_eq!(state.iteration, 1);
        assert_eq!(state.final_answer, "v2");
    }

    #[test]
    fn run_returns_last_state_on_max_iters() {
        // 3 iters of (executor, reviewer ПЕРЕДЕЛАТЬ)
        let llm = ScriptedLlm::new(vec![
            "a", "ПЕРЕДЕЛАТЬ",
            "b", "ПЕРЕДЕЛАТЬ",
            "c", "ПЕРЕДЕЛАТЬ",
        ]);
        let cfg = GraphConfig {
            max_iters: 2, // 0..=2 = 3 attempts
            require_review: true,
        };
        let state = run(&llm, "short task", &cfg).unwrap();
        assert_eq!(state.final_answer, "c");
        assert_eq!(state.iteration, 2);
    }
}
