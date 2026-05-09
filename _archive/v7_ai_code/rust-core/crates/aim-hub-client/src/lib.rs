//! aim-hub-client — node-side glue to the AIM Hub.
//!
//! A "node" is a per-user local AIM install. It runs the full stack locally
//! (own SQLite, own DeepSeek/Groq keys, own Patients/). The only thing it
//! asks the hub:
//!
//! 1. "Is this `AIM_USER_TOKEN` valid? Whose is it?" (on startup, then 24h cache)
//! 2. "Heartbeat: I am node <id> for user <X> at <host>" (best-effort, optional)
//!
//! LLM calls NEVER go through the hub. Patients NEVER go to the hub.
//!
//! Env vars (from `~/.aim_env`, cross-platform):
//! - `AIM_HUB_URL`        e.g. `https://hub.longevity.ge` (omit → local-only mode)
//! - `AIM_USER_TOKEN`     long-lived opaque token issued by hub admin
//! - `AIM_NODE_ID`        optional stable id; default: `<hostname>-<username>`
//! - `AIM_OFFLINE_GRACE`  hours the cached identity stays valid offline (default 168 = 7d)
//!
//! Public API (mirrors Python `agents/hub_client.py`):
//! - [`Client::current_user`]
//! - [`Client::validate`]
//! - [`Client::require_user`]
//! - [`Client::heartbeat`]
//! - [`Client::is_local_only`]

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Duration;
use thiserror::Error;

pub const NODE_VERSION: &str = "7.0";
pub const DEFAULT_OFFLINE_GRACE_H: f64 = 168.0;
pub const FRESH_CACHE_H: f64 = 24.0;
const HTTP_TIMEOUT_MS: u64 = 5_000;
const HEARTBEAT_TIMEOUT_MS: u64 = 3_000;

#[derive(Debug, Error)]
pub enum HubError {
    #[error("AIM_USER_TOKEN not set in ~/.aim_env")]
    NoToken,
    #[error("hub rejected AIM_USER_TOKEN")]
    Rejected,
    #[error("local-only mode (AIM_HUB_URL not set)")]
    LocalOnly,
    #[error("hub unreachable and no valid cache")]
    Unreachable,
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct User {
    pub id: i64,
    pub username: String,
    #[serde(default)]
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(default)]
    pub local_only: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Cache {
    token: String,
    user: User,
    cached_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ValidateResponse {
    ok: bool,
    #[serde(default)]
    user: Option<User>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct HeartbeatResponse {
    ok: bool,
}

/// Source of environment variables. The default reads from the real process
/// env, but tests can substitute a [`HashMapEnv`] for hermetic runs.
pub trait Env: Send + Sync {
    fn get(&self, key: &str) -> Option<String>;
}

#[derive(Debug, Default, Clone)]
pub struct ProcessEnv;

impl Env for ProcessEnv {
    fn get(&self, key: &str) -> Option<String> {
        std::env::var(key).ok()
    }
}

#[derive(Debug, Default, Clone)]
pub struct HashMapEnv {
    map: std::collections::HashMap<String, String>,
}

impl HashMapEnv {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set(mut self, k: impl Into<String>, v: impl Into<String>) -> Self {
        self.map.insert(k.into(), v.into());
        self
    }
}

impl Env for HashMapEnv {
    fn get(&self, key: &str) -> Option<String> {
        self.map.get(key).cloned()
    }
}

/// Cross-platform cache directory. Mirrors the Python implementation:
/// - Windows: `%LOCALAPPDATA%\aim\Cache`
/// - macOS:   `~/Library/Caches/aim`
/// - Linux:   `${XDG_CACHE_HOME:-~/.cache}/aim`
pub fn default_cache_dir() -> PathBuf {
    let home = dirs_home();
    if cfg!(target_os = "windows") {
        let base = std::env::var("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home.join("AppData").join("Local"));
        base.join("aim").join("Cache")
    } else if cfg!(target_os = "macos") {
        home.join("Library").join("Caches").join("aim")
    } else {
        let base = std::env::var("XDG_CACHE_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home.join(".cache"));
        base.join("aim")
    }
}

fn dirs_home() -> PathBuf {
    if let Ok(h) = std::env::var("HOME") {
        return PathBuf::from(h);
    }
    if let Ok(h) = std::env::var("USERPROFILE") {
        return PathBuf::from(h);
    }
    PathBuf::from(".")
}

/// Hub client. Construct with [`Client::new`] (default env + default cache dir)
/// or [`Client::with_env_and_cache`] for hermetic tests.
pub struct Client<E: Env = ProcessEnv> {
    env: E,
    cache_dir: PathBuf,
    http: reqwest::Client,
}

impl Client<ProcessEnv> {
    pub fn new() -> Self {
        Self::with_env_and_cache(ProcessEnv, default_cache_dir())
    }
}

impl Default for Client<ProcessEnv> {
    fn default() -> Self {
        Self::new()
    }
}

impl<E: Env> Client<E> {
    pub fn with_env_and_cache(env: E, cache_dir: PathBuf) -> Self {
        let http = reqwest::Client::builder()
            .user_agent(format!("aim-node/{NODE_VERSION}"))
            .timeout(Duration::from_millis(HTTP_TIMEOUT_MS))
            .build()
            .unwrap_or_else(|_| reqwest::Client::new());
        Self { env, cache_dir, http }
    }

    pub fn cache_file(&self) -> PathBuf {
        self.cache_dir.join("hub_identity.json")
    }

    fn env_str(&self, key: &str) -> String {
        self.env.get(key).unwrap_or_default().trim().to_string()
    }

    pub fn is_local_only(&self) -> bool {
        self.env_str("AIM_HUB_URL").is_empty()
    }

    pub fn node_id(&self) -> String {
        let nid = self.env_str("AIM_NODE_ID");
        if !nid.is_empty() {
            return nid;
        }
        let host = hostname();
        let user = self
            .env
            .get("USER")
            .or_else(|| self.env.get("USERNAME"))
            .unwrap_or_else(|| "anon".to_string());
        format!("{host}-{user}")
    }

    fn read_cache(&self) -> Option<Cache> {
        let f = self.cache_file();
        if !f.exists() {
            return None;
        }
        let raw = std::fs::read_to_string(&f).ok()?;
        serde_json::from_str(&raw).ok()
    }

    fn write_cache(&self, cache: &Cache) -> Result<(), HubError> {
        std::fs::create_dir_all(&self.cache_dir)?;
        let f = self.cache_file();
        let raw = serde_json::to_string_pretty(cache)?;
        std::fs::write(&f, raw)?;
        secure_perms(&f);
        Ok(())
    }

    pub fn clear_cache(&self) {
        let f = self.cache_file();
        if f.exists() {
            let _ = std::fs::remove_file(f);
        }
    }

    fn cache_fresh(cache: &Cache, max_age_h: f64) -> bool {
        let now = chrono::Utc::now().timestamp();
        let age = (now - cache.cached_at) as f64;
        age < max_age_h * 3600.0
    }

    fn grace_h(&self) -> f64 {
        let raw = self.env_str("AIM_OFFLINE_GRACE");
        if raw.is_empty() {
            DEFAULT_OFFLINE_GRACE_H
        } else {
            raw.parse().unwrap_or(DEFAULT_OFFLINE_GRACE_H)
        }
    }

    fn hub_url(&self, path: &str) -> String {
        let base = self.env_str("AIM_HUB_URL");
        let base = base.trim_end_matches('/');
        format!("{base}{path}")
    }

    /// Round-trip to the hub if cache is missing or `force=true`. Returns
    /// `Some(user)` on success, `None` if hub said "no" or no token, or the
    /// cached user if the hub is unreachable but the cache is within
    /// `AIM_OFFLINE_GRACE`.
    pub async fn validate(&self, force: bool) -> Option<User> {
        if self.is_local_only() {
            return None;
        }
        let token = self.env_str("AIM_USER_TOKEN");
        if token.is_empty() {
            tracing::error!("AIM_USER_TOKEN not set in ~/.aim_env");
            return None;
        }
        let grace_h = self.grace_h();

        let cache = self.read_cache();
        if let Some(c) = &cache {
            if !force && Self::cache_fresh(c, FRESH_CACHE_H) && c.token == token {
                return Some(c.user.clone());
            }
        }

        let body = serde_json::json!({
            "token": token,
            "node_id": self.node_id(),
            "host": hostname(),
            "version": NODE_VERSION,
        });

        let resp = self
            .http
            .post(self.hub_url("/api/auth/validate-token"))
            .json(&body)
            .send()
            .await;

        match resp {
            Ok(r) if r.status().is_success() => {
                let parsed: Result<ValidateResponse, _> = r.json().await;
                match parsed {
                    Ok(v) if v.ok => {
                        if let Some(user) = v.user {
                            let new_cache = Cache {
                                token: token.clone(),
                                user: user.clone(),
                                cached_at: chrono::Utc::now().timestamp(),
                            };
                            if let Err(e) = self.write_cache(&new_cache) {
                                tracing::warn!("could not write hub cache: {e}");
                            }
                            return Some(user);
                        }
                        None
                    }
                    Ok(_) => {
                        tracing::error!("hub rejected AIM_USER_TOKEN");
                        self.clear_cache();
                        None
                    }
                    Err(e) => {
                        tracing::warn!("hub returned malformed json: {e}");
                        self.fall_back_to_cache(cache, &token, grace_h)
                    }
                }
            }
            Ok(r) => {
                tracing::warn!("hub returned status {}", r.status());
                self.fall_back_to_cache(cache, &token, grace_h)
            }
            Err(e) => {
                tracing::warn!("hub unreachable: {e}");
                self.fall_back_to_cache(cache, &token, grace_h)
            }
        }
    }

    fn fall_back_to_cache(&self, cache: Option<Cache>, token: &str, grace_h: f64) -> Option<User> {
        let c = cache?;
        if c.token == token && Self::cache_fresh(&c, grace_h) {
            tracing::warn!("hub unreachable; using cached identity (offline mode)");
            Some(c.user)
        } else {
            None
        }
    }

    /// Cheap path: returns cached user if fresh, otherwise validates.
    pub async fn current_user(&self) -> Option<User> {
        if self.is_local_only() {
            return None;
        }
        if let Some(c) = self.read_cache() {
            if Self::cache_fresh(&c, FRESH_CACHE_H) {
                return Some(c.user);
            }
        }
        self.validate(false).await
    }

    /// For CLI/GUI/Telegram entry points. Returns synthetic `local` user
    /// in local-only mode, or `Err` if multi-user is configured but auth fails.
    pub async fn require_user(&self) -> Result<User, HubError> {
        if self.is_local_only() {
            return Ok(User {
                id: 0,
                username: "local".into(),
                role: "user".into(),
                email: None,
                display_name: None,
                local_only: true,
            });
        }
        match self.validate(false).await {
            Some(u) => Ok(u),
            None => {
                let token = self.env_str("AIM_USER_TOKEN");
                if token.is_empty() {
                    Err(HubError::NoToken)
                } else {
                    Err(HubError::Unreachable)
                }
            }
        }
    }

    /// Best-effort heartbeat. Never blocks AIM operation.
    pub async fn heartbeat(&self) -> bool {
        if self.is_local_only() {
            return false;
        }
        let token = self.env_str("AIM_USER_TOKEN");
        if token.is_empty() {
            return false;
        }
        let body = serde_json::json!({
            "token": token,
            "node_id": self.node_id(),
            "host": hostname(),
            "version": NODE_VERSION,
        });

        let r = self
            .http
            .post(self.hub_url("/api/nodes/heartbeat"))
            .timeout(Duration::from_millis(HEARTBEAT_TIMEOUT_MS))
            .json(&body)
            .send()
            .await;

        match r {
            Ok(resp) if resp.status().is_success() => resp
                .json::<HeartbeatResponse>()
                .await
                .map(|h| h.ok)
                .unwrap_or(false),
            _ => false,
        }
    }
}

fn hostname() -> String {
    if let Ok(h) = std::env::var("HOSTNAME") {
        if !h.trim().is_empty() {
            return h;
        }
    }
    if let Ok(h) = std::env::var("COMPUTERNAME") {
        if !h.trim().is_empty() {
            return h;
        }
    }
    if let Ok(out) = std::process::Command::new("hostname").output() {
        let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if !s.is_empty() {
            return s;
        }
    }
    "unknown".into()
}

#[cfg(unix)]
fn secure_perms(p: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn secure_perms(_p: &Path) {}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn client_with(env: HashMapEnv, dir: &TempDir) -> Client<HashMapEnv> {
        Client::with_env_and_cache(env, dir.path().to_path_buf())
    }

    #[test]
    fn local_only_when_no_hub_url() {
        let dir = TempDir::new().unwrap();
        let c = client_with(HashMapEnv::new(), &dir);
        assert!(c.is_local_only());
    }

    #[test]
    fn not_local_when_hub_url_set() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new().set("AIM_HUB_URL", "https://hub.example.com");
        let c = client_with(env, &dir);
        assert!(!c.is_local_only());
    }

    #[test]
    fn node_id_uses_explicit_value() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new().set("AIM_NODE_ID", "lab-pi-01");
        let c = client_with(env, &dir);
        assert_eq!(c.node_id(), "lab-pi-01");
    }

    #[test]
    fn node_id_falls_back_to_host_user() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new().set("USER", "jaba");
        let c = client_with(env, &dir);
        let id = c.node_id();
        assert!(id.ends_with("-jaba"), "got {id}");
    }

    #[test]
    fn cache_round_trip() {
        let dir = TempDir::new().unwrap();
        let c = client_with(HashMapEnv::new(), &dir);
        let cache = Cache {
            token: "tok-A".into(),
            user: User {
                id: 7,
                username: "alice".into(),
                role: "admin".into(),
                email: Some("a@x".into()),
                display_name: None,
                local_only: false,
            },
            cached_at: chrono::Utc::now().timestamp(),
        };
        c.write_cache(&cache).unwrap();
        let back = c.read_cache().expect("present");
        assert_eq!(back.token, "tok-A");
        assert_eq!(back.user.username, "alice");
    }

    #[test]
    fn cache_fresh_window() {
        let now = chrono::Utc::now().timestamp();
        let fresh = Cache {
            token: "t".into(),
            user: User {
                id: 1,
                username: "u".into(),
                role: "".into(),
                email: None,
                display_name: None,
                local_only: false,
            },
            cached_at: now,
        };
        assert!(Client::<ProcessEnv>::cache_fresh(&fresh, 24.0));
        let stale = Cache {
            cached_at: now - 25 * 3600,
            ..fresh
        };
        assert!(!Client::<ProcessEnv>::cache_fresh(&stale, 24.0));
        assert!(Client::<ProcessEnv>::cache_fresh(&stale, 168.0));
    }

    #[tokio::test]
    async fn validate_returns_none_in_local_only() {
        let dir = TempDir::new().unwrap();
        let c = client_with(HashMapEnv::new(), &dir);
        assert!(c.validate(false).await.is_none());
    }

    #[tokio::test]
    async fn require_user_returns_synthetic_local() {
        let dir = TempDir::new().unwrap();
        let c = client_with(HashMapEnv::new(), &dir);
        let u = c.require_user().await.unwrap();
        assert!(u.local_only);
        assert_eq!(u.username, "local");
        assert_eq!(u.id, 0);
    }

    #[tokio::test]
    async fn require_user_errs_without_token() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new().set("AIM_HUB_URL", "https://hub.example.com");
        let c = client_with(env, &dir);
        let err = c.require_user().await.unwrap_err();
        assert!(matches!(err, HubError::NoToken));
    }

    #[tokio::test]
    async fn current_user_uses_fresh_cache_without_network() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new()
            .set("AIM_HUB_URL", "https://hub.invalid.localhost")
            .set("AIM_USER_TOKEN", "tok-X");
        let c = client_with(env, &dir);
        let cache = Cache {
            token: "tok-X".into(),
            user: User {
                id: 42,
                username: "frank".into(),
                role: "user".into(),
                email: None,
                display_name: None,
                local_only: false,
            },
            cached_at: chrono::Utc::now().timestamp(),
        };
        c.write_cache(&cache).unwrap();
        let u = c.current_user().await.expect("cache hit");
        assert_eq!(u.username, "frank");
    }

    #[tokio::test]
    async fn validate_falls_back_to_cache_when_hub_unreachable() {
        let dir = TempDir::new().unwrap();
        let env = HashMapEnv::new()
            .set("AIM_HUB_URL", "http://127.0.0.1:1") // refuses connections
            .set("AIM_USER_TOKEN", "tok-Y");
        let c = client_with(env, &dir);
        let cache = Cache {
            token: "tok-Y".into(),
            user: User {
                id: 99,
                username: "ghost".into(),
                role: "user".into(),
                email: None,
                display_name: None,
                local_only: false,
            },
            // 30h ago — outside 24h fresh window, inside default 168h grace
            cached_at: chrono::Utc::now().timestamp() - 30 * 3600,
        };
        c.write_cache(&cache).unwrap();
        let u = c.validate(true).await.expect("offline grace");
        assert_eq!(u.username, "ghost");
    }

    #[tokio::test]
    async fn heartbeat_false_in_local_only() {
        let dir = TempDir::new().unwrap();
        let c = client_with(HashMapEnv::new(), &dir);
        assert!(!c.heartbeat().await);
    }
}
