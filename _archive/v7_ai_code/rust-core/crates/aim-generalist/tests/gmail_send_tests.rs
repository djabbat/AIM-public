//! Validation-only tests for gmail_send. Real send needs OAuth tokens which
//! we don't supply in CI, so these tests exercise the kernel-check gate
//! and missing-arg paths.

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;

async fn dispatch(name: &str, args: serde_json::Value) -> ToolResult {
    let r = Registry::with_defaults();
    r.dispatch(&ToolCall { name: name.into(), args }).await
}

#[tokio::test]
async fn rejects_without_user_confirmed() {
    let res = dispatch("gmail_send", json!({
        "to": "x@example.com",
        "subject": "hi",
        "body": "test"
    })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("user_confirmed"),
            "expected L_CONSENT-style error, got: {e}"),
        ToolResult::Ok(o) => panic!("must reject without consent: {o}"),
    }
}

#[tokio::test]
async fn missing_to_arg() {
    let res = dispatch("gmail_send", json!({
        "user_confirmed": true,
        "subject": "hi",
        "body": "test"
    })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: to"), "{e}"),
        ToolResult::Ok(o) => panic!("must reject missing to: {o}"),
    }
}

#[tokio::test]
async fn rejects_without_oauth_env() {
    // Ensure env is empty for this test.
    std::env::remove_var("GMAIL_REFRESH_TOKEN");
    std::env::remove_var("GMAIL_CLIENT_ID");
    std::env::remove_var("GMAIL_CLIENT_SECRET");

    let res = dispatch("gmail_send", json!({
        "user_confirmed": true,
        "to": "x@example.com",
        "subject": "hi",
        "body": "test"
    })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("GMAIL_REFRESH_TOKEN"), "{e}"),
        ToolResult::Ok(o) => panic!("must reject without OAuth env: {o}"),
    }
}
