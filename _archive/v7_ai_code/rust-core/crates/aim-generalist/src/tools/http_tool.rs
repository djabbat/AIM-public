use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::Value;

pub struct HttpGet;

#[async_trait]
impl Tool for HttpGet {
    fn name(&self) -> &'static str { "http_get" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let url = args.get("url").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: url".to_string())?;
        if !(url.starts_with("http://") || url.starts_with("https://")) {
            return Err("only http(s):// allowed".into());
        }
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build().map_err(|e| e.to_string())?;
        let resp = client.get(url).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        let body = resp.text().await.map_err(|e| e.to_string())?;
        let trimmed = if body.len() > 16_000 {
            format!("{}…[truncated; total {} bytes]", &body[..16_000], body.len())
        } else { body };
        Ok(format!("[status {}]\n{}", status.as_u16(), trimmed))
    }
}
