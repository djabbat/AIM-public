//! memory_recall / memory_save talk to aim-rag :8771 over HTTP.
//! Without a live aim-rag, dispatch should error gracefully.

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;

async fn dispatch(name: &str, args: serde_json::Value) -> ToolResult {
    Registry::with_defaults().dispatch(&ToolCall { name: name.into(), args }).await
}

#[tokio::test]
async fn memory_recall_missing_query() {
    let res = dispatch("memory_recall", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: query")),
        ToolResult::Ok(_) => panic!("must require query"),
    }
}

#[tokio::test]
async fn memory_save_missing_text() {
    let res = dispatch("memory_save", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: text")),
        ToolResult::Ok(_) => panic!("must require text"),
    }
}

#[tokio::test]
async fn memory_recall_handles_unreachable_aim_rag() {
    // Point AIM_RAG_URL at a black hole so we can verify graceful failure.
    std::env::set_var("AIM_RAG_URL", "http://127.0.0.1:1");
    let res = dispatch("memory_recall", json!({ "query": "anything" })).await;
    match res {
        ToolResult::Err(e) => {
            assert!(e.contains("rag send") || e.contains("rag status") || e.contains("rag parse"),
                "expected rag error, got: {e}");
        }
        ToolResult::Ok(_) => panic!("must error when aim-rag is unreachable"),
    }
    std::env::remove_var("AIM_RAG_URL");
}
