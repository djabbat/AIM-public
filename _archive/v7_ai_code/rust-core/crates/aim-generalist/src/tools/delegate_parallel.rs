//! delegate_parallel — fan-out N independent tasks. Two modes:
//!
//!  - default: each task → one-shot LLM call (cheap, fast).
//!  - recursive: env AIM_DELEGATE_MODE=react OR args.recursive=true →
//!    each task spawns its OWN sub-Runner with full ReAct loop. Sub-runners
//!    share the same tool registry but get their own interrupt + prefetch.

use super::{Tool, ToolCtx};
use crate::llm_client::{LlmClient, Message};
use async_trait::async_trait;
use serde_json::{json, Value};

pub struct DelegateParallel;

#[async_trait]
impl Tool for DelegateParallel {
    fn name(&self) -> &'static str { "delegate_parallel" }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let tasks: Vec<String> = args.get("tasks").and_then(|v| v.as_array())
            .ok_or_else(|| "missing arg: tasks (array)".to_string())?
            .iter().filter_map(|t| t.as_str().map(String::from)).collect();
        if tasks.is_empty() { return Err("tasks must be non-empty".into()); }
        if tasks.len() > 8 { return Err("max 8 parallel tasks".into()); }

        let recursive = args.get("recursive").and_then(|v| v.as_bool()).unwrap_or(false)
            || std::env::var("AIM_DELEGATE_MODE").as_deref() == Ok("react");
        let max_iters = args.get("max_iters").and_then(|v| v.as_u64()).unwrap_or(4) as usize;

        let bullets: Vec<String> = if recursive {
            // Spawn sub-runners — each owns a Registry. Heavy but capable.
            let futs = tasks.iter().enumerate().map(|(i, t)| {
                let task = t.clone();
                async move {
                    let runner = crate::react::Runner::from_env();
                    match runner.run(&task, None, max_iters).await {
                        Ok(r)  => format!("### Task {} — {task}\n{}", i + 1, r.answer),
                        Err(e) => format!("### Task {} — {task}\n[ERROR] {e}", i + 1),
                    }
                }
            });
            futures::future::join_all(futs).await
        } else {
            let client = LlmClient::from_env();
            let futs = tasks.iter().enumerate().map(|(i, t)| {
                let client = &client;
                let task = t.clone();
                async move {
                    match client.chat(&[Message { role: "user".into(), content: task.clone() }]).await {
                        Ok(ans) => format!("### Task {} — {task}\n{ans}", i + 1),
                        Err(e)  => format!("### Task {} — {task}\n[ERROR] {e}", i + 1),
                    }
                }
            });
            futures::future::join_all(futs).await
        };

        // Synthesis call.
        let client = LlmClient::from_env();
        let synth_prompt = json!({
            "instruction": "Synthesise the following independent task results into one concise answer.",
            "results": bullets,
        }).to_string();
        let synth = client.chat(&[
            Message { role: "system".into(),
                      content: "You merge sub-agent answers, dropping duplicates and preserving citations.".into() },
            Message { role: "user".into(), content: synth_prompt },
        ]).await.map_err(|e| e.to_string())?;

        Ok(format!("# Synthesis\n{synth}\n\n---\n## Per-task results\n{}", bullets.join("\n\n")))
    }
}
