//! gmail_send — actually deliver a previously-drafted email via Gmail API.
//!
//! Auth model: install-time OAuth dance produces a refresh_token, stored in
//! ~/.aim_env as GMAIL_REFRESH_TOKEN + GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET.
//! Each send refreshes the access_token and POSTs to
//! https://gmail.googleapis.com/gmail/v1/users/me/messages/send.
//!
//! Side-effect = MUST pass kernel_check L_CONSENT first; we re-check here too.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::Deserialize;
use serde_json::{json, Value};

pub struct GmailSend;

#[derive(Deserialize)]
struct TokenResp { access_token: String }

#[async_trait]
impl Tool for GmailSend {
    fn name(&self) -> &'static str { "gmail_send" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        // Hard gate: explicit user_confirmed=true required.
        let confirmed = args.get("user_confirmed").and_then(|v| v.as_bool()).unwrap_or(false);
        if !confirmed {
            return Err("gmail_send: user_confirmed=true required (L_CONSENT)".into());
        }

        let to = args.get("to").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: to".to_string())?;
        let subject = args.get("subject").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: subject".to_string())?;
        let body = args.get("body").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: body".to_string())?;
        let from = args.get("from").and_then(|v| v.as_str())
            .or_else(|| Some("djabbat@gmail.com")).unwrap();

        let refresh_token = std::env::var("GMAIL_REFRESH_TOKEN")
            .map_err(|_| "GMAIL_REFRESH_TOKEN missing".to_string())?;
        let client_id = std::env::var("GMAIL_CLIENT_ID")
            .map_err(|_| "GMAIL_CLIENT_ID missing".to_string())?;
        let client_secret = std::env::var("GMAIL_CLIENT_SECRET")
            .map_err(|_| "GMAIL_CLIENT_SECRET missing".to_string())?;

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30)).build()
            .map_err(|e| e.to_string())?;

        // 1. Refresh access_token.
        let token: TokenResp = client.post("https://oauth2.googleapis.com/token")
            .form(&[
                ("client_id", client_id.as_str()),
                ("client_secret", client_secret.as_str()),
                ("refresh_token", refresh_token.as_str()),
                ("grant_type", "refresh_token"),
            ])
            .send().await.map_err(|e| format!("token: {e}"))?
            .error_for_status().map_err(|e| format!("token: {e}"))?
            .json().await.map_err(|e| format!("token parse: {e}"))?;

        // 2. Compose RFC822 + base64url.
        let raw = format!(
            "From: {from}\r\nTo: {to}\r\nSubject: {subject}\r\n\
             MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{body}"
        );
        let raw_b64 = URL_SAFE_NO_PAD.encode(raw.as_bytes());

        // 3. Send.
        let resp: Value = client
            .post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
            .bearer_auth(&token.access_token)
            .json(&json!({ "raw": raw_b64 }))
            .send().await.map_err(|e| format!("send: {e}"))?
            .error_for_status().map_err(|e| format!("send status: {e}"))?
            .json().await.map_err(|e| format!("send parse: {e}"))?;

        let id = resp.get("id").and_then(|v| v.as_str()).unwrap_or("?");
        Ok(format!("gmail_send OK; message_id={id}; to={to}; subject='{subject}'"))
    }
}
