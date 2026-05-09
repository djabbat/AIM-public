//! aim-tree-planner — Tree-of-Thoughts planner for hard tasks.
//!
//! Port of `agents/tree_planner.py`. Generates `branching` candidate
//! approaches, scores them via a Deep-tier LLM judge, expands the top-K
//! into concrete steps. Returns a flat plan that the LangGraph executor
//! can consume.
//!
//! The LLM sits behind [`Llm`] so the generate→evaluate→expand pipeline
//! is testable without API calls.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PlannerError {
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, PlannerError>;

pub const SYSTEM_PROMPT: &str =
    "Ты планировщик многошаговых задач. Отвечаешь на русском языке. Без преамбул, без воды.";

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Thought {
    pub text: String,
    pub score: f64,
    pub children: Vec<Thought>,
    pub rationale: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PlanResult {
    pub plan: Vec<String>,
    pub thoughts: Vec<ThoughtView>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ThoughtView {
    pub text: String,
    pub score: f64,
    pub children: Vec<String>,
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

// ── helpers ─────────────────────────────────────────────────────────────────

/// Trim leading bullets/dashes/spaces. Mirrors Python `line.strip("-•* \t")`.
pub fn strip_bullets(line: &str) -> String {
    line.trim_matches(|c: char| matches!(c, '-' | '•' | '*' | ' ' | '\t'))
        .trim()
        .to_string()
}

fn parse_lines(raw: &str, min_len: usize) -> Vec<String> {
    raw.lines()
        .map(strip_bullets)
        .filter(|l| !l.is_empty() && l.chars().count() > min_len)
        .collect()
}

// ── stages ──────────────────────────────────────────────────────────────────

pub fn generate(llm: &dyn Llm, task: &str, n: usize) -> Result<Vec<String>> {
    let prompt = format!(
        "ЗАДАЧА:\n{}\n\nСгенерируй {} принципиально РАЗНЫХ подходов к решению.\nКаждый подход = одна строка, ≤140 символов. Без нумерации.",
        task, n
    );
    let raw = llm.complete(LlmTier::Deep, SYSTEM_PROMPT, &prompt)?;
    Ok(parse_lines(&raw, 10).into_iter().take(n).collect())
}

/// Score regex: `(idea|approach|вариант) N: X.X` — verbatim from Python.
fn score_re() -> regex::Regex {
    regex::Regex::new(r"(?i)(?:идея|approach|вариант)\s*(\d+)\s*[:=]\s*([\d.]+)")
        .expect("score regex compiles")
}

pub fn evaluate(llm: &dyn Llm, task: &str, ideas: &[String]) -> Result<Vec<Thought>> {
    let listed: String = ideas
        .iter()
        .enumerate()
        .map(|(i, idea)| format!("{}. {}", i + 1, idea))
        .collect::<Vec<_>>()
        .join("\n");
    let prompt = format!(
        "ЗАДАЧА:\n{}\n\nОцени каждый подход 0–10 по критериям: feasibility, completeness, risk.\n\nПОДХОДЫ:\n{}\n\nВЫХОД: одна строка на подход, формат «Идея N: X.X» (число — итог 0–10).\nПосле списка — одна строка обоснования победителя ≤2 предложений.",
        task, listed
    );
    let raw = llm.complete(LlmTier::Deep, SYSTEM_PROMPT, &prompt)?;
    let re = score_re();
    let mut scores: std::collections::HashMap<usize, f64> = std::collections::HashMap::new();
    for cap in re.captures_iter(&raw) {
        if let (Some(idx_str), Some(val_str)) = (cap.get(1), cap.get(2)) {
            if let (Ok(idx), Ok(val)) = (
                idx_str.as_str().parse::<usize>(),
                val_str.as_str().parse::<f64>(),
            ) {
                if idx >= 1 {
                    scores.insert(idx - 1, val);
                }
            }
        }
    }
    let rationale: String = raw
        .lines()
        .filter(|line| !re.is_match(line))
        .collect::<Vec<_>>()
        .join("\n");
    let trimmed: String = rationale.trim().chars().take(400).collect();

    Ok(ideas
        .iter()
        .enumerate()
        .map(|(i, idea)| Thought {
            text: idea.clone(),
            score: scores.get(&i).copied().unwrap_or(5.0),
            children: Vec::new(),
            rationale: trimmed.clone(),
        })
        .collect())
}

pub fn expand(llm: &dyn Llm, task: &str, thought: &Thought, depth: usize) -> Result<Vec<String>> {
    if depth == 0 {
        return Ok(vec![thought.text.clone()]);
    }
    let cap = depth.max(1) * 2;
    let prompt = format!(
        "ЗАДАЧА:\n{}\n\nРазвивай выбранный подход в КОНКРЕТНЫЕ исполняемые шаги.\nПОДХОД: {}\n\nДай ≤{} шагов, по одному в строку, в повелительном наклонении, ≤120 символов, без нумерации, без преамбул.",
        task, thought.text, cap
    );
    let raw = llm.complete(LlmTier::Default, SYSTEM_PROMPT, &prompt)?;
    Ok(parse_lines(&raw, 5).into_iter().take(cap).collect())
}

// ── public ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct PlannerConfig {
    pub branching: usize,
    pub depth: usize,
    pub keep_top: usize,
}

impl Default for PlannerConfig {
    fn default() -> Self {
        Self {
            branching: 4,
            depth: 2,
            keep_top: 2,
        }
    }
}

/// Sequential variant of Python's `tree_plan`. Returns a flat list of
/// executable steps from the top-`keep_top` ideas.
pub fn tree_plan(llm: &dyn Llm, task: &str, config: &PlannerConfig) -> Result<PlanResult> {
    let ideas = generate(llm, task, config.branching)?;
    if ideas.is_empty() {
        return Ok(PlanResult {
            plan: vec![task.to_string()],
            thoughts: Vec::new(),
        });
    }
    let mut scored = evaluate(llm, task, &ideas)?;
    scored.sort_by(|a, b| {
        b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal)
    });
    let keep = config.keep_top.min(scored.len());

    for t in scored.iter_mut().take(keep) {
        let children = expand(llm, task, t, config.depth)?;
        t.children = children.into_iter().map(|s| Thought {
            text: s,
            ..Default::default()
        }).collect();
    }

    let mut plan: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    for t in scored.iter().take(keep) {
        for c in &t.children {
            if seen.insert(c.text.clone()) {
                plan.push(c.text.clone());
            }
        }
    }
    plan.truncate(config.branching * config.depth);

    let thoughts = scored
        .iter()
        .map(|t| ThoughtView {
            text: t.text.clone(),
            score: t.score,
            children: t.children.iter().map(|c| c.text.clone()).collect(),
        })
        .collect();

    Ok(PlanResult { plan, thoughts })
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    struct ScriptedLlm {
        responses: Mutex<Vec<String>>,
        calls: Mutex<Vec<(LlmTier, String)>>,
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
        fn complete(&self, tier: LlmTier, _system: &str, prompt: &str) -> Result<String> {
            self.calls.lock().push((tier, prompt.to_string()));
            let mut r = self.responses.lock();
            if r.is_empty() {
                Ok("(empty)".into())
            } else {
                Ok(r.remove(0))
            }
        }
    }

    // ── strip_bullets ──────────────────────────────────────────────────────

    #[test]
    fn strip_bullets_handles_common_prefixes() {
        assert_eq!(strip_bullets("- идея один"), "идея один");
        assert_eq!(strip_bullets("• другой"), "другой");
        assert_eq!(strip_bullets("\t\t  *third  "), "third");
    }

    #[test]
    fn strip_bullets_passthrough_clean_text() {
        assert_eq!(strip_bullets("plain text"), "plain text");
    }

    // ── generate ───────────────────────────────────────────────────────────

    #[test]
    fn generate_uses_deep_tier() {
        let llm = ScriptedLlm::new(vec!["идея первая длинная\n- идея вторая"]);
        let ideas = generate(&llm, "task", 5).unwrap();
        assert_eq!(ideas.len(), 2);
        assert_eq!(llm.calls.lock()[0].0, LlmTier::Deep);
    }

    #[test]
    fn generate_filters_too_short_lines() {
        let llm = ScriptedLlm::new(vec!["short\n- длинная и хорошая идея\n- мини"]);
        let ideas = generate(&llm, "t", 5).unwrap();
        // "short" (5) and "мини" (4) under min_len=10
        assert_eq!(ideas.len(), 1);
        assert!(ideas[0].contains("длинная"));
    }

    #[test]
    fn generate_caps_at_n() {
        let llm = ScriptedLlm::new(vec![
            "первая идея в плане\n- вторая идея\n- третья идея\n- четвёртая идея\n- пятая идея",
        ]);
        let ideas = generate(&llm, "t", 3).unwrap();
        assert_eq!(ideas.len(), 3);
    }

    // ── evaluate ───────────────────────────────────────────────────────────

    #[test]
    fn evaluate_parses_score_lines() {
        let llm = ScriptedLlm::new(vec![
            "Идея 1: 8.5\nИдея 2: 6.0\nИдея 3: 9.2\nПобедитель — третий: ясный план.",
        ]);
        let ideas = vec!["a".into(), "b".into(), "c".into()];
        let thoughts = evaluate(&llm, "t", &ideas).unwrap();
        assert_eq!(thoughts.len(), 3);
        assert!((thoughts[0].score - 8.5).abs() < 1e-9);
        assert!((thoughts[1].score - 6.0).abs() < 1e-9);
        assert!((thoughts[2].score - 9.2).abs() < 1e-9);
    }

    #[test]
    fn evaluate_default_score_when_missing() {
        let llm = ScriptedLlm::new(vec!["Идея 1: 9.0\n(нет второго)"]);
        let thoughts = evaluate(&llm, "t", &vec!["a".into(), "b".into()]).unwrap();
        assert!((thoughts[0].score - 9.0).abs() < 1e-9);
        // missing → 5.0 default
        assert!((thoughts[1].score - 5.0).abs() < 1e-9);
    }

    #[test]
    fn evaluate_records_rationale_truncated() {
        let long_line = "x".repeat(800);
        let resp = format!("Идея 1: 7.0\n{}", long_line);
        let llm = ScriptedLlm::new(vec![&resp]);
        let thoughts = evaluate(&llm, "t", &vec!["a".into()]).unwrap();
        assert!(thoughts[0].rationale.chars().count() <= 400);
    }

    #[test]
    fn evaluate_recognises_english_approach_label() {
        let llm = ScriptedLlm::new(vec!["Approach 1: 8.0\nApproach 2: 4.0"]);
        let thoughts = evaluate(&llm, "t", &vec!["a".into(), "b".into()]).unwrap();
        assert!((thoughts[0].score - 8.0).abs() < 1e-9);
        assert!((thoughts[1].score - 4.0).abs() < 1e-9);
    }

    // ── expand ─────────────────────────────────────────────────────────────

    #[test]
    fn expand_returns_thought_text_at_depth_zero() {
        let llm = ScriptedLlm::new(vec![]);
        let t = Thought {
            text: "as-is".into(),
            ..Default::default()
        };
        let steps = expand(&llm, "task", &t, 0).unwrap();
        assert_eq!(steps, vec!["as-is".to_string()]);
    }

    #[test]
    fn expand_uses_default_tier_and_caps_steps() {
        let llm = ScriptedLlm::new(vec![
            "- шаг первый длинный\n- шаг второй\n- шаг третий\n- шаг четвёртый\n- шаг пятый",
        ]);
        let t = Thought {
            text: "approach".into(),
            ..Default::default()
        };
        // depth=2 → cap = 4 steps
        let steps = expand(&llm, "task", &t, 2).unwrap();
        assert_eq!(steps.len(), 4);
        assert_eq!(llm.calls.lock()[0].0, LlmTier::Default);
    }

    // ── tree_plan ──────────────────────────────────────────────────────────

    #[test]
    fn tree_plan_orders_by_score_and_returns_top_children() {
        // generate: 2 ideas
        // evaluate: idea#2 wins (9.0), idea#1 second (4.0)
        // expand idea#2: 2 steps
        // expand idea#1: 2 steps
        let llm = ScriptedLlm::new(vec![
            "идея первая просто длинная\n- идея вторая важная и хорошая",
            "Идея 1: 4.0\nИдея 2: 9.0\nВторая лучше",
            "- step A first\n- step B first",
            "- step C second\n- step D second",
        ]);
        let cfg = PlannerConfig {
            branching: 2,
            depth: 1,
            keep_top: 2,
        };
        let res = tree_plan(&llm, "task", &cfg).unwrap();
        // top thought is idea#2 (score 9.0)
        assert_eq!(res.thoughts[0].score, 9.0);
        assert!(res.thoughts[0].text.contains("вторая"));
        assert!(res.plan.len() <= cfg.branching * cfg.depth.max(1) * 2);
        // plan starts with the top idea's children
        assert!(res.plan[0].contains("step A") || res.plan[0].contains("step C"));
    }

    #[test]
    fn tree_plan_empty_ideas_returns_task_as_plan() {
        let llm = ScriptedLlm::new(vec!["", "", ""]);
        let res = tree_plan(&llm, "the original task", &PlannerConfig::default()).unwrap();
        assert_eq!(res.plan, vec!["the original task".to_string()]);
        assert!(res.thoughts.is_empty());
    }

    #[test]
    fn tree_plan_dedupes_steps_across_branches() {
        let llm = ScriptedLlm::new(vec![
            "идея один длинная штука\n- идея два большая длинная",
            "Идея 1: 8.0\nИдея 2: 7.0",
            "- общий шаг\n- частный шаг A",
            "- общий шаг\n- частный шаг B",
        ]);
        let cfg = PlannerConfig {
            branching: 2,
            depth: 1,
            keep_top: 2,
        };
        let res = tree_plan(&llm, "task", &cfg).unwrap();
        let n = res.plan.iter().filter(|p| p.contains("общий")).count();
        assert_eq!(n, 1);
    }
}
