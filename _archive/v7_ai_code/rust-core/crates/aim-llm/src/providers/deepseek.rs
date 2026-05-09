use super::{Provider, ProviderId};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::json;

const URL: &str = "https://api.deepseek.com/v1/chat/completions";

pub struct DeepSeek {
    api_key: Option<String>,
    client: reqwest::Client,
}

impl DeepSeek {
    pub fn from_env() -> Self {
        Self {
            api_key: std::env::var("DEEPSEEK_API_KEY").ok(),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .expect("reqwest client"),
        }
    }
}

#[derive(Deserialize)]
struct OpenAIChoice { message: OpenAIMessage }
#[derive(Deserialize)]
struct OpenAIMessage { content: String }
#[derive(Deserialize)]
struct OpenAIResp { choices: Vec<OpenAIChoice> }

#[async_trait]
impl Provider for DeepSeek {
    fn id(&self) -> ProviderId { ProviderId::DeepSeek }
    fn default_model(&self) -> &'static str { "deepseek-chat" }
    fn is_ready(&self) -> bool { self.api_key.is_some() }

    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String> {
        let key = self.api_key.as_ref().ok_or_else(|| anyhow::anyhow!("DEEPSEEK_API_KEY missing"))?;

        let resp = self.client.post(URL)
            .bearer_auth(key)
            .json(&json!({
                "model": model,
                "messages": messages,
                "stream": false
            }))
            .send().await?
            .error_for_status()?
            .json::<OpenAIResp>().await?;

        resp.choices.into_iter().next()
            .map(|c| c.message.content)
            .ok_or_else(|| anyhow::anyhow!("deepseek: empty choices"))
    }
}
