//! aim-hooks — lightweight event registry inspired by Personal AI
//! Infrastructure (Miessler).
//!
//! Port of `agents/hooks.py`. Lets components subscribe to AIM events
//! without modifying core code.
//!
//! Events (verbatim from Python):
//!   • `on_lab_critical` — lab interpretation found a critical value
//!   • `on_kernel_decision` — kernel.decide() picked an alternative
//!   • `on_session_end` — session closed (hot→warm memory migration)
//!   • `on_intake_pdf` — new file landed in `Patients/INBOX/`
//!   • `on_pre_commit` — git pre-commit (kernel sync, AI_LOG flush)
//!
//! Semantics matched 1:1 with Python:
//!   • handlers run synchronously in registration order
//!   • exception in a handler is logged + recorded as `None`, doesn't
//!     break the chain
//!   • `register` is idempotent (same handler not added twice)
//!   • unknown event names → registration errors / fire warns + returns []

use std::collections::HashMap;
use std::sync::Arc;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HooksError {
    #[error("unknown hook: {0}")]
    UnknownHook(String),
}

pub type Result<T> = std::result::Result<T, HooksError>;

// ── known events ────────────────────────────────────────────────────────────

pub const HOOK_LAB_CRITICAL: &str = "on_lab_critical";
pub const HOOK_KERNEL_DECISION: &str = "on_kernel_decision";
pub const HOOK_SESSION_END: &str = "on_session_end";
pub const HOOK_INTAKE_PDF: &str = "on_intake_pdf";
pub const HOOK_PRE_COMMIT: &str = "on_pre_commit";

pub fn known_hooks() -> &'static [&'static str] {
    &[
        HOOK_LAB_CRITICAL,
        HOOK_KERNEL_DECISION,
        HOOK_SESSION_END,
        HOOK_INTAKE_PDF,
        HOOK_PRE_COMMIT,
    ]
}

pub fn is_known(event: &str) -> bool {
    known_hooks().iter().any(|&e| e == event)
}

// ── handler ─────────────────────────────────────────────────────────────────

pub type Payload = serde_json::Value;
pub type HandlerResult = std::result::Result<Payload, String>;

pub trait Handler: Send + Sync + 'static {
    fn name(&self) -> &str;
    fn call(&self, payload: &Payload) -> HandlerResult;
}

/// Function-pointer adapter: a unique `name`, plus a closure.
pub struct FnHandler {
    pub name: String,
    pub func: Arc<dyn Fn(&Payload) -> HandlerResult + Send + Sync>,
}

impl FnHandler {
    pub fn new(
        name: impl Into<String>,
        func: impl Fn(&Payload) -> HandlerResult + Send + Sync + 'static,
    ) -> Self {
        Self {
            name: name.into(),
            func: Arc::new(func),
        }
    }
}

impl Handler for FnHandler {
    fn name(&self) -> &str {
        &self.name
    }
    fn call(&self, payload: &Payload) -> HandlerResult {
        (self.func)(payload)
    }
}

// ── registry ────────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct Registry {
    handlers: Mutex<HashMap<String, Vec<Arc<dyn Handler>>>>,
}

impl Registry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a handler. Returns `Ok(true)` if newly added,
    /// `Ok(false)` on idempotent skip (same handler name already
    /// registered for this event), `Err(UnknownHook)` if `event` is not
    /// in [`known_hooks`].
    pub fn register(&self, event: &str, h: Arc<dyn Handler>) -> Result<bool> {
        if !is_known(event) {
            return Err(HooksError::UnknownHook(event.into()));
        }
        let mut map = self.handlers.lock();
        let entry = map.entry(event.to_string()).or_default();
        if entry.iter().any(|x| x.name() == h.name()) {
            return Ok(false);
        }
        entry.push(h);
        Ok(true)
    }

    /// Convenience: register an [`FnHandler`].
    pub fn register_fn(
        &self,
        event: &str,
        name: impl Into<String>,
        func: impl Fn(&Payload) -> HandlerResult + Send + Sync + 'static,
    ) -> Result<bool> {
        self.register(event, Arc::new(FnHandler::new(name, func)))
    }

    /// Remove a handler by name. Returns whether it was present.
    pub fn unregister(&self, event: &str, name: &str) -> bool {
        let mut map = self.handlers.lock();
        if let Some(list) = map.get_mut(event) {
            if let Some(pos) = list.iter().position(|h| h.name() == name) {
                list.remove(pos);
                return true;
            }
        }
        false
    }

    /// Run all handlers for `event`. Per-handler exceptions are logged
    /// and recorded as `None`; the chain continues. Unknown events warn
    /// and return an empty vec.
    pub fn fire(&self, event: &str, payload: Option<&Payload>) -> Vec<Option<Payload>> {
        if !is_known(event) {
            tracing::warn!("fire() called with unknown event: {}", event);
            return Vec::new();
        }
        let null = serde_json::Value::Null;
        let payload = payload.unwrap_or(&null);
        let handlers = {
            let map = self.handlers.lock();
            map.get(event).cloned().unwrap_or_default()
        };
        let mut results = Vec::with_capacity(handlers.len());
        for h in handlers {
            match h.call(payload) {
                Ok(v) => results.push(Some(v)),
                Err(err) => {
                    tracing::warn!(handler = h.name(), event, error = %err, "hook handler failed");
                    results.push(None);
                }
            }
        }
        results
    }

    /// Diagnostic: which handlers are registered, by name, per event.
    pub fn list_handlers(&self, event: Option<&str>) -> HashMap<String, Vec<String>> {
        let map = self.handlers.lock();
        match event {
            Some(ev) => {
                let names = map
                    .get(ev)
                    .map(|v| v.iter().map(|h| h.name().to_string()).collect())
                    .unwrap_or_default();
                let mut out = HashMap::new();
                out.insert(ev.to_string(), names);
                out
            }
            None => {
                let mut out = HashMap::new();
                for &ev in known_hooks() {
                    let names = map
                        .get(ev)
                        .map(|v| v.iter().map(|h| h.name().to_string()).collect())
                        .unwrap_or_default();
                    out.insert(ev.to_string(), names);
                }
                out
            }
        }
    }

    /// Clear all handlers — primarily for tests.
    pub fn clear(&self, event: Option<&str>) {
        let mut map = self.handlers.lock();
        match event {
            Some(ev) => {
                if let Some(list) = map.get_mut(ev) {
                    list.clear();
                }
            }
            None => map.clear(),
        }
    }
}

// ── snapshot & rehydrate (testing convenience) ──────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RegistrySnapshot {
    pub by_event: HashMap<String, Vec<String>>,
}

impl Registry {
    pub fn snapshot(&self) -> RegistrySnapshot {
        let by_event = self.list_handlers(None);
        RegistrySnapshot { by_event }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn json(v: serde_json::Value) -> Payload {
        v
    }

    // ── known_hooks ─────────────────────────────────────────────────────────

    #[test]
    fn known_hooks_lists_five_constants() {
        let hooks = known_hooks();
        assert_eq!(hooks.len(), 5);
        for h in [
            HOOK_LAB_CRITICAL,
            HOOK_KERNEL_DECISION,
            HOOK_SESSION_END,
            HOOK_INTAKE_PDF,
            HOOK_PRE_COMMIT,
        ] {
            assert!(is_known(h));
        }
    }

    #[test]
    fn is_known_rejects_unknown() {
        assert!(!is_known("on_unicorn"));
    }

    // ── register / fire happy path ──────────────────────────────────────────

    #[test]
    fn register_then_fire_runs_handler() {
        let r = Registry::new();
        let count = Arc::new(AtomicUsize::new(0));
        let c2 = count.clone();
        r.register_fn(HOOK_LAB_CRITICAL, "tally", move |_p| {
            c2.fetch_add(1, Ordering::SeqCst);
            Ok(json(serde_json::json!({"tallied": true})))
        })
        .unwrap();
        let res = r.fire(HOOK_LAB_CRITICAL, Some(&json(serde_json::json!({}))));
        assert_eq!(res.len(), 1);
        assert_eq!(count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn fire_passes_payload() {
        let r = Registry::new();
        let captured = Arc::new(Mutex::new(serde_json::Value::Null));
        let c2 = captured.clone();
        r.register_fn(HOOK_INTAKE_PDF, "capture", move |p| {
            *c2.lock() = p.clone();
            Ok(serde_json::Value::Null)
        })
        .unwrap();
        let payload = serde_json::json!({"path": "/tmp/x.pdf"});
        r.fire(HOOK_INTAKE_PDF, Some(&payload));
        assert_eq!(captured.lock().clone(), payload);
    }

    #[test]
    fn fire_with_none_payload_uses_null() {
        let r = Registry::new();
        let cap = Arc::new(Mutex::new(serde_json::Value::Null));
        let c = cap.clone();
        r.register_fn(HOOK_SESSION_END, "h", move |p| {
            *c.lock() = p.clone();
            Ok(serde_json::Value::Null)
        })
        .unwrap();
        r.fire(HOOK_SESSION_END, None);
        assert_eq!(*cap.lock(), serde_json::Value::Null);
    }

    // ── ordering ────────────────────────────────────────────────────────────

    #[test]
    fn fire_runs_handlers_in_registration_order() {
        let r = Registry::new();
        let log = Arc::new(Mutex::new(Vec::<&'static str>::new()));
        let l1 = log.clone();
        r.register_fn(HOOK_KERNEL_DECISION, "first", move |_| {
            l1.lock().push("first");
            Ok(serde_json::Value::Null)
        })
        .unwrap();
        let l2 = log.clone();
        r.register_fn(HOOK_KERNEL_DECISION, "second", move |_| {
            l2.lock().push("second");
            Ok(serde_json::Value::Null)
        })
        .unwrap();
        let l3 = log.clone();
        r.register_fn(HOOK_KERNEL_DECISION, "third", move |_| {
            l3.lock().push("third");
            Ok(serde_json::Value::Null)
        })
        .unwrap();
        r.fire(HOOK_KERNEL_DECISION, None);
        assert_eq!(*log.lock(), vec!["first", "second", "third"]);
    }

    // ── idempotent registration ─────────────────────────────────────────────

    #[test]
    fn duplicate_registration_returns_false() {
        let r = Registry::new();
        let first = r
            .register_fn(HOOK_PRE_COMMIT, "h", |_| Ok(serde_json::Value::Null))
            .unwrap();
        let second = r
            .register_fn(HOOK_PRE_COMMIT, "h", |_| Ok(serde_json::Value::Null))
            .unwrap();
        assert!(first);
        assert!(!second);
        let map = r.list_handlers(Some(HOOK_PRE_COMMIT));
        assert_eq!(map[HOOK_PRE_COMMIT].len(), 1);
    }

    // ── unknown event ───────────────────────────────────────────────────────

    #[test]
    fn register_unknown_event_errors() {
        let r = Registry::new();
        let err = r
            .register_fn("on_unicorn", "h", |_| Ok(serde_json::Value::Null))
            .unwrap_err();
        assert!(matches!(err, HooksError::UnknownHook(_)));
    }

    #[test]
    fn fire_unknown_event_returns_empty() {
        let r = Registry::new();
        let res = r.fire("on_unicorn", None);
        assert!(res.is_empty());
    }

    // ── handler exceptions ──────────────────────────────────────────────────

    #[test]
    fn failing_handler_does_not_break_chain() {
        let r = Registry::new();
        let saw = Arc::new(AtomicUsize::new(0));
        let s = saw.clone();
        r.register_fn(HOOK_LAB_CRITICAL, "good1", move |_| {
            s.fetch_add(1, Ordering::SeqCst);
            Ok(serde_json::json!({"ok": 1}))
        })
        .unwrap();
        r.register_fn(HOOK_LAB_CRITICAL, "bad", |_| Err("boom".into()))
            .unwrap();
        let s2 = saw.clone();
        r.register_fn(HOOK_LAB_CRITICAL, "good2", move |_| {
            s2.fetch_add(1, Ordering::SeqCst);
            Ok(serde_json::json!({"ok": 2}))
        })
        .unwrap();
        let res = r.fire(HOOK_LAB_CRITICAL, None);
        assert_eq!(res.len(), 3);
        assert!(res[0].is_some());
        assert!(res[1].is_none()); // failure recorded as None
        assert!(res[2].is_some());
        assert_eq!(saw.load(Ordering::SeqCst), 2);
    }

    // ── unregister ──────────────────────────────────────────────────────────

    #[test]
    fn unregister_removes_handler_returns_true() {
        let r = Registry::new();
        r.register_fn(HOOK_SESSION_END, "h", |_| Ok(serde_json::Value::Null))
            .unwrap();
        assert!(r.unregister(HOOK_SESSION_END, "h"));
        let map = r.list_handlers(Some(HOOK_SESSION_END));
        assert!(map[HOOK_SESSION_END].is_empty());
    }

    #[test]
    fn unregister_missing_returns_false() {
        let r = Registry::new();
        assert!(!r.unregister(HOOK_SESSION_END, "nope"));
    }

    // ── list_handlers / clear ───────────────────────────────────────────────

    #[test]
    fn list_handlers_lists_per_event() {
        let r = Registry::new();
        r.register_fn(HOOK_LAB_CRITICAL, "a", |_| Ok(serde_json::Value::Null))
            .unwrap();
        r.register_fn(HOOK_INTAKE_PDF, "b", |_| Ok(serde_json::Value::Null))
            .unwrap();
        let map = r.list_handlers(None);
        assert_eq!(map[HOOK_LAB_CRITICAL], vec!["a"]);
        assert_eq!(map[HOOK_INTAKE_PDF], vec!["b"]);
        // empty events still listed with empty vecs
        assert_eq!(map[HOOK_KERNEL_DECISION], Vec::<String>::new());
    }

    #[test]
    fn clear_event_only_clears_that_event() {
        let r = Registry::new();
        r.register_fn(HOOK_LAB_CRITICAL, "a", |_| Ok(serde_json::Value::Null))
            .unwrap();
        r.register_fn(HOOK_INTAKE_PDF, "b", |_| Ok(serde_json::Value::Null))
            .unwrap();
        r.clear(Some(HOOK_LAB_CRITICAL));
        let map = r.list_handlers(None);
        assert!(map[HOOK_LAB_CRITICAL].is_empty());
        assert_eq!(map[HOOK_INTAKE_PDF], vec!["b"]);
    }

    #[test]
    fn clear_all_empties_everything() {
        let r = Registry::new();
        r.register_fn(HOOK_LAB_CRITICAL, "a", |_| Ok(serde_json::Value::Null))
            .unwrap();
        r.register_fn(HOOK_INTAKE_PDF, "b", |_| Ok(serde_json::Value::Null))
            .unwrap();
        r.clear(None);
        let map = r.list_handlers(None);
        assert!(map[HOOK_LAB_CRITICAL].is_empty());
        assert!(map[HOOK_INTAKE_PDF].is_empty());
    }

    // ── snapshot ────────────────────────────────────────────────────────────

    #[test]
    fn snapshot_captures_current_state() {
        let r = Registry::new();
        r.register_fn(HOOK_PRE_COMMIT, "x", |_| Ok(serde_json::Value::Null))
            .unwrap();
        let snap = r.snapshot();
        assert_eq!(snap.by_event[HOOK_PRE_COMMIT], vec!["x"]);
    }
}
