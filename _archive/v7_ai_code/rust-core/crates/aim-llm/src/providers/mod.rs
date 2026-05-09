//! Provider trait + registry. Real HTTP implementations are TODO — this is the skeleton.

pub mod deepseek;
pub mod groq;
pub mod anthropic;
pub mod gemini;
pub mod ollama;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "lowercase")]
pub enum ProviderId {
    DeepSeek,
    Groq,
    Anthropic,
    Gemini,
    Ollama,
}

#[async_trait]
pub trait Provider: Send + Sync {
    fn id(&self) -> ProviderId;
    fn default_model(&self) -> &'static str;
    fn is_ready(&self) -> bool;
    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String>;
}

pub fn load_from_env() -> Vec<Box<dyn Provider>> {
    vec![
        Box::new(deepseek::DeepSeek::from_env()),
        Box::new(groq::Groq::from_env()),
        Box::new(anthropic::Anthropic::from_env()),
        Box::new(gemini::Gemini::from_env()),
        Box::new(ollama::Ollama::from_env()),
    ]
}
