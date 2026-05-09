use super::{Provider, ProviderId};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::json;

const URL: &str = "https://api.anthropic.com/v1/messages";
const VERSION: &str = "2023-06-01";

pub struct Anthropic {
    api_key: Option<String>,
    client: reqwest::Client,
}

impl Anthropic {
    pub fn from_env() -> Self {
        Self {
            api_key: std::env::var("ANTHROPIC_API_KEY").ok(),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(180))
                .build()
                .expect("reqwest client"),
        }
    }
}

#[derive(Deserialize)] struct Block { #[serde(rename = "type")] kind: String, text: Option<String> }
#[derive(Deserialize)] struct Resp { content: Vec<Block> }
#[derive(Deserialize)] struct ErrEnv { error: ErrBody }
#[derive(Deserialize)] struct ErrBody { message: String }

#[async_trait]
impl Provider for Anthropic {
    fn id(&self) -> ProviderId { ProviderId::Anthropic }
    fn default_model(&self) -> &'static str { "claude-haiku-4-5-20251001" }
    fn is_ready(&self) -> bool { self.api_key.is_some() }

    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String> {
        let key = self.api_key.as_ref()
            .ok_or_else(|| anyhow::anyhow!("ANTHROPIC_API_KEY missing"))?;

        // Anthropic separates `system` from messages and rejects empty arrays.
        let mut system_parts = Vec::new();
        let mut msgs: Vec<&crate::router::ChatMessage> = Vec::new();
        for m in messages {
            if m.role == "system" { system_parts.push(m.content.as_str()); }
            else { msgs.push(m); }
        }
        let system_text = system_parts.join("\n");

        // Guard: at least one user message is required.
        if msgs.is_empty() {
            anyhow::bail!("anthropic: no non-system messages");
        }
        // Anthropic also requires the conversation to start with `user`.
        if msgs[0].role != "user" {
            anyhow::bail!("anthropic: first non-system message must be user (got {})", msgs[0].role);
        }

        let max_tokens = std::env::var("AIM_LLM_MAX_TOKENS").ok()
            .and_then(|s| s.parse().ok()).unwrap_or(4096_u32);

        let mut body = json!({
            "model": model,
            "max_tokens": max_tokens,
            "messages": msgs,
        });
        if !system_text.is_empty() {
            body["system"] = json!(system_text);
        }

        let resp = self.client.post(URL)
            .header("x-api-key", key)
            .header("anthropic-version", VERSION)
            .json(&body)
            .send().await?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            // Try to extract Anthropic's error.message
            if let Ok(ErrEnv { error }) = serde_json::from_str::<ErrEnv>(&body) {
                anyhow::bail!("anthropic {}: {}", status, error.message);
            }
            anyhow::bail!("anthropic {}: {}", status, body);
        }

        let parsed: Resp = resp.json().await?;
        let text: String = parsed.content.into_iter()
            .filter(|b| b.kind == "text")
            .filter_map(|b| b.text)
            .collect::<Vec<_>>()
            .join("");

        if text.is_empty() {
            anyhow::bail!("anthropic: no text blocks in response");
        }
        Ok(text)
    }
}
