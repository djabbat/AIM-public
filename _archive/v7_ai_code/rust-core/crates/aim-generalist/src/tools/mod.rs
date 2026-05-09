//! Tool registry. Implemented tools (29 total):
//!   read_file, write_file, glob, grep, bash, http_get, llm_ask, notes,
//!   memory_recall, memory_save,
//!   verify_pmid, verify_doi, search_pubmed,
//!   web_search, apply_patch, kernel_check, delegate_parallel,
//!   bash_async, bash_status, bash_output, bash_kill,
//!   view_image,
//!   delegate_doctor, delegate_writer, delegate_researcher, delegate_coder,
//!   delegate_email,
//!   ze_verify, ze_verify_symbol.

mod fs_tools;
mod search_tools;
mod bash_tool;
mod http_tool;
mod llm_tool;
mod notes_tool;
mod memory_tools;
mod aim_fs_tools;
mod citation_tools;
mod web_search_tool;
mod patch_tool;
mod bash_async;
pub mod kernel_check;
mod delegate_parallel;
mod vision_tool;
mod delegates;
mod gmail_send;
pub mod sandbox;

use parking_lot_compat::Mutex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;

pub mod parking_lot_compat {
    pub use std::sync::Mutex;
}

pub struct ToolCall {
    pub name: String,
    pub args: Value,
}

pub enum ToolResult {
    Ok(String),
    Err(String),
}

#[async_trait::async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &'static str;
    async fn run(&self, args: &Value, ctx: &ToolCtx) -> Result<String, String>;
}

#[derive(Clone, Default)]
pub struct ToolCtx {
    pub notes: Arc<Mutex<HashMap<String, String>>>,
}

pub struct Registry {
    tools: Vec<Box<dyn Tool>>,
    ctx: ToolCtx,
}

impl Registry {
    pub fn with_defaults() -> Self {
        let jobs = bash_async::JobRegistry::new();
        let tools: Vec<Box<dyn Tool>> = vec![
            Box::new(fs_tools::ReadFile),
            Box::new(fs_tools::WriteFile),
            Box::new(search_tools::Glob),
            Box::new(search_tools::Grep),
            Box::new(bash_tool::Bash),
            Box::new(http_tool::HttpGet),
            Box::new(llm_tool::LlmAsk),
            Box::new(notes_tool::Notes),
            Box::new(memory_tools::MemoryRecall),
            Box::new(memory_tools::MemorySave),
            // AIM_FS bridge — propose / approve / reject + recall (SPEC §4.x + §5.2).
            Box::new(aim_fs_tools::MemorySaveAimFs),
            Box::new(aim_fs_tools::MemoryRecallAimFs),
            Box::new(aim_fs_tools::InboxPendingAimFs),
            Box::new(aim_fs_tools::InboxApproveAimFs),
            Box::new(aim_fs_tools::InboxRejectAimFs),
            Box::new(citation_tools::VerifyPmid),
            Box::new(citation_tools::VerifyDoi),
            Box::new(citation_tools::SearchPubmed),
            Box::new(web_search_tool::WebSearch),
            Box::new(patch_tool::ApplyPatch),
            Box::new(kernel_check::KernelCheck),
            Box::new(delegate_parallel::DelegateParallel),
            Box::new(vision_tool::ViewImage),
            Box::new(delegates::doctor()),
            Box::new(delegates::writer()),
            Box::new(delegates::researcher()),
            Box::new(delegates::coder()),
            Box::new(delegates::DelegateEmail),
            Box::new(delegates::ZeVerify),
            Box::new(delegates::ZeVerifySymbol),
            Box::new(gmail_send::GmailSend),
            Box::new(bash_async::BashAsync   { jobs: jobs.clone() }),
            Box::new(bash_async::BashStatus  { jobs: jobs.clone() }),
            Box::new(bash_async::BashOutput  { jobs: jobs.clone() }),
            Box::new(bash_async::BashKill    { jobs }),
        ];
        Self { tools, ctx: ToolCtx::default() }
    }

    pub fn names(&self) -> Vec<String> {
        self.tools.iter().map(|t| t.name().to_string()).collect()
    }

    pub async fn dispatch(&self, call: &ToolCall) -> ToolResult {
        let Some(tool) = self.tools.iter().find(|t| t.name() == call.name) else {
            return ToolResult::Err(format!("unknown tool: {}", call.name));
        };
        match tool.run(&call.args, &self.ctx).await {
            Ok(out) => ToolResult::Ok(out),
            Err(e)  => ToolResult::Err(e),
        }
    }
}
