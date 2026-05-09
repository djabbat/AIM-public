//! aim-metrics — Prometheus-compatible metrics + health snapshot.
//!
//! Port of `agents/metrics.py`. The Python original embeds an HTTP server
//! via `prometheus_client.start_http_server`. In Rust the HTTP layer
//! belongs in the binary that consumes this crate (axum/hyper/etc); this
//! crate provides:
//!   • `Registry` with Counter/Histogram/Gauge primitives
//!   • Prometheus-text-format rendering of the registry snapshot
//!   • `Health` snapshot struct + JSON serialization
//!   • `track_latency` helper that records both request count and duration
//!
//! Default metrics (`Registry::with_aim_defaults`) match the Python module
//! one-for-one so existing dashboards keep working.

use std::collections::BTreeMap;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum MetricsError {
    #[error("unknown metric: {0}")]
    UnknownMetric(String),
    #[error("label cardinality mismatch: expected {expected:?}, got {got:?}")]
    LabelMismatch { expected: Vec<String>, got: Vec<String> },
}

pub type Result<T> = std::result::Result<T, MetricsError>;

// ── label sets ──────────────────────────────────────────────────────────────

/// Ordered list of label values that matches a metric's declared label
/// names. Stored as a single string for O(1) hashing in the registry.
#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct LabelSet(pub Vec<(String, String)>);

impl LabelSet {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn from_pairs<I, K, V>(pairs: I) -> Self
    where
        I: IntoIterator<Item = (K, V)>,
        K: Into<String>,
        V: Into<String>,
    {
        let mut s = Self::default();
        for (k, v) in pairs {
            s.0.push((k.into(), v.into()));
        }
        s
    }

    /// Render as Prometheus text format: `{k1="v1",k2="v2"}` (or empty).
    pub fn render(&self) -> String {
        if self.0.is_empty() {
            String::new()
        } else {
            let parts: Vec<String> = self
                .0
                .iter()
                .map(|(k, v)| format!("{}=\"{}\"", k, escape_label_value(v)))
                .collect();
            format!("{{{}}}", parts.join(","))
        }
    }

    fn names(&self) -> Vec<String> {
        self.0.iter().map(|(k, _)| k.clone()).collect()
    }
}

fn escape_label_value(v: &str) -> String {
    v.replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('"', "\\\"")
}

// ── primitive metrics ───────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct CounterInner {
    /// label-set → cumulative counter value
    series: BTreeMap<Vec<(String, String)>, f64>,
}

#[derive(Clone, Debug, Default)]
pub struct GaugeInner {
    series: BTreeMap<Vec<(String, String)>, f64>,
}

#[derive(Clone, Debug)]
pub struct HistogramInner {
    buckets: Vec<f64>,
    series: BTreeMap<Vec<(String, String)>, HistogramSeries>,
}

#[derive(Clone, Debug)]
pub struct HistogramSeries {
    counts: Vec<u64>, // per upper-bucket (+inf appended)
    sum: f64,
    count: u64,
}

impl HistogramSeries {
    fn new(n_buckets: usize) -> Self {
        Self {
            counts: vec![0; n_buckets + 1], // include +Inf
            sum: 0.0,
            count: 0,
        }
    }
}

#[derive(Clone, Debug)]
pub enum Metric {
    Counter {
        help: String,
        labels: Vec<String>,
        inner: CounterInner,
    },
    Gauge {
        help: String,
        labels: Vec<String>,
        inner: GaugeInner,
    },
    Histogram {
        help: String,
        labels: Vec<String>,
        inner: HistogramInner,
    },
}

impl Metric {
    fn label_names(&self) -> &[String] {
        match self {
            Self::Counter { labels, .. } => labels,
            Self::Gauge { labels, .. } => labels,
            Self::Histogram { labels, .. } => labels,
        }
    }

    fn check_labels(&self, set: &LabelSet) -> Result<()> {
        let expected = self.label_names().to_vec();
        let got = set.names();
        if expected == got {
            Ok(())
        } else {
            Err(MetricsError::LabelMismatch { expected, got })
        }
    }
}

// ── registry ────────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct Registry {
    metrics: Mutex<BTreeMap<String, Metric>>,
}

impl Registry {
    pub fn new() -> Self {
        Self::default()
    }

    /// AIM default metric families, ports of `agents/metrics.py` constants.
    pub fn with_aim_defaults() -> Self {
        let r = Self::new();
        r.register_counter(
            "aim_requests_total",
            "Total requests handled by AIM components",
            &["endpoint", "status"],
        );
        r.register_histogram(
            "aim_latency_seconds",
            "Wall-clock latency",
            &["endpoint"],
            &[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
        );
        r.register_counter(
            "aim_memory_hits_total",
            "Semantic memory cache hits",
            &[],
        );
        r.register_counter(
            "aim_memory_misses_total",
            "Semantic memory cache misses",
            &[],
        );
        r.register_histogram(
            "aim_embed_latency_seconds",
            "Embedding daemon latency",
            &[],
            &[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
        );
        r.register_counter(
            "aim_llm_tokens_in_total",
            "LLM input tokens",
            &["provider", "model"],
        );
        r.register_counter(
            "aim_llm_tokens_out_total",
            "LLM output tokens",
            &["provider", "model"],
        );
        r.register_gauge(
            "aim_llm_cache_ratio",
            "DeepSeek prompt-cache hit ratio (%)",
            &["model"],
        );
        r.register_counter(
            "aim_llm_errors_total",
            "LLM errors by provider/cause",
            &["provider", "cause"],
        );
        r.register_gauge(
            "aim_embed_daemon_health",
            "Embed daemon: 1=ok 0=down",
            &[],
        );
        r.register_gauge(
            "aim_embed_cache_size",
            "Embed daemon LRU cache size",
            &[],
        );
        r.register_gauge(
            "aim_embed_cache_ratio",
            "Embed daemon LRU cache hit ratio (%)",
            &[],
        );
        r.register_histogram(
            "aim_graph_iterations",
            "Iterations per agent run",
            &[],
            &[1.0, 2.0, 3.0, 4.0, 5.0, 10.0],
        );
        r.register_histogram(
            "aim_graph_plan_size",
            "Planner step count",
            &[],
            &[1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0],
        );
        r
    }

    pub fn register_counter(&self, name: &str, help: &str, labels: &[&str]) {
        self.metrics.lock().insert(
            name.to_string(),
            Metric::Counter {
                help: help.to_string(),
                labels: labels.iter().map(|s| (*s).to_string()).collect(),
                inner: CounterInner::default(),
            },
        );
    }

    pub fn register_gauge(&self, name: &str, help: &str, labels: &[&str]) {
        self.metrics.lock().insert(
            name.to_string(),
            Metric::Gauge {
                help: help.to_string(),
                labels: labels.iter().map(|s| (*s).to_string()).collect(),
                inner: GaugeInner::default(),
            },
        );
    }

    pub fn register_histogram(&self, name: &str, help: &str, labels: &[&str], buckets: &[f64]) {
        self.metrics.lock().insert(
            name.to_string(),
            Metric::Histogram {
                help: help.to_string(),
                labels: labels.iter().map(|s| (*s).to_string()).collect(),
                inner: HistogramInner {
                    buckets: buckets.to_vec(),
                    series: BTreeMap::new(),
                },
            },
        );
    }

    pub fn inc(&self, name: &str, labels: &LabelSet) -> Result<()> {
        self.add(name, labels, 1.0)
    }

    pub fn add(&self, name: &str, labels: &LabelSet, n: f64) -> Result<()> {
        let mut m = self.metrics.lock();
        let metric = m.get_mut(name).ok_or_else(|| MetricsError::UnknownMetric(name.into()))?;
        metric.check_labels(labels)?;
        match metric {
            Metric::Counter { inner, .. } => {
                let entry = inner.series.entry(labels.0.clone()).or_insert(0.0);
                *entry += n;
                Ok(())
            }
            _ => Err(MetricsError::UnknownMetric(format!("{} is not a counter", name))),
        }
    }

    pub fn set(&self, name: &str, labels: &LabelSet, v: f64) -> Result<()> {
        let mut m = self.metrics.lock();
        let metric = m.get_mut(name).ok_or_else(|| MetricsError::UnknownMetric(name.into()))?;
        metric.check_labels(labels)?;
        match metric {
            Metric::Gauge { inner, .. } => {
                inner.series.insert(labels.0.clone(), v);
                Ok(())
            }
            _ => Err(MetricsError::UnknownMetric(format!("{} is not a gauge", name))),
        }
    }

    pub fn observe(&self, name: &str, labels: &LabelSet, v: f64) -> Result<()> {
        let mut m = self.metrics.lock();
        let metric = m.get_mut(name).ok_or_else(|| MetricsError::UnknownMetric(name.into()))?;
        metric.check_labels(labels)?;
        match metric {
            Metric::Histogram { inner, .. } => {
                let n_buckets = inner.buckets.len();
                let series = inner
                    .series
                    .entry(labels.0.clone())
                    .or_insert_with(|| HistogramSeries::new(n_buckets));
                let mut placed = false;
                for (i, &bound) in inner.buckets.iter().enumerate() {
                    if v <= bound {
                        series.counts[i] += 1;
                        placed = true;
                        break;
                    }
                }
                if !placed {
                    series.counts[n_buckets] += 1; // +Inf bucket
                }
                series.sum += v;
                series.count += 1;
                Ok(())
            }
            _ => Err(MetricsError::UnknownMetric(format!("{} is not a histogram", name))),
        }
    }

    /// Prometheus text-format snapshot. Matches v0.0.4 line shape.
    pub fn render(&self) -> String {
        let m = self.metrics.lock();
        let mut out = String::new();
        for (name, metric) in m.iter() {
            match metric {
                Metric::Counter { help, inner, .. } => {
                    out.push_str(&format!("# HELP {} {}\n", name, help));
                    out.push_str(&format!("# TYPE {} counter\n", name));
                    for (labels, val) in &inner.series {
                        let ls = LabelSet(labels.clone()).render();
                        out.push_str(&format!("{}{} {}\n", name, ls, format_float(*val)));
                    }
                }
                Metric::Gauge { help, inner, .. } => {
                    out.push_str(&format!("# HELP {} {}\n", name, help));
                    out.push_str(&format!("# TYPE {} gauge\n", name));
                    for (labels, val) in &inner.series {
                        let ls = LabelSet(labels.clone()).render();
                        out.push_str(&format!("{}{} {}\n", name, ls, format_float(*val)));
                    }
                }
                Metric::Histogram { help, inner, .. } => {
                    out.push_str(&format!("# HELP {} {}\n", name, help));
                    out.push_str(&format!("# TYPE {} histogram\n", name));
                    for (labels, series) in &inner.series {
                        let mut cumulative = 0u64;
                        for (i, bound) in inner.buckets.iter().enumerate() {
                            cumulative += series.counts[i];
                            let mut le_labels = labels.clone();
                            le_labels.push(("le".into(), format_float(*bound)));
                            let ls = LabelSet(le_labels).render();
                            out.push_str(&format!("{}_bucket{} {}\n", name, ls, cumulative));
                        }
                        cumulative += series.counts[inner.buckets.len()];
                        let mut inf_labels = labels.clone();
                        inf_labels.push(("le".into(), "+Inf".into()));
                        let ls = LabelSet(inf_labels).render();
                        out.push_str(&format!("{}_bucket{} {}\n", name, ls, cumulative));

                        let labels_only = LabelSet(labels.clone()).render();
                        out.push_str(&format!(
                            "{}_sum{} {}\n",
                            name,
                            labels_only,
                            format_float(series.sum)
                        ));
                        out.push_str(&format!(
                            "{}_count{} {}\n",
                            name, labels_only, series.count
                        ));
                    }
                }
            }
        }
        out
    }

    /// Return a single counter value (test convenience).
    pub fn counter_value(&self, name: &str, labels: &LabelSet) -> Option<f64> {
        let m = self.metrics.lock();
        match m.get(name)? {
            Metric::Counter { inner, .. } => inner.series.get(&labels.0).copied(),
            _ => None,
        }
    }

    pub fn gauge_value(&self, name: &str, labels: &LabelSet) -> Option<f64> {
        let m = self.metrics.lock();
        match m.get(name)? {
            Metric::Gauge { inner, .. } => inner.series.get(&labels.0).copied(),
            _ => None,
        }
    }

    pub fn histogram_summary(&self, name: &str, labels: &LabelSet) -> Option<(u64, f64)> {
        let m = self.metrics.lock();
        match m.get(name)? {
            Metric::Histogram { inner, .. } => inner
                .series
                .get(&labels.0)
                .map(|s| (s.count, s.sum)),
            _ => None,
        }
    }
}

fn format_float(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e15 {
        format!("{}", v as i64)
    } else {
        format!("{}", v)
    }
}

// ── track_latency ───────────────────────────────────────────────────────────

/// Run `f`, recording one tick to `aim_requests_total{endpoint=…,status=…}`
/// + an observation in `aim_latency_seconds{endpoint=…}`.
pub fn track_latency<F, T>(
    registry: &Registry,
    endpoint: &str,
    f: F,
) -> std::result::Result<T, String>
where
    F: FnOnce() -> std::result::Result<T, String>,
{
    let t0 = std::time::Instant::now();
    let outcome = f();
    let elapsed = t0.elapsed().as_secs_f64();
    let status = if outcome.is_ok() { "success" } else { "error" };
    let _ = registry.inc(
        "aim_requests_total",
        &LabelSet::from_pairs([("endpoint", endpoint), ("status", status)]),
    );
    let _ = registry.observe(
        "aim_latency_seconds",
        &LabelSet::from_pairs([("endpoint", endpoint)]),
        elapsed,
    );
    outcome
}

// ── health snapshot ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Health {
    pub status: String,
    pub timestamp: f64,
    pub components: BTreeMap<String, serde_json::Value>,
}

impl Health {
    pub fn ok_at(timestamp: f64) -> Self {
        Self {
            status: "ok".into(),
            timestamp,
            components: BTreeMap::new(),
        }
    }

    pub fn add_component(&mut self, name: &str, value: serde_json::Value) {
        self.components.insert(name.to_string(), value);
    }

    /// Mark "degraded" if any component reports `running: false`. Mirrors
    /// Python `_build_health`'s decision rule.
    pub fn evaluate(&mut self) {
        for (_, v) in &self.components {
            if v.get("running").and_then(|b| b.as_bool()) == Some(false) {
                self.status = "degraded".into();
                return;
            }
        }
        self.status = "ok".into();
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn empty() -> LabelSet {
        LabelSet::new()
    }

    fn pairs(p: &[(&str, &str)]) -> LabelSet {
        LabelSet::from_pairs(p.iter().map(|(k, v)| (*k, *v)))
    }

    // ── LabelSet ────────────────────────────────────────────────────────────

    #[test]
    fn label_set_empty_renders_empty() {
        assert_eq!(empty().render(), "");
    }

    #[test]
    fn label_set_renders_braces() {
        let s = pairs(&[("a", "1"), ("b", "x")]);
        assert_eq!(s.render(), r#"{a="1",b="x"}"#);
    }

    #[test]
    fn label_set_escapes_quotes_and_backslashes() {
        let s = pairs(&[("a", r#"x"y\z"#)]);
        assert!(s.render().contains(r#"a="x\"y\\z""#));
    }

    // ── counter ─────────────────────────────────────────────────────────────

    #[test]
    fn counter_inc_accumulates_per_label_set() {
        let r = Registry::new();
        r.register_counter("c", "help", &["k"]);
        r.inc("c", &pairs(&[("k", "a")])).unwrap();
        r.inc("c", &pairs(&[("k", "a")])).unwrap();
        r.inc("c", &pairs(&[("k", "b")])).unwrap();
        assert_eq!(r.counter_value("c", &pairs(&[("k", "a")])), Some(2.0));
        assert_eq!(r.counter_value("c", &pairs(&[("k", "b")])), Some(1.0));
    }

    #[test]
    fn counter_label_mismatch_errors() {
        let r = Registry::new();
        r.register_counter("c", "help", &["k"]);
        let err = r.inc("c", &pairs(&[("wrong", "x")])).unwrap_err();
        assert!(matches!(err, MetricsError::LabelMismatch { .. }));
    }

    #[test]
    fn counter_unknown_name_errors() {
        let r = Registry::new();
        let err = r.inc("missing", &empty()).unwrap_err();
        assert!(matches!(err, MetricsError::UnknownMetric(_)));
    }

    // ── gauge ───────────────────────────────────────────────────────────────

    #[test]
    fn gauge_set_overrides_value() {
        let r = Registry::new();
        r.register_gauge("g", "help", &[]);
        r.set("g", &empty(), 5.0).unwrap();
        r.set("g", &empty(), 10.0).unwrap();
        assert_eq!(r.gauge_value("g", &empty()), Some(10.0));
    }

    // ── histogram ───────────────────────────────────────────────────────────

    #[test]
    fn histogram_observe_records_count_and_sum() {
        let r = Registry::new();
        r.register_histogram("h", "help", &[], &[0.1, 1.0, 10.0]);
        r.observe("h", &empty(), 0.05).unwrap();
        r.observe("h", &empty(), 0.5).unwrap();
        r.observe("h", &empty(), 100.0).unwrap();
        let (count, sum) = r.histogram_summary("h", &empty()).unwrap();
        assert_eq!(count, 3);
        assert!((sum - 100.55).abs() < 1e-6);
    }

    #[test]
    fn histogram_buckets_are_cumulative_in_render() {
        let r = Registry::new();
        r.register_histogram("h", "help", &[], &[1.0, 5.0, 10.0]);
        r.observe("h", &empty(), 0.5).unwrap();
        r.observe("h", &empty(), 4.0).unwrap();
        r.observe("h", &empty(), 7.0).unwrap();
        let text = r.render();
        // bucket le="1" sees 1, le="5" sees 2, le="10" sees 3, +Inf sees 3
        assert!(text.contains(r#"h_bucket{le="1"} 1"#));
        assert!(text.contains(r#"h_bucket{le="5"} 2"#));
        assert!(text.contains(r#"h_bucket{le="10"} 3"#));
        assert!(text.contains(r#"h_bucket{le="+Inf"} 3"#));
    }

    // ── render ──────────────────────────────────────────────────────────────

    #[test]
    fn render_includes_help_and_type_for_counter() {
        let r = Registry::new();
        r.register_counter("c", "Total things", &[]);
        r.inc("c", &empty()).unwrap();
        let text = r.render();
        assert!(text.contains("# HELP c Total things"));
        assert!(text.contains("# TYPE c counter"));
        assert!(text.contains("\nc 1\n"));
    }

    #[test]
    fn render_emits_gauge_lines() {
        let r = Registry::new();
        r.register_gauge("g", "level", &[]);
        r.set("g", &empty(), 1.5).unwrap();
        let text = r.render();
        assert!(text.contains("# TYPE g gauge"));
        assert!(text.contains("g 1.5"));
    }

    // ── aim defaults ────────────────────────────────────────────────────────

    #[test]
    fn aim_defaults_include_known_metric_names() {
        let r = Registry::with_aim_defaults();
        let text = r.render();
        for name in [
            "aim_requests_total",
            "aim_latency_seconds",
            "aim_memory_hits_total",
            "aim_memory_misses_total",
            "aim_embed_latency_seconds",
            "aim_llm_tokens_in_total",
            "aim_llm_cache_ratio",
            "aim_embed_daemon_health",
            "aim_graph_iterations",
        ] {
            assert!(text.contains(name), "missing {}", name);
        }
    }

    // ── track_latency ───────────────────────────────────────────────────────

    #[test]
    fn track_latency_records_success() {
        let r = Registry::with_aim_defaults();
        let result: std::result::Result<i32, String> =
            track_latency(&r, "graph", || Ok(7));
        assert_eq!(result.unwrap(), 7);
        let v = r
            .counter_value(
                "aim_requests_total",
                &pairs(&[("endpoint", "graph"), ("status", "success")]),
            )
            .unwrap();
        assert_eq!(v, 1.0);
        let (count, _) = r
            .histogram_summary(
                "aim_latency_seconds",
                &pairs(&[("endpoint", "graph")]),
            )
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn track_latency_records_error_status_and_propagates() {
        let r = Registry::with_aim_defaults();
        let result: std::result::Result<i32, String> =
            track_latency(&r, "graph", || Err("boom".into()));
        assert!(result.is_err());
        let v = r
            .counter_value(
                "aim_requests_total",
                &pairs(&[("endpoint", "graph"), ("status", "error")]),
            )
            .unwrap();
        assert_eq!(v, 1.0);
    }

    // ── Health ──────────────────────────────────────────────────────────────

    #[test]
    fn health_starts_ok() {
        let h = Health::ok_at(1234.5);
        assert_eq!(h.status, "ok");
        assert_eq!(h.timestamp, 1234.5);
    }

    #[test]
    fn health_evaluates_to_degraded_when_running_false() {
        let mut h = Health::ok_at(0.0);
        h.add_component("embed", serde_json::json!({"running": false}));
        h.evaluate();
        assert_eq!(h.status, "degraded");
    }

    #[test]
    fn health_stays_ok_when_all_components_running() {
        let mut h = Health::ok_at(0.0);
        h.add_component("embed", serde_json::json!({"running": true}));
        h.add_component("memory", serde_json::json!({"rows": 100}));
        h.evaluate();
        assert_eq!(h.status, "ok");
    }

    #[test]
    fn health_to_json_round_trips() {
        let mut h = Health::ok_at(1.0);
        h.add_component("x", serde_json::json!({"running": true}));
        let s = h.to_json();
        let back: Health = serde_json::from_str(&s).unwrap();
        assert_eq!(back.status, "ok");
        assert_eq!(back.timestamp, 1.0);
    }
}
