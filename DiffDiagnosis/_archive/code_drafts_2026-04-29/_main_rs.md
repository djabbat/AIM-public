```toml
[package]
name = "diffdx-api"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
tower-http = { version = "0.5", features = ["cors", "trace"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
uuid = { version = "1", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }
```

```rust
// src/main.rs
use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};
use uuid::Uuid;

// -----------------------------------------------------------------------------
// Data structures
// -----------------------------------------------------------------------------

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Algorithm {
    pub id: String,
    pub source: String,
    pub system: String,
    pub nodes: Vec<String>,
    pub differentials: Vec<Differential>,
    pub red_flags: Vec<String>,
    pub presenting_complaint: String,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Differential {
    pub name: String,
    pub probability: f64,
    pub evidence_for: Vec<String>,
    pub evidence_against: Vec<String>,
    pub source_algorithm: String,
}

#[derive(Debug, Deserialize)]
pub struct CaseRequest {
    pub free_text: String,
    pub structured: Option<HashMap<String, serde_json::Value>>,
}

#[derive(Debug, Serialize)]
pub struct CaseResponse {
    pub id: Uuid,
    pub free_text: String,
    pub structured: HashMap<String, serde_json::Value>,
    pub created_at: DateTime<Utc>,
}

// -----------------------------------------------------------------------------
// Application state
// -----------------------------------------------------------------------------

#[derive(Clone)]
pub struct AppState {
    algorithms: HashMap<String, Algorithm>,       // keyed by id
    sources: Vec<String>,
}

// -----------------------------------------------------------------------------
// Algorithm loading (stub: reads JSON file)
// -----------------------------------------------------------------------------

fn load_algorithms(path: &str) -> Result<Vec<Algorithm>, Box<dyn std::error::Error>> {
    let data = std::fs::read_to_string(path)?;
    let algorithms: Vec<Algorithm> = serde_json::from_str(&data)?;
    Ok(algorithms)
}

// -----------------------------------------------------------------------------
// Handlers
// -----------------------------------------------------------------------------

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok"}))
}

/// POST /api/v1/case
/// Creates a new case (