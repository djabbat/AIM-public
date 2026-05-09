//! aim-permission — interactive permission broker (G3).
//!
//! Port of `agents/permission.py`. The kernel's `L_CONSENT` is a hard
//! binary: the side-effect runs only when `context.user_confirmed == true`.
//! That makes it impossible for AIM to **ask** at the moment of the
//! side-effect — it just refuses. This crate adds an opt-in interactive
//! layer on top:
//!
//! 1. Hard env overrides — `AIM_AUTO_CONSENT=1` grants everything,
//!    `AIM_NONINTERACTIVE=1` denies everything.
//! 2. Cache `(action_type, scope) → granted` with TTL — repeated similar
//!    actions in one session don't spam the user.
//! 3. Channel resolution — TUI / Telegram / custom impl via [`Channel`]
//!    trait. Tests inject [`StubChannel`].
//! 4. Audit log — every decision written to a sink (JSONL by default).
//!
//! The kernel's `evaluate_l_consent` integration is opt-in and orthogonal
//! to this crate. This crate just resolves a single permission request.

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PermissionError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("channel: {0}")]
    Channel(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Decision {
    pub granted: bool,
    pub reason: String,
    pub cached: bool,
    /// One of: `auto_consent`, `noninteractive_deny`, `tui`, `tg`, `cache`,
    /// `user_confirmed_flag`, `timeout_deny`, `fallback_block`, or a
    /// custom channel name.
    pub via: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Request<'a> {
    pub action_type: &'a str,
    pub scope: &'a str,
    pub preview: &'a str,
    pub blast_radius: &'a str,
    pub ttl_minutes: u32,
}

impl<'a> Request<'a> {
    pub fn new(action_type: &'a str, scope: &'a str) -> Self {
        Self {
            action_type,
            scope,
            preview: "",
            blast_radius: "external",
            ttl_minutes: 15,
        }
    }
    pub fn preview(mut self, p: &'a str) -> Self {
        self.preview = p;
        self
    }
    pub fn blast_radius(mut self, b: &'a str) -> Self {
        self.blast_radius = b;
        self
    }
    pub fn ttl_minutes(mut self, t: u32) -> Self {
        self.ttl_minutes = t;
        self
    }
}

/// Pluggable env source. Production reads `std::env`; tests inject a
/// [`HashMapEnv`] for hermetic runs.
pub trait EnvSource: Send + Sync {
    fn get(&self, key: &str) -> Option<String>;
}

#[derive(Debug, Default)]
pub struct ProcessEnv;

impl EnvSource for ProcessEnv {
    fn get(&self, key: &str) -> Option<String> {
        std::env::var(key).ok()
    }
}

#[derive(Debug, Default, Clone)]
pub struct HashMapEnv {
    map: HashMap<String, String>,
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

impl EnvSource for HashMapEnv {
    fn get(&self, key: &str) -> Option<String> {
        self.map.get(key).cloned()
    }
}

/// Pluggable clock — testable via [`ManualClock`].
pub trait Clock: Send + Sync {
    fn now_secs(&self) -> f64;
}

#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_secs(&self) -> f64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0)
    }
}

#[derive(Debug, Default)]
pub struct ManualClock {
    state: Mutex<f64>,
}

impl ManualClock {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set(&self, t: f64) {
        *self.state.lock() = t;
    }
    pub fn advance(&self, delta: f64) {
        *self.state.lock() += delta;
    }
}

impl Clock for ManualClock {
    fn now_secs(&self) -> f64 {
        *self.state.lock()
    }
}

/// One-of the permission resolution channels. Real impls: TUI prompt,
/// Telegram broker, custom GUI. Tests: [`StubChannel`].
pub trait Channel: Send + Sync {
    fn name(&self) -> &str;
    fn ask(&self, req: &Request<'_>) -> Result<(bool, String), PermissionError>;
}

/// Default-deny channel that never prompts. Used as fallback when no
/// channel is registered or to force deny in non-interactive contexts.
pub struct DenyChannel;
impl Channel for DenyChannel {
    fn name(&self) -> &str {
        "fallback_block"
    }
    fn ask(&self, _req: &Request<'_>) -> Result<(bool, String), PermissionError> {
        Ok((false, "no channel registered → deny".to_string()))
    }
}

/// Test-friendly channel with a script of (granted, reason) responses.
pub struct StubChannel {
    pub name: String,
    pub queue: Mutex<Vec<(bool, String)>>,
    pub call_count: Mutex<usize>,
}

impl StubChannel {
    pub fn new(name: impl Into<String>, responses: Vec<(bool, &str)>) -> Self {
        Self {
            name: name.into(),
            queue: Mutex::new(
                responses
                    .into_iter()
                    .map(|(g, r)| (g, r.to_string()))
                    .collect(),
            ),
            call_count: Mutex::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        *self.call_count.lock()
    }
}

impl Channel for StubChannel {
    fn name(&self) -> &str {
        &self.name
    }
    fn ask(&self, _req: &Request<'_>) -> Result<(bool, String), PermissionError> {
        *self.call_count.lock() += 1;
        let mut q = self.queue.lock();
        if q.is_empty() {
            return Ok((false, "stub queue exhausted → deny".to_string()));
        }
        Ok(q.remove(0))
    }
}

/// Audit sink. JSONL appender by default; tests use [`MemoryAudit`].
pub trait Audit: Send + Sync {
    fn record(
        &self,
        ts: f64,
        action_type: &str,
        scope: &str,
        decision: &Decision,
    ) -> Result<(), PermissionError>;
}

pub struct JsonlAudit {
    path: PathBuf,
}

impl JsonlAudit {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl Audit for JsonlAudit {
    fn record(
        &self,
        ts: f64,
        action_type: &str,
        scope: &str,
        decision: &Decision,
    ) -> Result<(), PermissionError> {
        if let Some(parent) = self.path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let entry = serde_json::json!({
            "ts": ts,
            "action_type": action_type,
            "scope": scope,
            "granted": decision.granted,
            "via": decision.via,
            "reason": decision.reason,
        });
        let line = serde_json::to_string(&entry)? + "\n";
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        std::io::Write::write_all(&mut f, line.as_bytes())?;
        Ok(())
    }
}

#[derive(Debug, Default, Clone)]
pub struct MemoryAudit {
    pub entries: Arc<Mutex<Vec<(f64, String, String, Decision)>>>,
}

impl MemoryAudit {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn snapshot(&self) -> Vec<(f64, String, String, Decision)> {
        self.entries.lock().clone()
    }
}

impl Audit for MemoryAudit {
    fn record(
        &self,
        ts: f64,
        action_type: &str,
        scope: &str,
        decision: &Decision,
    ) -> Result<(), PermissionError> {
        self.entries.lock().push((
            ts,
            action_type.to_string(),
            scope.to_string(),
            decision.clone(),
        ));
        Ok(())
    }
}

#[derive(Debug, Default)]
struct Cache {
    map: HashMap<(String, String), (bool, f64)>,
}

pub struct Broker {
    env: Arc<dyn EnvSource>,
    clock: Arc<dyn Clock>,
    audit: Arc<dyn Audit>,
    channels: HashMap<String, Arc<dyn Channel>>,
    cache: Mutex<Cache>,
}

pub struct BrokerBuilder {
    env: Arc<dyn EnvSource>,
    clock: Arc<dyn Clock>,
    audit: Arc<dyn Audit>,
    channels: HashMap<String, Arc<dyn Channel>>,
}

impl BrokerBuilder {
    pub fn new() -> Self {
        Self {
            env: Arc::new(ProcessEnv),
            clock: Arc::new(SystemClock),
            audit: Arc::new(MemoryAudit::default()),
            channels: HashMap::new(),
        }
    }

    pub fn env(mut self, e: Arc<dyn EnvSource>) -> Self {
        self.env = e;
        self
    }
    pub fn clock(mut self, c: Arc<dyn Clock>) -> Self {
        self.clock = c;
        self
    }
    pub fn audit(mut self, a: Arc<dyn Audit>) -> Self {
        self.audit = a;
        self
    }
    pub fn channel(mut self, c: Arc<dyn Channel>) -> Self {
        self.channels.insert(c.name().to_string(), c);
        self
    }
    pub fn build(self) -> Broker {
        Broker {
            env: self.env,
            clock: self.clock,
            audit: self.audit,
            channels: self.channels,
            cache: Mutex::new(Cache::default()),
        }
    }
}

impl Default for BrokerBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl Broker {
    /// Resolve a permission request: env overrides → cache → channel.
    pub fn request(&self, req: &Request<'_>) -> Result<Decision, PermissionError> {
        let ttl_secs = (req.ttl_minutes.max(1) as f64) * 60.0;

        // 1. Hard overrides
        if self.env.get("AIM_AUTO_CONSENT").as_deref() == Some("1") {
            return self.finalise(
                req,
                Decision {
                    granted: true,
                    reason: "AIM_AUTO_CONSENT=1".into(),
                    cached: false,
                    via: "auto_consent".into(),
                },
            );
        }
        if self.env.get("AIM_NONINTERACTIVE").as_deref() == Some("1") {
            return self.finalise(
                req,
                Decision {
                    granted: false,
                    reason: "AIM_NONINTERACTIVE=1 → deny".into(),
                    cached: false,
                    via: "noninteractive_deny".into(),
                },
            );
        }

        // 2. Cache
        let key = (req.action_type.to_string(), req.scope.to_string());
        let now = self.clock.now_secs();
        {
            let mut g = self.cache.lock();
            if let Some((granted, expires)) = g.map.get(&key).copied() {
                if now < expires {
                    return self.finalise(
                        req,
                        Decision {
                            granted,
                            reason: "cached".into(),
                            cached: true,
                            via: "cache".into(),
                        },
                    );
                }
                g.map.remove(&key);
            }
        }

        // 3. Channel
        let chan_name = self
            .env
            .get("AIM_PERMISSION_CHANNEL")
            .unwrap_or_else(|| "tui".to_string())
            .to_lowercase();
        let chan = self
            .channels
            .get(&chan_name)
            .cloned()
            .unwrap_or_else(|| Arc::new(DenyChannel) as Arc<dyn Channel>);
        let (granted, reason) = match chan.ask(req) {
            Ok(t) => t,
            Err(e) => (false, format!("channel error: {e}")),
        };

        // Cache positive grants and "always-X" decisions for the TTL.
        let should_cache = granted || reason.contains("always");
        if should_cache {
            let mut g = self.cache.lock();
            g.map.insert(key, (granted, now + ttl_secs));
        }
        let via = if reason.starts_with("channel error") {
            "fallback_block".to_string()
        } else if self.channels.contains_key(&chan_name) {
            chan.name().to_string()
        } else {
            "fallback_block".to_string()
        };
        self.finalise(
            req,
            Decision {
                granted,
                reason,
                cached: false,
                via,
            },
        )
    }

    fn finalise(&self, req: &Request<'_>, d: Decision) -> Result<Decision, PermissionError> {
        self.audit
            .record(self.clock.now_secs(), req.action_type, req.scope, &d)?;
        Ok(d)
    }

    /// Drop all cached decisions.
    pub fn clear_cache(&self) {
        self.cache.lock().map.clear();
    }
}

pub fn default_audit_path() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".cache").join("aim").join("permission_log.jsonl")
}

pub fn default_jsonl_audit() -> Arc<dyn Audit> {
    Arc::new(JsonlAudit::new(default_audit_path()))
}

#[allow(dead_code)]
fn _unused_path_check(_p: &Path) {}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make(env: HashMapEnv, channel: Arc<dyn Channel>) -> (Arc<MemoryAudit>, Arc<ManualClock>, Broker) {
        let audit = Arc::new(MemoryAudit::new());
        let clock = Arc::new(ManualClock::new());
        let broker = BrokerBuilder::new()
            .env(Arc::new(env))
            .clock(clock.clone())
            .audit(audit.clone())
            .channel(channel)
            .build();
        (audit, clock, broker)
    }

    #[test]
    fn auto_consent_grants_without_channel() {
        let env = HashMapEnv::new().set("AIM_AUTO_CONSENT", "1");
        let stub = Arc::new(StubChannel::new("tui", vec![]));
        let (audit, clock, b) = make(env, stub.clone());
        clock.set(100.0);
        let d = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(d.granted);
        assert_eq!(d.via, "auto_consent");
        assert_eq!(stub.calls(), 0, "channel must not be hit");
        assert_eq!(audit.snapshot().len(), 1);
    }

    #[test]
    fn noninteractive_denies_without_channel() {
        let env = HashMapEnv::new().set("AIM_NONINTERACTIVE", "1");
        let stub = Arc::new(StubChannel::new("tui", vec![(true, "would-grant")]));
        let (_audit, _clock, b) = make(env, stub.clone());
        let d = b.request(&Request::new("git_push_public", "djabbat/AIM")).unwrap();
        assert!(!d.granted);
        assert_eq!(d.via, "noninteractive_deny");
        assert_eq!(stub.calls(), 0);
    }

    #[test]
    fn channel_consulted_on_first_call() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new("tui", vec![(true, "tui allow")]));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        let d = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(d.granted);
        assert_eq!(d.via, "tui");
        assert_eq!(stub.calls(), 1);
    }

    #[test]
    fn positive_grant_cached_within_ttl() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new("tui", vec![(true, "tui allow")]));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        b.request(&Request::new("email_send", "to:x").ttl_minutes(15)).unwrap();
        clock.set(60.0);
        let d2 = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(d2.granted);
        assert!(d2.cached);
        assert_eq!(d2.via, "cache");
        assert_eq!(stub.calls(), 1, "channel hit only once");
    }

    #[test]
    fn deny_is_not_cached_user_can_retry() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![(false, "tui deny"), (true, "tui allow")],
        ));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        let d1 = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(!d1.granted);
        let d2 = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(d2.granted, "second prompt must hit channel again");
        assert!(!d2.cached);
        assert_eq!(stub.calls(), 2);
    }

    #[test]
    fn always_deny_is_cached() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![(false, "tui always-deny (15m)"), (true, "tui allow")],
        ));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        let d1 = b.request(&Request::new("email_send", "to:x").ttl_minutes(15)).unwrap();
        assert!(!d1.granted);
        clock.set(120.0);
        let d2 = b.request(&Request::new("email_send", "to:x")).unwrap();
        assert!(!d2.granted);
        assert!(d2.cached, "always-deny must persist");
        assert_eq!(stub.calls(), 1);
    }

    #[test]
    fn cache_expires_after_ttl() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![(true, "tui allow"), (false, "tui deny later")],
        ));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        b.request(&Request::new("a", "b").ttl_minutes(1)).unwrap();
        clock.set(120.0); // 2 minutes — past TTL
        let d2 = b.request(&Request::new("a", "b")).unwrap();
        assert!(!d2.granted);
        assert!(!d2.cached);
        assert_eq!(stub.calls(), 2);
    }

    #[test]
    fn unknown_channel_falls_back_to_deny() {
        let env = HashMapEnv::new().set("AIM_PERMISSION_CHANNEL", "magicians");
        let stub = Arc::new(StubChannel::new("tui", vec![(true, "would-grant")]));
        let (_audit, _clock, b) = make(env, stub.clone());
        let d = b.request(&Request::new("a", "b")).unwrap();
        assert!(!d.granted);
        assert_eq!(d.via, "fallback_block");
        assert_eq!(stub.calls(), 0);
    }

    #[test]
    fn audit_records_every_decision() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new("tui", vec![(true, "tui allow")]));
        let (audit, clock, b) = make(env, stub.clone());
        clock.set(42.0);
        b.request(&Request::new("send_telegram", "channel-X")).unwrap();
        let snap = audit.snapshot();
        assert_eq!(snap.len(), 1);
        assert_eq!(snap[0].1, "send_telegram");
        assert_eq!(snap[0].2, "channel-X");
        assert!(snap[0].3.granted);
        assert_eq!(snap[0].0, 42.0);
    }

    #[test]
    fn clear_cache_drops_state() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![(true, "tui allow"), (false, "tui deny")],
        ));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        b.request(&Request::new("a", "b")).unwrap();
        b.clear_cache();
        let d2 = b.request(&Request::new("a", "b")).unwrap();
        assert!(!d2.granted, "after clear_cache the channel must be re-asked");
        assert_eq!(stub.calls(), 2);
    }

    #[test]
    fn jsonl_audit_writes_one_line_per_call() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("audit.jsonl");
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![(true, "tui allow"), (false, "tui deny")],
        ));
        let audit: Arc<dyn Audit> = Arc::new(JsonlAudit::new(path.clone()));
        let clock = Arc::new(ManualClock::new());
        let broker = BrokerBuilder::new()
            .env(Arc::new(env))
            .clock(clock.clone())
            .audit(audit.clone())
            .channel(stub.clone())
            .build();
        clock.set(1.0);
        broker.request(&Request::new("a", "b")).unwrap();
        clock.set(2.0);
        broker.request(&Request::new("c", "d")).unwrap();
        let body = std::fs::read_to_string(&path).unwrap();
        assert_eq!(body.lines().count(), 2);
        assert!(body.contains("\"action_type\":\"a\""));
        assert!(body.contains("\"action_type\":\"c\""));
    }

    #[test]
    fn cache_keys_are_per_action_and_scope() {
        let env = HashMapEnv::new();
        let stub = Arc::new(StubChannel::new(
            "tui",
            vec![
                (true, "tui allow A"),
                (false, "tui deny B"),
                (true, "tui allow A again"),
            ],
        ));
        let (_audit, clock, b) = make(env, stub.clone());
        clock.set(0.0);
        let d1 = b.request(&Request::new("send", "alice")).unwrap();
        let d2 = b.request(&Request::new("send", "bob")).unwrap();
        assert!(d1.granted);
        assert!(!d2.granted);
        // Re-ask alice: cached
        let d3 = b.request(&Request::new("send", "alice")).unwrap();
        assert!(d3.cached);
        assert_eq!(stub.calls(), 2, "two distinct (action,scope) pairs");
    }

    #[test]
    fn channel_error_blocks_with_fallback_via() {
        struct ErrChannel;
        impl Channel for ErrChannel {
            fn name(&self) -> &str {
                "tui"
            }
            fn ask(&self, _req: &Request<'_>) -> Result<(bool, String), PermissionError> {
                Err(PermissionError::Channel("simulated".into()))
            }
        }
        let env = HashMapEnv::new();
        let audit = Arc::new(MemoryAudit::new());
        let clock = Arc::new(ManualClock::new());
        let broker = BrokerBuilder::new()
            .env(Arc::new(env))
            .clock(clock.clone())
            .audit(audit.clone())
            .channel(Arc::new(ErrChannel))
            .build();
        let d = broker.request(&Request::new("a", "b")).unwrap();
        assert!(!d.granted);
        assert_eq!(d.via, "fallback_block");
    }
}
