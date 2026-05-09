//! memory_recall + memory_save — semantic memory via aim-rag HTTP.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::{json, Value};

fn rag_url() -> String {
    std::env::var("AIM_RAG_URL").unwrap_or_else(|_| "http://127.0.0.1:8771".into())
}

fn http() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("reqwest")
}

pub struct MemoryRecall;

#[async_trait]
impl Tool for MemoryRecall {
    fn name(&self) -> &'static str { "memory_recall" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let query = args.get("query").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: query".to_string())?;
        let k = args.get("k").and_then(|v| v.as_u64()).unwrap_or(5);

        let resp = http().post(format!("{}/v1/search", rag_url()))
            .json(&json!({ "query": query, "k": k }))
            .send().await.map_err(|e| format!("rag send: {e}"))?
            .error_for_status().map_err(|e| format!("rag status: {e}"))?
            .json::<Value>().await.map_err(|e| format!("rag parse: {e}"))?;

        let hits = resp.get("hits").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        let lines: Vec<String> = hits.into_iter().map(|h| {
            let id = h.get("id").and_then(|v| v.as_str()).unwrap_or("?");
            let score = h.get("score").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let text = h.get("text").and_then(|v| v.as_str()).unwrap_or("");
            format!("[{score:.3}] {id}: {text}")
        }).collect();
        Ok(if lines.is_empty() { "(no memories found)".into() } else { lines.join("\n") })
    }
}

pub struct MemorySave;

#[async_trait]
impl Tool for MemorySave {
    fn name(&self) -> &'static str { "memory_save" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let text = args.get("text").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: text".to_string())?;
        let id = args.get("id").and_then(|v| v.as_str()).map(String::from);
        let metadata = args.get("metadata").cloned();

        let mut body = json!({ "text": text });
        if let Some(id) = id { body["id"] = json!(id); }
        if let Some(md) = metadata { body["metadata"] = md; }

        let resp = http().post(format!("{}/v1/upsert", rag_url()))
            .json(&body)
            .send().await.map_err(|e| format!("rag send: {e}"))?
            .error_for_status().map_err(|e| format!("rag status: {e}"))?
            .json::<Value>().await.map_err(|e| format!("rag parse: {e}"))?;
        Ok(resp.to_string())
    }
}
