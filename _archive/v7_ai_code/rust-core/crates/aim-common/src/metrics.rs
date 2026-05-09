//! Lightweight Prometheus metrics. Each service can register its own
//! counters/histograms; `metrics_handler` exposes /metrics in plain-text
//! exposition format.

use axum::response::IntoResponse;
use once_cell::sync::Lazy;
use prometheus::{Encoder, IntCounterVec, Registry, TextEncoder};

pub static REGISTRY: Lazy<Registry> = Lazy::new(Registry::new);

pub static REQUESTS: Lazy<IntCounterVec> = Lazy::new(|| {
    let c = IntCounterVec::new(
        prometheus::Opts::new("aim_requests_total", "Total HTTP requests"),
        &["service", "endpoint", "status"],
    ).expect("metric");
    REGISTRY.register(Box::new(c.clone())).ok();
    c
});

pub static UPSTREAM_CALLS: Lazy<IntCounterVec> = Lazy::new(|| {
    let c = IntCounterVec::new(
        prometheus::Opts::new("aim_upstream_calls_total",
            "Calls to upstream services (LLM, DB, etc.)"),
        &["service", "upstream", "outcome"],
    ).expect("metric");
    REGISTRY.register(Box::new(c.clone())).ok();
    c
});

/// Expose at /metrics
pub async fn metrics_handler() -> impl IntoResponse {
    let metric_families = REGISTRY.gather();
    let mut buffer = Vec::new();
    TextEncoder::new().encode(&metric_families, &mut buffer).ok();
    (
        axum::http::StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        buffer,
    )
}

pub fn req_inc(service: &str, endpoint: &str, status: &str) {
    REQUESTS.with_label_values(&[service, endpoint, status]).inc();
}

pub fn upstream_inc(service: &str, upstream: &str, outcome: &str) {
    UPSTREAM_CALLS.with_label_values(&[service, upstream, outcome]).inc();
}
