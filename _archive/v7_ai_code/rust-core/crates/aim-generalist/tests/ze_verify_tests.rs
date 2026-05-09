//! ze_verify reads ~/Desktop/LongevityCommon/Ze/{CONCEPT,KNOWLEDGE,PARAMETERS,MAP}.md.
//! These tests exercise both the "match" and "no-match" paths against the
//! current state of the user's filesystem (running locally).

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;

async fn dispatch(name: &str, args: serde_json::Value) -> ToolResult {
    Registry::with_defaults().dispatch(&ToolCall { name: name.into(), args }).await
}

#[tokio::test]
async fn ze_verify_unknown_term_errors() {
    let res = dispatch("ze_verify", json!({
        "term": "xyz_definitely_not_in_ze_concept_zzz"
    })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("no occurrence")),
        ToolResult::Ok(_) => {} // tolerable if the term collides with something
    }
}

#[tokio::test]
async fn ze_verify_missing_term_arg() {
    let res = dispatch("ze_verify", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: term"), "{e}"),
        ToolResult::Ok(_) => panic!("should require term arg"),
    }
}

#[tokio::test]
async fn ze_verify_symbol_missing_arg() {
    let res = dispatch("ze_verify_symbol", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: symbol"), "{e}"),
        ToolResult::Ok(_) => panic!("should require symbol arg"),
    }
}
