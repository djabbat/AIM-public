//! aim-tracing — pluggable tracing abstraction for AIM.
//!
//! Port of `agents/tracing.py`. The Python original glues OpenTelemetry +
//! OTLP/gRPC. In Rust the workspace already uses `tracing` for logs;
//! distributed-tracing export sits behind a [`Tracer`] trait so production
//! binaries can wire `tracing-opentelemetry` while tests use a recording
//! stub. This crate intentionally pulls **no** OTel deps to keep the
//! workspace build lean — production glue lives in the binary that
//! consumes it.

use std::collections::BTreeMap;
use std::sync::Arc;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TracingError {
    #[error("tracing not initialised")]
    NotInitialised,
}

pub type Result<T> = std::result::Result<T, TracingError>;

// ── config ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TracingConfig {
    pub enabled: bool,
    pub endpoint: String,
    pub service: String,
}

impl Default for TracingConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            endpoint: "http://localhost:4317".into(),
            service: "aim".into(),
        }
    }
}

impl TracingConfig {
    /// Read `AIM_TRACING`, `AIM_TRACING_ENDPOINT`, `AIM_TRACING_SERVICE` from
    /// the process environment (delegated through `from_source`).
    pub fn from_env() -> Self {
        Self::from_source(|name| std::env::var(name).ok())
    }

    /// Test-friendly: caller supplies the env reader closure.
    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let mut c = Self::default();
        if let Some(v) = get("AIM_TRACING") {
            let v = v.to_lowercase();
            c.enabled = matches!(v.as_str(), "1" | "true" | "yes");
        }
        if let Some(v) = get("AIM_TRACING_ENDPOINT") {
            c.endpoint = v;
        }
        if let Some(v) = get("AIM_TRACING_SERVICE") {
            c.service = v;
        }
        c
    }
}

// ── attributes ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum AttrValue {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
}

impl From<&str> for AttrValue {
    fn from(s: &str) -> Self {
        // Cap long strings to 200 chars (matches Python `str(v)[:200]`).
        let truncated: String = s.chars().take(200).collect();
        Self::Str(truncated)
    }
}
impl From<String> for AttrValue {
    fn from(s: String) -> Self {
        AttrValue::from(s.as_str())
    }
}
impl From<i64> for AttrValue {
    fn from(n: i64) -> Self {
        Self::Int(n)
    }
}
impl From<i32> for AttrValue {
    fn from(n: i32) -> Self {
        Self::Int(n as i64)
    }
}
impl From<f64> for AttrValue {
    fn from(n: f64) -> Self {
        Self::Float(n)
    }
}
impl From<bool> for AttrValue {
    fn from(b: bool) -> Self {
        Self::Bool(b)
    }
}

pub type Attributes = BTreeMap<String, AttrValue>;

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SpanRecord {
    pub name: String,
    pub attributes: Attributes,
    pub status: SpanStatus,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum SpanStatus {
    #[default]
    Unset,
    Ok,
    Error,
}

// ── tracer trait ────────────────────────────────────────────────────────────

pub trait Tracer: Send + Sync {
    fn enter(&self, name: &str, attributes: &Attributes) -> SpanHandle;
    fn set_status(&self, handle: &SpanHandle, status: SpanStatus, error: Option<&str>);
    fn exit(&self, handle: SpanHandle);
}

/// Opaque per-span identifier the [`Tracer`] hands back at `enter`. The
/// noop tracer uses `0`; recording tracers use a monotonic counter.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SpanHandle(pub u64);

// ── noop tracer ─────────────────────────────────────────────────────────────

pub struct NoopTracer;

impl Tracer for NoopTracer {
    fn enter(&self, _name: &str, _attributes: &Attributes) -> SpanHandle {
        SpanHandle(0)
    }
    fn set_status(&self, _handle: &SpanHandle, _status: SpanStatus, _error: Option<&str>) {}
    fn exit(&self, _handle: SpanHandle) {}
}

// ── recording tracer (test fixture) ─────────────────────────────────────────

#[derive(Default)]
pub struct RecordingTracer {
    inner: Mutex<RecordingInner>,
}

#[derive(Default)]
struct RecordingInner {
    next_id: u64,
    /// Spans that have been entered but not yet exited (in-flight).
    open: BTreeMap<u64, SpanRecord>,
    /// Closed spans, in completion order.
    closed: Vec<SpanRecord>,
}

impl RecordingTracer {
    pub fn new() -> Self {
        Self::default()
    }

    /// Snapshot of completed spans.
    pub fn closed_spans(&self) -> Vec<SpanRecord> {
        self.inner.lock().closed.clone()
    }

    /// Snapshot of currently-open spans (debug aid).
    pub fn open_spans(&self) -> Vec<SpanRecord> {
        self.inner.lock().open.values().cloned().collect()
    }
}

impl Tracer for RecordingTracer {
    fn enter(&self, name: &str, attributes: &Attributes) -> SpanHandle {
        let mut inner = self.inner.lock();
        let id = {
            inner.next_id += 1;
            inner.next_id
        };
        inner.open.insert(
            id,
            SpanRecord {
                name: name.to_string(),
                attributes: attributes.clone(),
                status: SpanStatus::Unset,
                error: None,
            },
        );
        SpanHandle(id)
    }

    fn set_status(&self, handle: &SpanHandle, status: SpanStatus, error: Option<&str>) {
        let mut inner = self.inner.lock();
        if let Some(rec) = inner.open.get_mut(&handle.0) {
            rec.status = status;
            rec.error = error.map(|e| e.chars().take(200).collect());
        }
    }

    fn exit(&self, handle: SpanHandle) {
        let mut inner = self.inner.lock();
        if let Some(rec) = inner.open.remove(&handle.0) {
            inner.closed.push(rec);
        }
    }
}

// ── span guard ──────────────────────────────────────────────────────────────

/// RAII span guard. On drop, exits the span. Use [`SpanGuard::record_error`]
/// to mark Error status before drop.
pub struct SpanGuard<'a> {
    tracer: &'a dyn Tracer,
    handle: SpanHandle,
    closed: bool,
}

impl<'a> SpanGuard<'a> {
    pub fn record_error(&mut self, msg: &str) {
        self.tracer
            .set_status(&self.handle, SpanStatus::Error, Some(msg));
    }
    pub fn ok(&mut self) {
        self.tracer.set_status(&self.handle, SpanStatus::Ok, None);
    }
}

impl<'a> Drop for SpanGuard<'a> {
    fn drop(&mut self) {
        if !self.closed {
            self.tracer.exit(self.handle);
            self.closed = true;
        }
    }
}

/// Public entry-point: open a span. Mirrors Python `with span(name, **attrs)`.
pub fn span<'a>(tracer: &'a dyn Tracer, name: &str, attributes: Attributes) -> SpanGuard<'a> {
    let handle = tracer.enter(name, &attributes);
    SpanGuard {
        tracer,
        handle,
        closed: false,
    }
}

/// Run a closure inside a span; record Error on panic-as-Result. Mirrors
/// Python's `traced` decorator behaviour for plain (non-async) bodies.
pub fn traced<F, T>(
    tracer: &dyn Tracer,
    name: &str,
    attributes: Attributes,
    f: F,
) -> std::result::Result<T, String>
where
    F: FnOnce() -> std::result::Result<T, String>,
{
    let mut g = span(tracer, name, attributes);
    match f() {
        Ok(v) => {
            g.ok();
            Ok(v)
        }
        Err(e) => {
            g.record_error(&e);
            Err(e)
        }
    }
}

// ── shared global tracer (opt-in) ───────────────────────────────────────────

/// Process-wide shared tracer. Initialised once via [`init_global`].
/// Multiple inits return the previously-installed tracer (idempotent).
static GLOBAL: parking_lot::Mutex<Option<Arc<dyn Tracer>>> = parking_lot::Mutex::new(None);

pub fn init_global(tracer: Arc<dyn Tracer>) -> Arc<dyn Tracer> {
    let mut g = GLOBAL.lock();
    if let Some(existing) = g.as_ref() {
        return existing.clone();
    }
    *g = Some(tracer.clone());
    tracer
}

pub fn global() -> Option<Arc<dyn Tracer>> {
    GLOBAL.lock().clone()
}

#[cfg(test)]
pub fn reset_global() {
    *GLOBAL.lock() = None;
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn attrs(pairs: &[(&str, AttrValue)]) -> Attributes {
        let mut m = Attributes::new();
        for (k, v) in pairs {
            m.insert((*k).to_string(), v.clone());
        }
        m
    }

    // ── TracingConfig ───────────────────────────────────────────────────────

    #[test]
    fn config_default_disabled() {
        let c = TracingConfig::default();
        assert!(!c.enabled);
        assert_eq!(c.service, "aim");
    }

    #[test]
    fn config_from_source_reads_env() {
        let mut env = HashMap::new();
        env.insert("AIM_TRACING".to_string(), "1".to_string());
        env.insert("AIM_TRACING_ENDPOINT".to_string(), "http://otel:4317".into());
        env.insert("AIM_TRACING_SERVICE".to_string(), "aim-test".into());
        let c = TracingConfig::from_source(|k| env.get(k).cloned());
        assert!(c.enabled);
        assert_eq!(c.endpoint, "http://otel:4317");
        assert_eq!(c.service, "aim-test");
    }

    #[test]
    fn config_disabled_when_value_not_truthy() {
        let mut env = HashMap::new();
        env.insert("AIM_TRACING".to_string(), "no".to_string());
        let c = TracingConfig::from_source(|k| env.get(k).cloned());
        assert!(!c.enabled);
    }

    // ── AttrValue ───────────────────────────────────────────────────────────

    #[test]
    fn attr_string_truncates_at_200_chars() {
        let s = "x".repeat(500);
        let v: AttrValue = (&*s).into();
        if let AttrValue::Str(out) = v {
            assert_eq!(out.chars().count(), 200);
        } else {
            panic!();
        }
    }

    #[test]
    fn attr_value_from_typed_inputs() {
        let _: AttrValue = 5_i64.into();
        let _: AttrValue = 5_i32.into();
        let _: AttrValue = 1.5_f64.into();
        let _: AttrValue = true.into();
        let _: AttrValue = String::from("x").into();
    }

    // ── NoopTracer ──────────────────────────────────────────────────────────

    #[test]
    fn noop_tracer_returns_zero_handle() {
        let t = NoopTracer;
        let h = t.enter("x", &attrs(&[]));
        assert_eq!(h.0, 0);
        // exits + status calls don't crash
        t.set_status(&h, SpanStatus::Ok, None);
        t.exit(h);
    }

    // ── RecordingTracer + span guard ────────────────────────────────────────

    #[test]
    fn span_guard_records_open_then_closed() {
        let t = RecordingTracer::new();
        {
            let _g = span(&t, "outer", attrs(&[("k", "v".into())]));
            assert_eq!(t.open_spans().len(), 1);
            assert_eq!(t.open_spans()[0].name, "outer");
        }
        assert_eq!(t.open_spans().len(), 0);
        let closed = t.closed_spans();
        assert_eq!(closed.len(), 1);
        assert_eq!(closed[0].name, "outer");
        assert_eq!(
            closed[0].attributes.get("k"),
            Some(&AttrValue::Str("v".into()))
        );
    }

    #[test]
    fn span_guard_records_status_on_ok() {
        let t = RecordingTracer::new();
        {
            let mut g = span(&t, "ok-span", attrs(&[]));
            g.ok();
        }
        let c = t.closed_spans();
        assert_eq!(c[0].status, SpanStatus::Ok);
    }

    #[test]
    fn span_guard_records_error_with_truncated_message() {
        let t = RecordingTracer::new();
        let long = "x".repeat(500);
        {
            let mut g = span(&t, "bad", attrs(&[]));
            g.record_error(&long);
        }
        let c = t.closed_spans();
        assert_eq!(c[0].status, SpanStatus::Error);
        assert!(c[0].error.is_some());
        assert_eq!(c[0].error.as_ref().unwrap().chars().count(), 200);
    }

    #[test]
    fn nested_spans_close_in_order() {
        let t = RecordingTracer::new();
        {
            let _outer = span(&t, "outer", attrs(&[]));
            {
                let _inner = span(&t, "inner", attrs(&[]));
            }
        }
        let c = t.closed_spans();
        assert_eq!(c.len(), 2);
        assert_eq!(c[0].name, "inner"); // inner closes first
        assert_eq!(c[1].name, "outer");
    }

    // ── traced() ────────────────────────────────────────────────────────────

    #[test]
    fn traced_ok_branch_marks_ok() {
        let t = RecordingTracer::new();
        let result = traced(&t, "task", attrs(&[]), || Ok::<_, String>(42));
        assert_eq!(result.unwrap(), 42);
        let c = t.closed_spans();
        assert_eq!(c[0].status, SpanStatus::Ok);
    }

    #[test]
    fn traced_err_branch_marks_error_and_propagates() {
        let t = RecordingTracer::new();
        let result: std::result::Result<i32, String> =
            traced(&t, "task", attrs(&[]), || Err("kaboom".into()));
        assert!(result.is_err());
        let c = t.closed_spans();
        assert_eq!(c[0].status, SpanStatus::Error);
        assert_eq!(c[0].error.as_deref(), Some("kaboom"));
    }

    // ── attributes ──────────────────────────────────────────────────────────

    #[test]
    fn span_carries_typed_attributes() {
        let t = RecordingTracer::new();
        {
            let _g = span(
                &t,
                "compute",
                attrs(&[
                    ("user_id", AttrValue::Int(42)),
                    ("ratio", AttrValue::Float(0.95)),
                    ("admin", AttrValue::Bool(true)),
                ]),
            );
        }
        let c = t.closed_spans();
        assert_eq!(c[0].attributes.get("user_id"), Some(&AttrValue::Int(42)));
        assert_eq!(
            c[0].attributes.get("ratio"),
            Some(&AttrValue::Float(0.95))
        );
        assert_eq!(c[0].attributes.get("admin"), Some(&AttrValue::Bool(true)));
    }

    // ── global tracer (single test, since global state is shared) ──────────

    #[test]
    fn global_lifecycle_init_idempotent_then_reset() {
        reset_global();
        // 1. Before init → None
        assert!(global().is_none());
        // 2. First init returns the stored tracer
        let first = init_global(Arc::new(NoopTracer));
        assert!(global().is_some());
        // 3. Second init is idempotent: returns the already-installed tracer
        let second = init_global(Arc::new(RecordingTracer::new()));
        assert!(Arc::ptr_eq(&first, &second));
        // 4. Reset clears the slot
        reset_global();
        assert!(global().is_none());
    }
}
