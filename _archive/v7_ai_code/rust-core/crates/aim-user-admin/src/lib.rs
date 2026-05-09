//! aim-user-admin — admin operations for the AIM hub.
//!
//! Port of `scripts/user_admin.py`. The Python module is a thin CLI on
//! top of `agents.auth`; here we reproduce the deterministic command
//! dispatch + first-user-auto-promotion + password-validation + table
//! formatting, with the actual user store hidden behind the
//! [`UserStoreOps`] trait.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

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
    pub fn as_str(&self) -> &'static str {
        match self {
            Role::Admin => "admin",
            Role::User => "user",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct User {
    pub id: u64,
    pub username: String,
    pub role: Role,
    pub email: Option<String>,
    pub disabled: bool,
    pub telegram_id: Option<i64>,
    pub created_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AuditEntry {
    pub ts: String,
    pub user_id: u64,
    pub action: String,
    pub target: Option<String>,
    pub ip: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct NodeRow {
    pub username: Option<String>,
    pub node_id: String,
    pub host: Option<String>,
    pub version: Option<String>,
    pub last_seen: String,
}

// ── errors ─────────────────────────────────────────────────────────────────

#[derive(Debug, Error, PartialEq)]
pub enum AdminError {
    #[error("user not found: {0}")]
    NotFound(String),
    #[error("password must be at least 8 characters")]
    PasswordTooShort,
    #[error("passwords do not match")]
    PasswordMismatch,
    #[error("invalid role: {0}")]
    InvalidRole(String),
}

// ── traits ─────────────────────────────────────────────────────────────────

pub trait UserStoreOps: Send + Sync {
    fn list_users(&self) -> Vec<User>;
    fn get_user(&self, id: u64) -> Option<User>;
    fn get_user_by_username(&self, username: &str) -> Option<User>;
    fn create_user(&self, username: &str, password: &str, role: Role, email: Option<&str>) -> User;
    fn set_password(&self, id: u64, password: &str);
    fn disable_user(&self, id: u64);
    fn enable_user(&self, id: u64);
    fn issue_api_token(&self, id: u64) -> String;
    fn revoke_api_token(&self, id: u64);
    fn create_link_code(&self, id: u64, ttl_min: u32) -> String;
    fn list_nodes(&self) -> Vec<NodeRow>;
    fn list_audit(&self, user_id: Option<u64>, limit: u32) -> Vec<AuditEntry>;
    fn audit(&self, id: u64, action: &str, target: Option<&str>);
}

// ── helpers ────────────────────────────────────────────────────────────────

pub fn validate_password(pw: &str) -> Result<(), AdminError> {
    if pw.len() < 8 {
        return Err(AdminError::PasswordTooShort);
    }
    Ok(())
}

pub fn passwords_match(a: &str, b: &str) -> Result<(), AdminError> {
    if a != b {
        return Err(AdminError::PasswordMismatch);
    }
    Ok(())
}

pub fn resolve_user(store: &dyn UserStoreOps, name_or_id: &str) -> Result<User, AdminError> {
    if let Ok(id) = name_or_id.parse::<u64>() {
        if let Some(u) = store.get_user(id) {
            return Ok(u);
        }
    } else if let Some(u) = store.get_user_by_username(name_or_id) {
        return Ok(u);
    }
    Err(AdminError::NotFound(name_or_id.to_string()))
}

/// Mirrors Python's "first user → auto-promoted to admin" logic.
pub fn effective_create_role(store: &dyn UserStoreOps, requested: Role) -> Role {
    if store.list_users().is_empty() && requested == Role::User {
        Role::Admin
    } else {
        requested
    }
}

// ── command implementations ───────────────────────────────────────────────

pub fn cmd_create(
    store: &dyn UserStoreOps,
    username: &str,
    password: &str,
    role: Role,
    email: Option<&str>,
) -> Result<User, AdminError> {
    validate_password(password)?;
    let role = effective_create_role(store, role);
    let u = store.create_user(username, password, role, email);
    store.audit(u.id, "user.create", Some(&u.username));
    Ok(u)
}

pub fn cmd_token(store: &dyn UserStoreOps, name_or_id: &str) -> Result<String, AdminError> {
    let u = resolve_user(store, name_or_id)?;
    let tok = store.issue_api_token(u.id);
    store.audit(u.id, "token.issue", None);
    Ok(tok)
}

pub fn cmd_revoke_token(store: &dyn UserStoreOps, name_or_id: &str) -> Result<(), AdminError> {
    let u = resolve_user(store, name_or_id)?;
    store.revoke_api_token(u.id);
    store.audit(u.id, "token.revoke", None);
    Ok(())
}

pub fn cmd_reset(
    store: &dyn UserStoreOps,
    name_or_id: &str,
    password: &str,
) -> Result<(), AdminError> {
    validate_password(password)?;
    let u = resolve_user(store, name_or_id)?;
    store.set_password(u.id, password);
    store.audit(u.id, "password.reset", None);
    Ok(())
}

pub fn cmd_disable(store: &dyn UserStoreOps, name_or_id: &str) -> Result<(), AdminError> {
    let u = resolve_user(store, name_or_id)?;
    store.disable_user(u.id);
    store.audit(u.id, "user.disable", None);
    Ok(())
}

pub fn cmd_enable(store: &dyn UserStoreOps, name_or_id: &str) -> Result<(), AdminError> {
    let u = resolve_user(store, name_or_id)?;
    store.enable_user(u.id);
    store.audit(u.id, "user.enable", None);
    Ok(())
}

pub fn cmd_link_code(
    store: &dyn UserStoreOps,
    name_or_id: &str,
    ttl_min: u32,
) -> Result<String, AdminError> {
    let u = resolve_user(store, name_or_id)?;
    Ok(store.create_link_code(u.id, ttl_min))
}

// ── formatters ────────────────────────────────────────────────────────────

pub fn format_user_table(rows: &[User]) -> String {
    if rows.is_empty() {
        return "(no users)".to_string();
    }
    let mut out = vec![format!(
        "{:>3}  {:<20} {:<6} {:>10} {:<8} CREATED",
        "ID", "USERNAME", "ROLE", "TG", "STATE"
    )];
    for u in rows {
        let state = if u.disabled { "DISABLED" } else { "active" };
        let tg = u
            .telegram_id
            .map(|id| id.to_string())
            .unwrap_or_else(|| "-".to_string());
        out.push(format!(
            "{:>3}  {:<20} {:<6} {:>10} {:<8} {}",
            u.id,
            u.username,
            u.role.as_str(),
            tg,
            state,
            u.created_at
        ));
    }
    out.join("\n")
}

pub fn format_node_table(rows: &[NodeRow]) -> String {
    if rows.is_empty() {
        return "(no nodes have phoned home yet)".to_string();
    }
    let mut out = vec![format!(
        "{:<20} {:<20} {:<25} {:<8} LAST_SEEN",
        "USER", "NODE_ID", "HOST", "VER"
    )];
    for n in rows {
        out.push(format!(
            "{:<20} {:<20} {:<25} {:<8} {}",
            n.username.clone().unwrap_or_else(|| "?".into()),
            n.node_id,
            n.host.clone().unwrap_or_else(|| "-".into()),
            n.version.clone().unwrap_or_else(|| "-".into()),
            n.last_seen
        ));
    }
    out.join("\n")
}

// ── reference in-memory implementation (for tests) ─────────────────────────

#[derive(Default)]
pub struct InMemUserStore {
    inner: parking_lot::Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    next_id: u64,
    users: Vec<User>,
    audit: Vec<AuditEntry>,
    tokens: std::collections::BTreeMap<u64, String>,
}

impl InMemUserStore {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn audit_log(&self) -> Vec<AuditEntry> {
        self.inner.lock().audit.clone()
    }
}

fn fixed_ts() -> String {
    let dt: DateTime<Utc> = Utc::now();
    dt.format("%Y-%m-%dT%H:%M:%S").to_string()
}

impl UserStoreOps for InMemUserStore {
    fn list_users(&self) -> Vec<User> {
        self.inner.lock().users.clone()
    }
    fn get_user(&self, id: u64) -> Option<User> {
        self.inner.lock().users.iter().find(|u| u.id == id).cloned()
    }
    fn get_user_by_username(&self, username: &str) -> Option<User> {
        self.inner
            .lock()
            .users
            .iter()
            .find(|u| u.username == username)
            .cloned()
    }
    fn create_user(&self, username: &str, _: &str, role: Role, email: Option<&str>) -> User {
        let mut g = self.inner.lock();
        g.next_id += 1;
        let u = User {
            id: g.next_id,
            username: username.to_string(),
            role,
            email: email.map(String::from),
            disabled: false,
            telegram_id: None,
            created_at: fixed_ts(),
        };
        g.users.push(u.clone());
        u
    }
    fn set_password(&self, _id: u64, _password: &str) {}
    fn disable_user(&self, id: u64) {
        let mut g = self.inner.lock();
        if let Some(u) = g.users.iter_mut().find(|u| u.id == id) {
            u.disabled = true;
        }
        g.tokens.remove(&id);
    }
    fn enable_user(&self, id: u64) {
        let mut g = self.inner.lock();
        if let Some(u) = g.users.iter_mut().find(|u| u.id == id) {
            u.disabled = false;
        }
    }
    fn issue_api_token(&self, id: u64) -> String {
        let mut g = self.inner.lock();
        let tok = format!("aim_tok_{}_{}", id, fixed_ts());
        g.tokens.insert(id, tok.clone());
        tok
    }
    fn revoke_api_token(&self, id: u64) {
        self.inner.lock().tokens.remove(&id);
    }
    fn create_link_code(&self, id: u64, _ttl: u32) -> String {
        // 6 digits derived deterministically from id for testability
        format!("{:06}", id * 111111 % 1_000_000)
    }
    fn list_nodes(&self) -> Vec<NodeRow> {
        Vec::new()
    }
    fn list_audit(&self, user_id: Option<u64>, limit: u32) -> Vec<AuditEntry> {
        let g = self.inner.lock();
        let filtered: Vec<AuditEntry> = g
            .audit
            .iter()
            .filter(|e| user_id.map(|id| e.user_id == id).unwrap_or(true))
            .cloned()
            .collect();
        let from = filtered.len().saturating_sub(limit as usize);
        filtered[from..].to_vec()
    }
    fn audit(&self, id: u64, action: &str, target: Option<&str>) {
        let mut g = self.inner.lock();
        g.audit.push(AuditEntry {
            ts: fixed_ts(),
            user_id: id,
            action: action.to_string(),
            target: target.map(String::from),
            ip: None,
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> InMemUserStore {
        InMemUserStore::new()
    }

    // ── role parsing ──────────────────────────────────────────────────────

    #[test]
    fn role_parse_known_values() {
        assert_eq!(Role::parse("admin"), Some(Role::Admin));
        assert_eq!(Role::parse("user"), Some(Role::User));
        assert_eq!(Role::parse("guest"), None);
    }

    // ── password validation ───────────────────────────────────────────────

    #[test]
    fn password_validation_min_length() {
        assert!(validate_password("12345678").is_ok());
        assert_eq!(
            validate_password("short").unwrap_err(),
            AdminError::PasswordTooShort
        );
    }

    #[test]
    fn passwords_match_check() {
        assert!(passwords_match("abc", "abc").is_ok());
        assert_eq!(
            passwords_match("a", "b").unwrap_err(),
            AdminError::PasswordMismatch
        );
    }

    // ── resolve user ──────────────────────────────────────────────────────

    #[test]
    fn resolve_user_by_id_and_username() {
        let s = store();
        let _ = cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        let u_by_name = resolve_user(&s, "alice").unwrap();
        let u_by_id = resolve_user(&s, &u_by_name.id.to_string()).unwrap();
        assert_eq!(u_by_name.id, u_by_id.id);
    }

    #[test]
    fn resolve_user_not_found() {
        let s = store();
        let err = resolve_user(&s, "ghost").unwrap_err();
        assert!(matches!(err, AdminError::NotFound(_)));
    }

    // ── auto-promote first user ───────────────────────────────────────────

    #[test]
    fn first_user_auto_promoted_to_admin() {
        let s = store();
        let role = effective_create_role(&s, Role::User);
        assert_eq!(role, Role::Admin);
    }

    #[test]
    fn second_user_keeps_role() {
        let s = store();
        cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        let role = effective_create_role(&s, Role::User);
        assert_eq!(role, Role::User);
    }

    #[test]
    fn first_user_explicit_admin_stays_admin() {
        let s = store();
        let role = effective_create_role(&s, Role::Admin);
        assert_eq!(role, Role::Admin);
    }

    // ── cmd_create ────────────────────────────────────────────────────────

    #[test]
    fn cmd_create_writes_user_and_audit_entry() {
        let s = store();
        let u = cmd_create(&s, "alice", "password123", Role::User, Some("a@x")).unwrap();
        assert_eq!(u.username, "alice");
        assert_eq!(u.role, Role::Admin); // auto-promoted
        let audit = s.audit_log();
        assert_eq!(audit.len(), 1);
        assert_eq!(audit[0].action, "user.create");
        assert_eq!(audit[0].target.as_deref(), Some("alice"));
    }

    #[test]
    fn cmd_create_rejects_short_password() {
        let s = store();
        let err = cmd_create(&s, "alice", "short", Role::User, None).unwrap_err();
        assert_eq!(err, AdminError::PasswordTooShort);
    }

    // ── token / disable / enable / link-code ─────────────────────────────

    #[test]
    fn cmd_token_issues_and_audits() {
        let s = store();
        cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        let tok = cmd_token(&s, "alice").unwrap();
        assert!(tok.starts_with("aim_tok_"));
        let kinds: Vec<String> = s.audit_log().iter().map(|e| e.action.clone()).collect();
        assert!(kinds.contains(&"token.issue".to_string()));
    }

    #[test]
    fn cmd_disable_records_audit() {
        let s = store();
        cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        cmd_disable(&s, "alice").unwrap();
        let kinds: Vec<String> = s.audit_log().iter().map(|e| e.action.clone()).collect();
        assert!(kinds.contains(&"user.disable".to_string()));
        let u = s.get_user_by_username("alice").unwrap();
        assert!(u.disabled);
    }

    #[test]
    fn cmd_link_code_six_digits() {
        let s = store();
        cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        let code = cmd_link_code(&s, "alice", 10).unwrap();
        assert_eq!(code.len(), 6);
        assert!(code.chars().all(|c| c.is_ascii_digit()));
    }

    // ── format_user_table ─────────────────────────────────────────────────

    #[test]
    fn user_table_empty_message() {
        assert_eq!(format_user_table(&[]), "(no users)");
    }

    #[test]
    fn user_table_renders_rows() {
        let s = store();
        cmd_create(&s, "alice", "password123", Role::User, None).unwrap();
        let rows = s.list_users();
        let table = format_user_table(&rows);
        assert!(table.contains("alice"));
        assert!(table.contains("admin")); // auto-promoted
        assert!(table.contains("active"));
    }

    #[test]
    fn node_table_empty_message() {
        assert_eq!(
            format_node_table(&[]),
            "(no nodes have phoned home yet)"
        );
    }
}
