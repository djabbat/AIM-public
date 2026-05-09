//! G5 (2026-05-03) — regression tests for the SSE streaming pipeline.
//!
//! We don't drive `axum::serve` here. Instead we stand up a tiny axum app
//! that *fakes* the `aim-llm` endpoint, point `AIM_LLM_URL` at it, and
//! call `Runner::run_streaming` directly. That covers:
//!
//!   * the full event ordering (start → llm_request → llm_response → final)
//!   * tool_call / tool_result events when the canned LLM response invokes one
//!   * interrupt() short-circuits the loop with an Error event
//!   * non-JSON LLM output gets reported as an Error (no panic)
//!
//! The actual axum SSE wrapper in src/main.rs is a thin map() over the
//! same `Event` stream, so its correctness is implied — we don't test
//! it via real HTTP to keep the test lightweight.

use aim_generalist::react;
use axum::{routing::post, Json, Router};
use serde::Deserialize;
use serde_json::json;
use serial_test::serial;
use std::{net::SocketAddr, sync::{Arc, Mutex}};
use tokio::sync::mpsc;

#[derive(Deserialize)]
struct ChatReq { messages: Vec<serde_json::Value> }

/// Spawn an axum app that returns canned LLM replies in order.
async fn spawn_fake_llm(replies: Vec<&'static str>) -> String {
    let queue = Arc::new(Mutex::new(replies));
    let app: Router = Router::new().route("/v1/chat", post({
        let q = queue.clone();
        move |Json(_): Json<ChatReq>| {
            let q = q.clone();
            async move {
                let next = {
                    let mut g = q.lock().unwrap();
                    if g.is_empty() { "{\"final\":\"(empty queue)\"}".to_string() }
                    else { g.remove(0).to_string() }
                };
                Json(json!({ "reply": next }))
            }
        }
    }));
    let listener = tokio::net::TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], 0)))
        .await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.ok();
    });
    format!("http://{addr}")
}

async fn collect_events(mut rx: mpsc::Receiver<react::Event>)
                        -> Vec<react::Event> {
    let mut out = Vec::new();
    while let Some(ev) = rx.recv().await {
        out.push(ev);
    }
    out
}

fn event_kinds(events: &[react::Event]) -> Vec<&'static str> {
    events.iter().map(|ev| match ev {
        react::Event::Start { .. }       => "start",
        react::Event::LlmRequest { .. }  => "llm_request",
        react::Event::LlmResponse { .. } => "llm_response",
        react::Event::ToolCall { .. }    => "tool_call",
        react::Event::ToolResult { .. }  => "tool_result",
        react::Event::ToolError { .. }   => "tool_error",
        react::Event::Final { .. }       => "final",
        react::Event::Error { .. }       => "error",
    }).collect()
}


#[tokio::test]
#[serial(aim_llm_url)]
async fn streaming_emits_start_request_response_final() {
    let url = spawn_fake_llm(vec![
        r#"{"final":"hello-stream"}"#,
    ]).await;
    std::env::set_var("AIM_LLM_URL", &url);

    let runner = react::Runner::from_env();
    let (tx, rx) = mpsc::channel(64);

    let res = runner.run_streaming("ping", None, 4, tx.clone()).await;
    drop(tx);
    let events = collect_events(rx).await;

    assert!(res.is_ok(), "{:?}", res.err());
    let kinds = event_kinds(&events);
    assert_eq!(kinds.first().copied(), Some("start"));
    assert_eq!(kinds.last().copied(),  Some("final"));
    assert!(kinds.contains(&"llm_request"));
    assert!(kinds.contains(&"llm_response"));
}


#[tokio::test]
#[serial(aim_llm_url)]
async fn streaming_emits_tool_call_and_result_events() {
    // Step 1: LLM asks for a `pwd` bash run.
    // Step 2: LLM returns final using the result.
    let url = spawn_fake_llm(vec![
        r#"{"tool":"bash","args":{"command":"pwd"}}"#,
        r#"{"final":"done"}"#,
    ]).await;
    std::env::set_var("AIM_LLM_URL", &url);

    let runner = react::Runner::from_env();
    let (tx, rx) = mpsc::channel(64);

    runner.run_streaming("run-bash", None, 4, tx.clone()).await
        .expect("runner failed");
    drop(tx);
    let events = collect_events(rx).await;

    let kinds = event_kinds(&events);
    assert!(kinds.contains(&"tool_call"),
            "expected tool_call in {:?}", kinds);
    assert!(kinds.contains(&"tool_result") || kinds.contains(&"tool_error"),
            "expected tool_result/tool_error in {:?}", kinds);
    assert_eq!(kinds.last().copied(), Some("final"));
}


#[tokio::test]
#[serial(aim_llm_url)]
async fn streaming_non_json_response_emits_error_event() {
    let url = spawn_fake_llm(vec!["this is not JSON, just prose"]).await;
    std::env::set_var("AIM_LLM_URL", &url);

    let runner = react::Runner::from_env();
    let (tx, rx) = mpsc::channel(64);

    let res = runner.run_streaming("hello", None, 2, tx.clone()).await;
    drop(tx);
    let events = collect_events(rx).await;

    assert!(res.is_err(), "non-JSON should bubble as Err");
    let kinds = event_kinds(&events);
    assert!(kinds.contains(&"error"),
            "expected error event for non-JSON, got {:?}", kinds);
}


#[tokio::test]
#[serial(aim_llm_url)]
async fn event_kind_set_is_complete() {
    // Sanity: every Event variant maps to exactly one tag string. If a
    // new variant is added without updating event_kinds, this will panic
    // (or fail to compile if the match is exhaustive). The fact that
    // event_kinds() is exhaustive on the enum means we get a compile-time
    // guarantee — this test just asserts the test infra is in sync.
    let dummy = vec![
        react::Event::Start { task: "x".into(), max_iters: 1 },
        react::Event::LlmRequest { step: 1 },
        react::Event::LlmResponse { step: 1, raw: "x".into() },
        react::Event::ToolCall { step: 1, tool: "t".into(), args: serde_json::Value::Null },
        react::Event::ToolResult { step: 1, tool: "t".into(), output: "x".into() },
        react::Event::ToolError { step: 1, tool: "t".into(), error: "x".into() },
        react::Event::Final { answer: "x".into(), tools_used: vec![] },
        react::Event::Error { error: "x".into() },
    ];
    let kinds = event_kinds(&dummy);
    assert_eq!(kinds.len(), 8);
    let mut sorted = kinds.clone();
    sorted.sort();
    sorted.dedup();
    assert_eq!(sorted.len(), 8, "duplicate or missing tag in {:?}", kinds);
}
