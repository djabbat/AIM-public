//! aim-rag :8771 — embeddings + cosine search over SQLite store.
//!
//! Endpoints:
//!   GET  /health
//!   POST /v1/embed   — { texts:[..] } -> { vectors:[[..]] }
//!   POST /v1/upsert  — { id, text, metadata? } -> { ok:true, dim }
//!   POST /v1/search  — { query, k? } -> { hits:[{id, score, text, metadata}] }

use aim_rag::{embed, store};

use aim_common::{cors_layer, health_handler, init_tracing, ApiError, ApiResult};
use axum::{extract::State, routing::{get, post}, Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{net::SocketAddr, sync::Arc};

#[derive(Clone)]
struct AppState {
    embedder: Arc<embed::Embedder>,
    store: Arc<store::Store>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing("info");

    let db_path = std::env::var("AIM_RAG_DB").unwrap_or_else(|_| "aim_rag.db".into());
    let store = Arc::new(store::Store::open(&db_path)?);
    let embedder = Arc::new(embed::Embedder::from_env());
    let state = AppState { embedder, store };

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/metrics", get(aim_common::metrics_handler))
        .route("/v1/embed", post(embed_handler))
        .route("/v1/upsert", post(upsert))
        .route("/v1/search", post(search))
        .with_state(state)
        .layer(cors_layer());

    let port: u16 = std::env::var("AIM_RAG_PORT").ok()
        .and_then(|s| s.parse().ok()).unwrap_or(8771);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "aim-rag listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

#[derive(Deserialize)] struct EmbedReq { texts: Vec<String> }
#[derive(Serialize)]   struct EmbedResp { vectors: Vec<Vec<f32>> }

async fn embed_handler(
    State(s): State<AppState>,
    Json(req): Json<EmbedReq>,
) -> ApiResult<Json<EmbedResp>> {
    let v = s.embedder.embed_batch(&req.texts).await
        .map_err(|e| { aim_common::req_inc("aim-rag", "/v1/embed", "fail"); ApiError::Upstream(e.to_string()) })?;
    aim_common::req_inc("aim-rag", "/v1/embed", "ok");
    Ok(Json(EmbedResp { vectors: v }))
}

#[derive(Deserialize)] struct UpsertReq { id: Option<String>, text: String, metadata: Option<Value> }
#[derive(Serialize)]   struct UpsertResp { id: String, dim: usize }

async fn upsert(
    State(s): State<AppState>,
    Json(req): Json<UpsertReq>,
) -> ApiResult<Json<UpsertResp>> {
    let id = req.id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let v = s.embedder.embed_one(&req.text).await
        .map_err(|e| ApiError::Upstream(e.to_string()))?;
    let dim = v.len();
    s.store.upsert(&id, &req.text, &v, req.metadata.as_ref())
        .map_err(ApiError::Internal)?;
    aim_common::req_inc("aim-rag", "/v1/upsert", "ok");
    Ok(Json(UpsertResp { id, dim }))
}

#[derive(Deserialize)] struct SearchReq { query: String, k: Option<usize> }
#[derive(Serialize)]   struct Hit { id: String, score: f32, text: String, metadata: Option<Value> }
#[derive(Serialize)]   struct SearchResp { hits: Vec<Hit> }

async fn search(
    State(s): State<AppState>,
    Json(req): Json<SearchReq>,
) -> ApiResult<Json<SearchResp>> {
    let q = s.embedder.embed_one(&req.query).await
        .map_err(|e| ApiError::Upstream(e.to_string()))?;
    let k = req.k.unwrap_or(8).min(100);
    let raw = s.store.search(&q, k).map_err(ApiError::Internal)?;
    aim_common::req_inc("aim-rag", "/v1/search", "ok");
    let hits = raw.into_iter().map(|(id, score, text, md)| Hit {
        id, score, text, metadata: md,
    }).collect();
    Ok(Json(SearchResp { hits }))
}
