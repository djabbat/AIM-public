mod engine;
mod types;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Json,
    routing::{get, post},
    Router,
};
use std::{net::SocketAddr, sync::Arc};
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

use crate::engine::{load_algorithms, rank};
use crate::types::*;

#[derive(Clone)]
struct AppState {
    algorithms: Arc<Vec<Algorithm>>,
    top_k: usize,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,tower_http=debug")))
        .with(fmt::layer())
        .init();

    let algo_path = std::env::var("DIFFDX_ALGORITHMS")
        .unwrap_or_else(|_| "../algorithms.json".to_string());
    let port: u16 = std::env::var("DIFFDX_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8765);
    let top_k: usize = std::env::var("DIFFDX_TOP_K")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);

    let algorithms = load_algorithms(&algo_path).unwrap_or_else(|e| {
        tracing::warn!("could not load {}: {} — starting with empty bank", algo_path, e);
        Vec::new()
    });
    tracing::info!("loaded {} algorithms from {}", algorithms.len(), algo_path);

    let state = AppState {
        algorithms: Arc::new(algorithms),
        top_k,
    };

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/v1/case", post(post_case))
        .route("/api/v1/diff", post(post_diff))
        .route("/api/v1/algorithm/:id", get(get_algorithm))
        .route("/api/v1/algorithms", get(list_algorithms))
        .route("/api/v1/sources", get(list_sources))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!("diffdx-api listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status":"ok","service":"diffdx-api","version":env!("CARGO_PKG_VERSION")}))
}

async fn post_case(Json(input): Json<CaseInput>) -> Json<Case> {
    Json(input.into_case())
}

async fn post_diff(
    State(s): State<AppState>,
    Json(input): Json<CaseInput>,
) -> Json<DiffResponse> {
    let case = input.into_case();
    let resp = rank(&case, &s.algorithms, s.top_k);
    Json(resp)
}

async fn get_algorithm(
    State(s): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Algorithm>, StatusCode> {
    s.algorithms
        .iter()
        .find(|a| a.id == id)
        .cloned()
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

#[derive(serde::Serialize)]
struct AlgorithmSummary<'a> {
    id: &'a str,
    presenting_complaint: &'a str,
    system: SystemSchool,
    differentials_count: usize,
}

async fn list_algorithms(State(s): State<AppState>) -> Json<Vec<AlgorithmSummary<'static>>> {
    let summaries: Vec<AlgorithmSummary<'static>> = s
        .algorithms
        .iter()
        .map(|a| {
            let id: &'static str = Box::leak(a.id.clone().into_boxed_str());
            let pc: &'static str = Box::leak(a.presenting_complaint.clone().into_boxed_str());
            AlgorithmSummary {
                id,
                presenting_complaint: pc,
                system: a.system,
                differentials_count: a.differentials.len(),
            }
        })
        .collect();
    Json(summaries)
}

async fn list_sources() -> Json<Vec<&'static str>> {
    Json(vec![
        "Vinogradov А.В. Дифференциальный диагноз внутренних болезней. 3-е изд.",
        "Robert B. Taylor (ed.). Difficult Diagnosis. 2nd ed.",
    ])
}
