//! HTTP client to aim-llm (or any compatible /v1/chat endpoint).

use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Clone)]
pub struct LlmClient {
    base: String,
    client: reqwest::Client,
}

#[derive(Serialize, Clone, Debug)]
pub struct Message {
    pub role: String,
    pub content: String,
}

#[derive(Deserialize)]
struct ChatResp {
    reply: String,
    #[allow(dead_code)] provider: Option<serde_json::Value>,
    #[allow(dead_code)] model: Option<String>,
}

impl LlmClient {
    pub fn from_env() -> Self {
        Self {
            base: std::env::var("AIM_LLM_URL").unwrap_or_else(|_| "http://127.0.0.1:8770".into()),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(180))
                .build().expect("reqwest"),
        }
    }

    pub async fn chat(&self, messages: &[Message]) -> anyhow::Result<String> {
        let resp: ChatResp = self.client.post(format!("{}/v1/chat", self.base))
            .json(&json!({ "messages": messages }))
            .send().await?
            .error_for_status()?
            .json().await?;
        Ok(resp.reply)
    }
}
