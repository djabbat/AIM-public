//! aim-complexity-classifier — heuristic task-complexity classifier.
//!
//! Port of `agents/complexity_classifier.py`. Classifies a free-form
//! task string as `direct` / `simple` / `medium` / `complex` and
//! suggests a planner mode (`direct` / `flat` / `tree-plan`) plus
//! a plan size. Pure regex + length heuristics — no LLM call.

use std::collections::HashSet;

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};

static REASONING_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(почему|объясни|обоснуй|проанализируй|сравни|оцени|why|explain|analyse|analyze|compare|reason|prove|justify|докажи|выведи|разложи|обсуди)\b",
    )
    .expect("REASONING_RE")
});

static LOOKUP_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^(что|кто|когда|где|сколько|when|who|where|how many|what is|какой|какая|какое)\s",
    )
    .expect("LOOKUP_RE")
});

// Note: Rust's `regex` crate has no Unicode property in [...] groups by
// default outside character classes, so we build the entity matcher by
// scanning Unicode words. We accept either:
//   * Title-cased word (cap + ≥2 lowercase letters), or
//   * 3+ uppercase ASCII letters in a row (acronyms), or
//   * a 4-digit number (years, dosages, codes).
static ENTITY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\b([A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}|[A-ZА-Я]{3,}|\d{4})\b",
    )
    .expect("ENTITY_RE")
});

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Complexity {
    Direct,
    Simple,
    Medium,
    Complex,
}

impl Complexity {
    pub fn as_str(&self) -> &'static str {
        match self {
            Complexity::Direct => "direct",
            Complexity::Simple => "simple",
            Complexity::Medium => "medium",
            Complexity::Complex => "complex",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PlanType {
    Direct,
    Flat,
    #[serde(rename = "tree-plan")]
    TreePlan,
}

impl PlanType {
    pub fn as_str(&self) -> &'static str {
        match self {
            PlanType::Direct => "direct",
            PlanType::Flat => "flat",
            PlanType::TreePlan => "tree-plan",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Classification {
    pub complexity: Complexity,
    pub reasoning_markers: bool,
    pub lookup_pattern: bool,
    pub entity_count: usize,
    pub length: usize,
    pub plan_type: PlanType,
    pub plan_size: u8,
    pub tree_plan: bool,
}

const STOP: &[&str] = &["the", "this", "that", "что", "это", "todo"];

pub fn classify(task: &str) -> Classification {
    let task = task.trim();
    let n = task.chars().count();
    let has_reasoning = REASONING_RE.is_match(task);
    let is_lookup = LOOKUP_RE.is_match(task);

    let mut entities: HashSet<String> = HashSet::new();
    for m in ENTITY_RE.find_iter(task) {
        let s = m.as_str().to_lowercase();
        if !STOP.contains(&s.as_str()) {
            entities.insert(s);
        }
    }
    let n_entities = entities.len();

    let complexity = if has_reasoning || n_entities >= 3 || n >= 1200 {
        Complexity::Complex
    } else if is_lookup || n < 80 {
        Complexity::Direct
    } else if n < 200 {
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

    Classification {
        complexity,
        reasoning_markers: has_reasoning,
        lookup_pattern: is_lookup,
        entity_count: n_entities,
        length: n,
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
    fn empty_is_direct() {
        let r = classify("");
        assert_eq!(r.complexity, Complexity::Direct);
        assert_eq!(r.plan_type, PlanType::Direct);
        assert_eq!(r.length, 0);
    }

    #[test]
    fn short_lookup_is_direct() {
        let r = classify("что такое центриоль");
        assert_eq!(r.complexity, Complexity::Direct);
        assert!(r.lookup_pattern);
    }

    #[test]
    fn english_lookup_is_direct() {
        let r = classify("when did the cell divide");
        assert_eq!(r.complexity, Complexity::Direct);
        assert!(r.lookup_pattern);
    }

    #[test]
    fn short_non_lookup_is_direct() {
        let r = classify("краткий обзор статьи");
        assert_eq!(r.complexity, Complexity::Direct);
    }

    #[test]
    fn medium_length_is_simple_or_medium() {
        // 100 chars, no reasoning markers, no lookup pattern
        let s: String = "a".repeat(100);
        let r = classify(&s);
        assert_eq!(r.complexity, Complexity::Simple);
        assert_eq!(r.plan_size, 2);
    }

    #[test]
    fn longer_length_is_medium() {
        let s: String = "x".repeat(500);
        let r = classify(&s);
        assert_eq!(r.complexity, Complexity::Medium);
        assert_eq!(r.plan_size, 3);
    }

    #[test]
    fn very_long_is_complex_by_length() {
        let s: String = "a".repeat(1300);
        let r = classify(&s);
        assert_eq!(r.complexity, Complexity::Complex);
        assert!(r.tree_plan);
    }

    #[test]
    fn reasoning_marker_makes_complex() {
        let r = classify("сравни два подхода к диагностике в хирургии");
        assert_eq!(r.complexity, Complexity::Complex);
        assert!(r.reasoning_markers);
        assert_eq!(r.plan_type, PlanType::TreePlan);
    }

    #[test]
    fn english_reasoning_marker() {
        let r = classify("explain how mitochondria work in eukaryotic cells");
        assert_eq!(r.complexity, Complexity::Complex);
        assert!(r.reasoning_markers);
    }

    #[test]
    fn three_entities_makes_complex() {
        // Three Title-cased words → 3 entities → complex
        let r = classify("Alpha Bravo Charlie quick brief");
        assert_eq!(r.complexity, Complexity::Complex);
        assert_eq!(r.entity_count, 3);
    }

    #[test]
    fn acronym_counts_as_entity() {
        let r = classify("WHO ICD CDC publish guidelines");
        assert_eq!(r.entity_count, 3);
        assert_eq!(r.complexity, Complexity::Complex);
    }

    #[test]
    fn year_counts_as_entity() {
        let r = classify("2024 2025 2026 trends summary");
        assert!(r.entity_count >= 3);
        assert_eq!(r.complexity, Complexity::Complex);
    }

    #[test]
    fn stopwords_dont_count_as_entities() {
        // 'The This That' would be 3 title-cased words → but all stopwords
        let r = classify("The This That review here");
        assert_eq!(r.entity_count, 0);
    }

    #[test]
    fn suggest_plan_type_convenience() {
        assert_eq!(suggest_plan_type("что"), PlanType::Direct);
        assert_eq!(
            suggest_plan_type("сравни препарат A и препарат B"),
            PlanType::TreePlan
        );
    }

    #[test]
    fn json_round_trip_uses_lowercase_strings() {
        let r = classify("explain it in detail");
        let s = serde_json::to_string(&r).unwrap();
        assert!(s.contains("\"complexity\":\"complex\""));
        assert!(s.contains("\"plan_type\":\"tree-plan\""));
    }
}
