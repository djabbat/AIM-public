//! aim-webhooks — webhook payload schemas + auth check.
//!
//! Port of `web/webhooks.py`. Pure data structures (Serde) + the
//! token-check state machine. The actual axum router stays in the
//! binary.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum AuthError {
    #[error("AIM_WEBHOOK_TOKEN not set on server")]
    NotConfigured,
    #[error("invalid webhook token")]
    Invalid,
}

pub fn check_token(server_token: Option<&str>, supplied: Option<&str>) -> Result<(), AuthError> {
    match server_token {
        None => Err(AuthError::NotConfigured),
        Some(s) if s.is_empty() => Err(AuthError::NotConfigured),
        Some(s) => match supplied {
            None => Err(AuthError::Invalid),
            Some(t) if t == s => Ok(()),
            _ => Err(AuthError::Invalid),
        },
    }
}

// ── payloads ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MemoryAddPayload {
    pub fact: String,
    #[serde(default = "default_webhook_category")]
    pub category: String,
    #[serde(default)]
    pub tags: Option<Vec<String>>,
    #[serde(default)]
    pub priority: Option<String>,
    #[serde(default)]
    pub ttl_hours: Option<u32>,
    #[serde(default)]
    pub callback_url: Option<String>,
}

fn default_webhook_category() -> String {
    "webhook".into()
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GraphRunPayload {
    pub task: String,
    #[serde(default = "default_true")]
    pub use_memory: bool,
    #[serde(default)]
    pub full_memory: bool,
    #[serde(default)]
    pub parallel: bool,
    #[serde(default)]
    pub debate: bool,
    #[serde(default)]
    pub tree_plan: bool,
    #[serde(default)]
    pub callback_url: Option<String>,
}

fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MemorySearchPayload {
    pub query: String,
    #[serde(default = "default_k")]
    pub k: u32,
    #[serde(default)]
    pub graph: bool,
}

fn default_k() -> u32 {
    8
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AcceptedJob {
    pub task_id: String,
    pub status: String,
}

impl AcceptedJob {
    pub fn new(task_id: impl Into<String>) -> Self {
        Self {
            task_id: task_id.into(),
            status: "accepted".into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── token check ───────────────────────────────────────────────────────

    #[test]
    fn token_unset_rejects_with_503_meaning() {
        assert_eq!(check_token(None, Some("x")), Err(AuthError::NotConfigured));
        assert_eq!(check_token(Some(""), Some("x")), Err(AuthError::NotConfigured));
    }

    #[test]
    fn token_match_passes() {
        assert!(check_token(Some("secret"), Some("secret")).is_ok());
    }

    #[test]
    fn token_mismatch_rejects() {
        assert_eq!(
            check_token(Some("secret"), Some("wrong")),
            Err(AuthError::Invalid)
        );
        assert_eq!(check_token(Some("secret"), None), Err(AuthError::Invalid));
    }

    // ── payload defaults ──────────────────────────────────────────────────

    #[test]
    fn memory_add_default_category() {
        let p: MemoryAddPayload = serde_json::from_str(r#"{"fact":"hi"}"#).unwrap();
        assert_eq!(p.category, "webhook");
        assert!(p.tags.is_none());
    }

    #[test]
    fn graph_run_use_memory_default_true() {
        let p: GraphRunPayload = serde_json::from_str(r#"{"task":"plan dinner"}"#).unwrap();
        assert!(p.use_memory);
        assert!(!p.parallel);
    }

    #[test]
    fn memory_search_default_k_is_8() {
        let p: MemorySearchPayload = serde_json::from_str(r#"{"query":"x"}"#).unwrap();
        assert_eq!(p.k, 8);
        assert!(!p.graph);
    }

    // ── accepted job shape ────────────────────────────────────────────────

    #[test]
    fn accepted_serialises_to_python_shape() {
        let j = AcceptedJob::new("abc123");
        let s = serde_json::to_string(&j).unwrap();
        assert_eq!(s, r#"{"task_id":"abc123","status":"accepted"}"#);
    }
}
