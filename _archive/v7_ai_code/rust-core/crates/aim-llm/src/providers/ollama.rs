use super::{Provider, ProviderId};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::json;

pub struct Ollama {
    base_url: String,
    client: reqwest::Client,
}

impl Ollama {
    pub fn from_env() -> Self {
        Self {
            base_url: std::env::var("OLLAMA_URL").unwrap_or_else(|_| "http://127.0.0.1:11434".into()),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(300))
                .build()
                .expect("reqwest client"),
        }
    }
}

#[derive(Deserialize)] struct Msg { content: String }
#[derive(Deserialize)] struct Resp { message: Msg }

#[async_trait]
impl Provider for Ollama {
    fn id(&self) -> ProviderId { ProviderId::Ollama }
    fn default_model(&self) -> &'static str { "llama3.2" }
    fn is_ready(&self) -> bool { !self.base_url.is_empty() }

    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String> {
        let url = format!("{}/api/chat", self.base_url.trim_end_matches('/'));

        let resp = self.client.post(&url)
            .json(&json!({
                "model": model,
                "messages": messages,
                "stream": false
            }))
            .send().await?
            .error_for_status()?
            .json::<Resp>().await?;

        Ok(resp.message.content)
    }
}
