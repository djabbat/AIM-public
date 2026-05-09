//! view_image — multimodal vision via aim-llm's Anthropic/Gemini providers.
//!
//! Args: { path: <sandbox path>, prompt?: "Describe this image" }
//!
//! Strategy:
//!   1. sandbox::validate path (must be .png/.jpg/.jpeg/.webp/.gif).
//!   2. Read bytes, base64-encode.
//!   3. POST to aim-llm /v1/chat with a vision-capable provider hint.
//!      For now we send a multimodal prompt directly to Anthropic via aim-llm:
//!      since /v1/chat takes plain ChatMessage strings, we wrap the image as
//!      a markdown-style data URI inside the user message — providers that
//!      support inline data URIs (Anthropic, Gemini) will accept it.
//!
//! For offline/no-key environments we fall back to a stub describing the
//! file size + type so the ReAct loop can keep going.

use super::{Tool, ToolCtx};
use crate::tools::sandbox;
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};

const ALLOWED_EXT: &[&str] = &["png", "jpg", "jpeg", "webp", "gif"];

pub struct ViewImage;

#[async_trait]
impl Tool for ViewImage {
    fn name(&self) -> &'static str { "view_image" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let path = args.get("path").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: path".to_string())?;
        let prompt = args.get("prompt").and_then(|v| v.as_str())
            .unwrap_or("Describe this image factually. List visible text verbatim.");

        let resolved = sandbox::validate(path, true)?;
        let ext = resolved.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
        if !ALLOWED_EXT.iter().any(|e| *e == ext) {
            return Err(format!("view_image: unsupported extension '{ext}'; want one of {ALLOWED_EXT:?}"));
        }

        let bytes = tokio::fs::read(&resolved).await
            .map_err(|e| format!("read {}: {e}", resolved.display()))?;
        let b64 = STANDARD.encode(&bytes);
        let mime = match ext.as_str() {
            "jpg" | "jpeg" => "image/jpeg",
            "png" => "image/png",
            "webp" => "image/webp",
            "gif" => "image/gif",
            _ => "image/png",
        };

        // Try Anthropic vision via direct API call (skipping aim-llm /v1/chat to
        // preserve image_block typing).
        if let Ok(key) = std::env::var("ANTHROPIC_API_KEY") {
            if !key.is_empty() {
                return anthropic_vision(&key, mime, &b64, prompt).await;
            }
        }
        if let Ok(key) = std::env::var("GEMINI_API_KEY") {
            if !key.is_empty() {
                return gemini_vision(&key, mime, &b64, prompt).await;
            }
        }
        Ok(format!(
            "[view_image stub: {} bytes, {mime}, prompt='{prompt}'; no vision provider configured]",
            bytes.len()
        ))
    }
}

async fn anthropic_vision(key: &str, mime: &str, b64: &str, prompt: &str) -> Result<String, String> {
    let model = std::env::var("AIM_VISION_MODEL_ANTHROPIC")
        .unwrap_or_else(|_| "claude-haiku-4-5-20251001".into());
    let body = json!({
        "model": model,
        "max_tokens": 1024,
        "messages": [{
            "role": "user",
            "content": [
                { "type": "image", "source": { "type": "base64", "media_type": mime, "data": b64 } },
                { "type": "text", "text": prompt }
            ]
        }]
    });
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120)).build()
        .map_err(|e| e.to_string())?;
    let resp = client.post("https://api.anthropic.com/v1/messages")
        .header("x-api-key", key)
        .header("anthropic-version", "2023-06-01")
        .json(&body).send().await.map_err(|e| format!("anthropic vision: {e}"))?;
    if !resp.status().is_success() {
        let s = resp.status();
        let t = resp.text().await.unwrap_or_default();
        return Err(format!("anthropic vision {s}: {t}"));
    }
    let v: Value = resp.json().await.map_err(|e| format!("anthropic parse: {e}"))?;
    let text: String = v.get("content").and_then(|c| c.as_array()).map(|arr| {
        arr.iter().filter_map(|b| b.get("text").and_then(|t| t.as_str()))
            .collect::<Vec<_>>().join("")
    }).unwrap_or_default();
    if text.is_empty() { Err("anthropic vision: empty".into()) } else { Ok(text) }
}

async fn gemini_vision(key: &str, mime: &str, b64: &str, prompt: &str) -> Result<String, String> {
    let model = std::env::var("AIM_VISION_MODEL_GEMINI")
        .unwrap_or_else(|_| "gemini-2.5-flash".into());
    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
        model, key
    );
    let body = json!({
        "contents": [{
            "role": "user",
            "parts": [
                { "inline_data": { "mime_type": mime, "data": b64 } },
                { "text": prompt }
            ]
        }]
    });
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120)).build()
        .map_err(|e| e.to_string())?;
    let resp = client.post(&url).json(&body).send().await.map_err(|e| format!("gemini vision: {e}"))?;
    if !resp.status().is_success() {
        let s = resp.status();
        let t = resp.text().await.unwrap_or_default();
        return Err(format!("gemini vision {s}: {t}"));
    }
    let v: Value = resp.json().await.map_err(|e| format!("gemini parse: {e}"))?;
    let text = v.get("candidates").and_then(|c| c.as_array())
        .and_then(|a| a.first())
        .and_then(|c| c.get("content")).and_then(|c| c.get("parts"))
        .and_then(|p| p.as_array())
        .and_then(|a| a.iter().find_map(|p| p.get("text").and_then(|t| t.as_str())))
        .map(String::from);
    text.ok_or_else(|| "gemini vision: empty".into())
}
