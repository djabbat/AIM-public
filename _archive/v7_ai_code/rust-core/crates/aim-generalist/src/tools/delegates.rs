//! delegate_doctor / writer / researcher / coder — single-shot LLM calls
//! with role-specific system prompts. These are NOT recursive ReAct loops
//! (that would require sub-agent dispatch and self-reference); they're
//! specialised one-pass calls that the main generalist can use as workers.

use super::{Tool, ToolCtx};
use crate::llm_client::{LlmClient, Message};
use async_trait::async_trait;
use serde_json::Value;

const DOCTOR_PROMPT: &str = r#"You are AIM Doctor. Given a clinical query (intake, labs, plan question),
respond with structured medical reasoning:
1) Differential (3-5 most likely diagnoses, ranked).
2) Red flags / cannot-miss conditions.
3) Immediate workup (specific labs/imaging/exams).
4) Treatment first-line if diagnosis is clear; deferred if not.
5) Follow-up plan.
NEVER fabricate dosages or guideline citations. If unsure, say so explicitly."#;

const WRITER_PROMPT: &str = r#"You are AIM Writer. Goals (in order):
1. Match the requested register (peer-review reply, cover letter, manuscript edit, blog).
2. Cite sources only with explicit PMID/DOI provided in the user prompt.
3. Brevity: kill filler. Each sentence earns its place.
4. Russian if input is Russian, English otherwise (default English for academic).
Output only the requested artifact text, no meta-commentary."#;

const RESEARCHER_PROMPT: &str = r#"You are AIM Researcher. For each user query:
1. Frame the question precisely (PICO if clinical).
2. List the strongest sources you would consult: prefer Cochrane, Lancet, NEJM,
   PubMed primary with pubdate, Crossref-resolvable DOIs.
3. NEVER invent PMIDs/DOIs. If the user wants verification, say so — your
   role is to plan the search, not invent results.
4. End with a 5-bullet takeaway."#;

const CODER_PROMPT: &str = r#"You are AIM Coder. Output WORKING code only:
1. Default to Rust for backends, Elixir for Phoenix, Python only when needed
   for legacy or ML.
2. No example placeholders; if you don't know an API, say so.
3. Tests where they make sense.
4. Match existing project style (read first if asked)."#;

fn make(prompt: &'static str, name: &'static str, default_model: Option<&'static str>) -> SimpleDelegate {
    SimpleDelegate { name, system_prompt: prompt, default_model }
}

pub struct SimpleDelegate {
    pub name: &'static str,
    pub system_prompt: &'static str,
    pub default_model: Option<&'static str>,
}

#[async_trait]
impl Tool for SimpleDelegate {
    fn name(&self) -> &'static str { self.name }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let task = args.get("task").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: task".to_string())?;
        let extra_context = args.get("context").and_then(|v| v.as_str()).unwrap_or("");

        let user = if extra_context.is_empty() {
            task.to_string()
        } else {
            format!("[context]\n{extra_context}\n\n[task]\n{task}")
        };

        let client = LlmClient::from_env();
        let mut msgs = vec![
            Message { role: "system".into(), content: self.system_prompt.into() },
            Message { role: "user".into(), content: user },
        ];
        // Allow caller to suggest a model.
        if let Some(model) = args.get("model").and_then(|v| v.as_str()) {
            msgs.push(Message { role: "system".into(), content: format!("[preferred_model: {model}]") });
        } else if let Some(m) = self.default_model {
            msgs.push(Message { role: "system".into(), content: format!("[preferred_model: {m}]") });
        }
        client.chat(&msgs).await.map_err(|e| e.to_string())
    }
}

pub fn doctor()     -> SimpleDelegate { make(DOCTOR_PROMPT,     "delegate_doctor",     None) }
pub fn writer()     -> SimpleDelegate { make(WRITER_PROMPT,     "delegate_writer",     None) }
pub fn researcher() -> SimpleDelegate { make(RESEARCHER_PROMPT, "delegate_researcher", None) }
pub fn coder()      -> SimpleDelegate { make(CODER_PROMPT,      "delegate_coder",      None) }

// ── delegate_email ───────────────────────────────────────────────────────────
//
// Drafts an email and writes it to <SANDBOX>/_drafts/<uuid>.md.
// Real send is gated through kernel_check L_CONSENT — we never POST to a
// mail provider here.

const EMAIL_PROMPT: &str = r#"You compose professional emails. Reply with the email body only,
no headers, no envelope. Russian if input is Russian, otherwise English."#;

pub struct DelegateEmail;

#[async_trait]
impl Tool for DelegateEmail {
    fn name(&self) -> &'static str { "delegate_email" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let to = args.get("to").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: to".to_string())?;
        let subject = args.get("subject").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: subject".to_string())?;
        let goal = args.get("goal").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: goal".to_string())?;

        let client = LlmClient::from_env();
        let body = client.chat(&[
            Message { role: "system".into(), content: EMAIL_PROMPT.into() },
            Message { role: "user".into(),
                      content: format!("To: {to}\nSubject: {subject}\nGoal: {goal}") },
        ]).await.map_err(|e| e.to_string())?;

        // Write draft into Patients/_drafts/.
        let root = crate::tools::sandbox::root();
        let drafts_dir = root.join("_drafts");
        tokio::fs::create_dir_all(&drafts_dir).await
            .map_err(|e| format!("mkdir _drafts: {e}"))?;
        let id = uuid::Uuid::new_v4().to_string();
        let path = drafts_dir.join(format!("_email_{id}.md"));
        let content = format!(
            "---\nto: {to}\nsubject: {subject}\nstatus: DRAFT — requires kernel_check + L_CONSENT to send\n---\n\n{body}\n"
        );
        tokio::fs::write(&path, &content).await
            .map_err(|e| format!("write draft: {e}"))?;
        Ok(format!("DRAFT saved to {}\n\n---\n{content}", path.display()))
    }
}

// ── ze_verify / ze_verify_symbol ─────────────────────────────────────────────
//
// Look up a symbol or term in the Ze project's CONCEPT.md / KNOWLEDGE.md.
// Returns the matching paragraph (if any) so an LLM cannot hallucinate Ze
// definitions out of thin air.

pub struct ZeVerify;
pub struct ZeVerifySymbol;

fn ze_concept_paths() -> Vec<std::path::PathBuf> {
    let mut v: Vec<std::path::PathBuf> = Vec::new();
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/oem".into());
    let base = format!("{home}/Desktop/LongevityCommon/Ze");
    for p in &["CONCEPT.md", "KNOWLEDGE.md", "PARAMETERS.md", "MAP.md"] {
        v.push(format!("{base}/{p}").into());
    }
    v
}

#[async_trait]
impl Tool for ZeVerify {
    fn name(&self) -> &'static str { "ze_verify" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let term = args.get("term").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: term".to_string())?;
        ze_search(term, false).await
    }
}

#[async_trait]
impl Tool for ZeVerifySymbol {
    fn name(&self) -> &'static str { "ze_verify_symbol" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let symbol = args.get("symbol").and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: symbol".to_string())?;
        ze_search(symbol, true).await
    }
}

async fn ze_search(needle: &str, exact: bool) -> Result<String, String> {
    let mut hits: Vec<String> = Vec::new();
    for path in ze_concept_paths() {
        let Ok(text) = tokio::fs::read_to_string(&path).await else { continue };
        for (i, line) in text.lines().enumerate() {
            let matched = if exact {
                line.split(|c: char| !c.is_alphanumeric() && c != '_')
                    .any(|tok| tok == needle)
            } else {
                line.to_lowercase().contains(&needle.to_lowercase())
            };
            if matched {
                hits.push(format!("{}:{}: {}", path.display(), i + 1, line));
                if hits.len() >= 30 { break; }
            }
        }
        if hits.len() >= 30 { break; }
    }
    if hits.is_empty() {
        Err(format!("Ze: no occurrence of '{needle}' in CONCEPT/KNOWLEDGE/PARAMETERS/MAP — verify your claim or update the canon"))
    } else {
        Ok(hits.join("\n"))
    }
}
