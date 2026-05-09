//! aim-llm :8770 — LLM router skeleton.
//!
//! Endpoints (skeleton-only):
//!   GET  /health
//!   POST /v1/chat        — { messages, model_hint } -> { reply, model_used }
//!   GET  /v1/providers   — list configured providers + readiness
//!
//! Provider modules (`providers/*`) hold trait-based stubs to be filled in.

use aim_llm::{ensemble, router};

use aim_common::{cors_layer, health_handler, init_tracing};
use axum::{routing::{get, post}, Router};
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing("info");
    let state = router::RouterState::from_env();

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/metrics", get(aim_common::metrics_handler))
        .route("/v1/providers", get(router::list_providers))
        .route("/v1/chat", post(router::chat))
        .route("/v1/ensemble", post(ensemble::ensemble))
        .route("/v1/critique", post(ensemble::critique))
        .with_state(state)
        .layer(cors_layer());

    let port: u16 = aim_common::port(
        "AIM_LLM_PORT",
        aim_common::AimConfig::load().ports.aim_llm,
        8770,
    );
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "aim-llm listening");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
