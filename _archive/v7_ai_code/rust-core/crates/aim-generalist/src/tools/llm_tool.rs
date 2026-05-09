use super::{Tool, ToolCtx};
use crate::llm_client::{LlmClient, Message};
use async_trait::async_trait;
use serde_json::Value;

pub struct LlmAsk;

#[async_trait]
impl Tool for LlmAsk {
    fn name(&self) -> &'static str { "llm_ask" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let prompt = args.get("prompt").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: prompt".to_string())?;
        let system = args.get("system").and_then(|v| v.as_str()).unwrap_or("");

        let client = LlmClient::from_env();
        let mut msgs = Vec::new();
        if !system.is_empty() {
            msgs.push(Message { role: "system".into(), content: system.into() });
        }
        msgs.push(Message { role: "user".into(), content: prompt.into() });
        client.chat(&msgs).await.map_err(|e| e.to_string())
    }
}
