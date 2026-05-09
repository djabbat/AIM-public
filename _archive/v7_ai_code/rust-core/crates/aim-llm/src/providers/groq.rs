use super::{Provider, ProviderId};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::json;

const URL: &str = "https://api.groq.com/openai/v1/chat/completions";

pub struct Groq {
    api_key: Option<String>,
    client: reqwest::Client,
}

impl Groq {
    pub fn from_env() -> Self {
        Self {
            api_key: std::env::var("GROQ_API_KEY").ok(),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("reqwest client"),
        }
    }
}

#[derive(Deserialize)] struct Choice { message: Msg }
#[derive(Deserialize)] struct Msg { content: String }
#[derive(Deserialize)] struct Resp { choices: Vec<Choice> }

#[async_trait]
impl Provider for Groq {
    fn id(&self) -> ProviderId { ProviderId::Groq }
    fn default_model(&self) -> &'static str { "llama-3.3-70b-versatile" }
    fn is_ready(&self) -> bool { self.api_key.is_some() }

    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String> {
        let key = self.api_key.as_ref().ok_or_else(|| anyhow::anyhow!("GROQ_API_KEY missing"))?;

        let resp = self.client.post(URL)
            .bearer_auth(key)
            .json(&json!({ "model": model, "messages": messages }))
            .send().await?
            .error_for_status()?
            .json::<Resp>().await?;

        resp.choices.into_iter().next()
            .map(|c| c.message.content)
            .ok_or_else(|| anyhow::anyhow!("groq: empty choices"))
    }
}
