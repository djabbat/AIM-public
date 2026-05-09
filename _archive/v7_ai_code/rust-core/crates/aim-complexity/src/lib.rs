//! aim-complexity — heuristic task-complexity classifier.
//!
//! Used by `graph._planner` to auto-decide whether to use Tree-of-Thoughts,
//! flat planning, or skip planning entirely (single-step direct execution).
//!
//! ## Classes
//! | Complexity | Trigger                                                      | Plan       |
//! |------------|--------------------------------------------------------------|------------|
//! | `direct`   | lookup pattern OR length < 80                                | direct, 1  |
//! | `simple`   | length < 200                                                 | flat, 2    |
//! | `medium`   | default                                                       | flat, 3    |
//! | `complex`  | reasoning markers OR ≥3 entities OR length ≥ 1200            | tree, 4    |
//!
//! Wire-in: `graph._suggest_plan_size()` calls [`suggest_plan_type`]. If the
//! user explicitly passes `--tree-plan`, that wins.

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::OnceLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Complexity {
    Direct,
    Simple,
    Medium,
    Complex,
}

impl Complexity {
    pub fn as_str(self) -> &'static str {
        match self {
            Complexity::Direct => "direct",
            Complexity::Simple => "simple",
            Complexity::Medium => "medium",
            Complexity::Complex => "complex",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PlanType {
    Direct,
    Flat,
    #[serde(rename = "tree-plan")]
    TreePlan,
}

impl PlanType {
    pub fn as_str(self) -> &'static str {
        match self {
            PlanType::Direct => "direct",
            PlanType::Flat => "flat",
            PlanType::TreePlan => "tree-plan",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Verdict {
    pub complexity: Complexity,
    pub reasoning_markers: bool,
    pub lookup_pattern: bool,
    pub entity_count: usize,
    pub length: usize,
    pub plan_type: PlanType,
    pub plan_size: u32,
    pub tree_plan: bool,
}

static REASONING_RE: OnceLock<Regex> = OnceLock::new();
static LOOKUP_RE: OnceLock<Regex> = OnceLock::new();
static ENTITY_RE: OnceLock<Regex> = OnceLock::new();

fn reasoning_re() -> &'static Regex {
    REASONING_RE.get_or_init(|| {
        Regex::new(
            r"(?i)\b(?:почему|объясни|обоснуй|проанализируй|сравни|оцени|why|explain|analyse|analyze|compare|reason|prove|justify|докажи|выведи|разложи|обсуди)\b",
        )
        .expect("reasoning regex")
    })
}

fn lookup_re() -> &'static Regex {
    LOOKUP_RE.get_or_init(|| {
        Regex::new(
            r"(?i)^(?:что|кто|когда|где|сколько|when|who|where|how many|what is|какой|какая|какое)\s",
        )
        .expect("lookup regex")
    })
}

fn entity_re() -> &'static Regex {
    ENTITY_RE.get_or_init(|| {
        // Capitalised word (≥3 chars), all-caps acronym (≥3 chars), or 4-digit year
        Regex::new(
            r"(?:[A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}|[A-ZА-Я]{3,}|\d{4})",
        )
        .expect("entity regex")
    })
}

const ENTITY_STOPWORDS: &[&str] = &["the", "this", "that", "что", "это", "todo"];

pub fn classify(task: &str) -> Verdict {
    let task = task.trim();
    let length = task.chars().count();
    let has_reasoning = reasoning_re().is_match(task);
    let is_lookup = lookup_re().is_match(task);
    let mut entities: HashSet<String> = HashSet::new();
    for m in entity_re().find_iter(task) {
        let s = m.as_str().to_string();
        let lc = s.to_lowercase();
        if ENTITY_STOPWORDS.contains(&lc.as_str()) {
            continue;
        }
        entities.insert(s);
    }
    let entity_count = entities.len();

    let complexity = if has_reasoning || entity_count >= 3 || length >= 1200 {
        Complexity::Complex
    } else if is_lookup || length < 80 {
        Complexity::Direct
    } else if length < 200 {
        Complexity::Simple
    } else {
        Complexity::Medium
    };

    let (plan_type, plan_size, tree_plan) = match complexity {
        Complexity::Direct => (PlanType::Direct, 1, false),
        Complexity::Simple => (PlanType::Flat, 2, false),
        Complexity::Medium => (PlanType::Flat, 3, false),
        Complexity::Complex => (PlanType::TreePlan, 4, true),
    };

    Verdict {
        complexity,
        reasoning_markers: has_reasoning,
        lookup_pattern: is_lookup,
        entity_count,
        length,
        plan_type,
        plan_size,
        tree_plan,
    }
}

pub fn suggest_plan_type(task: &str) -> PlanType {
    classify(task).plan_type
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn direct_lookup_short_question() {
        let v = classify("кто такой Эйнштейн?");
        assert_eq!(v.complexity, Complexity::Direct);
        assert_eq!(v.plan_type, PlanType::Direct);
        assert!(v.lookup_pattern);
        assert!(!v.tree_plan);
    }

    #[test]
    fn direct_short_command() {
        let v = classify("rename file x to y");
        assert_eq!(v.complexity, Complexity::Direct);
    }

    #[test]
    fn simple_below_200_chars() {
        let s = "Update the README to mention the new endpoint and bump version in package.json before pushing to main branch tomorrow morning";
        let v = classify(s);
        assert_eq!(v.complexity, Complexity::Simple);
        assert_eq!(v.plan_type, PlanType::Flat);
        assert_eq!(v.plan_size, 2);
    }

    #[test]
    fn medium_default() {
        // 200-1199 chars, no reasoning markers, no lookup, <3 entities
        let s = "x".repeat(300);
        let v = classify(&s);
        assert_eq!(v.complexity, Complexity::Medium);
        assert_eq!(v.plan_type, PlanType::Flat);
        assert_eq!(v.plan_size, 3);
    }

    #[test]
    fn complex_when_reasoning_markers() {
        let v = classify("сравни препарат A и препарат B");
        assert_eq!(v.complexity, Complexity::Complex);
        assert!(v.reasoning_markers);
        assert!(v.tree_plan);
        assert_eq!(v.plan_size, 4);
    }

    #[test]
    fn complex_when_long() {
        let s = "x".repeat(1300);
        let v = classify(&s);
        assert_eq!(v.complexity, Complexity::Complex);
    }

    #[test]
    fn complex_when_three_entities() {
        // Three capitalized entities (≥3 chars) trip the threshold
        let v = classify("Compare Boston Toronto Ottawa");
        assert!(v.entity_count >= 3, "got {}", v.entity_count);
        assert_eq!(v.complexity, Complexity::Complex);
    }

    #[test]
    fn english_compare_marker_triggers_complex() {
        let v = classify("compare these results");
        assert_eq!(v.complexity, Complexity::Complex);
    }

    #[test]
    fn entity_dedup() {
        // "Tokyo" appears twice; should count as 1 entity
        let v = classify("Tokyo and Tokyo are the same place actually");
        assert_eq!(v.entity_count, 1);
    }

    #[test]
    fn entity_stopwords_excluded() {
        let v = classify("что это todo привет это");
        // "что", "это", "todo" all stopwords; only common entities remain.
        assert!(v.entity_count < 3);
    }

    #[test]
    fn suggest_plan_type_returns_class() {
        assert_eq!(suggest_plan_type("how many files in repo"), PlanType::Direct);
        assert_eq!(
            suggest_plan_type("explain how this algorithm works in detail"),
            PlanType::TreePlan
        );
    }

    #[test]
    fn empty_task_classified_as_direct() {
        let v = classify("");
        assert_eq!(v.length, 0);
        assert_eq!(v.complexity, Complexity::Direct);
    }

    #[test]
    fn serde_round_trip() {
        let v = classify("compare A B C");
        let s = serde_json::to_string(&v).unwrap();
        assert!(s.contains("\"complexity\":\"complex\""));
        assert!(s.contains("\"plan_type\":\"tree-plan\""));
    }
}
