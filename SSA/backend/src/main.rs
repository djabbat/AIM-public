mod engine;
mod types;

use axum::{extract::State, response::Json, routing::{get, post}, Router};
use std::{net::SocketAddr, sync::Arc};
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

use crate::engine::{digitize, load_patterns, load_ranges, match_patterns};
use crate::types::*;

#[derive(Clone)]
struct AppState {
    refs: Arc<RangesFile>,
    patterns: Arc<PatternsFile>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,tower_http=debug")))
        .with(fmt::layer())
        .init();

    let ranges_path = std::env::var("SSA_RANGES").unwrap_or_else(|_| "../data/ranges.json".into());
    let patterns_path = std::env::var("SSA_PATTERNS").unwrap_or_else(|_| "../data/patterns.json".into());
    let port: u16 = std::env::var("SSA_PORT").ok().and_then(|s| s.parse().ok()).unwrap_or(8766);

    let refs = load_ranges(&ranges_path)?;
    let patterns = load_patterns(&patterns_path)?;
    tracing::info!("loaded {} parameters, {} patterns",
        refs.parameters.len(), patterns.patterns.len());

    let state = AppState { refs: Arc::new(refs), patterns: Arc::new(patterns) };

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/v1/digitize", post(post_digitize))
        .route("/api/v1/syndromes", post(post_syndromes))
        .route("/api/v1/parameters", get(list_params))
        .route("/api/v1/patterns", get(list_patterns))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!("ssa-api listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status":"ok","service":"ssa-api","version":env!("CARGO_PKG_VERSION")}))
}

async fn post_digitize(State(s): State<AppState>, Json(input): Json<CbcInput>) -> Json<DigitizeResponse> {
    Json(digitize(&input, &s.refs))
}

async fn post_syndromes(State(s): State<AppState>, Json(input): Json<CbcInput>) -> Json<SyndromesResponse> {
    let d = digitize(&input, &s.refs);
    let matched = match_patterns(&d.digitized, &s.patterns.patterns);
    let red = matched.iter().filter(|p| p.severity == "red").count();
    let amber = matched.iter().filter(|p| p.severity == "amber").count();
    let green = matched.iter().filter(|p| p.severity == "green").count();
    Json(SyndromesResponse {
        digitized: d.digitized,
        patterns: matched,
        red_count: red, amber_count: amber, green_count: green,
    })
}

#[derive(serde::Serialize)]
struct ParamSummary {
    id: String,
    unit: String,
    derived: Option<String>,
}

async fn list_params(State(s): State<AppState>) -> Json<Vec<ParamSummary>> {
    Json(s.refs.parameters.iter().map(|p| ParamSummary {
        id: p.id.clone(), unit: p.unit.clone(), derived: p.derived.clone()
    }).collect())
}

#[derive(serde::Serialize)]
struct PatternSummary {
    id: String, label: String, severity: String, differentials_count: usize,
}

async fn list_patterns(State(s): State<AppState>) -> Json<Vec<PatternSummary>> {
    Json(s.patterns.patterns.iter().map(|p| PatternSummary {
        id: p.id.clone(), label: p.label.clone(), severity: p.severity.clone(),
        differentials_count: p.differentials.len()
    }).collect())
}
