//! aim-web-api — request/response shapes + Bearer-token + role-gate helpers.
//!
//! Port of the deterministic core of `web/api.py`. The actual axum
//! handlers live in the binary; here we keep the pydantic-equivalent
//! schemas and the auth state machine.

use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── pydantic-equivalent payloads ──────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ChatRequest {
    pub query: String,
    #[serde(default = "default_true")]
    pub use_memory: bool,
    #[serde(default)]
    pub full_memory: bool,
    #[serde(default)]
    pub parallel: bool,
    #[serde(default)]
    pub debate: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ChatResponse {
    pub task_id: String,
    pub status: String,
    pub websocket: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct LoginRequest {
    pub username: String,
    pub password: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CreateUserRequest {
    pub username: String,
    pub password: String,
    #[serde(default = "default_user_role")]
    pub role: String,
    #[serde(default)]
    pub email: Option<String>,
}

fn default_user_role() -> String {
    "user".into()
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TokenValidateRequest {
    pub token: String,
    #[serde(default)]
    pub node_id: Option<String>,
    #[serde(default)]
    pub host: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HeartbeatRequest {
    pub token: String,
    pub node_id: String,
    #[serde(default)]
    pub host: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MemoryAdd {
    pub fact: String,
    #[serde(default = "default_memory_category")]
    pub category: String,
    #[serde(default)]
    pub tags: Option<Vec<String>>,
}

fn default_memory_category() -> String {
    "general".into()
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MemoryUpdate {
    pub key: String,
    pub fact: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MemoryDelete {
    pub key: String,
}

// ── Bearer / role helpers ─────────────────────────────────────────────────

pub fn parse_bearer(authorization: Option<&str>) -> Option<&str> {
    let h = authorization?.trim();
    let lower = h.to_lowercase();
    if !lower.starts_with("bearer ") {
        return None;
    }
    let tok = h.get(7..)?.trim();
    if tok.is_empty() {
        None
    } else {
        Some(tok)
    }
}

#[derive(Debug, Error, PartialEq)]
pub enum AuthError {
    #[error("authentication required")]
    Unauthenticated,
    #[error("admin role required")]
    NotAdmin,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Admin,
    User,
}

impl Role {
    pub fn parse(s: &str) -> Option<Role> {
        match s {
            "admin" => Some(Role::Admin),
            "user" => Some(Role::User),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AuthUser {
    pub id: u64,
    pub username: String,
    pub role: Role,
}

pub fn require_user(user: Option<AuthUser>) -> Result<AuthUser, AuthError> {
    user.ok_or(AuthError::Unauthenticated)
}

pub fn require_admin(user: AuthUser) -> Result<AuthUser, AuthError> {
    if user.role == Role::Admin {
        Ok(user)
    } else {
        Err(AuthError::NotAdmin)
    }
}

// ── error response shape (matches FastAPI HTTPException JSON body) ────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ErrorBody {
    pub detail: String,
}

impl ErrorBody {
    pub fn new(detail: impl Into<String>) -> Self {
        Self { detail: detail.into() }
    }
}

pub fn error_status(err: &AuthError) -> u16 {
    match err {
        AuthError::Unauthenticated => 401,
        AuthError::NotAdmin => 403,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── parse_bearer ──────────────────────────────────────────────────────

    #[test]
    fn bearer_extracts_token() {
        assert_eq!(parse_bearer(Some("Bearer abc")), Some("abc"));
        assert_eq!(parse_bearer(Some("bearer xyz")), Some("xyz"));
    }

    #[test]
    fn bearer_rejects_other_schemes() {
        assert_eq!(parse_bearer(Some("Basic abc")), None);
        assert_eq!(parse_bearer(Some("abc")), None);
        assert_eq!(parse_bearer(None), None);
    }

    #[test]
    fn bearer_empty_token_is_none() {
        assert_eq!(parse_bearer(Some("Bearer ")), None);
    }

    // ── role/auth ─────────────────────────────────────────────────────────

    #[test]
    fn role_parse() {
        assert_eq!(Role::parse("admin"), Some(Role::Admin));
        assert_eq!(Role::parse("user"), Some(Role::User));
        assert_eq!(Role::parse("guest"), None);
    }

    #[test]
    fn require_user_when_present() {
        let u = AuthUser {
            id: 1,
            username: "a".into(),
            role: Role::User,
        };
        let r = require_user(Some(u.clone())).unwrap();
        assert_eq!(r.username, "a");
    }

    #[test]
    fn require_user_none_returns_401() {
        let err = require_user(None).unwrap_err();
        assert_eq!(err, AuthError::Unauthenticated);
        assert_eq!(error_status(&err), 401);
    }

    #[test]
    fn require_admin_passes_for_admin() {
        let u = AuthUser {
            id: 1,
            username: "a".into(),
            role: Role::Admin,
        };
        assert!(require_admin(u).is_ok());
    }

    #[test]
    fn require_admin_blocks_user_with_403() {
        let u = AuthUser {
            id: 1,
            username: "a".into(),
            role: Role::User,
        };
        let err = require_admin(u).unwrap_err();
        assert_eq!(err, AuthError::NotAdmin);
        assert_eq!(error_status(&err), 403);
    }

    // ── payload defaults ──────────────────────────────────────────────────

    #[test]
    fn chat_request_defaults() {
        let r: ChatRequest = serde_json::from_str(r#"{"query":"hi"}"#).unwrap();
        assert!(r.use_memory);
        assert!(!r.parallel);
    }

    #[test]
    fn create_user_default_role_user() {
        let r: CreateUserRequest =
            serde_json::from_str(r#"{"username":"a","password":"longpass1"}"#).unwrap();
        assert_eq!(r.role, "user");
    }

    #[test]
    fn memory_add_default_category() {
        let r: MemoryAdd = serde_json::from_str(r#"{"fact":"x"}"#).unwrap();
        assert_eq!(r.category, "general");
    }

    #[test]
    fn chat_response_serialises() {
        let r = ChatResponse {
            task_id: "t1".into(),
            status: "accepted".into(),
            websocket: "/ws/t1".into(),
        };
        let s = serde_json::to_string(&r).unwrap();
        assert_eq!(s, r#"{"task_id":"t1","status":"accepted","websocket":"/ws/t1"}"#);
    }

    #[test]
    fn token_validate_optional_fields() {
        let r: TokenValidateRequest = serde_json::from_str(r#"{"token":"t"}"#).unwrap();
        assert!(r.node_id.is_none());
        assert!(r.host.is_none());
    }

    // ── error body ────────────────────────────────────────────────────────

    #[test]
    fn error_body_shape() {
        let e = ErrorBody::new("nope");
        let s = serde_json::to_string(&e).unwrap();
        assert_eq!(s, r#"{"detail":"nope"}"#);
    }
}
