//! Shared building blocks for every AIM Rust service:
//! - structured error type
//! - JSON health endpoint
//! - tracing init
//! - permissive CORS for dev / locked-down for prod via env flag

pub mod error;
pub mod health;
pub mod telemetry;
pub mod cors;
pub mod config;
pub mod metrics;

pub use error::{ApiError, ApiResult};
pub use health::{health_handler, HealthInfo};
pub use telemetry::init_tracing;
pub use cors::cors_layer;
pub use config::{AimConfig, port, upstream_url};
pub use metrics::{metrics_handler, req_inc, upstream_inc};
