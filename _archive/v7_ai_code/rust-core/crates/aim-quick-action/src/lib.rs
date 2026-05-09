//! aim-quick-action — deterministic intent classifier (Q1).
//!
//! Port of the rule engine from `agents/quick_action.py`. Lets `aim do
//! "draft email to Geiger about Phase B"` choose the right module.
//! Classification is purely heuristic (regex + keyword); the LLM fallback
//! handler stays in the host (this crate has zero LLM deps).
//!
//! ## Supported intents
//! - `brief` — morning brief
//! - `escalate` — what's hot / what's urgent
//! - `followups` — ping all stakeholders
//! - `health` — system status check
//! - `recall` — semantic memory query
//! - `project_brief` — `<PROJECT> brief`
//! - `project_transition` — `transition <PROJECT> to <PHASE>`
//! - `draft_email` — `draft email to <Name>`
//! - `noop` — empty input
//! - `unknown` — no rule matched

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::OnceLock;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Intent {
    pub name: String,
    pub args: serde_json::Map<String, serde_json::Value>,
    /// 0..1 — only relative; 0.95 for transition, 0.85 for project_brief,
    /// 0.8 for top-level rules, 0.7 for draft_email, 0.0 for unknown/noop.
    pub confidence: f64,
    pub rule: String,
}

impl Intent {
    fn empty() -> Self {
        Intent {
            name: "noop".into(),
            args: serde_json::Map::new(),
            confidence: 0.0,
            rule: "empty input".into(),
        }
    }
    fn unknown(query: &str) -> Self {
        let mut args = serde_json::Map::new();
        args.insert("query".into(), serde_json::Value::String(query.to_string()));
        Intent {
            name: "unknown".into(),
            args,
            confidence: 0.0,
            rule: "no rule matched".into(),
        }
    }
}

const TRANSITION_TARGETS: &[&str] = &[
    "DRAFT",
    "REVIEW",
    "SUBMITTED",
    "ACCEPTED",
    "PUBLISHED",
    "REJECTED",
    "ARCHIVED",
];

static RULE_BRIEF: OnceLock<Regex> = OnceLock::new();
static RULE_ESCALATE: OnceLock<Regex> = OnceLock::new();
static RULE_FOLLOWUPS: OnceLock<Regex> = OnceLock::new();
static RULE_HEALTH: OnceLock<Regex> = OnceLock::new();
static RULE_RECALL: OnceLock<Regex> = OnceLock::new();
static PROJECT_RE: OnceLock<Regex> = OnceLock::new();
static TRANSITION_RE: OnceLock<Regex> = OnceLock::new();
static PROJECT_BRIEF_RE: OnceLock<Regex> = OnceLock::new();
static DRAFT_EMAIL_RE: OnceLock<Regex> = OnceLock::new();
static RECIPIENT_LATIN_RE: OnceLock<Regex> = OnceLock::new();
static RECIPIENT_CYR_RE: OnceLock<Regex> = OnceLock::new();
static RECALL_TRIGGER_RE: OnceLock<Regex> = OnceLock::new();

fn rule_brief() -> &'static Regex {
    RULE_BRIEF.get_or_init(|| {
        Regex::new(
            r"(?i)\b(?:morning\s+)?brief\b|\bбриф(?:инг)?\b|\bдоброе\s+утро\b|\bкак\s+дела\b",
        )
        .unwrap()
    })
}
fn rule_escalate() -> &'static Regex {
    RULE_ESCALATE.get_or_init(|| {
        Regex::new(
            r"(?i)\bwhat'?s\s+hot\b|\bwhat'?s\s+urgent\b|\bчто\s+горит\b|\bчто\s+(?:срочно|критично)\b",
        )
        .unwrap()
    })
}
fn rule_followups() -> &'static Regex {
    RULE_FOLLOWUPS.get_or_init(|| {
        Regex::new(r"(?i)\bfollow[-\s]?ups?\b|\bнапомни\b|\bпинг\s+всех\b").unwrap()
    })
}
fn rule_health() -> &'static Regex {
    RULE_HEALTH.get_or_init(|| {
        // Note: dropped the `\b` before `/healthz` — the Python original
        // had `\b/healthz\b` which never actually matches in re semantics
        // (no word boundary between start-of-string and `/`). The intent
        // was clearly to catch `/healthz` requests, so we honour that.
        Regex::new(
            r"(?i)\bhealth\s+check\b|\b(?:обзор|статус)\s+систем\b|/healthz\b",
        )
        .unwrap()
    })
}
fn rule_recall() -> &'static Regex {
    RULE_RECALL.get_or_init(|| Regex::new(r"(?i)\b(?:recall|find|найди|вспомни)\b").unwrap())
}

fn project_re() -> &'static Regex {
    PROJECT_RE.get_or_init(|| Regex::new(r"\b([A-Z][A-Za-z0-9_-]{1,30})\b").unwrap())
}
fn transition_re() -> &'static Regex {
    TRANSITION_RE.get_or_init(|| {
        let alt = TRANSITION_TARGETS.join("|");
        Regex::new(&format!(
            r"(?i)\b(?:transition|перевест[ия]|move)\b.*?\b({alt})\b"
        ))
        .unwrap()
    })
}
fn project_brief_re() -> &'static Regex {
    PROJECT_BRIEF_RE.get_or_init(|| {
        Regex::new(r"(?i)\b(?:brief|статус|status|state|обзор)\b").unwrap()
    })
}
fn draft_email_re() -> &'static Regex {
    DRAFT_EMAIL_RE
        .get_or_init(|| Regex::new(r"(?i)\b(?:draft|написать|подготовь)\b.*?\bemail\b").unwrap())
}
fn recipient_latin_re() -> &'static Regex {
    RECIPIENT_LATIN_RE.get_or_init(|| {
        Regex::new(r"\bto\s+([A-Z][\w'-]{1,40}(?:\s+[A-Z][\w'-]{1,40})?)").unwrap()
    })
}
fn recipient_cyr_re() -> &'static Regex {
    RECIPIENT_CYR_RE.get_or_init(|| Regex::new(r"\b(?:к|для)\s+([А-ЯҐЁA-Z][\w'-]{1,40})").unwrap())
}
fn recall_trigger_re() -> &'static Regex {
    RECALL_TRIGGER_RE
        .get_or_init(|| Regex::new(r"(?i)^\s*(?:recall|find|найди|вспомни)[:\s]+").unwrap())
}

fn extract_project(query: &str, known_projects: &HashSet<String>) -> Option<String> {
    for cap in project_re().captures_iter(query) {
        let tok = cap.get(1)?.as_str().to_string();
        if known_projects.contains(&tok) {
            return Some(tok);
        }
        let upper = tok.to_uppercase();
        if known_projects.contains(&upper) {
            return Some(upper);
        }
    }
    let low = query.to_lowercase();
    for k in known_projects {
        if low.contains(&k.to_lowercase()) {
            return Some(k.clone());
        }
    }
    None
}

fn extract_recipient(query: &str) -> Option<String> {
    if let Some(cap) = recipient_latin_re().captures(query) {
        if let Some(m) = cap.get(1) {
            return Some(m.as_str().trim().to_string());
        }
    }
    if let Some(cap) = recipient_cyr_re().captures(query) {
        if let Some(m) = cap.get(1) {
            return Some(m.as_str().trim().to_string());
        }
    }
    None
}

/// Classify a free-form query against the rule set. `known_projects` lets
/// the dispatch detect project mentions (case-insensitive substring
/// fallback). Pass an empty set to disable project detection.
pub fn classify(query: &str, known_projects: &HashSet<String>) -> Intent {
    let q = query.trim();
    if q.is_empty() {
        return Intent::empty();
    }

    // Project + transition?
    let proj = extract_project(q, known_projects);
    if let Some(p) = &proj {
        if let Some(cap) = transition_re().captures(q) {
            let dst = cap.get(1).unwrap().as_str().to_uppercase();
            let mut args = serde_json::Map::new();
            args.insert("project".into(), serde_json::Value::String(p.clone()));
            args.insert("dst".into(), serde_json::Value::String(dst));
            return Intent {
                name: "project_transition".into(),
                args,
                confidence: 0.95,
                rule: "transition".into(),
            };
        }
        // Project + brief
        if project_brief_re().is_match(q) {
            let mut args = serde_json::Map::new();
            args.insert("project".into(), serde_json::Value::String(p.clone()));
            return Intent {
                name: "project_brief".into(),
                args,
                confidence: 0.85,
                rule: "project_brief".into(),
            };
        }
    }

    // Draft email
    if draft_email_re().is_match(q) {
        let recipient = extract_recipient(q).unwrap_or_default();
        let mut args = serde_json::Map::new();
        args.insert(
            "recipient_hint".into(),
            serde_json::Value::String(recipient),
        );
        args.insert("free_text".into(), serde_json::Value::String(q.to_string()));
        return Intent {
            name: "draft_email".into(),
            args,
            confidence: 0.7,
            rule: "draft_email".into(),
        };
    }

    // Top-level rules — order matches Python (brief, escalate, followups, health, recall)
    for (name, pat) in [
        ("brief", rule_brief()),
        ("escalate", rule_escalate()),
        ("followups", rule_followups()),
        ("health", rule_health()),
        ("recall", rule_recall()),
    ] {
        if pat.is_match(q) {
            let mut args = serde_json::Map::new();
            if name == "recall" {
                let cleaned = recall_trigger_re().replace(q, "").trim().to_string();
                args.insert(
                    "query".into(),
                    serde_json::Value::String(if cleaned.is_empty() {
                        q.to_string()
                    } else {
                        cleaned
                    }),
                );
            }
            return Intent {
                name: name.to_string(),
                args,
                confidence: 0.8,
                rule: format!("rule:{name}"),
            };
        }
    }

    Intent::unknown(q)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn projects(names: &[&str]) -> HashSet<String> {
        names.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn empty_query_is_noop() {
        let intent = classify("", &HashSet::new());
        assert_eq!(intent.name, "noop");
        assert_eq!(intent.confidence, 0.0);
    }

    #[test]
    fn whitespace_only_is_noop() {
        let intent = classify("  \t \n", &HashSet::new());
        assert_eq!(intent.name, "noop");
    }

    #[test]
    fn brief_rule_en() {
        let intent = classify("show me the morning brief", &HashSet::new());
        assert_eq!(intent.name, "brief");
        assert_eq!(intent.confidence, 0.8);
    }

    #[test]
    fn brief_rule_ru() {
        let intent = classify("утренний брифинг пожалуйста", &HashSet::new());
        assert_eq!(intent.name, "brief");
    }

    #[test]
    fn escalate_rule() {
        assert_eq!(classify("what's hot?", &HashSet::new()).name, "escalate");
        assert_eq!(classify("что горит сегодня", &HashSet::new()).name, "escalate");
    }

    #[test]
    fn followups_rule() {
        assert_eq!(
            classify("send follow-ups", &HashSet::new()).name,
            "followups"
        );
        assert_eq!(classify("напомни всем", &HashSet::new()).name, "followups");
    }

    #[test]
    fn health_rule() {
        assert_eq!(
            classify("/healthz now", &HashSet::new()).name,
            "health"
        );
        assert_eq!(
            classify("статус систем пожалуйста", &HashSet::new()).name,
            "health"
        );
    }

    #[test]
    fn recall_strips_trigger() {
        let intent = classify("recall: PMID 12345 results", &HashSet::new());
        assert_eq!(intent.name, "recall");
        assert_eq!(
            intent.args.get("query").and_then(|v| v.as_str()),
            Some("PMID 12345 results")
        );
    }

    #[test]
    fn recall_falls_through_to_full_query_when_no_trigger_strip() {
        let intent = classify("найди что-то полезное", &HashSet::new());
        assert_eq!(intent.name, "recall");
        let q = intent.args.get("query").and_then(|v| v.as_str()).unwrap();
        assert!(q.contains("полезное"));
    }

    #[test]
    fn project_transition_intent() {
        let known = projects(&["FCLC"]);
        let intent = classify("transition FCLC to SUBMITTED", &known);
        assert_eq!(intent.name, "project_transition");
        assert_eq!(intent.confidence, 0.95);
        assert_eq!(
            intent.args.get("project").and_then(|v| v.as_str()),
            Some("FCLC")
        );
        assert_eq!(
            intent.args.get("dst").and_then(|v| v.as_str()),
            Some("SUBMITTED")
        );
    }

    #[test]
    fn project_transition_ru() {
        let known = projects(&["FCLC"]);
        let intent = classify("перевести FCLC в SUBMITTED завтра", &known);
        assert_eq!(intent.name, "project_transition");
        assert_eq!(
            intent.args.get("dst").and_then(|v| v.as_str()),
            Some("SUBMITTED")
        );
    }

    #[test]
    fn project_brief_intent() {
        let known = projects(&["FCLC"]);
        let intent = classify("FCLC статус", &known);
        assert_eq!(intent.name, "project_brief");
        assert_eq!(intent.confidence, 0.85);
        assert_eq!(
            intent.args.get("project").and_then(|v| v.as_str()),
            Some("FCLC")
        );
    }

    #[test]
    fn project_brief_lowercase_match() {
        let known = projects(&["FCLC"]);
        let intent = classify("show me fclc brief", &known);
        assert_eq!(intent.name, "project_brief");
        assert_eq!(
            intent.args.get("project").and_then(|v| v.as_str()),
            Some("FCLC")
        );
    }

    #[test]
    fn draft_email_extracts_recipient() {
        let intent = classify("draft email to Geiger about Phase B", &HashSet::new());
        assert_eq!(intent.name, "draft_email");
        assert_eq!(
            intent.args.get("recipient_hint").and_then(|v| v.as_str()),
            Some("Geiger")
        );
    }

    #[test]
    fn draft_email_extracts_two_word_name() {
        let intent = classify("draft email to Diana Dzidziguri urgent", &HashSet::new());
        assert_eq!(intent.name, "draft_email");
        assert_eq!(
            intent.args.get("recipient_hint").and_then(|v| v.as_str()),
            Some("Diana Dzidziguri")
        );
    }

    #[test]
    fn draft_email_ru_recipient() {
        let intent = classify("подготовь email к Лежаве срочно", &HashSet::new());
        assert_eq!(intent.name, "draft_email");
        assert_eq!(
            intent.args.get("recipient_hint").and_then(|v| v.as_str()),
            Some("Лежаве")
        );
    }

    #[test]
    fn unknown_query_returns_unknown() {
        let intent = classify("zZ random text without trigger", &HashSet::new());
        assert_eq!(intent.name, "unknown");
        assert_eq!(intent.confidence, 0.0);
        assert_eq!(
            intent.args.get("query").and_then(|v| v.as_str()),
            Some("zZ random text without trigger")
        );
    }

    #[test]
    fn project_match_only_no_brief_keyword_falls_through() {
        let known = projects(&["FCLC"]);
        // Project mentioned but no brief/status keyword and no transition
        let intent = classify("ping FCLC team", &known);
        // Falls through to other rules; no rule matches "ping" as a top-level
        // intent → unknown (matches Python — `followups` matches "пинг всех"
        // not bare "ping")
        assert_eq!(intent.name, "unknown");
    }

    #[test]
    fn transition_takes_precedence_over_brief() {
        let known = projects(&["FCLC"]);
        let intent = classify("transition FCLC to SUBMITTED, brief later", &known);
        assert_eq!(intent.name, "project_transition");
    }

    #[test]
    fn extract_project_substring_lowercase() {
        let known = projects(&["FCLC"]);
        let intent = classify("how is fclc going", &known);
        assert_eq!(intent.name, "unknown"); // no brief keyword
                                            // But project would resolve in deeper code paths
        assert_eq!(extract_project("how is fclc going", &known).as_deref(), Some("FCLC"));
    }

    #[test]
    fn extract_project_unknown_returns_none() {
        let known = projects(&["FCLC"]);
        assert!(extract_project("show me the X status", &known).is_none());
    }

    #[test]
    fn intent_serialises_to_json() {
        let mut args = serde_json::Map::new();
        args.insert("project".into(), serde_json::Value::String("FCLC".into()));
        let i = Intent {
            name: "project_brief".into(),
            args,
            confidence: 0.85,
            rule: "project_brief".into(),
        };
        let s = serde_json::to_string(&i).unwrap();
        assert!(s.contains("\"name\":\"project_brief\""));
        assert!(s.contains("\"FCLC\""));
    }
}
