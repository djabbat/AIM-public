use super::{Provider, ProviderId};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::{json, Value};

pub struct Gemini {
    api_key: Option<String>,
    client: reqwest::Client,
}

impl Gemini {
    pub fn from_env() -> Self {
        Self {
            api_key: std::env::var("GEMINI_API_KEY").ok(),
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(180))
                .build()
                .expect("reqwest client"),
        }
    }
}

#[derive(Deserialize)] struct Part { text: Option<String> }
#[derive(Deserialize)] struct Content { parts: Vec<Part> }
#[derive(Deserialize)] struct Candidate { content: Content }
#[derive(Deserialize)] struct Resp { candidates: Vec<Candidate> }
#[derive(Deserialize)] struct ErrEnv { error: ErrBody }
#[derive(Deserialize)] struct ErrBody { message: String, #[allow(dead_code)] status: Option<String> }

#[async_trait]
impl Provider for Gemini {
    fn id(&self) -> ProviderId { ProviderId::Gemini }
    fn default_model(&self) -> &'static str { "gemini-2.5-pro" }
    fn is_ready(&self) -> bool { self.api_key.is_some() }

    async fn complete(
        &self,
        messages: &[crate::router::ChatMessage],
        model: &str,
    ) -> anyhow::Result<String> {
        let key = self.api_key.as_ref()
            .ok_or_else(|| anyhow::anyhow!("GEMINI_API_KEY missing"))?;
        let url = format!(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
            model, key
        );

        // Pull system messages out into a systemInstruction block.
        let mut system_text = String::new();
        let mut convo: Vec<&crate::router::ChatMessage> = Vec::new();
        for m in messages {
            if m.role == "system" {
                if !system_text.is_empty() { system_text.push('\n'); }
                system_text.push_str(&m.content);
            } else {
                convo.push(m);
            }
        }
        if convo.is_empty() {
            anyhow::bail!("gemini: no user/model messages");
        }

        // Collapse consecutive same-role messages so Gemini sees alternation.
        let mut contents: Vec<Value> = Vec::new();
        let mut cur_role: Option<String> = None;
        let mut cur_buf = String::new();
        let flush = |role: &str, buf: String, sink: &mut Vec<Value>| {
            let g_role = if role == "assistant" { "model" } else { "user" };
            sink.push(json!({ "role": g_role, "parts": [{ "text": buf }] }));
        };
        for m in &convo {
            let role = if m.role == "assistant" { "assistant" } else { "user" }.to_string();
            match &cur_role {
                Some(r) if *r == role => {
                    cur_buf.push('\n');
                    cur_buf.push_str(&m.content);
                }
                Some(r) => {
                    let prev = std::mem::take(&mut cur_buf);
                    flush(r, prev, &mut contents);
                    cur_role = Some(role.clone());
                    cur_buf = m.content.clone();
                }
                None => {
                    cur_role = Some(role.clone());
                    cur_buf = m.content.clone();
                }
            }
        }
        if let Some(r) = cur_role { flush(&r, cur_buf, &mut contents); }

        // Gemini requires the first content to be role=user.
        if contents.first().and_then(|v| v.get("role")).and_then(|v| v.as_str()) != Some("user") {
            // Synthesise a leading user turn.
            contents.insert(0, json!({ "role": "user", "parts": [{ "text": "[continue]" }] }));
        }

        let mut body = json!({ "contents": contents });
        if !system_text.is_empty() {
            body["systemInstruction"] = json!({ "parts": [{ "text": system_text }] });
        }

        let resp = self.client.post(&url).json(&body).send().await?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            if let Ok(ErrEnv { error }) = serde_json::from_str::<ErrEnv>(&body) {
                anyhow::bail!("gemini {}: {}", status, error.message);
            }
            anyhow::bail!("gemini {}: {}", status, body);
        }

        let parsed: Resp = resp.json().await?;
        let text = parsed.candidates.into_iter().next()
            .and_then(|c| c.content.parts.into_iter().filter_map(|p| p.text).next())
            .ok_or_else(|| anyhow::anyhow!("gemini: empty"))?;
        Ok(text)
    }
}
