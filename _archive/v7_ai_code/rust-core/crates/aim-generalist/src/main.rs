//! aim-generalist :8774 — ReAct tool-using executor.
//!
//! Endpoints:
//!   GET  /health
//!   GET  /v1/tools      — list registered tool names
//!   POST /v1/run        — sync: { task, max_iters? } -> { answer, trace, tools_used }
//!   POST /v1/run/stream — SSE: each step emits a typed event

use aim_generalist::react;

use aim_common::{cors_layer, health_handler, init_tracing, ApiError, ApiResult};
use axum::{
    extract::{Path as AxPath, State},
    response::sse::{Event as SseEvent, KeepAlive, Sse},
    routing::{get, post},
    Json, Router,
};
use futures::stream::Stream;
use serde::{Deserialize, Serialize};
use std::{convert::Infallible, net::SocketAddr, sync::Arc};
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tokio_stream::StreamExt;

#[derive(Clone)]
struct AppState {
    runner: Arc<react::Runner>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing("info");
    let runner = Arc::new(react::Runner::from_env());
    let state = AppState { runner };

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/metrics", get(aim_common::metrics_handler))
        .route("/v1/tools", get(list_tools))
        .route("/v1/run", post(run_handler))
        .route("/v1/run/stream", post(run_stream_handler))
        .route("/v1/interrupt/:run_id", post(interrupt_handler))
        .with_state(state)
        .layer(cors_layer());

    let port: u16 = aim_common::port(
        "AIM_GENERALIST_PORT",
        aim_common::AimConfig::load().ports.aim_generalist,
        8774,
    );
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!(%addr, "aim-generalist listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

#[derive(Serialize)]
struct ToolsResp { tools: Vec<String>, count: usize }

async fn list_tools(State(s): State<AppState>) -> Json<ToolsResp> {
    let tools = s.runner.tool_names();
    let count = tools.len();
    Json(ToolsResp { tools, count })
}

#[derive(Deserialize)]
struct RunReq {
    task: String,
    #[serde(default)] max_iters: Option<usize>,
    #[serde(default)] system: Option<String>,
}

#[derive(Serialize)]
struct RunResp {
    answer: String,
    trace: Vec<react::TraceEntry>,
    tools_used: Vec<String>,
}

async fn run_handler(
    State(s): State<AppState>,
    Json(req): Json<RunReq>,
) -> ApiResult<Json<RunResp>> {
    let max = req.max_iters.unwrap_or(8).min(20);
    let result = s.runner.run(&req.task, req.system.as_deref(), max).await
        .map_err(ApiError::Internal)?;
    Ok(Json(RunResp {
        answer: result.answer,
        trace: result.trace,
        tools_used: result.tools_used,
    }))
}

async fn run_stream_handler(
    State(s): State<AppState>,
    Json(req): Json<RunReq>,
) -> Sse<impl Stream<Item = Result<SseEvent, Infallible>>> {
    let (tx, rx) = mpsc::channel::<react::Event>(64);
    let runner = s.runner.clone();
    let max = req.max_iters.unwrap_or(8).min(20);
    let task = req.task;
    let system = req.system;

    tokio::spawn(async move {
        if let Err(e) = runner.run_streaming(&task, system.as_deref(), max, tx.clone()).await {
            let _ = tx.send(react::Event::Error { error: e.to_string() }).await;
        }
    });

    let stream = ReceiverStream::new(rx).map(|ev| {
        let tag = event_tag(&ev);
        let data = serde_json::to_string(&ev).unwrap_or_else(|_| "{}".into());
        Ok(SseEvent::default().event(tag).data(data))
    });

    Sse::new(stream).keep_alive(KeepAlive::default())
}

async fn interrupt_handler(
    State(s): State<AppState>,
    AxPath(run_id): AxPath<String>,
) -> Json<serde_json::Value> {
    let ok = s.runner.interrupt(&run_id);
    Json(serde_json::json!({ "ok": ok, "run_id": run_id }))
}

fn event_tag(ev: &react::Event) -> &'static str {
    match ev {
        react::Event::Start { .. }       => "start",
        react::Event::LlmRequest { .. }  => "llm_request",
        react::Event::LlmResponse { .. } => "llm_response",
        react::Event::ToolCall { .. }    => "tool_call",
        react::Event::ToolResult { .. }  => "tool_result",
        react::Event::ToolError { .. }   => "tool_error",
        react::Event::Final { .. }       => "final",
        react::Event::Error { .. }       => "error",
    }
}
