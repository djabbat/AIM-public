//! aim-self-health — full-stack self-diagnostic for AIM.
//!
//! Port of `agents/self_health.py`. Provides the framework — Status enum,
//! ComponentReport, SelfHealthChecker — with [`Probe`] trait for actual
//! component checks. Production binaries register concrete probes
//! (embed daemon, sqlite checks, web server ping, disk free, etc.);
//! tests use synthetic stubs to exercise the aggregation logic.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HealthError {
    #[error("probe error: {0}")]
    Probe(String),
}

// ── status ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Healthy,
    Degraded,
    Warning,
    Stopped,
    Unhealthy,
    Critical,
    Error,
}

impl Status {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Degraded => "degraded",
            Self::Warning => "warning",
            Self::Stopped => "stopped",
            Self::Unhealthy => "unhealthy",
            Self::Critical => "critical",
            Self::Error => "error",
        }
    }

    pub fn is_bad(&self) -> bool {
        matches!(self, Self::Unhealthy | Self::Critical | Self::Error)
    }
    pub fn is_degraded(&self) -> bool {
        matches!(self, Self::Warning | Self::Degraded)
    }
}

// ── component report ───────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComponentReport {
    pub status: Status,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub fields: BTreeMap<String, serde_json::Value>,
}

impl ComponentReport {
    pub fn healthy() -> Self {
        Self {
            status: Status::Healthy,
            error: None,
            message: None,
            fields: BTreeMap::new(),
        }
    }
    pub fn unhealthy(error: impl Into<String>) -> Self {
        Self {
            status: Status::Unhealthy,
            error: Some(error.into()),
            message: None,
            fields: BTreeMap::new(),
        }
    }
    pub fn stopped(message: impl Into<String>) -> Self {
        Self {
            status: Status::Stopped,
            error: None,
            message: Some(message.into()),
            fields: BTreeMap::new(),
        }
    }
    pub fn warning(msg: impl Into<String>) -> Self {
        Self {
            status: Status::Warning,
            error: None,
            message: Some(msg.into()),
            fields: BTreeMap::new(),
        }
    }
    pub fn with_field(mut self, key: &str, value: serde_json::Value) -> Self {
        self.fields.insert(key.into(), value);
        self
    }
}

// ── probe trait ────────────────────────────────────────────────────────────

pub trait Probe: Send + Sync {
    fn name(&self) -> &str;
    fn check(&self) -> ComponentReport;
}

/// Closure-backed probe; convenient for tests.
pub struct FnProbe {
    pub name: String,
    pub func: Box<dyn Fn() -> ComponentReport + Send + Sync>,
}

impl FnProbe {
    pub fn new<F>(name: impl Into<String>, f: F) -> Self
    where
        F: Fn() -> ComponentReport + Send + Sync + 'static,
    {
        Self {
            name: name.into(),
            func: Box::new(f),
        }
    }
}

impl Probe for FnProbe {
    fn name(&self) -> &str {
        &self.name
    }
    fn check(&self) -> ComponentReport {
        (self.func)()
    }
}

// ── overall report ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HealthReport {
    pub timestamp: DateTime<Utc>,
    pub overall_status: Status,
    pub components: BTreeMap<String, ComponentReport>,
    pub unhealthy_components: Vec<String>,
    pub degraded_components: Vec<String>,
}

impl HealthReport {
    pub fn is_overall_healthy(&self) -> bool {
        matches!(self.overall_status, Status::Healthy)
    }
}

// ── checker ────────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

pub struct SelfHealthChecker<'a> {
    pub probes: Vec<Box<dyn Probe>>,
    pub clock: &'a dyn Clock,
    pub quick: bool,
    /// Probe names skipped in `quick` mode.
    pub slow_probes: Vec<String>,
}

impl<'a> SelfHealthChecker<'a> {
    pub fn new(clock: &'a dyn Clock) -> Self {
        Self {
            probes: Vec::new(),
            clock,
            quick: false,
            slow_probes: Vec::new(),
        }
    }

    pub fn with_probe(mut self, probe: Box<dyn Probe>) -> Self {
        self.probes.push(probe);
        self
    }

    pub fn add(&mut self, probe: Box<dyn Probe>) {
        self.probes.push(probe);
    }

    pub fn mark_slow(&mut self, name: &str) {
        self.slow_probes.push(name.into());
    }

    pub fn check_all(&self) -> HealthReport {
        let mut components: BTreeMap<String, ComponentReport> = BTreeMap::new();
        for probe in &self.probes {
            let name = probe.name().to_string();
            if self.quick && self.slow_probes.iter().any(|s| s == &name) {
                continue;
            }
            // Probes don't return Result here — they're expected to handle
            // their own errors and surface them as ComponentReport. If
            // production wraps a fallible operation, it should map errors
            // into Status::Error inside the probe.
            let report = probe.check();
            components.insert(name, report);
        }
        let unhealthy: Vec<String> = components
            .iter()
            .filter(|(_, r)| r.status.is_bad())
            .map(|(n, _)| n.clone())
            .collect();
        let degraded: Vec<String> = components
            .iter()
            .filter(|(_, r)| r.status.is_degraded())
            .map(|(n, _)| n.clone())
            .collect();
        let overall = if !unhealthy.is_empty() {
            Status::Unhealthy
        } else if !degraded.is_empty() {
            Status::Degraded
        } else {
            Status::Healthy
        };
        HealthReport {
            timestamp: self.clock.now(),
            overall_status: overall,
            components,
            unhealthy_components: unhealthy,
            degraded_components: degraded,
        }
    }
}

// ── filesystem helpers ─────────────────────────────────────────────────────

/// Build a probe that checks a Unix socket file's existence and (optionally)
/// some pluggable predicate. Mirrors the `embed_daemon`-style probes.
pub fn socket_probe(name: &'static str, path: std::path::PathBuf) -> Box<dyn Probe> {
    Box::new(FnProbe::new(name, move || {
        if path.exists() {
            ComponentReport::healthy().with_field(
                "path",
                serde_json::Value::String(path.to_string_lossy().to_string()),
            )
        } else {
            ComponentReport::unhealthy("socket missing")
        }
    }))
}

/// Build a probe that checks for a process pid file. Returns Stopped when
/// the file is missing (Python parity).
pub fn pidfile_probe(name: &'static str, path: std::path::PathBuf) -> Box<dyn Probe> {
    Box::new(FnProbe::new(name, move || {
        if !path.exists() {
            return ComponentReport::stopped("no pid file");
        }
        match std::fs::read_to_string(&path) {
            Ok(text) => match text.trim().parse::<i32>() {
                Ok(pid) => ComponentReport::healthy().with_field(
                    "pid",
                    serde_json::Value::Number(serde_json::Number::from(pid)),
                ),
                Err(e) => ComponentReport::unhealthy(format!("invalid pid: {}", e)),
            },
            Err(e) => ComponentReport::unhealthy(format!("read failed: {}", e)),
        }
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use std::sync::Arc;

    fn dt(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).unwrap()
    }

    // ── Status ──────────────────────────────────────────────────────────────

    #[test]
    fn status_classification() {
        assert!(Status::Unhealthy.is_bad());
        assert!(Status::Critical.is_bad());
        assert!(Status::Error.is_bad());
        assert!(!Status::Healthy.is_bad());
        assert!(Status::Warning.is_degraded());
        assert!(Status::Degraded.is_degraded());
        assert!(!Status::Healthy.is_degraded());
    }

    #[test]
    fn status_serialises_lowercase() {
        let s = serde_json::to_string(&Status::Unhealthy).unwrap();
        assert_eq!(s, "\"unhealthy\"");
    }

    // ── ComponentReport builders ───────────────────────────────────────────

    #[test]
    fn component_builders() {
        let h = ComponentReport::healthy();
        assert_eq!(h.status, Status::Healthy);
        let u = ComponentReport::unhealthy("boom");
        assert_eq!(u.error.as_deref(), Some("boom"));
        let s = ComponentReport::stopped("nope");
        assert_eq!(s.message.as_deref(), Some("nope"));
        let f = ComponentReport::healthy().with_field("x", serde_json::json!(42));
        assert_eq!(f.fields["x"], serde_json::json!(42));
    }

    // ── checker aggregation ────────────────────────────────────────────────

    #[test]
    fn check_all_overall_healthy_when_all_probes_pass() {
        let clock = FixedClock(dt(1_700_000_000));
        let mut checker = SelfHealthChecker::new(&clock);
        checker.add(Box::new(FnProbe::new("a", || ComponentReport::healthy())));
        checker.add(Box::new(FnProbe::new("b", || ComponentReport::healthy())));
        let r = checker.check_all();
        assert_eq!(r.overall_status, Status::Healthy);
        assert!(r.unhealthy_components.is_empty());
        assert!(r.degraded_components.is_empty());
        assert!(r.is_overall_healthy());
    }

    #[test]
    fn check_all_overall_unhealthy_takes_priority_over_degraded() {
        let clock = FixedClock(dt(1_700_000_000));
        let mut checker = SelfHealthChecker::new(&clock);
        checker.add(Box::new(FnProbe::new("ok", || ComponentReport::healthy())));
        checker.add(Box::new(FnProbe::new("warn", || ComponentReport::warning("slow"))));
        checker.add(Box::new(FnProbe::new("dead", || ComponentReport::unhealthy("down"))));
        let r = checker.check_all();
        assert_eq!(r.overall_status, Status::Unhealthy);
        assert_eq!(r.unhealthy_components, vec!["dead".to_string()]);
        assert_eq!(r.degraded_components, vec!["warn".to_string()]);
    }

    #[test]
    fn check_all_overall_degraded_when_only_warnings() {
        let clock = FixedClock(dt(1_700_000_000));
        let mut checker = SelfHealthChecker::new(&clock);
        checker.add(Box::new(FnProbe::new("a", || ComponentReport::healthy())));
        checker.add(Box::new(FnProbe::new("warn", || ComponentReport::warning("slow"))));
        let r = checker.check_all();
        assert_eq!(r.overall_status, Status::Degraded);
    }

    #[test]
    fn check_all_quick_skips_slow_probes() {
        let clock = FixedClock(dt(1_700_000_000));
        let counter = Arc::new(Mutex::new(0usize));
        let c2 = counter.clone();
        let mut checker = SelfHealthChecker::new(&clock);
        checker.add(Box::new(FnProbe::new("fast", || ComponentReport::healthy())));
        checker.add(Box::new(FnProbe::new("slow", move || {
            *c2.lock() += 1;
            ComponentReport::healthy()
        })));
        checker.mark_slow("slow");
        checker.quick = true;
        let r = checker.check_all();
        assert!(r.components.contains_key("fast"));
        assert!(!r.components.contains_key("slow"));
        assert_eq!(*counter.lock(), 0);
    }

    #[test]
    fn check_all_includes_timestamp() {
        let clock = FixedClock(dt(1_700_000_123));
        let mut checker = SelfHealthChecker::new(&clock);
        checker.add(Box::new(FnProbe::new("a", || ComponentReport::healthy())));
        let r = checker.check_all();
        assert_eq!(r.timestamp, dt(1_700_000_123));
    }

    // ── socket / pidfile probes ────────────────────────────────────────────

    #[test]
    fn socket_probe_unhealthy_when_missing() {
        let p = std::path::PathBuf::from("/tmp/__nonexistent_socket_for_test_4242");
        let probe = socket_probe("sock", p);
        let r = probe.check();
        assert_eq!(r.status, Status::Unhealthy);
        assert_eq!(r.error.as_deref(), Some("socket missing"));
    }

    #[test]
    fn socket_probe_healthy_when_present() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("real_file");
        std::fs::write(&p, "ignored").unwrap();
        let probe = socket_probe("sock", p);
        let r = probe.check();
        assert_eq!(r.status, Status::Healthy);
        assert!(r.fields.contains_key("path"));
    }

    #[test]
    fn pidfile_probe_stopped_when_missing() {
        let p = std::path::PathBuf::from("/tmp/__no_pid_file_test_4242");
        let probe = pidfile_probe("watcher", p);
        let r = probe.check();
        assert_eq!(r.status, Status::Stopped);
    }

    #[test]
    fn pidfile_probe_healthy_with_pid_field() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("watcher.pid");
        std::fs::write(&p, "12345\n").unwrap();
        let probe = pidfile_probe("watcher", p);
        let r = probe.check();
        assert_eq!(r.status, Status::Healthy);
        assert_eq!(r.fields["pid"], serde_json::json!(12345));
    }

    #[test]
    fn pidfile_probe_unhealthy_when_invalid_content() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("watcher.pid");
        std::fs::write(&p, "not-a-pid").unwrap();
        let probe = pidfile_probe("watcher", p);
        let r = probe.check();
        assert_eq!(r.status, Status::Unhealthy);
        assert!(r.error.as_deref().unwrap().contains("invalid pid"));
    }
}
