//! web_search hits DuckDuckGo HTML. We test missing-arg and malformed-URL
//! paths only; live HTML scraping would be flaky.

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;

async fn dispatch(name: &str, args: serde_json::Value) -> ToolResult {
    Registry::with_defaults().dispatch(&ToolCall { name: name.into(), args }).await
}

#[tokio::test]
async fn web_search_missing_query() {
    let res = dispatch("web_search", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: query")),
        ToolResult::Ok(_) => panic!("must require query"),
    }
}

#[tokio::test]
async fn http_get_rejects_non_http_scheme() {
    let res = dispatch("http_get", json!({ "url": "file:///etc/passwd" })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("only http(s)")),
        ToolResult::Ok(_) => panic!("must reject file://"),
    }
}

#[tokio::test]
async fn http_get_missing_url() {
    let res = dispatch("http_get", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: url")),
        ToolResult::Ok(_) => panic!("must require url"),
    }
}
