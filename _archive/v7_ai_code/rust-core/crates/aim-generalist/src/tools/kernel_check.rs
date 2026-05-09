//! kernel_check — pre-action gate enforcing CLAUDE.md decision-kernel laws:
//!   L_PRIVACY      — no Patients-data egress without context.privacy_consent
//!   L_CONSENT      — email/git_push_public/web_publish need user_confirmed
//!   L_VERIFIABILITY — every PMID/DOI in `text` must be verifiable
//!
//! Args: { action, text?, context? }. Returns "OK" or a list of blockers.

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use regex::Regex;
use serde_json::Value;

pub struct KernelCheck;

/// Pure logic — exposed for tests.
pub fn evaluate(action: &str, text: &str, ctx: &Value) -> Vec<String> {
    let privacy = ctx.get("privacy_consent").and_then(|v| v.as_bool()).unwrap_or(false);
    let user_confirmed = ctx.get("user_confirmed").and_then(|v| v.as_bool()).unwrap_or(false);

    let mut blockers: Vec<String> = Vec::new();

    if is_egress(action) {
        if (text.contains("/Patients/") || text.contains("\\Patients\\")) && !privacy {
            blockers.push("L_PRIVACY: text references Patients/ path; requires context.privacy_consent=true".into());
        }
        let phone_re = Regex::new(r"\+?\d[\d\s\-\(\)]{8,}").unwrap();
        let dob_re = Regex::new(r"\b(19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b").unwrap();
        if phone_re.is_match(text) && !privacy {
            blockers.push("L_PRIVACY: text contains phone-like pattern; requires privacy_consent".into());
        }
        if dob_re.is_match(text) && !privacy {
            blockers.push("L_PRIVACY: text contains DOB-like pattern; requires privacy_consent".into());
        }
    }

    let consent_required = matches!(action,
        "email_send" | "git_push_public" | "web_publish" | "telegram_broadcast" | "post_remote"
    );
    if consent_required && !user_confirmed {
        blockers.push(format!("L_CONSENT: action '{action}' requires context.user_confirmed=true"));
    }

    if is_egress(action) {
        let pmid_re = Regex::new(r"PMID[:\s]*(\d+)").unwrap();
        for cap in pmid_re.captures_iter(text) {
            let id = &cap[1];
            if id.len() < 4 || id.len() > 9 {
                blockers.push(format!("L_VERIFIABILITY: PMID {id} fails sanity check (length); call verify_pmid first"));
            }
        }
        let doi_re = Regex::new(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b").unwrap();
        for cap in doi_re.find_iter(&text.to_uppercase()) {
            let _doi = cap.as_str();
            if !text.contains("VERIFIED") {
                blockers.push("L_VERIFIABILITY: DOI present in text but no VERIFIED marker; call verify_doi first".into());
                break;
            }
        }
    }
    blockers
}

#[async_trait]
impl Tool for KernelCheck {
    fn name(&self) -> &'static str { "kernel_check" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let action = args.get("action").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: action".to_string())?;
        let text = args.get("text").and_then(|v| v.as_str()).unwrap_or("");
        let ctx = args.get("context").cloned().unwrap_or(serde_json::json!({}));

        let blockers = evaluate(action, text, &ctx);
        if blockers.is_empty() { Ok("OK".into()) } else { Err(blockers.join("\n")) }
    }
}

fn is_egress(action: &str) -> bool {
    matches!(action,
        "email_send" | "telegram_send" | "telegram_broadcast" |
        "git_push_public" | "web_publish" | "post_remote" | "write_external"
    )
}
